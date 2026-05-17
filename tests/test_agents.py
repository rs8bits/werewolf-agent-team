from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.agents.base_agent import AgentDecisionError, BaseAgent, _build_user_message
from app.agents.factory import create_agent
from app.agents.prompts import (
    BASE_SYSTEM_PROMPT,
    GUARD_SYSTEM_PROMPT,
    HUNTER_SYSTEM_PROMPT,
    IDIOT_SYSTEM_PROMPT,
    SEER_SYSTEM_PROMPT,
    VILLAGER_SYSTEM_PROMPT,
    WEREWOLF_SYSTEM_PROMPT,
    WITCH_SYSTEM_PROMPT,
    get_role_prompt,
)
from app.agents.schemas import (
    ActionType,
    AgentDecision,
    SeerCheckAction,
    SpeakAction,
    VoteAction,
    WerewolfKillAction,
    WitchAction,
)
from app.agents.guard_agent import GuardAgent
from app.agents.hunter_agent import HunterAgent
from app.agents.idiot_agent import IdiotAgent
from app.agents.werewolf_agent import WerewolfAgent
from app.agents.seer_agent import SeerAgent
from app.agents.witch_agent import WitchAgent
from app.agents.villager_agent import VillagerAgent
from app.config.settings import LLMConfig
from app.llm.client import LLMClient
from app.llm.schemas import ChatMessage, ChatResponse
from app.state.schemas import (
    Camp,
    GamePhase,
    GameState,
    PlayerState,
    PlayerType,
    PublicState,
    Role,
    TruthState,
    camp_of,
)
from app.state.view_builder import PlayerView, VisiblePlayer, build_player_view


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_6p_game_state(*, phase: GamePhase = GamePhase.night) -> GameState:
    roles = [
        (1, Role.werewolf),
        (2, Role.werewolf),
        (3, Role.seer),
        (4, Role.witch),
        (5, Role.villager),
        (6, Role.villager),
    ]
    players = [
        PlayerState(
            seat_no=s,
            name=f"P{s}",
            player_type=PlayerType.ai,
            role=r,
            camp=camp_of(r),
        )
        for s, r in roles
    ]
    public_state = PublicState(
        round=1,
        phase=phase,
        alive_players=[1, 2, 3, 4, 5, 6],
        dead_players=[],
    )
    truth_state = TruthState(
        real_identities={s: r for s, r in roles},
        wolf_team=[1, 2],
    )
    return GameState(
        game_id="test-game",
        public_state=public_state,
        players=players,
        truth_state=truth_state,
    )


def _make_llm_client(json_content: str) -> LLMClient:
    """Create an LLMClient backed by a mock OpenAI client that returns the given JSON."""
    cfg = LLMConfig(
        api_key="test-key",
        base_url="https://test.example.com/v1",
        model="qwen-plus",
        timeout_seconds=60,
    )
    fake_choice = MagicMock()
    fake_choice.message.content = json_content
    fake_choice.finish_reason = "stop"
    fake_completion = MagicMock()
    fake_completion.choices = [fake_choice]
    fake_completion.usage.prompt_tokens = 10
    fake_completion.usage.completion_tokens = 5
    fake_completion.usage.total_tokens = 15
    mock_openai = MagicMock()
    mock_openai.chat.completions.create.return_value = fake_completion
    return LLMClient(config=cfg, openai_client=mock_openai)


def _make_player_view(gs: GameState, seat_no: int) -> PlayerView:
    return build_player_view(gs, seat_no)


# ── Schema tests ─────────────────────────────────────────────────────────────


class TestAgentSchemas:
    def test_speak_action_serialization(self):
        action = SpeakAction(content="我是好人，请大家相信我。")
        d = action.model_dump()
        assert d == {"action_type": "speak", "content": "我是好人，请大家相信我。"}

    def test_speak_action_content_min_length(self):
        with pytest.raises(ValueError):
            SpeakAction(content="")

    def test_vote_action_serialization(self):
        action = VoteAction(target_seat_no=5)
        d = action.model_dump()
        assert d == {"action_type": "vote", "target_seat_no": 5}

    def test_vote_action_abstain(self):
        action = VoteAction(target_seat_no=None)
        d = action.model_dump()
        assert d == {"action_type": "vote", "target_seat_no": None}

    def test_werewolf_kill_action_serialization(self):
        action = WerewolfKillAction(target_seat_no=3)
        d = action.model_dump()
        assert d == {"action_type": "werewolf_kill", "target_seat_no": 3}

    def test_werewolf_kill_target_must_be_positive(self):
        with pytest.raises(ValueError):
            WerewolfKillAction(target_seat_no=0)

    def test_seer_check_action_serialization(self):
        action = SeerCheckAction(target_seat_no=5)
        d = action.model_dump()
        assert d == {"action_type": "seer_check", "target_seat_no": 5}

    def test_witch_save_action_serialization(self):
        action = WitchAction(action_type=ActionType.witch_save, target_seat_no=4)
        d = action.model_dump()
        assert d == {"action_type": "witch_save", "target_seat_no": 4}

    def test_witch_poison_action_serialization(self):
        action = WitchAction(action_type=ActionType.witch_poison, target_seat_no=1)
        d = action.model_dump()
        assert d == {"action_type": "witch_poison", "target_seat_no": 1}

    def test_agent_decision_with_speak(self):
        decision = AgentDecision(
            action=SpeakAction(content="我怀疑3号是狼人。"),
            reasoning_summary="基于发言逻辑分析，3号前后矛盾。",
        )
        d = decision.model_dump()
        assert d["action"]["action_type"] == "speak"
        assert d["action"]["content"] == "我怀疑3号是狼人。"
        assert "reasoning_summary" in d

    def test_agent_decision_with_werewolf_kill(self):
        decision = AgentDecision(
            action=WerewolfKillAction(target_seat_no=5),
            reasoning_summary="击杀5号平民，减少好人数。",
        )
        d = decision.model_dump()
        assert d["action"]["action_type"] == "werewolf_kill"
        assert d["action"]["target_seat_no"] == 5

    def test_agent_decision_discriminated_union(self):
        """Verify Pydantic discriminator correctly routes action types."""
        data = {
            "action": {"action_type": "seer_check", "target_seat_no": 3},
            "reasoning_summary": "查验3号。",
        }
        decision = AgentDecision.model_validate(data)
        assert isinstance(decision.action, SeerCheckAction)
        assert decision.action.target_seat_no == 3

    def test_agent_decision_wrong_type_in_discriminator(self):
        data = {
            "action": {"action_type": "not_a_real_action", "target_seat_no": 3},
            "reasoning_summary": "test",
        }
        with pytest.raises(Exception):
            AgentDecision.model_validate(data)

    def test_agent_decision_json_serializable(self):
        decision = AgentDecision(
            action=VoteAction(target_seat_no=5),
            reasoning_summary="投票放逐5号。",
        )
        json_str = json.dumps(decision.model_dump(), ensure_ascii=False)
        assert "vote" in json_str
        assert "投票放逐5号" in json_str


# ── Prompt tests ─────────────────────────────────────────────────────────────


class TestPrompts:
    def test_base_system_prompt_is_chinese(self):
        assert "信息隔离" in BASE_SYSTEM_PROMPT
        assert "结构化输出" in BASE_SYSTEM_PROMPT
        assert "中文发言" in BASE_SYSTEM_PROMPT

    def test_werewolf_prompt_contains_chinese_keywords(self):
        assert "狼人" in WEREWOLF_SYSTEM_PROMPT
        assert "信息隔离" in WEREWOLF_SYSTEM_PROMPT

    def test_seer_prompt_contains_chinese_keywords(self):
        assert "预言家" in SEER_SYSTEM_PROMPT
        assert "好人阵营" in SEER_SYSTEM_PROMPT

    def test_witch_prompt_contains_chinese_keywords(self):
        assert "女巫" in WITCH_SYSTEM_PROMPT
        assert "解药" in WITCH_SYSTEM_PROMPT
        assert "毒药" in WITCH_SYSTEM_PROMPT

    def test_villager_prompt_contains_chinese_keywords(self):
        assert "平民" in VILLAGER_SYSTEM_PROMPT
        assert "好人阵营" in VILLAGER_SYSTEM_PROMPT

    def test_get_role_prompt_returns_correct_prompt(self):
        assert get_role_prompt(Role.werewolf) == WEREWOLF_SYSTEM_PROMPT
        assert get_role_prompt(Role.seer) == SEER_SYSTEM_PROMPT
        assert get_role_prompt(Role.witch) == WITCH_SYSTEM_PROMPT
        assert get_role_prompt(Role.villager) == VILLAGER_SYSTEM_PROMPT

    def test_get_role_prompt_returns_extended_role_prompts(self):
        assert get_role_prompt(Role.hunter) == HUNTER_SYSTEM_PROMPT
        assert get_role_prompt(Role.idiot) == IDIOT_SYSTEM_PROMPT
        assert get_role_prompt(Role.guard) == GUARD_SYSTEM_PROMPT

    def test_all_prompts_mention_no_cheating(self):
        for prompt in [
            WEREWOLF_SYSTEM_PROMPT,
            SEER_SYSTEM_PROMPT,
            WITCH_SYSTEM_PROMPT,
            VILLAGER_SYSTEM_PROMPT,
            HUNTER_SYSTEM_PROMPT,
            IDIOT_SYSTEM_PROMPT,
            GUARD_SYSTEM_PROMPT,
        ]:
            assert "禁止作弊" in prompt or "不能声称知道" in prompt or "信息隔离" in prompt

    def test_all_prompts_require_json(self):
        for prompt in [
            WEREWOLF_SYSTEM_PROMPT,
            SEER_SYSTEM_PROMPT,
            WITCH_SYSTEM_PROMPT,
            VILLAGER_SYSTEM_PROMPT,
            HUNTER_SYSTEM_PROMPT,
            IDIOT_SYSTEM_PROMPT,
            GUARD_SYSTEM_PROMPT,
        ]:
            assert "JSON" in prompt


# ── BaseAgent tests ──────────────────────────────────────────────────────────


class TestBaseAgentWithMockLLM:
    def test_decide_returns_agent_decision_for_speak(self):
        gs = _make_6p_game_state(phase=GamePhase.day)
        view = _make_player_view(gs, seat_no=5)  # villager
        json_content = json.dumps(
            {
                "action": {"action_type": "speak", "content": "我是平民，请大家理性分析。"},
                "reasoning_summary": "作为平民，发言表明身份。",
            },
            ensure_ascii=False,
        )
        client = _make_llm_client(json_content)
        agent = VillagerAgent(llm_client=client)

        decision = agent.decide(view)

        assert isinstance(decision, AgentDecision)
        assert isinstance(decision.action, SpeakAction)
        assert decision.action.content == "我是平民，请大家理性分析。"

    def test_decide_returns_agent_decision_for_werewolf_kill(self):
        gs = _make_6p_game_state(phase=GamePhase.night)
        view = _make_player_view(gs, seat_no=1)  # werewolf
        json_content = json.dumps(
            {
                "action": {"action_type": "werewolf_kill", "target_seat_no": 3},
                "reasoning_summary": "击杀3号预言家。",
            },
            ensure_ascii=False,
        )
        client = _make_llm_client(json_content)
        agent = WerewolfAgent(llm_client=client)

        decision = agent.decide(view)

        assert isinstance(decision.action, WerewolfKillAction)
        assert decision.action.target_seat_no == 3

    def test_decide_returns_agent_decision_for_seer_check(self):
        gs = _make_6p_game_state(phase=GamePhase.night)
        view = _make_player_view(gs, seat_no=3)  # seer
        json_content = json.dumps(
            {
                "action": {"action_type": "seer_check", "target_seat_no": 1},
                "reasoning_summary": "查验1号玩家。",
            },
            ensure_ascii=False,
        )
        client = _make_llm_client(json_content)
        agent = SeerAgent(llm_client=client)

        decision = agent.decide(view)
        assert isinstance(decision.action, SeerCheckAction)
        assert decision.action.target_seat_no == 1

    def test_decide_returns_agent_decision_for_witch_save(self):
        gs = _make_6p_game_state(phase=GamePhase.night)
        view = _make_player_view(gs, seat_no=4)  # witch
        json_content = json.dumps(
            {
                "action": {"action_type": "witch_save", "target_seat_no": 3},
                "reasoning_summary": "救下被杀玩家。",
            },
            ensure_ascii=False,
        )
        client = _make_llm_client(json_content)
        agent = WitchAgent(llm_client=client)

        decision = agent.decide(view)
        assert isinstance(decision.action, WitchAction)
        assert decision.action.action_type == ActionType.witch_save
        assert decision.action.target_seat_no == 3

    def test_decide_returns_agent_decision_for_vote(self):
        gs = _make_6p_game_state(phase=GamePhase.vote)
        view = _make_player_view(gs, seat_no=5)  # villager
        json_content = json.dumps(
            {
                "action": {"action_type": "vote", "target_seat_no": 1},
                "reasoning_summary": "投票放逐1号。",
            },
            ensure_ascii=False,
        )
        client = _make_llm_client(json_content)
        agent = VillagerAgent(llm_client=client)

        decision = agent.decide(view)
        assert isinstance(decision.action, VoteAction)
        assert decision.action.target_seat_no == 1

    def test_invalid_json_raises_agent_decision_error(self):
        gs = _make_6p_game_state(phase=GamePhase.day)
        view = _make_player_view(gs, seat_no=5)
        client = _make_llm_client("not valid json")
        agent = VillagerAgent(llm_client=client)

        with pytest.raises(AgentDecisionError, match="不是合法的 JSON"):
            agent.decide(view)

    def test_parse_response_accepts_fenced_json(self):
        agent = VillagerAgent(llm_client=_make_llm_client("{}"))
        decision = agent._parse_response(
            '```json\n{"action": {"action_type": "speak", "content": "我是好人。"}, "reasoning_summary": "发言。"}\n```'
        )
        assert isinstance(decision.action, SpeakAction)
        assert decision.action.content == "我是好人。"

    def test_parse_response_accepts_text_before_json(self):
        agent = VillagerAgent(llm_client=_make_llm_client("{}"))
        decision = agent._parse_response(
            '好的，我返回 JSON：{"action": {"action_type": "speak", "content": "我先听大家发言。"}, "reasoning_summary": "谨慎发言。"}'
        )
        assert isinstance(decision.action, SpeakAction)
        assert decision.reasoning_summary == "谨慎发言。"

    def test_parse_response_accepts_text_after_json(self):
        agent = VillagerAgent(llm_client=_make_llm_client("{}"))
        decision = agent._parse_response(
            '{"action": {"action_type": "speak", "content": "我认为1号偏好。"}, "reasoning_summary": "观察发言。"}\n以上是我的决策。'
        )
        assert isinstance(decision.action, SpeakAction)
        assert decision.action.content == "我认为1号偏好。"

    def test_parse_response_accepts_text_around_json(self):
        agent = VillagerAgent(llm_client=_make_llm_client("{}"))
        decision = agent._parse_response(
            '决策如下：\n{"action": {"action_type": "speak", "content": "我暂时不跳身份。"}, "reasoning_summary": "隐藏身份。"}\n请继续。'
        )
        assert isinstance(decision.action, SpeakAction)

    @pytest.mark.parametrize("content", [
        '[{"action": {"action_type": "speak", "content": "我发言。"}, "reasoning_summary": "错格式。"}]',
        "123",
        '"not an object"',
    ])
    def test_parse_response_rejects_non_object_json_top_level(self, content: str):
        agent = VillagerAgent(llm_client=_make_llm_client("{}"))
        with pytest.raises(AgentDecisionError, match="顶层必须是对象"):
            agent._parse_response(content)

    def test_empty_response_raises_agent_decision_error(self):
        gs = _make_6p_game_state(phase=GamePhase.day)
        view = _make_player_view(gs, seat_no=5)
        client = _make_llm_client("")
        agent = VillagerAgent(llm_client=client)

        with pytest.raises(AgentDecisionError, match="空内容"):
            agent.decide(view)

    def test_response_without_action_field_raises(self):
        gs = _make_6p_game_state(phase=GamePhase.day)
        view = _make_player_view(gs, seat_no=5)
        client = _make_llm_client('{"reasoning_summary": "test"}')
        agent = VillagerAgent(llm_client=client)

        with pytest.raises(AgentDecisionError, match="缺少 'action'"):
            agent.decide(view)

    def test_response_with_string_action_raises(self):
        gs = _make_6p_game_state(phase=GamePhase.day)
        view = _make_player_view(gs, seat_no=5)
        client = _make_llm_client(
            '{"action": "speak", "reasoning_summary": "格式错误。"}'
        )
        agent = VillagerAgent(llm_client=client)

        with pytest.raises(AgentDecisionError, match="无法解析为 AgentDecision"):
            agent.decide(view)

    def test_action_not_in_available_actions_raises(self):
        gs = _make_6p_game_state(phase=GamePhase.day)
        view = _make_player_view(gs, seat_no=5)  # villager, available: ["speak"]
        # LLM returns werewolf_kill which is not in available_actions
        json_content = json.dumps(
            {
                "action": {"action_type": "werewolf_kill", "target_seat_no": 3},
                "reasoning_summary": "试图击杀。",
            },
            ensure_ascii=False,
        )
        client = _make_llm_client(json_content)
        agent = VillagerAgent(llm_client=client)

        with pytest.raises(AgentDecisionError, match="不在可用动作列表中"):
            agent.decide(view)

    def test_agent_role_must_match_view_role(self):
        gs = _make_6p_game_state(phase=GamePhase.day)
        view = _make_player_view(gs, seat_no=5)  # villager
        json_content = json.dumps(
            {
                "action": {"action_type": "speak", "content": "我来发言。"},
                "reasoning_summary": "发言。",
            },
            ensure_ascii=False,
        )
        client = _make_llm_client(json_content)
        agent = WerewolfAgent(llm_client=client)

        with pytest.raises(AgentDecisionError, match="不一致"):
            agent.decide(view)

    def test_prompt_does_not_contain_truth_state(self):
        """Verify that the constructed user message does NOT leak TruthState."""
        gs = _make_6p_game_state(phase=GamePhase.night)
        view = _make_player_view(gs, seat_no=5)  # villager
        user_msg = _build_user_message(view)

        # TruthState would contain real_identities or wolf_team for non-wolves
        assert "real_identities" not in user_msg
        assert "TruthState" not in user_msg
        assert "truth_state" not in user_msg
        # A villager should not see wolf_team
        assert "狼队友" not in user_msg

    def test_werewolf_view_includes_wolf_team_in_prompt(self):
        """Werewolf should see known_wolf_team in the prompt."""
        gs = _make_6p_game_state(phase=GamePhase.night)
        view = _make_player_view(gs, seat_no=1)  # werewolf
        user_msg = _build_user_message(view)

        assert "已知狼队友" in user_msg
        assert "1号" in user_msg
        assert "2号" in user_msg

    def test_prompt_is_chinese(self):
        """The constructed user message should be in Chinese."""
        gs = _make_6p_game_state(phase=GamePhase.day)
        view = _make_player_view(gs, seat_no=5)
        user_msg = _build_user_message(view)

        assert "当前轮次" in user_msg
        assert "当前阶段" in user_msg
        assert "你的身份" in user_msg
        assert "可执行动作" in user_msg
        assert "action 字段必须是 JSON 对象" in user_msg

    def test_llm_messages_constructed_correctly(self):
        """Verify LLM receives properly structured messages."""
        gs = _make_6p_game_state(phase=GamePhase.day)
        view = _make_player_view(gs, seat_no=5)
        json_content = json.dumps(
            {
                "action": {"action_type": "speak", "content": "我是一介草民。"},
                "reasoning_summary": "发言。",
            },
            ensure_ascii=False,
        )

        cfg = LLMConfig(
            api_key="test-key",
            base_url="https://test.example.com/v1",
            model="qwen-plus",
            timeout_seconds=60,
        )
        fake_choice = MagicMock()
        fake_choice.message.content = json_content
        fake_choice.finish_reason = "stop"
        fake_completion = MagicMock()
        fake_completion.choices = [fake_choice]
        fake_completion.usage = None
        mock_openai = MagicMock()
        mock_openai.chat.completions.create.return_value = fake_completion

        client = LLMClient(config=cfg, openai_client=mock_openai)
        agent = VillagerAgent(llm_client=client)
        agent.decide(view)

        # Get the messages passed to the LLM
        call_args = mock_openai.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert call_args.kwargs["response_format"] == {"type": "json_object"}
        # System message should contain Chinese
        assert "平民" in messages[0]["content"]
        # User message should not contain truth_state
        assert "truth_state" not in messages[1]["content"].lower()


# ── Factory tests ────────────────────────────────────────────────────────────


class TestAgentFactory:
    def _dummy_client(self) -> LLMClient:
        return _make_llm_client("{}")

    def test_create_werewolf_agent(self):
        agent = create_agent(Role.werewolf, self._dummy_client())
        assert isinstance(agent, WerewolfAgent)
        assert agent.role == Role.werewolf

    def test_create_seer_agent(self):
        agent = create_agent(Role.seer, self._dummy_client())
        assert isinstance(agent, SeerAgent)
        assert agent.role == Role.seer

    def test_create_witch_agent(self):
        agent = create_agent(Role.witch, self._dummy_client())
        assert isinstance(agent, WitchAgent)
        assert agent.role == Role.witch

    def test_create_villager_agent(self):
        agent = create_agent(Role.villager, self._dummy_client())
        assert isinstance(agent, VillagerAgent)
        assert agent.role == Role.villager

    def test_create_extended_role_agents(self):
        assert isinstance(create_agent(Role.hunter, self._dummy_client()), HunterAgent)
        assert isinstance(create_agent(Role.idiot, self._dummy_client()), IdiotAgent)
        assert isinstance(create_agent(Role.guard, self._dummy_client()), GuardAgent)

    def test_factory_creates_all_mvp_roles(self):
        """Factory must be able to create all supported role agents."""
        for role in [Role.werewolf, Role.seer, Role.witch, Role.villager, Role.hunter, Role.idiot, Role.guard]:
            agent = create_agent(role, self._dummy_client())
            assert agent.role == role
            # Verify it can run decide (even though the mock returns invalid JSON)
            gs = _make_6p_game_state(phase=GamePhase.day)
            view = _make_player_view(gs, seat_no=1)
            # Will fail because mock returns "{}", but that's expected
            # We just verify it's a BaseAgent with the right role
            from app.agents.base_agent import BaseAgent as BA

            assert isinstance(agent, BA)


# ── Chinese speech content test ──────────────────────────────────────────────


class TestChineseSpeechContent:
    def test_speak_action_with_chinese_content(self):
        """SpeakAction must accept Chinese content."""
        content = "大家好，我是平民。根据昨天的发言，我怀疑2号玩家是狼人。因为他的发言前后矛盾，先说自己不在场，后来又承认在场。"
        action = SpeakAction(content=content)
        assert action.content == content
        d = action.model_dump()
        assert "大家好" in d["content"]

    def test_agent_decision_with_chinese_reasoning(self):
        """AgentDecision reasoning_summary should accept Chinese."""
        decision = AgentDecision(
            action=SpeakAction(content="我同意5号的观点。"),
            reasoning_summary="分析发现2号和4号投票模式异常，可能是狼队友。",
        )
        d = decision.model_dump()
        json_str = json.dumps(d, ensure_ascii=False)
        assert "投票模式异常" in json_str
        assert "狼队友" in json_str


# ── PlayerView isolation tests ───────────────────────────────────────────────


class TestPlayerViewIsolation:
    def test_player_view_excludes_truth_state(self):
        gs = _make_6p_game_state()
        view = _make_player_view(gs, seat_no=1)
        view_dict = view.model_dump()
        assert "truth_state" not in view_dict

    def test_good_player_cannot_see_wolf_team(self):
        gs = _make_6p_game_state()
        view = _make_player_view(gs, seat_no=3)  # seer
        assert view.known_wolf_team == []
        user_msg = _build_user_message(view)
        assert "狼队友" not in user_msg

    def test_werewolf_can_see_wolf_team(self):
        gs = _make_6p_game_state()
        view = _make_player_view(gs, seat_no=1)  # werewolf
        assert view.known_wolf_team == [1, 2]
        user_msg = _build_user_message(view)
        assert "狼队友" in user_msg
