from __future__ import annotations

from app.agents.schemas import (
    ActionType,
    AgentDecision,
    SeerCheckAction,
    SpeakAction,
    VoteAction,
    WerewolfKillAction,
    WitchAction,
)
from app.state.schemas import GamePhase, Role
from app.state.view_builder import PlayerView

# ── Chinese speech templates per role ────────────────────────────────────────

_SPEECH_TEMPLATES: dict[Role, list[str]] = {
    Role.werewolf: [
        "我是普通村民，目前局势不太明朗，希望预言家能给出查验结果。",
        "我觉得大家要冷静分析，不要轻易下结论。先听听预言家的发言。",
        "暂时没有特别明确的怀疑对象，但我建议大家多观察发言较少的人。",
    ],
    Role.seer: [
        "我昨晚查验了{target}号，是{result}，大家今天可以重点考虑。",
        "目前我掌握了一些信息，但还不完整。请大家理性讨论，不要盲从。",
        "作为预言家，我会继续查验可疑目标，希望大家今天投票时慎重。",
    ],
    Role.witch: [
        "我手上有药，但暂时不打算使用。大家先发言，我看看局势。",
        "目前情况比较复杂，但我认为我们应该团结一致，找出狼人。",
        "我会根据今晚的情况决定是否用药。请大家今天积极发言。",
    ],
    Role.villager: [
        "我是平民，没有什么特殊信息。但我认为{target}号的发言有点可疑。",
        "我建议大家多关注发言内容，看看谁在刻意引导方向。",
        "票型是最真实的，让我们通过投票来验证猜测。",
    ],
}

_FALLBACK_SPEECH: dict[Role, str] = {
    Role.werewolf: "我觉得我们要保持耐心，不要急于下结论。",
    Role.seer: "请大家理性分析，我会继续提供查验结果。",
    Role.witch: "大家先冷静，我今晚会看情况采取行动。",
    Role.villager: "我没有特殊信息，只能依靠大家的分析来判断。",
}


def _pick_other_alive(view: PlayerView) -> int | None:
    """Pick the first alive player who is not the viewer."""
    for p in view.players:
        if p.alive and p.seat_no != view.viewer_seat_no:
            return p.seat_no
    return None


def _night_decision(view: PlayerView) -> AgentDecision:
    actions = view.available_actions

    if ActionType.werewolf_kill.value in actions:
        # Kill first alive non-wolf (non wolf-team) player
        wolf_team = set(view.known_wolf_team)
        for p in view.players:
            if p.alive and p.seat_no not in wolf_team:
                return AgentDecision(
                    action=WerewolfKillAction(target_seat_no=p.seat_no),
                    reasoning_summary=f"狼队选择猎杀{p.seat_no}号",
                )
        return AgentDecision(
            action=WerewolfKillAction(target_seat_no=view.viewer_seat_no),
            reasoning_summary="无有效目标",
        )

    if ActionType.seer_check.value in actions:
        # Check first alive player who hasn't been checked (tracked roughly
        # by avoiding self)
        target = _pick_other_alive(view)
        if target is None:
            target = view.viewer_seat_no
        return AgentDecision(
            action=SeerCheckAction(target_seat_no=target),
            reasoning_summary=f"预言家查验{target}号",
        )

    if ActionType.witch_save.value in actions or ActionType.witch_poison.value in actions:
        # Check if informed of kill target
        kill_target = None
        for evt in view.public_events:
            if evt.get("type") == "night_kill_info":
                kill_target = evt.get("killed_seat_no")
        if kill_target is not None:
            # Save the killed player if they are not a known wolf
            if kill_target not in view.known_wolf_team:
                return AgentDecision(
                    action=WitchAction(action_type=ActionType.witch_save, target_seat_no=kill_target),
                    reasoning_summary=f"使用解药救{kill_target}号",
                )
            # Killed target is a teammate — poison someone else
            other = _pick_other_alive(view)
            return AgentDecision(
                action=WitchAction(action_type=ActionType.witch_poison, target_seat_no=other or view.viewer_seat_no),
                reasoning_summary=f"使用毒药毒杀{other or view.viewer_seat_no}号",
            )
        # No kill info — save self as no-op
        return AgentDecision(
            action=WitchAction(action_type=ActionType.witch_save, target_seat_no=view.viewer_seat_no),
            reasoning_summary="今夜无人死亡，不使用解药",
        )

    # Fallback: shouldn't reach here
    return AgentDecision(
        action=SpeakAction(content=_FALLBACK_SPEECH.get(view.own_role, "无行动。")),
        reasoning_summary="无可用的夜间动作",
    )


def _day_decision(view: PlayerView) -> AgentDecision:
    # Use round number to pick a varied template
    templates = _SPEECH_TEMPLATES.get(view.own_role, _SPEECH_TEMPLATES[Role.villager])
    idx = view.round % len(templates)
    content = templates[idx]

    # For seer, try to fill in target/result from previous seer_check events
    if view.own_role == Role.seer:
        # Look for a prior seer_check result in public events
        check_target = None
        check_result = None
        for evt in view.public_events:
            if evt.get("type") == "night_resolved" and evt.get("seer_result") is not None:
                # Find the seer_check action to get the target
                pass
        # Look in public events for seer's own request (simplified: we
        # don't have the result in PlayerView, so use a generic line)
        content = content.format(target="?", result="?")
    elif view.own_role == Role.villager:
        other = _pick_other_alive(view)
        content = content.format(target=str(other or "?"))
    else:
        # For werewolf and witch, format if needed
        pass

    return AgentDecision(
        action=SpeakAction(content=content),
        reasoning_summary=f"{view.own_role.value}在第{view.round}轮发言",
    )


def _vote_decision(view: PlayerView) -> AgentDecision:
    # Vote for the first alive non-self player
    target = _pick_other_alive(view)
    return AgentDecision(
        action=VoteAction(target_seat_no=target),
        reasoning_summary=f"投票给{target}号" if target else "弃票",
    )


# ── Main agent class ─────────────────────────────────────────────────────────


class ScriptedAgent:
    """A deterministic, rule-based agent for API demos and testing.

    Does **not** call any LLM.  Decisions are purely based on ``PlayerView``
    (the same information-isolation contract as the real agents).
    """

    def __init__(self, role: Role):
        self._role = role

    @property
    def role(self) -> Role:
        return self._role

    def decide(self, view: PlayerView) -> AgentDecision:
        phase = view.phase

        if phase == GamePhase.night:
            return _night_decision(view)
        elif phase == GamePhase.day:
            return _day_decision(view)
        elif phase == GamePhase.vote:
            return _vote_decision(view)
        else:
            return AgentDecision(
                action=SpeakAction(content="等待游戏开始。"),
                reasoning_summary="setup/ended 阶段无动作",
            )
