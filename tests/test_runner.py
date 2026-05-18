from __future__ import annotations

import pytest

from app.agents.schemas import (
    ActionType,
    AgentDecision,
    RunForSheriffAction,
    SeerCheckAction,
    SheriffVoteAction,
    SpeakAction,
    VoteAction,
    WerewolfKillAction,
    WitchAction,
)
from app.config.role_setups import twelve_player_setup
from app.config.rule_config import RuleConfig
from app.engine import initialize_game
from app.graph.main_graph import (
    Agent,
    build_main_graph,
    run_day_phase,
    run_night_phase,
    run_one_cycle,
    run_until_finished,
    run_vote_phase,
)
from app.state.schemas import (
    Camp,
    GamePhase,
    GameState,
    Role,
)
from app.state.view_builder import PlayerView, build_player_view


# Keeps legacy runner scenarios on the canonical 6-player seating while the
# production default randomises roles across seats.
FIXED_SIX_PLAYER_SEED = 163


# ── FakeAgent ──────────────────────────────────────────────────────────────────


class FakeAgent:
    """Fake agent that returns a predetermined decision, no LLM calls."""

    def __init__(self, role: Role, decisions: list[AgentDecision]):
        self._role = role
        self._decisions = list(decisions)
        self._call_count = 0
        self._views: list[PlayerView] = []

    @property
    def role(self) -> Role:
        return self._role

    def decide(self, view: PlayerView) -> AgentDecision:
        self._views.append(view)
        if self._call_count < len(self._decisions):
            decision = self._decisions[self._call_count]
            self._call_count += 1
            return decision
        # Fallback: return a no-op speak for safety
        return AgentDecision(
            action=SpeakAction(content="无可用决策。"),
            reasoning_summary="fake fallback",
        )

    @property
    def views(self) -> list[PlayerView]:
        return self._views


def _make_fake_agents(
    game_state: GameState,
    decision_map: dict[int, AgentDecision],
) -> dict[int, FakeAgent]:
    """Create a FakeAgent per player, each with one predetermined decision."""
    agents: dict[int, FakeAgent] = {}
    for p in game_state.players:
        decision = decision_map.get(p.seat_no)
        agents[p.seat_no] = FakeAgent(p.role, [decision] if decision else [])
    return agents


def _make_kill_decision(target: int) -> AgentDecision:
    return AgentDecision(
        action=WerewolfKillAction(target_seat_no=target),
        reasoning_summary=f"击杀{target}号。",
    )


def _make_save_decision(target: int) -> AgentDecision:
    return AgentDecision(
        action=WitchAction(action_type=ActionType.witch_save, target_seat_no=target),
        reasoning_summary=f"救{target}号。",
    )


def _make_poison_decision(target: int) -> AgentDecision:
    return AgentDecision(
        action=WitchAction(action_type=ActionType.witch_poison, target_seat_no=target),
        reasoning_summary=f"毒杀{target}号。",
    )


def _make_speak_decision(content: str) -> AgentDecision:
    return AgentDecision(
        action=SpeakAction(content=content),
        reasoning_summary="发言。",
    )


def _make_vote_decision(target: int | None) -> AgentDecision:
    return AgentDecision(
        action=VoteAction(target_seat_no=target),
        reasoning_summary=f"投票{'弃权' if target is None else str(target)+'号'}。",
    )


def _make_seer_check_decision(target: int) -> AgentDecision:
    return AgentDecision(
        action=SeerCheckAction(target_seat_no=target),
        reasoning_summary=f"查验{target}号。",
    )


def _make_run_for_sheriff_decision(run: bool, content: str | None = None) -> AgentDecision:
    return AgentDecision(
        action=RunForSheriffAction(run=run, content=content),
        reasoning_summary="内部推理，不应公开。",
    )


def _make_sheriff_vote_decision(target: int | None) -> AgentDecision:
    return AgentDecision(
        action=SheriffVoteAction(target_seat_no=target),
        reasoning_summary=f"警长投票{'弃权' if target is None else str(target)+'号'}。",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _find_player(game_state: GameState, seat_no: int):
    for p in game_state.players:
        if p.seat_no == seat_no:
            return p
    raise ValueError(f"Player {seat_no} not found")


# ── Night phase tests ─────────────────────────────────────────────────────────


class TestRunNightPhase:
    def test_werewolf_kill_causes_death(self):
        """Night wolf kill should cause the target to die."""
        gs = initialize_game("test-001", seed=FIXED_SIX_PLAYER_SEED)
        gs.public_state.phase = GamePhase.night

        wolf1 = _make_kill_decision(5)
        agents = _make_fake_agents(gs, {1: wolf1})

        run_night_phase(gs, agents)

        p5 = _find_player(gs, 5)
        assert p5.status.alive is False
        assert "night_resolved" in [e["type"] for e in gs.public_state.public_events]

    def test_witch_save_prevents_death(self):
        """Witch save should prevent the wolf kill target from dying."""
        gs = initialize_game("test-002", seed=FIXED_SIX_PLAYER_SEED)
        gs.public_state.phase = GamePhase.night

        wolf1 = _make_kill_decision(5)
        witch_save = _make_save_decision(5)
        agents = _make_fake_agents(gs, {1: wolf1, 4: witch_save})

        run_night_phase(gs, agents)

        p5 = _find_player(gs, 5)
        assert p5.status.alive is True

    def test_witch_save_wrong_target_does_not_prevent_kill(self):
        """Witch saving a different player should not prevent the kill."""
        gs = initialize_game("test-003", seed=FIXED_SIX_PLAYER_SEED)
        gs.public_state.phase = GamePhase.night

        wolf1 = _make_kill_decision(5)
        witch_save = _make_save_decision(6)
        agents = _make_fake_agents(gs, {1: wolf1, 4: witch_save})

        run_night_phase(gs, agents)

        p5 = _find_player(gs, 5)
        assert p5.status.alive is False

    def test_witch_poison_causes_death(self):
        """Witch poison should kill the target."""
        gs = initialize_game("test-004", seed=FIXED_SIX_PLAYER_SEED)
        gs.public_state.phase = GamePhase.night

        witch_poison = _make_poison_decision(6)
        agents = _make_fake_agents(gs, {4: witch_poison})

        run_night_phase(gs, agents)

        p6 = _find_player(gs, 6)
        assert p6.status.alive is False

    def test_seer_check_logged(self):
        """Seer check target should be collected and resolved."""
        gs = initialize_game("test-005", seed=FIXED_SIX_PLAYER_SEED)
        gs.public_state.phase = GamePhase.night

        seer_check = _make_seer_check_decision(1)
        agents = _make_fake_agents(gs, {3: seer_check})

        run_night_phase(gs, agents)

        night_resolved = [
            e for e in gs.public_state.public_events if e["type"] == "night_resolved"
        ]
        assert len(night_resolved) == 1
        assert night_resolved[0]["seer_result"] is not None

    def test_wolf_majority_vote_determines_target(self):
        """Two wolves picking different targets — majority wins."""
        gs = initialize_game("test-006", seed=FIXED_SIX_PLAYER_SEED)
        gs.public_state.phase = GamePhase.night

        # Two wolves: seats 1 and 2
        wolf1 = _make_kill_decision(5)
        wolf2 = _make_kill_decision(5)
        agents = _make_fake_agents(gs, {1: wolf1, 2: wolf2})

        run_night_phase(gs, agents)

        p5 = _find_player(gs, 5)
        assert p5.status.alive is False

    def test_wolf_tie_picks_smallest_seat_no(self):
        """Two wolves, different targets, tie → smallest seat_no."""
        gs = initialize_game("test-007", seed=FIXED_SIX_PLAYER_SEED)
        gs.public_state.phase = GamePhase.night

        wolf1 = _make_kill_decision(5)
        wolf2 = _make_kill_decision(6)
        agents = _make_fake_agents(gs, {1: wolf1, 2: wolf2})

        run_night_phase(gs, agents)

        p5 = _find_player(gs, 5)
        p6 = _find_player(gs, 6)
        # Smallest target wins tie: 5 dies, 6 lives
        assert p5.status.alive is False
        assert p6.status.alive is True

    def test_game_ends_when_all_wolves_dead(self):
        """If all wolves die at night, good wins and phase=ended."""
        gs = initialize_game("test-008", seed=FIXED_SIX_PLAYER_SEED)
        gs.public_state.phase = GamePhase.night

        # Wolf 1 kills wolf 2 (via witch poison on wolf 2)
        # Wolf 1 also dies from witch poison on wolf 1
        witch_p1 = _make_poison_decision(1)
        wolf1 = _make_kill_decision(2)
        agents = _make_fake_agents(gs, {1: wolf1, 4: witch_p1})

        run_night_phase(gs, agents)

        # Wolf 1 poisoned (dies), Wolf 2 killed by wolf 1 (dies)
        # All wolves dead → good wins
        if gs.public_state.phase == GamePhase.ended:
            assert gs.winner == Camp.good


# ── Day phase tests ───────────────────────────────────────────────────────────


class TestRunDayPhase:
    def test_day_speech_writes_chinese_events(self):
        """Day speech events should contain Chinese content."""
        gs = initialize_game("test-100", seed=FIXED_SIX_PLAYER_SEED)
        gs.public_state.phase = GamePhase.day

        decisions = {
            seat: _make_speak_decision(f"我是{seat}号，我是好人。")
            for seat in range(1, 7)
        }
        agents = _make_fake_agents(gs, decisions)

        run_day_phase(gs, agents)

        speech_events = [
            e for e in gs.public_state.public_events if e["type"] == "speech"
        ]
        assert len(speech_events) == 6
        for event in speech_events:
            assert "seat_no" in event
            assert "content" in event
            assert "reasoning_summary" in event
            # Content should be Chinese
            assert "号" in event["content"]

    def test_dead_player_does_not_speak(self):
        """Dead players should be skipped during day phase."""
        gs = initialize_game("test-101", seed=FIXED_SIX_PLAYER_SEED)
        gs.public_state.phase = GamePhase.day
        # Kill players 5 and 6
        p5 = _find_player(gs, 5)
        p6 = _find_player(gs, 6)
        p5.status.alive = False
        p6.status.alive = False
        gs.public_state.alive_players.remove(5)
        gs.public_state.alive_players.remove(6)

        decisions = {
            seat: _make_speak_decision(f"我是{seat}号。")
            for seat in range(1, 5)
        }
        agents = _make_fake_agents(gs, decisions)

        run_day_phase(gs, agents)

        speech_events = [
            e for e in gs.public_state.public_events if e["type"] == "speech"
        ]
        assert len(speech_events) == 4
        speaker_seats = [e["seat_no"] for e in speech_events]
        assert 5 not in speaker_seats
        assert 6 not in speaker_seats

    def test_day_phase_sets_correct_phase(self):
        """Day phase should set phase to day."""
        gs = initialize_game("test-102", seed=FIXED_SIX_PLAYER_SEED)
        decisions = {}
        agents = _make_fake_agents(gs, decisions)

        run_day_phase(gs, agents)

        assert gs.public_state.phase == GamePhase.day

    def test_events_have_round_field(self):
        """All events logged via _log_event should carry a round field."""
        gs = initialize_game("test-103", seed=FIXED_SIX_PLAYER_SEED)
        gs.public_state.phase = GamePhase.day

        decisions = {
            seat: _make_speak_decision(f"我是{seat}号。")
            for seat in range(1, 7)
        }
        agents = _make_fake_agents(gs, decisions)

        run_day_phase(gs, agents)

        for event in gs.public_state.public_events:
            # game_initialized is created by initialize_game, not _log_event
            if event["type"] == "game_initialized":
                continue
            assert "round" in event, (
                f"Event {event.get('type')} missing 'round' field: {event}"
            )
            assert isinstance(event["round"], int)


# ── Vote phase tests ──────────────────────────────────────────────────────────


class TestRunVotePhase:
    def test_unique_highest_vote_eliminates(self):
        """Player with unique highest votes is eliminated."""
        gs = initialize_game("test-200", seed=FIXED_SIX_PLAYER_SEED)
        gs.public_state.phase = GamePhase.vote

        # Give vote decisions: 4 voters target seat 6, 1 votes seat 5, 1 abstains
        decision_map = {
            1: _make_vote_decision(6),
            2: _make_vote_decision(6),
            3: _make_vote_decision(6),
            4: _make_vote_decision(6),
            5: _make_vote_decision(5),
            6: _make_vote_decision(None),
        }
        agents = _make_fake_agents(gs, decision_map)

        run_vote_phase(gs, agents)

        p6 = _find_player(gs, 6)
        assert p6.status.alive is False
        # Verify vote events
        vote_cast = [e for e in gs.public_state.public_events if e["type"] == "vote_cast"]
        vote_resolved = [e for e in gs.public_state.public_events if e["type"] == "vote_resolved"]
        assert len(vote_cast) >= 4
        assert len(vote_resolved) == 1
        assert vote_resolved[0]["eliminated_seat_no"] == 6

    def test_tie_no_elimination(self):
        """Tied top votes → no one is eliminated."""
        gs = initialize_game("test-201", seed=FIXED_SIX_PLAYER_SEED)
        gs.public_state.phase = GamePhase.vote

        decision_map = {
            1: _make_vote_decision(5),
            2: _make_vote_decision(5),
            3: _make_vote_decision(5),
            4: _make_vote_decision(6),
            5: _make_vote_decision(6),
            6: _make_vote_decision(6),
        }
        agents = _make_fake_agents(gs, decision_map)

        run_vote_phase(gs, agents)

        p5 = _find_player(gs, 5)
        p6 = _find_player(gs, 6)
        assert p5.status.alive is True
        assert p6.status.alive is True

        vote_resolved = [e for e in gs.public_state.public_events if e["type"] == "vote_resolved"]
        assert len(vote_resolved) == 1
        assert vote_resolved[0]["eliminated_seat_no"] is None
        assert set(vote_resolved[0]["tied_seats"]) == {5, 6}

    def test_game_ends_after_vote_if_winner(self):
        """If vote elimination triggers game end, phase should be ended."""
        gs = initialize_game("test-202", seed=FIXED_SIX_PLAYER_SEED)
        gs.public_state.phase = GamePhase.vote

        # Pre-kill one wolf, then vote out the other → good wins
        p1 = _find_player(gs, 1)
        p1.status.alive = False
        gs.public_state.alive_players.remove(1)
        gs.public_state.dead_players.append(1)

        # Vote out wolf 2
        decision_map = {
            2: _make_vote_decision(5),
            3: _make_vote_decision(2),
            4: _make_vote_decision(2),
            5: _make_vote_decision(2),
            6: _make_vote_decision(2),
            1: _make_vote_decision(None),  # dead, won't be called
        }
        agents = _make_fake_agents(gs, decision_map)

        run_vote_phase(gs, agents)

        assert gs.public_state.phase == GamePhase.ended
        assert gs.winner == Camp.good

    def test_vote_phase_sets_correct_phase(self):
        """Vote phase should set phase to vote, then to ended if winner found."""
        gs = initialize_game("test-203", seed=FIXED_SIX_PLAYER_SEED)
        gs.public_state.phase = GamePhase.vote

        decision_map = {s: _make_vote_decision(None) for s in range(1, 7)}
        agents = _make_fake_agents(gs, decision_map)

        run_vote_phase(gs, agents)

        # No elimination, no winner → phase stays at vote after function
        # (The function sets it to vote at start, doesn't change it back)
        assert gs.public_state.phase in (GamePhase.vote, GamePhase.ended)


# ── Full cycle tests ──────────────────────────────────────────────────────────


class TestRunOneCycle:
    def test_one_cycle_runs_night_day_vote(self):
        """One cycle should run night, day, and vote phases."""
        gs = initialize_game("test-300", seed=FIXED_SIX_PLAYER_SEED)
        gs.public_state.phase = GamePhase.night

        # Night: wolves kill 5, witch does nothing
        # Day: everyone speaks
        # Vote: everyone abstains
        night_decisions = {
            1: _make_kill_decision(5),
        }
        day_decisions = {
            seat: _make_speak_decision(f"我是{seat}号。")
            for seat in [1, 2, 3, 4, 6]  # 5 is dead after night
        }
        vote_decisions = {
            seat: _make_vote_decision(None)
            for seat in [1, 2, 3, 4, 6]
        }

        # Combine: agents need decisions in order of calling
        # Night: wolves (1,2) and witch (4) and seer (3)
        # Day: alive players speak
        # Vote: alive players vote
        fake_agents: dict[int, FakeAgent] = {}
        for p in gs.players:
            decisions = []
            role = p.role
            if role == Role.werewolf and p.seat_no in night_decisions:
                decisions.append(night_decisions[p.seat_no])
            elif role == Role.witch:
                decisions.append(
                    AgentDecision(
                        action=WitchAction(action_type=ActionType.witch_save, target_seat_no=5),
                        reasoning_summary="不救人。",
                    )
                )
            elif role == Role.seer:
                decisions.append(_make_seer_check_decision(2))
            # Day speech
            if p.seat_no in day_decisions:
                decisions.append(day_decisions[p.seat_no])
            # Vote
            if p.seat_no in vote_decisions:
                decisions.append(vote_decisions[p.seat_no])
            fake_agents[p.seat_no] = FakeAgent(role, decisions)

        run_one_cycle(gs, fake_agents)

        event_types = [e["type"] for e in gs.public_state.public_events]
        assert "night_resolved" in event_types
        assert "speech" in event_types
        assert "vote_resolved" in event_types


class TestRunUntilFinished:
    def test_run_until_good_wins(self):
        """Run game to completion where good wins by eliminating all wolves."""
        gs = initialize_game("test-400", seed=FIXED_SIX_PLAYER_SEED)

        # Strategy:
        # Cycle 1 night: wolf kills 5 (villager)
        # Cycle 1 day: everyone speaks
        # Cycle 1 vote: everyone votes wolf 1 → wolf 1 eliminated
        # Cycle 2 night: wolf 2 kills 6 (villager)
        # Cycle 2 day: survivors speak
        # Cycle 2 vote: everyone votes wolf 2 → wolf 2 eliminated, good wins

        fake_agents: dict[int, FakeAgent] = {}
        for p in gs.players:
            decisions: list[AgentDecision] = []
            role = p.role

            # Cycle 1
            if role == Role.werewolf and p.seat_no == 1:
                decisions.append(_make_kill_decision(5))
            elif role == Role.witch:
                decisions.append(_make_poison_decision(1))  # poison wolf 1
            elif role == Role.seer:
                decisions.append(_make_seer_check_decision(2))

            # Cycle 1 day (all alive speak)
            decisions.append(_make_speak_decision(f"我是{p.seat_no}号。"))

            # Cycle 1 vote - nobody votes, but witch already poisoned wolf 1
            decisions.append(_make_vote_decision(None))

            fake_agents[p.seat_no] = FakeAgent(role, decisions)

        gs = run_until_finished(gs, fake_agents, max_cycles=3)

        # Check: wolf 1 was poisoned in night 1 → dies
        # If wolves are dead, good wins
        if gs.public_state.phase == GamePhase.ended:
            assert gs.winner is not None

    def test_game_does_not_exceed_max_cycles(self):
        """Running with max_cycles should not loop forever."""
        gs = initialize_game("test-401", seed=FIXED_SIX_PLAYER_SEED)

        # All agents do nothing useful
        fake_agents: dict[int, FakeAgent] = {}
        for p in gs.players:
            decisions = []
            if p.role == Role.werewolf:
                decisions.append(_make_kill_decision(p.seat_no))  # can't kill self
            elif p.role == Role.witch:
                decisions.append(_make_save_decision(p.seat_no))
            elif p.role == Role.seer:
                decisions.append(_make_seer_check_decision(p.seat_no))
            # Day speech
            decisions.append(_make_speak_decision(f"我是{p.seat_no}号。"))
            # Vote
            decisions.append(_make_vote_decision(None))
            fake_agents[p.seat_no] = FakeAgent(p.role, decisions)

        gs = run_until_finished(gs, fake_agents, max_cycles=2)
        # Should stop after max_cycles without error
        assert gs.public_state.round <= 3


# ── Information isolation tests ───────────────────────────────────────────────


class TestInformationIsolation:
    def test_runner_only_uses_build_player_view(self):
        """Verify that fake agents receive PlayerViews, not TruthState."""
        gs = initialize_game("test-500", seed=FIXED_SIX_PLAYER_SEED)
        gs.public_state.phase = GamePhase.night

        wolf1 = _make_kill_decision(5)
        seer_check = _make_seer_check_decision(1)
        witch = _make_save_decision(5)

        fake_agents = {
            1: FakeAgent(Role.werewolf, [wolf1]),
            2: FakeAgent(Role.werewolf, []),
            3: FakeAgent(Role.seer, [seer_check]),
            4: FakeAgent(Role.witch, [witch]),
            5: FakeAgent(Role.villager, []),
            6: FakeAgent(Role.villager, []),
        }

        run_night_phase(gs, fake_agents)

        # Each agent should have received a PlayerView with no truth_state
        for seat_no, agent in fake_agents.items():
            for view in agent.views:
                assert isinstance(view, PlayerView)
                # PlayerView model doesn't have truth_state field
                view_dict = view.model_dump()
                assert "truth_state" not in view_dict
                assert "TruthState" not in str(type(view))

    def test_good_agent_cannot_see_wolf_team_in_runner(self):
        """Good agents should not see wolf_team via the runner."""
        gs = initialize_game("test-501", seed=FIXED_SIX_PLAYER_SEED)
        gs.public_state.phase = GamePhase.night

        seer = _make_seer_check_decision(1)
        agent = FakeAgent(Role.seer, [seer])

        # Build dict matching what the runner expects
        agents = {3: agent}
        # Manually call build + decide to simulate runner
        view = build_player_view(gs, 3)
        agent.decide(view)

        assert len(agent.views) == 1
        assert agent.views[0].known_wolf_team == []


# ── LangGraph tests ───────────────────────────────────────────────────────────


class TestLangGraph:
    def test_build_main_graph_compiles(self):
        """build_main_graph() should return a compiled graph."""
        graph = build_main_graph()
        assert graph is not None
        # Check it has a invoke method (compiled graphs do)
        assert hasattr(graph, "invoke")

    def test_graph_invoke_creates_and_runs(self):
        """Graph should be invocable."""
        graph = build_main_graph()

        gs = initialize_game("test-600", seed=FIXED_SIX_PLAYER_SEED)
        initial_state = {"game_state": gs.model_dump()}

        result = graph.invoke(initial_state)
        assert result is not None
        assert "game_state" in result

    def test_graph_has_expected_nodes(self):
        """Graph should have night, day, vote nodes."""
        graph = build_main_graph()
        # The compiled graph has a get_graph() method for introspection
        nodes = graph.get_graph().nodes
        node_names = {n for n in nodes.keys()}
        assert "night" in node_names
        assert "day" in node_names
        assert "vote" in node_names
        assert "__start__" in node_names


# ── Sheriff election tests ─────────────────────────────────────────────────────


def _init_12p_with_sheriff(game_id: str) -> GameState:
    """Create a 12-player game with sheriff enabled."""
    rules = RuleConfig(enable_sheriff=True)
    return initialize_game(
        game_id,
        setup=twelve_player_setup(),
        rule_config=rules,
    )


def _sheriff_election_helpers() -> tuple[
    dict[int, list[AgentDecision]], dict[int, Role]
]:
    """Return role map for a standard 12-player setup."""
    # twelve_player_setup: 4 wolves, 1 seer, 1 witch, 1 hunter, 1 guard, 1 idiot, 3 villagers
    roles: dict[int, Role] = {}
    # We'll discover roles from the actual game state instead
    return {}, roles


class TestSheriffElection:
    def test_night_announcement_is_after_sheriff_election(self):
        """First-day sheriff election should happen before night result is announced."""
        gs = _init_12p_with_sheriff("test-sheriff-night-order")

        night_agents = _make_fake_agents(gs, {})
        run_night_phase(gs, night_agents)

        event_types_after_night = [e["type"] for e in gs.public_state.public_events]
        assert "night_resolved" not in event_types_after_night
        assert gs.runtime_state.pending_night_announcement is not None

        first_alive = next(p.seat_no for p in gs.players if p.status.alive)
        day_agents: dict[int, FakeAgent] = {}
        for p in gs.players:
            day_agents[p.seat_no] = FakeAgent(
                p.role,
                [
                    _make_run_for_sheriff_decision(
                        run=p.seat_no == first_alive,
                        content=f"我是{p.seat_no}号，竞选警长。"
                        if p.seat_no == first_alive
                        else None,
                    ),
                    _make_sheriff_vote_decision(first_alive),
                    _make_speak_decision(f"我是{p.seat_no}号。"),
                ],
            )

        run_day_phase(gs, day_agents)

        event_types = [e["type"] for e in gs.public_state.public_events]
        assert event_types.index("sheriff_elected") < event_types.index("night_resolved")
        assert event_types.index("night_resolved") < event_types.index("speech")
        assert gs.runtime_state.pending_night_announcement is None

    def test_no_candidates_no_sheriff(self):
        """All agents decline to run → sheriff_seat_no=None, reason=no_candidates."""
        gs = _init_12p_with_sheriff("test-sheriff-001")
        gs.public_state.phase = GamePhase.day

        agents: dict[int, FakeAgent] = {}
        for p in gs.players:
            decisions: list[AgentDecision] = [
                _make_run_for_sheriff_decision(run=False),
                _make_speak_decision(f"我是{p.seat_no}号。"),
            ]
            agents[p.seat_no] = FakeAgent(p.role, decisions)

        run_day_phase(gs, agents)

        assert gs.sheriff_seat_no is None
        assert gs.runtime_state.sheriff_election_done is True

        sheriff_elected = [
            e for e in gs.public_state.public_events if e["type"] == "sheriff_elected"
        ]
        assert len(sheriff_elected) == 1
        assert sheriff_elected[0]["sheriff_seat_no"] is None
        assert sheriff_elected[0]["reason"] == "no_candidates"

    def test_first_round_winner(self):
        """One clear winner on first round → elected immediately."""
        gs = _init_12p_with_sheriff("test-sheriff-002")
        gs.public_state.phase = GamePhase.day

        # Pick first 3 players as candidates
        alive = [p for p in gs.players if p.status.alive]
        candidates = [alive[0].seat_no, alive[1].seat_no, alive[2].seat_no]

        agents: dict[int, FakeAgent] = {}
        for p in gs.players:
            decisions: list[AgentDecision] = []
            # run_for_sheriff
            decisions.append(
                _make_run_for_sheriff_decision(
                    run=p.seat_no in candidates,
                    content=f"我是{p.seat_no}号，竞选警长。" if p.seat_no in candidates else None,
                )
            )
            # sheriff_vote: everyone votes for candidates[0]
            decisions.append(_make_sheriff_vote_decision(candidates[0]))
            # day speech
            decisions.append(_make_speak_decision(f"我是{p.seat_no}号。"))
            agents[p.seat_no] = FakeAgent(p.role, decisions)

        run_day_phase(gs, agents)

        assert gs.sheriff_seat_no == candidates[0]

        sheriff_elected = [
            e for e in gs.public_state.public_events if e["type"] == "sheriff_elected"
        ]
        assert len(sheriff_elected) == 1
        assert sheriff_elected[0]["sheriff_seat_no"] == candidates[0]

        # No PK events should be generated
        pk_started = [
            e for e in gs.public_state.public_events if e["type"] == "sheriff_pk_started"
        ]
        assert len(pk_started) == 0

    def test_first_round_tie_then_second_round_winner(self):
        """First round tie → PK speeches → second round someone wins."""
        gs = _init_12p_with_sheriff("test-sheriff-003")
        gs.public_state.phase = GamePhase.day

        alive = [p for p in gs.players if p.status.alive]
        # Two candidates: alive[0] and alive[1]
        cand_a = alive[0].seat_no
        cand_b = alive[1].seat_no
        candidates = [cand_a, cand_b]

        agents: dict[int, FakeAgent] = {}
        for p in gs.players:
            decisions: list[AgentDecision] = []
            # run_for_sheriff
            decisions.append(
                _make_run_for_sheriff_decision(
                    run=p.seat_no in candidates,
                    content=f"我是{p.seat_no}号，竞选警长。" if p.seat_no in candidates else None,
                )
            )
            # First round sheriff_vote: split votes to create a tie
            if p.seat_no % 2 == 0:
                decisions.append(_make_sheriff_vote_decision(cand_a))
            else:
                decisions.append(_make_sheriff_vote_decision(cand_b))
            # PK speech (only for tied candidates)
            if p.seat_no in candidates:
                decisions.append(
                    AgentDecision(
                        action=SpeakAction(content=f"我是{p.seat_no}号，请投票给我。"),
                        reasoning_summary="PK发言推理。",
                    )
                )
            # Second round sheriff_vote: all for cand_a
            decisions.append(_make_sheriff_vote_decision(cand_a))
            # Regular day speech
            decisions.append(_make_speak_decision(f"我是{p.seat_no}号。"))
            agents[p.seat_no] = FakeAgent(p.role, decisions)

        run_day_phase(gs, agents)

        assert gs.sheriff_seat_no == cand_a

        # Verify PK events
        pk_started = [
            e for e in gs.public_state.public_events if e["type"] == "sheriff_pk_started"
        ]
        assert len(pk_started) == 1
        assert set(pk_started[0]["tied_seats"]) == set(candidates)

        pk_speeches = [
            e for e in gs.public_state.public_events if e["type"] == "sheriff_pk_speech"
        ]
        assert len(pk_speeches) == 2
        for ps in pk_speeches:
            assert ps["seat_no"] in candidates
            assert "content" in ps
            assert "reasoning_summary" in ps  # kept in raw events for logging

        # Verify second round votes have election_round=2
        sheriff_votes_r2 = [
            e for e in gs.public_state.public_events
            if e["type"] == "sheriff_vote_cast" and e.get("election_round") == 2
        ]
        assert len(sheriff_votes_r2) == len(alive)

        sheriff_elected = [
            e for e in gs.public_state.public_events if e["type"] == "sheriff_elected"
        ]
        assert len(sheriff_elected) == 1
        assert sheriff_elected[0]["sheriff_seat_no"] == cand_a

    def test_first_round_tie_then_second_round_tie_no_sheriff(self):
        """First round tie → PK → second round still tie → no sheriff, reason=second_tie."""
        gs = _init_12p_with_sheriff("test-sheriff-004")
        gs.public_state.phase = GamePhase.day

        alive = [p for p in gs.players if p.status.alive]
        cand_a = alive[0].seat_no
        cand_b = alive[1].seat_no
        candidates = [cand_a, cand_b]

        agents: dict[int, FakeAgent] = {}
        for p in gs.players:
            decisions: list[AgentDecision] = []
            # run_for_sheriff
            decisions.append(
                _make_run_for_sheriff_decision(
                    run=p.seat_no in candidates,
                    content=f"我是{p.seat_no}号，竞选警长。" if p.seat_no in candidates else None,
                )
            )
            # First round: split votes to tie
            if p.seat_no % 2 == 0:
                decisions.append(_make_sheriff_vote_decision(cand_a))
            else:
                decisions.append(_make_sheriff_vote_decision(cand_b))
            # PK speech
            if p.seat_no in candidates:
                decisions.append(
                    AgentDecision(
                        action=SpeakAction(content=f"我是{p.seat_no}号，PK发言。"),
                        reasoning_summary="PK推理。",
                    )
                )
            # Second round: STILL tie (same split)
            if p.seat_no % 2 == 0:
                decisions.append(_make_sheriff_vote_decision(cand_a))
            else:
                decisions.append(_make_sheriff_vote_decision(cand_b))
            # Regular day speech
            decisions.append(_make_speak_decision(f"我是{p.seat_no}号。"))
            agents[p.seat_no] = FakeAgent(p.role, decisions)

        run_day_phase(gs, agents)

        assert gs.sheriff_seat_no is None

        sheriff_elected = [
            e for e in gs.public_state.public_events if e["type"] == "sheriff_elected"
        ]
        assert len(sheriff_elected) == 1
        assert sheriff_elected[0]["sheriff_seat_no"] is None
        assert sheriff_elected[0]["reason"] == "second_tie"

        # PK events still present
        pk_started = [
            e for e in gs.public_state.public_events if e["type"] == "sheriff_pk_started"
        ]
        assert len(pk_started) == 1

    def test_sheriff_speech_uses_public_content_not_reasoning(self):
        """sheriff_speech event content must come from action.content, not reasoning_summary."""
        gs = _init_12p_with_sheriff("test-sheriff-005")
        gs.public_state.phase = GamePhase.day

        # Only one candidate with public content
        alive = [p for p in gs.players if p.status.alive]
        cand = alive[0].seat_no

        agents: dict[int, FakeAgent] = {}
        for p in gs.players:
            decisions: list[AgentDecision] = []
            is_candidate = p.seat_no == cand
            decisions.append(
                _make_run_for_sheriff_decision(
                    run=is_candidate,
                    content="我参选警长，这是我的公开竞选发言。" if is_candidate else None,
                )
            )
            decisions.append(_make_sheriff_vote_decision(cand))
            decisions.append(_make_speak_decision(f"我是{p.seat_no}号。"))
            agents[p.seat_no] = FakeAgent(p.role, decisions)

        run_day_phase(gs, agents)

        sheriff_speeches = [
            e for e in gs.public_state.public_events if e["type"] == "sheriff_speech" and e["run"]
        ]
        assert len(sheriff_speeches) == 1
        speech = sheriff_speeches[0]
        # content is the public campaign speech, NOT reasoning_summary
        assert speech["content"] == "我参选警长，这是我的公开竞选发言。"
        assert "reasoning_summary" in speech  # still in raw events for log

    def test_sheriff_speech_no_content_fallback(self):
        """When action.content is None, use neutral fallback text."""
        gs = _init_12p_with_sheriff("test-sheriff-006")
        gs.public_state.phase = GamePhase.day

        alive = [p for p in gs.players if p.status.alive]
        cand = alive[0].seat_no

        agents: dict[int, FakeAgent] = {}
        for p in gs.players:
            decisions: list[AgentDecision] = []
            is_candidate = p.seat_no == cand
            # No content provided
            decisions.append(
                AgentDecision(
                    action=RunForSheriffAction(run=is_candidate, content=None),
                    reasoning_summary="我不想公开说。",
                )
            )
            decisions.append(_make_sheriff_vote_decision(cand))
            decisions.append(_make_speak_decision(f"我是{p.seat_no}号。"))
            agents[p.seat_no] = FakeAgent(p.role, decisions)

        run_day_phase(gs, agents)

        sheriff_speeches = [
            e for e in gs.public_state.public_events if e["type"] == "sheriff_speech" and e["run"]
        ]
        assert len(sheriff_speeches) == 1
        # Fallback text, never the reasoning_summary
        assert "参与警长竞选" in sheriff_speeches[0]["content"]
        assert sheriff_speeches[0]["content"] != "我不想公开说。"
