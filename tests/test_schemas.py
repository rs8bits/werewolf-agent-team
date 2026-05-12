import pytest
from pydantic import ValidationError

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
    camp_of,
)


class TestRoleCampMapping:
    def test_werewolf_is_werewolf_camp(self):
        assert camp_of(Role.werewolf) == Camp.werewolf

    def test_seer_is_good_camp(self):
        assert camp_of(Role.seer) == Camp.good

    def test_witch_is_good_camp(self):
        assert camp_of(Role.witch) == Camp.good

    def test_villager_is_good_camp(self):
        assert camp_of(Role.villager) == Camp.good

    def test_hunter_is_good_camp(self):
        assert camp_of(Role.hunter) == Camp.good

    def test_idiot_is_good_camp(self):
        assert camp_of(Role.idiot) == Camp.good

    def test_guard_is_good_camp(self):
        assert camp_of(Role.guard) == Camp.good

    def test_only_werewolf_role_is_werewolf_camp(self):
        wolf_roles = [role for role in Role if camp_of(role) == Camp.werewolf]
        assert wolf_roles == [Role.werewolf]


class TestPlayerState:
    def test_default_status_alive_can_vote(self):
        p = PlayerState(
            seat_no=1,
            name="Alice",
            player_type=PlayerType.ai,
            role=Role.villager,
            camp=Camp.good,
        )
        assert p.status.alive is True
        assert p.status.can_vote is True

    def test_seat_no_must_be_positive(self):
        with pytest.raises(ValidationError):
            PlayerState(
                seat_no=0,
                name="Alice",
                player_type=PlayerType.ai,
                role=Role.villager,
                camp=Camp.good,
            )

    def test_role_and_camp_must_match(self):
        with pytest.raises(ValidationError, match="belongs to camp"):
            PlayerState(
                seat_no=1,
                name="Alice",
                player_type=PlayerType.ai,
                role=Role.werewolf,
                camp=Camp.good,
            )


class TestGameState:
    def _make_player(self, seat: int, role: Role, name: str = "") -> PlayerState:
        return PlayerState(
            seat_no=seat,
            name=name or f"P{seat}",
            player_type=PlayerType.ai,
            role=role,
            camp=camp_of(role),
        )

    def test_init_with_six_players(self):
        roles = [
            Role.werewolf,
            Role.werewolf,
            Role.seer,
            Role.witch,
            Role.villager,
            Role.villager,
        ]
        players = [self._make_player(i + 1, role) for i, role in enumerate(roles)]
        gs = GameState(game_id="test-001", players=players)
        assert len(gs.players) == 6
        assert gs.winner is None
        assert gs.public_state.phase == GamePhase.setup
        assert gs.public_state.round == 0

    def test_truth_state_has_wolf_team(self):
        roles = [
            Role.werewolf,
            Role.werewolf,
            Role.seer,
            Role.witch,
            Role.villager,
            Role.villager,
        ]
        players = [self._make_player(i + 1, role) for i, role in enumerate(roles)]
        ts = TruthState(
            real_identities={p.seat_no: p.role for p in players},
            wolf_team=[1, 2],
        )
        assert ts.wolf_team == [1, 2]
        assert ts.real_identities[1] == Role.werewolf

    def test_game_state_serializes_to_dict(self):
        roles = [
            Role.werewolf,
            Role.werewolf,
            Role.seer,
            Role.witch,
            Role.villager,
            Role.villager,
        ]
        players = [self._make_player(i + 1, role) for i, role in enumerate(roles)]
        gs = GameState(game_id="test-001", players=players)
        d = gs.model_dump()
        assert d["game_id"] == "test-001"
        assert len(d["players"]) == 6
