from __future__ import annotations

import pytest

from app.state.schemas import (
    Camp,
    GamePhase,
    GameState,
    PlayerState,
    PlayerStatus,
    PlayerType,
    PublicState,
    Role,
    RuntimeState,
    SeerCheckRecord,
    TruthState,
)
from app.state.view_builder import (
    PlayerView,
    VisiblePlayer,
    _compress_old_speeches,
    build_player_view,
)


def _make_6p_game_state(phase: GamePhase = GamePhase.night) -> GameState:
    players = [
        PlayerState(seat_no=1, name="P1", player_type=PlayerType.ai, role=Role.werewolf, camp=Camp.werewolf),
        PlayerState(seat_no=2, name="P2", player_type=PlayerType.ai, role=Role.werewolf, camp=Camp.werewolf),
        PlayerState(seat_no=3, name="P3", player_type=PlayerType.ai, role=Role.seer, camp=Camp.good),
        PlayerState(seat_no=4, name="P4", player_type=PlayerType.ai, role=Role.witch, camp=Camp.good),
        PlayerState(seat_no=5, name="P5", player_type=PlayerType.ai, role=Role.villager, camp=Camp.good),
        PlayerState(seat_no=6, name="P6", player_type=PlayerType.ai, role=Role.villager, camp=Camp.good),
    ]
    public_state = PublicState(
        round=1,
        phase=phase,
        alive_players=[1, 2, 3, 4, 5, 6],
        dead_players=[],
        public_events=[{"type": "night_start"}],
    )
    truth_state = TruthState(
        real_identities={1: Role.werewolf, 2: Role.werewolf, 3: Role.seer, 4: Role.witch, 5: Role.villager, 6: Role.villager},
        wolf_team=[1, 2],
        night_actions=[],
    )
    return GameState(
        game_id="test-game",
        public_state=public_state,
        players=players,
        truth_state=truth_state,
    )


# ── Wolf view ──────────────────────────────────────────────────────────────────


class TestWolfView:
    def test_wolf_sees_wolf_team(self):
        gs = _make_6p_game_state()
        view = build_player_view(gs, 1)
        assert view.known_wolf_team == [1, 2]
        assert view.own_role == Role.werewolf
        assert view.own_camp == Camp.werewolf

    def test_wolf_night_actions(self):
        gs = _make_6p_game_state(phase=GamePhase.night)
        view = build_player_view(gs, 1)
        assert view.available_actions == ["werewolf_kill"]


# ── Good views must not see wolf team ──────────────────────────────────────────


class TestGoodViews:
    def test_seer_cannot_see_wolf_team(self):
        gs = _make_6p_game_state()
        view = build_player_view(gs, 3)
        assert view.known_wolf_team == []
        assert view.own_role == Role.seer
        assert view.own_camp == Camp.good

    def test_witch_cannot_see_wolf_team(self):
        gs = _make_6p_game_state()
        view = build_player_view(gs, 4)
        assert view.known_wolf_team == []
        assert view.own_role == Role.witch

    def test_villager_cannot_see_wolf_team(self):
        gs = _make_6p_game_state()
        view = build_player_view(gs, 5)
        assert view.known_wolf_team == []
        assert view.own_role == Role.villager


class TestPlayerViewResult:
    def test_view_includes_public_winner(self):
        gs = _make_6p_game_state(phase=GamePhase.ended)
        gs.winner = Camp.good
        view = build_player_view(gs, 5)

        assert view.winner == Camp.good
        assert view.model_dump(mode="json")["winner"] == "good"


# ── VisiblePlayer must not expose role or camp ─────────────────────────────────


class TestVisiblePlayer:
    def test_no_role_field(self):
        gs = _make_6p_game_state()
        view = build_player_view(gs, 1)
        for vp in view.players:
            assert "role" not in type(vp).model_fields

    def test_no_camp_field(self):
        gs = _make_6p_game_state()
        view = build_player_view(gs, 1)
        for vp in view.players:
            assert "camp" not in type(vp).model_fields

    def test_serialized_no_role_or_camp(self):
        gs = _make_6p_game_state()
        view = build_player_view(gs, 1)
        data = view.model_dump()
        for vp_data in data["players"]:
            assert "role" not in vp_data
            assert "camp" not in vp_data

    def test_visible_fields_present(self):
        gs = _make_6p_game_state()
        view = build_player_view(gs, 1)
        vp = view.players[0]
        assert vp.seat_no == 1
        assert vp.name == "P1"
        assert vp.player_type == PlayerType.ai
        assert vp.alive is True
        assert vp.can_vote is True


# ── Invalid seat ───────────────────────────────────────────────────────────────


class TestInvalidSeat:
    def test_nonexistent_seat_raises(self):
        gs = _make_6p_game_state()
        with pytest.raises(ValueError, match="seat_no=99"):
            build_player_view(gs, 99)

    def test_zero_seat_raises(self):
        gs = _make_6p_game_state()
        with pytest.raises(ValueError):
            build_player_view(gs, 0)

    def test_negative_seat_raises(self):
        gs = _make_6p_game_state()
        with pytest.raises(ValueError):
            build_player_view(gs, -1)


# ── available_actions per phase / role ─────────────────────────────────────────


class TestAvailableActions:
    def test_setup_all_empty(self):
        gs = _make_6p_game_state(phase=GamePhase.setup)
        for seat in range(1, 7):
            view = build_player_view(gs, seat)
            assert view.available_actions == []

    def test_night_werewolf(self):
        gs = _make_6p_game_state(phase=GamePhase.night)
        view = build_player_view(gs, 1)
        assert view.available_actions == ["werewolf_kill"]

    def test_night_seer(self):
        gs = _make_6p_game_state(phase=GamePhase.night)
        view = build_player_view(gs, 3)
        assert view.available_actions == ["seer_check"]

    def test_night_witch(self):
        gs = _make_6p_game_state(phase=GamePhase.night)
        view = build_player_view(gs, 4)
        assert view.available_actions == ["witch_save", "witch_poison"]

    def test_night_villager_empty(self):
        gs = _make_6p_game_state(phase=GamePhase.night)
        view = build_player_view(gs, 5)
        assert view.available_actions == []

    def test_night_dead_player_empty(self):
        gs = _make_6p_game_state(phase=GamePhase.night)
        gs.players[0].status.alive = False
        view = build_player_view(gs, 1)
        assert view.available_actions == []

    def test_day_all_speak(self):
        gs = _make_6p_game_state(phase=GamePhase.day)
        for seat in range(1, 7):
            view = build_player_view(gs, seat)
            assert view.available_actions == ["speak"]

    def test_day_dead_player_empty(self):
        gs = _make_6p_game_state(phase=GamePhase.day)
        gs.players[0].status.alive = False
        view = build_player_view(gs, 1)
        assert view.available_actions == []

    def test_vote_alive_player(self):
        gs = _make_6p_game_state(phase=GamePhase.vote)
        view = build_player_view(gs, 1)
        assert view.available_actions == ["vote"]

    def test_vote_dead_player_empty(self):
        gs = _make_6p_game_state(phase=GamePhase.vote)
        gs.players[0].status.alive = False
        view = build_player_view(gs, 1)
        assert view.available_actions == []

    def test_vote_no_vote_right_empty(self):
        gs = _make_6p_game_state(phase=GamePhase.vote)
        gs.players[0].status.can_vote = False
        view = build_player_view(gs, 1)
        assert view.available_actions == []

    def test_ended_all_empty(self):
        gs = _make_6p_game_state(phase=GamePhase.ended)
        for seat in range(1, 7):
            view = build_player_view(gs, seat)
            assert view.available_actions == []


# ── PlayerView must not contain truth_state ────────────────────────────────────


class TestNoTruthStateInView:
    def test_model_fields_excludes_truth_state(self):
        gs = _make_6p_game_state()
        view = build_player_view(gs, 1)
        assert "truth_state" not in type(view).model_fields

    def test_model_dump_excludes_truth_state(self):
        gs = _make_6p_game_state()
        view = build_player_view(gs, 1)
        data = view.model_dump()
        assert "truth_state" not in data

    def test_model_dump_json_excludes_truth_state(self):
        gs = _make_6p_game_state()
        view = build_player_view(gs, 1)
        data = view.model_dump_json()
        assert "truth_state" not in data


class TestPrivateInfoIsolation:
    def test_seer_checks_visible_only_to_seer(self):
        gs = _make_6p_game_state()
        gs.runtime_state.seer_checks.append(
            SeerCheckRecord(
                round=1,
                seer_seat_no=3,
                target_seat_no=1,
                result=Camp.werewolf,
            )
        )
        seer_view = build_player_view(gs, 3)
        villager_view = build_player_view(gs, 5)
        assert seer_view.private_info["seer_checks"][0]["target_seat_no"] == 1
        assert "seer_checks" not in villager_view.private_info

    def test_witch_kill_target_visible_only_to_witch(self):
        gs = _make_6p_game_state()
        gs.runtime_state.pending_wolf_kill_target = 3
        witch_view = build_player_view(gs, 4)
        seer_view = build_player_view(gs, 3)
        assert witch_view.private_info["pending_wolf_kill_target"] == 3
        assert "pending_wolf_kill_target" not in seer_view.private_info

class TestReasoningSummaryRemoval:
    """reasoning_summary must never appear in Agent PlayerView.public_events."""

    def test_speech_event_strips_reasoning_summary(self):
        gs = _make_6p_game_state()
        gs.public_state.public_events = [
            {
                "type": "speech",
                "seat_no": 1,
                "content": "我是好人。",
                "reasoning_summary": "分析局势后决定发言。",
            }
        ]
        view = build_player_view(gs, 3)
        for event in view.public_events:
            assert "reasoning_summary" not in event, (
                f"reasoning_summary leaked into {event['type']}: {event}"
            )
        assert view.public_events[0]["content"] == "我是好人。"

    def test_vote_cast_strips_reasoning_summary(self):
        gs = _make_6p_game_state()
        gs.public_state.public_events = [
            {
                "type": "vote_cast",
                "seat_no": 1,
                "target_seat_no": 3,
                "reasoning_summary": "投票理由。",
            }
        ]
        view = build_player_view(gs, 5)
        for event in view.public_events:
            assert "reasoning_summary" not in event
        assert view.public_events[0]["target_seat_no"] == 3

    def test_sheriff_speech_strips_reasoning_summary(self):
        gs = _make_6p_game_state()
        gs.public_state.public_events = [
            {
                "type": "sheriff_speech",
                "seat_no": 1,
                "run": True,
                "content": "竞选警长发言。",
                "reasoning_summary": "内部推理。",
            }
        ]
        view = build_player_view(gs, 2)
        for event in view.public_events:
            assert "reasoning_summary" not in event
        assert view.public_events[0]["content"] == "竞选警长发言。"

    def test_sheriff_vote_cast_strips_reasoning_summary(self):
        gs = _make_6p_game_state()
        gs.public_state.public_events = [
            {
                "type": "sheriff_vote_cast",
                "seat_no": 2,
                "target_seat_no": 1,
                "reasoning_summary": "投票警长。",
            }
        ]
        view = build_player_view(gs, 5)
        for event in view.public_events:
            assert "reasoning_summary" not in event

    def test_sheriff_pk_speech_strips_reasoning_summary(self):
        gs = _make_6p_game_state()
        gs.public_state.public_events = [
            {
                "type": "sheriff_pk_speech",
                "seat_no": 3,
                "content": "PK发言。",
                "reasoning_summary": "PK推理。",
            }
        ]
        view = build_player_view(gs, 6)
        for event in view.public_events:
            assert "reasoning_summary" not in event
        assert view.public_events[0]["content"] == "PK发言。"

    def test_night_resolved_strips_seer_result_and_death_reasons_and_reasoning_summary(self):
        gs = _make_6p_game_state()
        gs.public_state.public_events = [
            {
                "type": "night_resolved",
                "deaths": [5],
                "death_reasons": {"5": "werewolf_kill"},
                "seer_result": "werewolf",
                "reasoning_summary": "夜间总结。",
            }
        ]
        view = build_player_view(gs, 3)
        nr = view.public_events[0]
        assert "seer_result" not in nr
        assert "death_reasons" not in nr
        assert "reasoning_summary" not in nr
        assert nr["deaths"] == [5]

    def test_multiple_events_all_strip_reasoning_summary(self):
        gs = _make_6p_game_state()
        gs.public_state.public_events = [
            {"type": "speech", "seat_no": 1, "content": "a", "reasoning_summary": "x"},
            {"type": "vote_cast", "seat_no": 2, "target_seat_no": 3, "reasoning_summary": "x"},
            {"type": "sheriff_speech", "seat_no": 3, "run": False, "content": "b", "reasoning_summary": "x"},
            {"type": "sheriff_vote_cast", "seat_no": 4, "target_seat_no": 5, "reasoning_summary": "x"},
            {"type": "sheriff_elected", "sheriff_seat_no": 1, "reasoning_summary": "x"},
        ]
        view = build_player_view(gs, 6)
        for event in view.public_events:
            assert "reasoning_summary" not in event, (
                f"reasoning_summary leaked into {event['type']}: {event}"
            )

    def test_pk_speech_strips_reasoning_summary(self):
        gs = _make_6p_game_state()
        gs.public_state.public_events = [
            {
                "type": "pk_speech",
                "seat_no": 2,
                "content": "PK内容。",
                "reasoning_summary": "PK推理。",
            }
        ]
        view = build_player_view(gs, 4)
        for event in view.public_events:
            assert "reasoning_summary" not in event

    def test_reasoning_summary_still_in_raw_game_state(self):
        """reasoning_summary is stripped from PlayerView but still in GameState."""
        gs = _make_6p_game_state()
        gs.public_state.public_events = [
            {
                "type": "speech",
                "seat_no": 1,
                "content": "测试。",
                "reasoning_summary": "推理摘要。",
            }
        ]
        # Raw game state still has it
        assert "reasoning_summary" in gs.public_state.public_events[0]
        # PlayerView strips it
        view = build_player_view(gs, 2)
        assert "reasoning_summary" not in view.public_events[0]


    def test_private_night_events_are_filtered_from_view(self):
        gs = _make_6p_game_state()
        gs.public_state.public_events.extend(
            [
                {"type": "night_action", "seat_no": 1, "target_seat_no": 3},
                {"type": "night_resolved", "deaths": [], "seer_result": "werewolf"},
            ]
        )
        view = build_player_view(gs, 5)
        event_types = [event["type"] for event in view.public_events]
        assert "night_action" not in event_types
        night_resolved = next(event for event in view.public_events if event["type"] == "night_resolved")
        assert "seer_result" not in night_resolved


# ── Speech compression tests ───────────────────────────────────────────────────


def _speech(round_num: int, seat: int, content: str) -> dict:
    return {"type": "speech", "round": round_num, "seat_no": seat, "content": content}


def _vote_cast(round_num: int, seat: int, target: int) -> dict:
    return {"type": "vote_cast", "round": round_num, "seat_no": seat, "target_seat_no": target}


def _night_resolved(round_num: int) -> dict:
    return {"type": "night_resolved", "round": round_num, "deaths": []}


class TestSpeechCompression:
    def test_recent_speeches_kept(self):
        """Speeches from current round and within retention window are preserved."""
        events = [
            _speech(1, 1, "旧发言"),
            _speech(2, 2, "上一轮"),
            _speech(3, 3, "当前轮"),
            _vote_cast(3, 3, 5),
        ]
        # retention_rounds=2 → threshold=1, so only round 1 is compressed
        result = _compress_old_speeches(events, current_round=3, retention_rounds=2)
        types = [e["type"] for e in result]
        assert "round_summary" in types
        assert types.count("speech") == 2  # round 2 and round 3 kept
        assert "vote_cast" in types

    def test_old_speeches_compressed_to_summary(self):
        """Speeches in compressed rounds become one round_summary per round."""
        events = [
            _speech(1, 1, "一号发言内容"),
            _speech(1, 2, "二号不同观点"),
            _speech(2, 3, "当前轮发言"),
        ]
        # retention_rounds=0 → threshold=2, both rounds compressed
        result = _compress_old_speeches(events, current_round=2, retention_rounds=0)
        summaries = [e for e in result if e["type"] == "round_summary"]
        assert len(summaries) == 2  # one per round
        assert summaries[0]["round"] == 1
        assert "1号" in summaries[0]["content"]
        assert "2号" in summaries[0]["content"]
        assert summaries[1]["round"] == 2
        # No raw speech events remain
        assert all(e["type"] != "speech" for e in result)

    def test_non_speech_events_preserved(self):
        """vote_cast, night_resolved, etc. are never compressed."""
        events = [
            _night_resolved(1),
            _speech(1, 1, "旧发言"),
            _vote_cast(1, 1, 3),
        ]
        result = _compress_old_speeches(events, current_round=2, retention_rounds=0)
        types = [e["type"] for e in result]
        assert types.count("night_resolved") == 1
        assert types.count("vote_cast") == 1
        assert types.count("round_summary") == 1

    def test_retention_zero_compresses_all_speeches(self):
        """retention_rounds=0 compresses even current-round speeches."""
        events = [
            _speech(3, 1, "当前发言"),
            _speech(3, 2, "也是当前"),
        ]
        result = _compress_old_speeches(events, current_round=3, retention_rounds=0)
        # threshold = 3 - 0 = 3, so round 3 speeches are compressed
        assert all(e["type"] != "speech" for e in result)
        summaries = [e for e in result if e["type"] == "round_summary"]
        assert len(summaries) == 1
        assert summaries[0]["round"] == 3

    def test_no_events_no_crash(self):
        result = _compress_old_speeches([], current_round=1, retention_rounds=1)
        assert result == []

    def test_mixed_rounds_single_summary_per_round(self):
        """Multiple compressed rounds each get their own summary."""
        events = [
            _speech(1, 1, "r1a"),
            _speech(1, 2, "r1b"),
            _night_resolved(1),
            _speech(2, 1, "r2a"),
            _speech(2, 2, "r2b"),
            _night_resolved(2),
            _speech(3, 1, "current"),
        ]
        # retention=0 → threshold=3, all 3 rounds compressed
        result = _compress_old_speeches(events, current_round=3, retention_rounds=0)
        summaries = [e for e in result if e["type"] == "round_summary"]
        assert len(summaries) == 3  # one per round
        assert summaries[0]["round"] == 1
        assert summaries[1]["round"] == 2
        assert summaries[2]["round"] == 3
        # Non-speech events preserved
        assert any(e["type"] == "night_resolved" for e in result)

    def test_same_round_speeches_split_by_non_speech_share_one_summary(self):
        events = [
            _speech(1, 1, "第一段"),
            _vote_cast(1, 1, 3),
            _speech(1, 2, "第二段"),
            _night_resolved(1),
            _speech(1, 3, "第三段"),
        ]
        result = _compress_old_speeches(events, current_round=3, retention_rounds=0)
        summaries = [e for e in result if e["type"] == "round_summary" and e["round"] == 1]
        assert len(summaries) == 1
        assert "1号" in summaries[0]["content"]
        assert "2号" in summaries[0]["content"]
        assert "3号" in summaries[0]["content"]
        assert any(e["type"] == "vote_cast" for e in result)
        assert any(e["type"] == "night_resolved" for e in result)

    def test_sheriff_speech_also_compressed(self):
        """sheriff_speech events are speech-like and should be compressed."""
        events = [
            {"type": "sheriff_speech", "round": 1, "seat_no": 3, "content": "竞选"},
            {"type": "speech", "round": 1, "seat_no": 1, "content": "发言"},
        ]
        result = _compress_old_speeches(events, current_round=2, retention_rounds=0)
        assert all(e["type"] != "sheriff_speech" for e in result)
        summaries = [e for e in result if e["type"] == "round_summary"]
        assert len(summaries) == 1

    def test_long_speech_truncated_in_summary(self):
        """Individual speech content is truncated to ~60 chars in summary."""
        long_content = "这是一个非常长的发言内容用来测试摘要截断功能" * 3  # ~90 chars
        events = [_speech(1, 5, long_content)]
        result = _compress_old_speeches(events, current_round=2, retention_rounds=0)
        summary = result[0]
        assert "…" in summary["content"]
        assert len(summary["content"].split(": ")[-1]) <= 63  # ~60 chars + "…"

    def test_compression_integrated_in_build_player_view(self):
        """build_player_view should keep current and previous round speeches by default."""
        gs = _make_6p_game_state()
        gs.public_state.round = 3
        gs.public_state.public_events = [
            {"type": "speech", "round": 1, "seat_no": 1, "content": "旧发言内容"},
            {"type": "speech", "round": 2, "seat_no": 6, "content": "上一轮发言"},
            {"type": "speech", "round": 3, "seat_no": 2, "content": "当前发言"},
            {"type": "vote_cast", "round": 3, "seat_no": 1, "target_seat_no": 2},
        ]
        view = build_player_view(gs, 3)
        types = [e["type"] for e in view.public_events]
        assert "round_summary" in types
        speeches = [e for e in view.public_events if e["type"] == "speech"]
        assert {e["round"] for e in speeches} == {2, 3}
        assert "vote_cast" in types
