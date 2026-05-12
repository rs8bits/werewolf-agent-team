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
    TruthState,
)
from app.state.view_builder import PlayerView, VisiblePlayer, build_player_view


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
