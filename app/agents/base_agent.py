from __future__ import annotations

import json
import logging

from app.agents.prompts import BASE_SYSTEM_PROMPT, get_role_prompt
from app.agents.schemas import ActionType, AgentDecision
from app.llm.client import LLMClient
from app.llm.schemas import ChatMessage
from app.state.schemas import Role
from app.state.view_builder import PlayerView

logger = logging.getLogger(__name__)


class AgentDecisionError(Exception):
    """Agent 决策过程中的异常。"""


def _build_user_message(view: PlayerView) -> str:
    """根据 PlayerView 构建中文用户消息。"""
    lines: list[str] = []

    phase_names = {
        "night": "夜晚",
        "day": "白天",
        "vote": "投票",
        "setup": "准备",
        "ended": "结束",
    }
    role_names = {
        "werewolf": "狼人",
        "seer": "预言家",
        "witch": "女巫",
        "villager": "平民",
        "hunter": "猎人",
        "idiot": "白痴",
        "guard": "守卫",
    }
    camp_names = {
        "werewolf": "狼人阵营",
        "good": "好人阵营",
    }

    phase_cn = phase_names.get(view.phase.value, view.phase.value)
    role_cn = role_names.get(view.own_role.value, view.own_role.value)
    camp_cn = camp_names.get(view.own_camp.value, view.own_camp.value)

    lines.append(f"游戏ID: {view.game_id}")
    lines.append(f"当前轮次: 第{view.round}轮")
    lines.append(f"当前阶段: {phase_cn}")
    lines.append(f"你的座位号: {view.viewer_seat_no}")
    lines.append(f"你的身份: {role_cn}")
    lines.append(f"你的阵营: {camp_cn}")

    if view.known_wolf_team:
        wolf_str = "、".join(f"{s}号" for s in view.known_wolf_team)
        lines.append(f"已知狼队友: {wolf_str}")

    lines.append("")
    lines.append("## 存活玩家")
    for p in view.players:
        status = "存活" if p.alive else "死亡"
        note = ""
        if not p.alive:
            note = " (已死亡)"
        elif not p.can_vote:
            note = " (无投票权)"
        lines.append(f"- {p.seat_no}号 {p.name}: {status}{note}")

    if view.public_events:
        lines.append("")
        lines.append("## 公共事件")
        for event in view.public_events:
            lines.append(f"- {json.dumps(event, ensure_ascii=False)}")

    if view.private_info:
        lines.append("")
        lines.append("## 你的私有信息")
        lines.append(json.dumps(view.private_info, ensure_ascii=False))

    lines.append("")
    lines.append("## 可执行动作")
    if view.available_actions:
        for action in view.available_actions:
            lines.append(f"- {action}")
    else:
        lines.append("- 当前无可执行动作")

    lines.append("")
    lines.append("## 输出要求")
    lines.append("请根据以上信息，以 JSON 格式返回你的决策。")
    lines.append("注意：action 字段必须是 JSON 对象，不能是字符串；action 对象内必须包含 action_type。")

    action_schemas = _action_schema_hints(view.available_actions)
    lines.append(action_schemas)

    return "\n".join(lines)


def _action_schema_hints(available_actions: list[str]) -> str:
    """为可用动作生成 JSON schema 提示。"""
    hints: dict[str, str] = {
        ActionType.speak.value:
            '- speak: {"action_type": "speak", "content": "你的中文发言内容"}',
        ActionType.vote.value:
            '- vote: {"action_type": "vote", "target_seat_no": <座位号或null表示弃票>}',
        ActionType.werewolf_kill.value:
            '- werewolf_kill: {"action_type": "werewolf_kill", "target_seat_no": <目标座位号>}',
        ActionType.seer_check.value:
            '- seer_check: {"action_type": "seer_check", "target_seat_no": <目标座位号>}',
        ActionType.witch_save.value:
            '- witch_save: {"action_type": "witch_save", "target_seat_no": <目标座位号>}',
        ActionType.witch_poison.value:
            '- witch_poison: {"action_type": "witch_poison", "target_seat_no": <目标座位号>}',
        ActionType.hunter_shoot.value:
            '- hunter_shoot: {"action_type": "hunter_shoot", "target_seat_no": <目标座位号>}',
        ActionType.guard_protect.value:
            '- guard_protect: {"action_type": "guard_protect", "target_seat_no": <目标座位号>}',
        ActionType.run_for_sheriff.value:
            '- run_for_sheriff: {"action_type": "run_for_sheriff", "run": true, "content": "你的竞选公开发言"}',
        ActionType.sheriff_vote.value:
            '- sheriff_vote: {"action_type": "sheriff_vote", "target_seat_no": <候选人座位号或null表示弃票>}',
        ActionType.sheriff_assign.value:
            '- sheriff_assign: {"action_type": "sheriff_assign", "target_seat_no": <移交警徽的座位号>}',
    }

    action_list = "\n".join(
        hints[action] for action in available_actions if action in hints
    )
    return (
        "返回格式必须严格类似：\n"
        '{"action": {"action_type": "speak", "content": "你的中文发言内容"}, '
        '"reasoning_summary": "你的简短推理（中文）"}\n'
        "不要返回 {\"action\": \"speak\"} 这种格式。\n"
        "注意：reasoning_summary 是你的内心推理，只有观战者能看到，不会作为公开发言。\n"
        "参选警长时 content 才是公开发言内容，reasoning_summary 不能代替。\n"
        f"\n可选动作及其JSON格式：\n{action_list}"
    )


class BaseAgent:
    """基础 Agent。输入 PlayerView，输出 AgentDecision。

    不直接访问 TruthState —— 只能通过 PlayerView 获取信息。
    """

    def __init__(self, llm_client: LLMClient):
        self._llm_client = llm_client

    @property
    def role(self) -> Role:
        raise NotImplementedError

    def _system_prompt(self) -> str:
        return get_role_prompt(self.role)

    def decide(self, view: PlayerView) -> AgentDecision:
        """基于 PlayerView 做出决策。解析失败时自动重试最多 3 次。"""
        if view.own_role != self.role:
            raise AgentDecisionError(
                f"Agent 角色 {self.role.value} 与视图身份 {view.own_role.value} 不一致"
            )

        system_prompt = self._system_prompt()
        user_message = _build_user_message(view)

        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_message),
        ]

        last_error: Exception | None = None
        for attempt in range(3):
            logger.debug("Agent %s sending request (attempt %d)", self.role.value, attempt + 1)
            response = self._llm_client.chat_json(
                messages,
                temperature=0.7 if attempt == 0 else 0.3,
                max_tokens=1024,
                response_format={"type": "json_object"},
            )

            logger.debug("Agent %s raw response: %s", self.role.value, response.content[:500])

            try:
                decision = self._parse_response(response.content)
                self._validate_decision(decision, view.available_actions)
                logger.debug(
                    "Agent %s decided: action_type=%s reasoning=%s",
                    self.role.value,
                    decision.action.action_type.value,
                    decision.reasoning_summary[:80] if decision.reasoning_summary else "",
                )
                return decision
            except AgentDecisionError as exc:
                last_error = exc
                logger.warning(
                    "Agent %s parse failed (attempt %d/3): %s. Raw: %s",
                    self.role.value, attempt + 1, exc, response.content[:300],
                )
                # Append correction and retry
                messages.append(ChatMessage(
                    role="assistant",
                    content=response.content[:200],
                ))
                messages.append(ChatMessage(
                    role="user",
                    content=(
                        "你上一次返回的内容不是合法的 JSON 对象。"
                        "请严格只返回一个 JSON 对象，顶层必须是字典，包含 action 和 reasoning_summary 两个字段。"
                        "不要返回数字、字符串、列表或其他类型。"
                    ),
                ))

        raise AgentDecisionError(
            f"Agent {self.role.value} 重试 3 次后仍然解析失败。最后一次错误: {last_error}"
        ) from last_error

    def _parse_response(self, content: str) -> AgentDecision:
        """将 LLM 返回的内容解析为 AgentDecision。

        Handles common OpenAI-compatible model failures:
        - response wrapped in markdown fences
        - trailing text after the JSON object
        - plain number/string instead of object
        """
        text = content.strip()
        if not text:
            raise AgentDecisionError("LLM 返回了空内容，无法解析为决策")

        # Try to extract JSON object even when wrapped in markdown or trailing text
        json_text = text
        if not text.startswith("{"):
            start = text.find("{")
            if start != -1:
                end = text.rfind("}")
                if end > start:
                    json_text = text[start : end + 1]

        try:
            data = json.loads(json_text)
        except json.JSONDecodeError:
            raise AgentDecisionError(
                f"LLM 返回的内容不是合法的 JSON。原始内容: {text[:200]}"
            )

        if not isinstance(data, dict):
            raise AgentDecisionError(
                f"LLM 返回的 JSON 顶层必须是对象，当前类型: {type(data).__name__}。"
                f"原始内容: {text[:200]}"
            )

        if "action" not in data:
            raise AgentDecisionError(
                f"LLM 返回的 JSON 缺少 'action' 字段。返回数据: {data}"
            )

        try:
            return AgentDecision.model_validate(data)
        except Exception as exc:
            raise AgentDecisionError(
                f"LLM 返回的 JSON 无法解析为 AgentDecision。"
                f"解析错误: {exc}。原始数据: {data}"
            ) from exc

    def _validate_decision(
        self, decision: AgentDecision, available_actions: list[str]
    ) -> None:
        """校验决策动作在允许的行动空间中。"""
        action_value = decision.action.action_type.value

        if action_value not in available_actions:
            raise AgentDecisionError(
                f"Agent 返回了不在可用动作列表中的动作: '{action_value}'。"
                f"当前可用动作: {available_actions}"
            )

        # 校验目标座位号：对于有 target_seat_no 的动作，target 不能是 viewer 自己（speak 和 vote 除外）
        action = decision.action
        if hasattr(action, "target_seat_no") and action.target_seat_no is not None:
            # 具体业务校验留给上层（如不能杀狼队友等）
            pass
