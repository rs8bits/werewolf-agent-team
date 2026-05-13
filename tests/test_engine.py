from __future__ import annotations

import pytest

from app.engine import (
    NightActionSet,
    NightResult,
    Vote,
    VoteResult,
    apply_vote_result,
    check_winner,
    initialize_game,
    kill_player,
    resolve_night,
    tally_votes,
)
from app.config.role_setups import RoleSetup, RoleCount
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
            seat_no=s, name=f"P{s}", player_type=PlayerType.ai,
            role=r, camp=camp_of(r),
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


# ── initialize_game ──────────────────────────────────────────────────────────────


class TestInitializeGame:
    def test_initialize_default_six_player_game(self):
        gs = initialize_game("game-001")
        assert gs.game_id == "game-001"
        assert gs.public_state.phase == GamePhase.setup
        assert gs.public_state.alive_players == [1, 2, 3, 4, 5, 6]
        assert gs.public_state.dead_players == []
        assert len(gs.players) == 6
        # With random seat assignment we only check count, not specific seats
        assert len(gs.truth_state.wolf_team) == 2
        for seat in gs.truth_state.wolf_team:
            assert 1 <= seat <= 6
            assert gs.truth_state.real_identities[seat] == Role.werewolf

    def test_initialize_role_counts(self):
        gs = initialize_game("game-001")
        role_counts: dict[Role, int] = {}
        for player in gs.players:
            role_counts[player.role] = role_counts.get(player.role, 0) + 1
        assert role_counts[Role.werewolf] == 2
        assert role_counts[Role.seer] == 1
        assert role_counts[Role.witch] == 1
        assert role_counts[Role.villager] == 2

    def test_initialize_seed_produces_deterministic_seats(self):
        gs1 = initialize_game("game-001", seed=42)
        gs2 = initialize_game("game-002", seed=42)
        roles1 = [p.role for p in gs1.players]
        roles2 = [p.role for p in gs2.players]
        assert roles1 == roles2

    def test_initialize_without_seed_is_not_always_same(self):
        # Extremely unlikely (1 / 6P2_2_1_1_2) that two calls produce identical ordering
        roles_samples = set()
        for _ in range(5):
            gs = initialize_game("test")
            roles_samples.add(tuple(p.role for p in gs.players))
        # With 5 samples and 180 possible orderings, we expect multiple distinct samples
        assert len(roles_samples) >= 2

    def test_initialize_custom_names_and_types(self):
        names = ["A", "B", "C", "D", "E", "F"]
        player_types = [
            PlayerType.human,
            PlayerType.ai,
            PlayerType.ai,
            PlayerType.ai,
            PlayerType.ai,
            PlayerType.ai,
        ]
        gs = initialize_game("game-001", player_names=names, player_types=player_types)
        assert [player.name for player in gs.players] == names
        assert gs.players[0].player_type == PlayerType.human

    def test_initialize_rejects_wrong_name_count(self):
        with pytest.raises(ValueError, match="player names"):
            initialize_game("game-001", player_names=["A"])

    def test_initialize_rejects_wrong_player_type_count(self):
        with pytest.raises(ValueError, match="player types"):
            initialize_game("game-001", player_types=[PlayerType.ai])

    def test_initialize_supports_explicit_setup(self):
        setup = RoleSetup(
            player_count=6,
            role_counts=[
                RoleCount(role=Role.werewolf, count=2),
                RoleCount(role=Role.seer, count=1),
                RoleCount(role=Role.witch, count=1),
                RoleCount(role=Role.villager, count=2),
            ],
        )
        gs = initialize_game("game-001", setup=setup)
        assert len(gs.players) == 6


# ── kill_player ──────────────────────────────────────────────────────────────────


class TestKillPlayer:
    def test_kill_player_updates_status(self):
        gs = _make_6p_game_state()
        kill_player(gs, 1, reason="test_kill")
        p1 = next(p for p in gs.players if p.seat_no == 1)
        assert p1.status.alive is False
        assert p1.status.can_vote is False
        assert 1 not in gs.public_state.alive_players
        assert 1 in gs.public_state.dead_players

    def test_kill_player_writes_public_event(self):
        gs = _make_6p_game_state()
        kill_player(gs, 3, reason="night_death")
        events = gs.public_state.public_events
        assert len(events) == 1
        assert events[0]["type"] == "player_death"
        assert events[0]["seat_no"] == 3
        assert events[0]["reason"] == "night_death"

    def test_cannot_kill_nonexistent_seat(self):
        gs = _make_6p_game_state()
        with pytest.raises(ValueError, match="seat_no=99"):
            kill_player(gs, 99, reason="test")

    def test_cannot_kill_already_dead_player(self):
        gs = _make_6p_game_state()
        kill_player(gs, 2, reason="first")
        with pytest.raises(ValueError, match="already dead"):
            kill_player(gs, 2, reason="second")


# ── tally_votes ──────────────────────────────────────────────────────────────────


class TestTallyVotes:
    def test_unique_highest_vote_returns_elimination(self):
        gs = _make_6p_game_state(phase=GamePhase.vote)
        votes = [
            Vote(voter_seat_no=1, target_seat_no=6),
            Vote(voter_seat_no=2, target_seat_no=6),
            Vote(voter_seat_no=3, target_seat_no=5),
            Vote(voter_seat_no=4, target_seat_no=6),
            Vote(voter_seat_no=5, target_seat_no=3),
            Vote(voter_seat_no=6, target_seat_no=5),
        ]
        result = tally_votes(gs, votes)
        assert result.eliminated_seat_no == 6
        assert result.tied_seats == []

    def test_tie_returns_no_elimination(self):
        gs = _make_6p_game_state(phase=GamePhase.vote)
        votes = [
            Vote(voter_seat_no=1, target_seat_no=5),
            Vote(voter_seat_no=2, target_seat_no=5),
            Vote(voter_seat_no=3, target_seat_no=5),
            Vote(voter_seat_no=4, target_seat_no=6),
            Vote(voter_seat_no=5, target_seat_no=6),
            Vote(voter_seat_no=6, target_seat_no=6),
        ]
        result = tally_votes(gs, votes)
        assert result.eliminated_seat_no is None
        assert set(result.tied_seats) == {5, 6}

    def test_all_abstain_returns_no_elimination(self):
        gs = _make_6p_game_state(phase=GamePhase.vote)
        votes = [Vote(voter_seat_no=i) for i in range(1, 7)]
        result = tally_votes(gs, votes)
        assert result.eliminated_seat_no is None
        assert result.tied_seats == []
        assert result.vote_counts == {}

    def test_dead_player_vote_ignored(self):
        gs = _make_6p_game_state(phase=GamePhase.vote)
        kill_player(gs, 1, reason="test")
        votes = [
            Vote(voter_seat_no=1, target_seat_no=6),
            Vote(voter_seat_no=2, target_seat_no=6),
            Vote(voter_seat_no=3, target_seat_no=5),
            Vote(voter_seat_no=4, target_seat_no=5),
            Vote(voter_seat_no=5, target_seat_no=5),
            Vote(voter_seat_no=6, target_seat_no=6),
        ]
        result = tally_votes(gs, votes)
        # Without player 1: 6 gets 2 votes (P2, P6), 5 gets 3 votes (P3, P4, P5)
        assert result.eliminated_seat_no == 5

    def test_no_vote_right_player_vote_ignored(self):
        gs = _make_6p_game_state(phase=GamePhase.vote)
        gs.players[0].status.can_vote = False  # seat 1
        votes = [
            Vote(voter_seat_no=1, target_seat_no=5),
            Vote(voter_seat_no=2, target_seat_no=6),
            Vote(voter_seat_no=3, target_seat_no=6),
            Vote(voter_seat_no=4, target_seat_no=6),
            Vote(voter_seat_no=5, target_seat_no=5),
            Vote(voter_seat_no=6, target_seat_no=5),
        ]
        result = tally_votes(gs, votes)
        # Without player 1: 6 gets 3 votes, 5 gets 2 votes
        assert result.eliminated_seat_no == 6

    def test_abstain_vote_not_counted(self):
        gs = _make_6p_game_state(phase=GamePhase.vote)
        votes = [
            Vote(voter_seat_no=1, target_seat_no=5),
            Vote(voter_seat_no=2),  # abstain
            Vote(voter_seat_no=3, target_seat_no=5),
            Vote(voter_seat_no=4),  # abstain
            Vote(voter_seat_no=5, target_seat_no=6),
            Vote(voter_seat_no=6, target_seat_no=6),
        ]
        result = tally_votes(gs, votes)
        assert result.vote_counts == {5: 2, 6: 2}
        assert result.eliminated_seat_no is None
        assert set(result.tied_seats) == {5, 6}

    def test_vote_count_recorded(self):
        gs = _make_6p_game_state(phase=GamePhase.vote)
        votes = [
            Vote(voter_seat_no=1, target_seat_no=5),
            Vote(voter_seat_no=2, target_seat_no=5),
            Vote(voter_seat_no=3, target_seat_no=6),
        ]
        result = tally_votes(gs, votes)
        assert result.vote_counts == {5: 2, 6: 1}
        assert result.eliminated_seat_no == 5

    def test_vote_for_dead_target_ignored(self):
        gs = _make_6p_game_state(phase=GamePhase.vote)
        kill_player(gs, 5, reason="test")
        votes = [
            Vote(voter_seat_no=1, target_seat_no=5),
            Vote(voter_seat_no=2, target_seat_no=6),
        ]
        result = tally_votes(gs, votes)
        assert result.vote_counts == {6: 1}
        assert result.eliminated_seat_no == 6

    def test_duplicate_voter_counted_once(self):
        gs = _make_6p_game_state(phase=GamePhase.vote)
        votes = [
            Vote(voter_seat_no=1, target_seat_no=5),
            Vote(voter_seat_no=1, target_seat_no=6),
            Vote(voter_seat_no=2, target_seat_no=6),
        ]
        result = tally_votes(gs, votes)
        assert result.vote_counts == {5: 1, 6: 1}
        assert set(result.tied_seats) == {5, 6}


# ── apply_vote_result ────────────────────────────────────────────────────────────


class TestApplyVoteResult:
    def test_apply_eliminates_player(self):
        gs = _make_6p_game_state(phase=GamePhase.vote)
        result = VoteResult(eliminated_seat_no=3)
        apply_vote_result(gs, result)
        p3 = next(p for p in gs.players if p.seat_no == 3)
        assert p3.status.alive is False

    def test_apply_tie_does_nothing(self):
        gs = _make_6p_game_state(phase=GamePhase.vote)
        result = VoteResult(tied_seats=[5, 6])
        apply_vote_result(gs, result)
        assert all(p.status.alive for p in gs.players)

    def test_apply_none_elimination_does_nothing(self):
        gs = _make_6p_game_state(phase=GamePhase.vote)
        result = VoteResult()
        apply_vote_result(gs, result)
        assert all(p.status.alive for p in gs.players)


# ── check_winner ─────────────────────────────────────────────────────────────────


class TestCheckWinner:
    def test_all_werewolves_dead_good_wins(self):
        gs = _make_6p_game_state()
        kill_player(gs, 1, reason="test")
        kill_player(gs, 2, reason="test")
        assert check_winner(gs) == Camp.good

    def test_all_gods_dead_werewolf_wins(self):
        gs = _make_6p_game_state()
        kill_player(gs, 3, reason="test")  # seer
        kill_player(gs, 4, reason="test")  # witch
        assert check_winner(gs) == Camp.werewolf

    def test_all_villagers_dead_werewolf_wins(self):
        gs = _make_6p_game_state()
        kill_player(gs, 5, reason="test")  # villager
        kill_player(gs, 6, reason="test")  # villager
        assert check_winner(gs) == Camp.werewolf

    def test_game_not_over(self):
        gs = _make_6p_game_state()
        kill_player(gs, 1, reason="test")  # one wolf dead
        assert check_winner(gs) is None

    def test_everyone_alive_no_winner(self):
        gs = _make_6p_game_state()
        assert check_winner(gs) is None


# ── resolve_night ────────────────────────────────────────────────────────────────


class TestResolveNight:
    def test_wolf_kill_causes_death(self):
        gs = _make_6p_game_state()
        actions = NightActionSet(wolf_kill_target=5)
        result = resolve_night(gs, actions)
        assert result.deaths == [5]
        p5 = next(p for p in gs.players if p.seat_no == 5)
        assert p5.status.alive is False

    def test_witch_save_prevents_wolf_kill(self):
        gs = _make_6p_game_state()
        actions = NightActionSet(wolf_kill_target=5, witch_save_target=5)
        result = resolve_night(gs, actions)
        assert result.deaths == []
        p5 = next(p for p in gs.players if p.seat_no == 5)
        assert p5.status.alive is True

    def test_witch_poison_kills(self):
        gs = _make_6p_game_state()
        actions = NightActionSet(witch_poison_target=1)
        result = resolve_night(gs, actions)
        assert result.deaths == [1]
        p1 = next(p for p in gs.players if p.seat_no == 1)
        assert p1.status.alive is False

    def test_same_player_killed_and_poisoned_dies_once(self):
        gs = _make_6p_game_state()
        actions = NightActionSet(
            wolf_kill_target=5, witch_poison_target=5
        )
        result = resolve_night(gs, actions)
        assert result.deaths == [5]
        # One death event, not two
        death_events = [
            e for e in gs.public_state.public_events if e["type"] == "player_death"
        ]
        assert len(death_events) == 1

    def test_seer_check_returns_camp(self):
        gs = _make_6p_game_state()
        actions = NightActionSet(seer_check_target=1)
        result = resolve_night(gs, actions)
        assert result.seer_result == Camp.werewolf

    def test_seer_check_good_player(self):
        gs = _make_6p_game_state()
        actions = NightActionSet(seer_check_target=5)
        result = resolve_night(gs, actions)
        assert result.seer_result == Camp.good

    def test_wolf_kill_saved_poison_different_target(self):
        gs = _make_6p_game_state()
        actions = NightActionSet(
            wolf_kill_target=5, witch_save_target=5, witch_poison_target=1
        )
        result = resolve_night(gs, actions)
        assert set(result.deaths) == {1}
        p5 = next(p for p in gs.players if p.seat_no == 5)
        assert p5.status.alive is True
        p1 = next(p for p in gs.players if p.seat_no == 1)
        assert p1.status.alive is False

    def test_no_actions_no_deaths(self):
        gs = _make_6p_game_state()
        actions = NightActionSet()
        result = resolve_night(gs, actions)
        assert result.deaths == []
        assert result.seer_result is None
        assert all(p.status.alive for p in gs.players)

    def test_witch_save_wrong_target_does_not_prevent_kill(self):
        gs = _make_6p_game_state()
        actions = NightActionSet(
            wolf_kill_target=5, witch_save_target=6
        )
        result = resolve_night(gs, actions)
        assert result.deaths == [5]

    def test_invalid_night_target_raises(self):
        gs = _make_6p_game_state()
        actions = NightActionSet(wolf_kill_target=99)
        with pytest.raises(ValueError, match="seat_no=99"):
            resolve_night(gs, actions)

    def test_dead_night_target_raises(self):
        gs = _make_6p_game_state()
        kill_player(gs, 5, reason="test")
        actions = NightActionSet(witch_poison_target=5)
        with pytest.raises(ValueError, match="not alive"):
            resolve_night(gs, actions)


# ── Pydantic model serialization ─────────────────────────────────────────────────


class TestModelSerialization:
    def test_vote_serialization(self):
        v = Vote(voter_seat_no=1, target_seat_no=5)
        d = v.model_dump()
        assert d == {"voter_seat_no": 1, "target_seat_no": 5}

    def test_vote_abstain_serialization(self):
        v = Vote(voter_seat_no=1)
        d = v.model_dump()
        assert d == {"voter_seat_no": 1, "target_seat_no": None}

    def test_vote_result_elimination_serialization(self):
        vr = VoteResult(eliminated_seat_no=5, vote_counts={5: 4, 6: 2})
        d = vr.model_dump()
        assert d["eliminated_seat_no"] == 5
        assert d["tied_seats"] == []

    def test_vote_result_tie_serialization(self):
        vr = VoteResult(tied_seats=[5, 6], vote_counts={5: 3, 6: 3})
        d = vr.model_dump()
        assert d["eliminated_seat_no"] is None
        assert d["tied_seats"] == [5, 6]

    def test_night_action_set_serialization(self):
        actions = NightActionSet(
            wolf_kill_target=5, witch_poison_target=1, seer_check_target=2
        )
        d = actions.model_dump()
        assert d["wolf_kill_target"] == 5
        assert d["witch_save_target"] is None
        assert d["witch_poison_target"] == 1
        assert d["seer_check_target"] == 2

    def test_night_result_serialization(self):
        nr = NightResult(deaths=[1, 5], seer_result=Camp.werewolf)
        d = nr.model_dump()
        assert d["deaths"] == [1, 5]
        assert d["seer_result"] == "werewolf"
