from __future__ import annotations

from collections.abc import Callable, Iterator
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, StateGraph

from app.agents.schemas import ActionType, AgentDecision
from app.engine.death import find_player, kill_player
from app.engine import (
    NightActionSet,
    Vote,
    VoteResult,
    apply_vote_result,
    check_winner,
    resolve_night,
    tally_votes,
)
from app.state.schemas import GamePhase, GameState, Role
from app.state.view_builder import PlayerView, build_player_view


# ── Agent protocol (decouples runner from BaseAgent / LLM) ────────────────────


class Agent(Protocol):
    """Minimal agent interface: takes PlayerView, returns AgentDecision."""

    role: Role

    def decide(self, view: PlayerView) -> AgentDecision: ...


# ── Event logging helper ──────────────────────────────────────────────────────


EventSink = Callable[[GameState, dict[str, Any]], None]
_event_sink: ContextVar[EventSink | None] = ContextVar("event_sink", default=None)


@contextmanager
def live_event_sink(sink: EventSink | None) -> Iterator[None]:
    token = _event_sink.set(sink)
    try:
        yield
    finally:
        _event_sink.reset(token)


def _log_event(game_state: GameState, event_type: str, **kwargs: Any) -> None:
    event = {"type": event_type, **kwargs}
    game_state.public_state.public_events.append(event)
    sink = _event_sink.get()
    if sink is not None:
        sink(game_state, event)


def _alive_seats(game_state: GameState) -> list[int]:
    return [p.seat_no for p in game_state.players if p.status.alive]


def _build_action_view(
    game_state: GameState,
    seat_no: int,
    action: ActionType,
    *,
    private_info: dict[str, Any] | None = None,
) -> PlayerView:
    return build_player_view(
        game_state,
        seat_no,
        available_actions_override=[action.value],
        private_info_override=private_info,
    )


def _maybe_transfer_sheriff_badge(
    game_state: GameState, agents: dict[int, Agent], dead_seat: int
) -> None:
    if game_state.sheriff_seat_no != dead_seat:
        return

    alive = _alive_seats(game_state)
    if not alive:
        game_state.sheriff_seat_no = None
        _log_event(game_state, "sheriff_badge_destroyed", from_seat_no=dead_seat)
        return

    decision = agents[dead_seat].decide(
        _build_action_view(game_state, dead_seat, ActionType.sheriff_assign)
    )
    action = decision.action
    target = getattr(action, "target_seat_no", None)
    if action.action_type == ActionType.sheriff_assign and target in alive:
        game_state.sheriff_seat_no = target
        _log_event(
            game_state,
            "sheriff_badge_assigned",
            from_seat_no=dead_seat,
            to_seat_no=target,
            reasoning_summary=decision.reasoning_summary,
        )
    else:
        game_state.sheriff_seat_no = None
        _log_event(game_state, "sheriff_badge_destroyed", from_seat_no=dead_seat)


def _maybe_trigger_hunter_shot(
    game_state: GameState,
    agents: dict[int, Agent],
    dead_seat: int,
    death_reason: str,
) -> int | None:
    player = find_player(game_state, dead_seat)
    if player.role != Role.hunter:
        return None
    if dead_seat in game_state.runtime_state.hunter_shot_used_seats:
        return None
    if (
        death_reason == "witch_poison"
        and not game_state.rule_config.hunter_can_shoot_when_poisoned
    ):
        _log_event(game_state, "hunter_no_shot", seat_no=dead_seat, reason=death_reason)
        return None

    decision = agents[dead_seat].decide(
        _build_action_view(game_state, dead_seat, ActionType.hunter_shoot)
    )
    action = decision.action
    target = getattr(action, "target_seat_no", None)
    alive = _alive_seats(game_state)
    game_state.runtime_state.hunter_shot_used_seats.append(dead_seat)
    if action.action_type != ActionType.hunter_shoot or target not in alive:
        _log_event(game_state, "hunter_no_shot", seat_no=dead_seat, reason="invalid_target")
        return None

    kill_player(game_state, target, reason="hunter_shot")
    _log_event(
        game_state,
        "hunter_shot",
        seat_no=dead_seat,
        target_seat_no=target,
        reasoning_summary=decision.reasoning_summary,
    )
    _maybe_transfer_sheriff_badge(game_state, agents, target)
    return target


# ── Night phase helpers ───────────────────────────────────────────────────────


def _collect_wolf_kill(
    game_state: GameState, agents: dict[int, Agent]
) -> int | None:
    """Collect werewolf kill target. Majority vote, tie → smallest seat_no."""
    wolf_seats = [
        p.seat_no
        for p in game_state.players
        if p.status.alive and p.role == Role.werewolf
    ]
    if not wolf_seats:
        return None

    targets: list[int] = []
    for seat_no in wolf_seats:
        view = build_player_view(game_state, seat_no)
        decision = agents[seat_no].decide(view)
        action = decision.action
        if action.action_type == ActionType.werewolf_kill:
            targets.append(action.target_seat_no)
            _log_event(
                game_state,
                "night_action",
                seat_no=seat_no,
                action_type=action.action_type.value,
                target_seat_no=action.target_seat_no,
                reasoning_summary=decision.reasoning_summary,
            )

    if not targets:
        return None

    counter = Counter(targets)
    max_count = max(counter.values())
    top = [t for t, c in counter.items() if c == max_count]
    return min(top)


def _collect_seer_check(
    game_state: GameState, agents: dict[int, Agent]
) -> int | None:
    """Collect seer check target."""
    seer_seats = [
        p.seat_no
        for p in game_state.players
        if p.status.alive and p.role == Role.seer
    ]
    if not seer_seats:
        return None

    seat_no = seer_seats[0]
    view = build_player_view(game_state, seat_no)
    decision = agents[seat_no].decide(view)
    action = decision.action
    if action.action_type == ActionType.seer_check:
        _log_event(
            game_state,
            "night_action",
            seat_no=seat_no,
            action_type=action.action_type.value,
            target_seat_no=action.target_seat_no,
            reasoning_summary=decision.reasoning_summary,
        )
        return action.target_seat_no
    return None


def _collect_guard_protect(
    game_state: GameState, agents: dict[int, Agent]
) -> int | None:
    guard_seats = [
        p.seat_no
        for p in game_state.players
        if p.status.alive and p.role == Role.guard
    ]
    if not guard_seats:
        return None

    seat_no = guard_seats[0]
    view = build_player_view(game_state, seat_no)
    decision = agents[seat_no].decide(view)
    action = decision.action
    if action.action_type == ActionType.guard_protect:
        _log_event(
            game_state,
            "night_action",
            seat_no=seat_no,
            action_type=action.action_type.value,
            target_seat_no=action.target_seat_no,
            reasoning_summary=decision.reasoning_summary,
        )
        return action.target_seat_no
    return None


def _collect_witch_action(
    game_state: GameState,
    agents: dict[int, Agent],
    wolf_kill_target: int | None,
) -> tuple[int | None, int | None]:
    """Collect witch save/poison. Returns (save_target, poison_target).

    The witch is informed of the pending kill target via a temporary public event
    (simulating the moderator telling the witch who was killed overnight),
    so the witch's view is built after the event is written.
    """
    witch_seats = [
        p.seat_no
        for p in game_state.players
        if p.status.alive and p.role == Role.witch
    ]
    if not witch_seats:
        return None, None

    seat_no = witch_seats[0]

    game_state.runtime_state.pending_wolf_kill_target = wolf_kill_target

    view = build_player_view(game_state, seat_no)
    if not view.available_actions:
        return None, None
    decision = agents[seat_no].decide(view)
    action = decision.action

    _log_event(
        game_state,
        "night_action",
        seat_no=seat_no,
        action_type=action.action_type.value,
        target_seat_no=getattr(action, "target_seat_no", None),
        reasoning_summary=decision.reasoning_summary,
    )

    save_target = None
    poison_target = None
    if action.action_type == ActionType.witch_save:
        save_target = action.target_seat_no
    elif action.action_type == ActionType.witch_poison:
        poison_target = action.target_seat_no

    return save_target, poison_target


def _run_sheriff_election(game_state: GameState, agents: dict[int, Agent]) -> None:
    if (
        not game_state.rule_config.enable_sheriff
        or game_state.runtime_state.sheriff_election_done
    ):
        return

    alive = _alive_seats(game_state)
    candidates: list[int] = []
    for seat_no in alive:
        decision = agents[seat_no].decide(
            _build_action_view(game_state, seat_no, ActionType.run_for_sheriff)
        )
        action = decision.action
        run = bool(getattr(action, "run", False))
        _log_event(
            game_state,
            "sheriff_run",
            seat_no=seat_no,
            run=run,
            reasoning_summary=decision.reasoning_summary,
        )
        if action.action_type == ActionType.run_for_sheriff and run:
            candidates.append(seat_no)

    if not candidates:
        game_state.runtime_state.sheriff_election_done = True
        _log_event(game_state, "sheriff_elected", sheriff_seat_no=None, reason="no_candidates")
        return

    votes: list[Vote] = []
    for seat_no in alive:
        decision = agents[seat_no].decide(
            _build_action_view(
                game_state,
                seat_no,
                ActionType.sheriff_vote,
                private_info={"sheriff_candidates": candidates},
            )
        )
        action = decision.action
        target = getattr(action, "target_seat_no", None)
        _log_event(
            game_state,
            "sheriff_vote_cast",
            seat_no=seat_no,
            target_seat_no=target,
            reasoning_summary=decision.reasoning_summary,
        )
        votes.append(Vote(voter_seat_no=seat_no, target_seat_no=target))

    result = tally_votes(game_state, votes, allowed_targets=set(candidates))
    elected = result.eliminated_seat_no if not result.tied_seats else None
    game_state.sheriff_seat_no = elected
    game_state.runtime_state.sheriff_election_done = True
    _log_event(
        game_state,
        "sheriff_elected",
        sheriff_seat_no=elected,
        candidates=candidates,
        tied_seats=result.tied_seats,
        vote_counts=result.vote_counts,
    )


def _collect_exile_votes(game_state: GameState, agents: dict[int, Agent]) -> list[Vote]:
    votes: list[Vote] = []
    for p in game_state.players:
        if not p.status.alive or not p.status.can_vote:
            continue
        view = build_player_view(game_state, p.seat_no)
        decision = agents[p.seat_no].decide(view)
        action = decision.action
        if action.action_type == ActionType.vote:
            _log_event(
                game_state,
                "vote_cast",
                seat_no=p.seat_no,
                target_seat_no=action.target_seat_no,
                reasoning_summary=decision.reasoning_summary,
            )
            votes.append(
                Vote(voter_seat_no=p.seat_no, target_seat_no=action.target_seat_no)
            )
    return votes


def _resolve_vote_with_pk(
    game_state: GameState,
    agents: dict[int, Agent],
    votes: list[Vote],
) -> VoteResult:
    result = tally_votes(game_state, votes)
    if not result.tied_seats or not game_state.rule_config.enable_tie_pk:
        return result

    tied = sorted(result.tied_seats)
    _log_event(game_state, "pk_started", tied_seats=tied, vote_counts=result.vote_counts)

    for seat_no in tied:
        if not find_player(game_state, seat_no).status.alive:
            continue
        decision = agents[seat_no].decide(
            _build_action_view(
                game_state,
                seat_no,
                ActionType.speak,
                private_info={"pk_tied_seats": tied},
            )
        )
        action = decision.action
        if action.action_type == ActionType.speak:
            _log_event(
                game_state,
                "pk_speech",
                seat_no=seat_no,
                content=action.content,
                reasoning_summary=decision.reasoning_summary,
            )

    pk_votes: list[Vote] = []
    for p in game_state.players:
        if not p.status.alive or not p.status.can_vote:
            continue
        decision = agents[p.seat_no].decide(
            _build_action_view(
                game_state,
                p.seat_no,
                ActionType.vote,
                private_info={"pk_tied_seats": tied},
            )
        )
        action = decision.action
        target = getattr(action, "target_seat_no", None)
        _log_event(
            game_state,
            "pk_vote_cast",
            seat_no=p.seat_no,
            target_seat_no=target,
            reasoning_summary=decision.reasoning_summary,
        )
        pk_votes.append(Vote(voter_seat_no=p.seat_no, target_seat_no=target))

    pk_result = tally_votes(game_state, pk_votes, allowed_targets=set(tied))
    _log_event(
        game_state,
        "pk_resolved",
        eliminated_seat_no=pk_result.eliminated_seat_no if not pk_result.tied_seats else None,
        tied_seats=pk_result.tied_seats,
        vote_counts=pk_result.vote_counts,
    )
    if (
        pk_result.eliminated_seat_no is None
        and not pk_result.tied_seats
        and not pk_result.vote_counts
    ):
        return VoteResult(tied_seats=tied, vote_counts=result.vote_counts)
    if pk_result.tied_seats:
        return VoteResult(tied_seats=pk_result.tied_seats, vote_counts=pk_result.vote_counts)
    return pk_result


# ── Phase functions ───────────────────────────────────────────────────────────


def run_night_phase(game_state: GameState, agents: dict[int, Agent]) -> None:
    """Execute night phase: collect night actions, resolve, check winner."""
    game_state.public_state.phase = GamePhase.night
    game_state.public_state.round += 1

    wolf_kill_target = _collect_wolf_kill(game_state, agents)
    seer_check_target = _collect_seer_check(game_state, agents)
    guard_target = _collect_guard_protect(game_state, agents)
    witch_save_target, witch_poison_target = _collect_witch_action(
        game_state, agents, wolf_kill_target
    )

    actions = NightActionSet(
        wolf_kill_target=wolf_kill_target,
        witch_save_target=witch_save_target,
        witch_poison_target=witch_poison_target,
        seer_check_target=seer_check_target,
        guard_target=guard_target,
    )
    result = resolve_night(game_state, actions)
    game_state.runtime_state.pending_wolf_kill_target = None

    _log_event(
        game_state,
        "night_resolved",
        deaths=result.deaths,
        death_reasons=result.death_reasons,
        seer_result=result.seer_result.value if result.seer_result else None,
    )

    for dead_seat in list(result.deaths):
        _maybe_transfer_sheriff_badge(game_state, agents, dead_seat)
        shot_target = _maybe_trigger_hunter_shot(
            game_state,
            agents,
            dead_seat,
            result.death_reasons.get(dead_seat, "night_death"),
        )
        if shot_target is not None:
            _maybe_trigger_hunter_shot(
                game_state, agents, shot_target, "hunter_shot"
            )

    winner = check_winner(game_state)
    if winner is not None:
        game_state.winner = winner
        game_state.public_state.phase = GamePhase.ended


def run_day_phase(game_state: GameState, agents: dict[int, Agent]) -> None:
    """Execute day phase: each alive player speaks in seat order."""
    game_state.public_state.phase = GamePhase.day
    _run_sheriff_election(game_state, agents)

    alive_seats = [
        p.seat_no for p in game_state.players if p.status.alive
    ]
    for seat_no in alive_seats:
        view = build_player_view(game_state, seat_no)
        decision = agents[seat_no].decide(view)
        action = decision.action
        if action.action_type == ActionType.speak:
            _log_event(
                game_state,
                "speech",
                seat_no=seat_no,
                content=action.content,
                reasoning_summary=decision.reasoning_summary,
            )


def run_vote_phase(game_state: GameState, agents: dict[int, Agent]) -> None:
    """Execute vote phase: collect votes, tally, apply result, check winner."""
    game_state.public_state.phase = GamePhase.vote

    votes = _collect_exile_votes(game_state, agents)
    result = _resolve_vote_with_pk(game_state, agents, votes)
    eliminated = apply_vote_result(game_state, result)
    if eliminated is not None:
        _maybe_transfer_sheriff_badge(game_state, agents, eliminated)
        shot_target = _maybe_trigger_hunter_shot(
            game_state, agents, eliminated, "vote_elimination"
        )
        if shot_target is not None:
            _maybe_trigger_hunter_shot(game_state, agents, shot_target, "hunter_shot")

    _log_event(
        game_state,
        "vote_resolved",
        eliminated_seat_no=eliminated,
        tied_seats=result.tied_seats,
        vote_counts=result.vote_counts,
    )

    winner = check_winner(game_state)
    if winner is not None:
        game_state.winner = winner
        game_state.public_state.phase = GamePhase.ended


# ── Cycle / full-game runners ─────────────────────────────────────────────────


def run_one_cycle(game_state: GameState, agents: dict[int, Agent]) -> None:
    """Run one full cycle: night → day → vote."""
    if game_state.public_state.phase == GamePhase.ended:
        return
    run_night_phase(game_state, agents)
    if game_state.public_state.phase == GamePhase.ended:
        return
    run_day_phase(game_state, agents)
    if game_state.public_state.phase == GamePhase.ended:
        return
    run_vote_phase(game_state, agents)


def run_until_finished(
    game_state: GameState, agents: dict[int, Agent], *, max_cycles: int = 50
) -> GameState:
    """Run cycles until game ends or max_cycles reached."""
    for _ in range(max_cycles):
        if game_state.public_state.phase == GamePhase.ended:
            break
        run_one_cycle(game_state, agents)
    return game_state


# ── LangGraph helper types ────────────────────────────────────────────────────


class GraphState(TypedDict):
    """Serialisable state for LangGraph nodes.

    This graph is a lightweight orchestration skeleton. The production runner
    functions above execute with injected Agent objects; graph nodes keep the
    state serialisable and mark phase transitions so the graph can be compiled
    and invoked without live LLM calls.
    """

    game_state: dict[str, Any]
    cycle_complete: bool


def _serialize_gs(gs: GameState) -> dict[str, Any]:
    return gs.model_dump()


def _deserialize_gs(data: dict[str, Any]) -> GameState:
    return GameState.model_validate(data)


# ── LangGraph node functions ──────────────────────────────────────────────────


def _graph_night(state: GraphState) -> GraphState:
    gs = _deserialize_gs(state["game_state"])
    if gs.public_state.phase != GamePhase.ended:
        gs.public_state.phase = GamePhase.night
        _log_event(gs, "graph_phase", phase=GamePhase.night.value)
    return {"game_state": _serialize_gs(gs), "cycle_complete": False}


def _graph_day(state: GraphState) -> GraphState:
    gs = _deserialize_gs(state["game_state"])
    if gs.public_state.phase != GamePhase.ended:
        gs.public_state.phase = GamePhase.day
        _log_event(gs, "graph_phase", phase=GamePhase.day.value)
    return {"game_state": _serialize_gs(gs), "cycle_complete": False}


def _graph_vote(state: GraphState) -> GraphState:
    gs = _deserialize_gs(state["game_state"])
    if gs.public_state.phase != GamePhase.ended:
        gs.public_state.phase = GamePhase.vote
        _log_event(gs, "graph_phase", phase=GamePhase.vote.value)
    return {"game_state": _serialize_gs(gs), "cycle_complete": True}


def _route_after_night(state: GraphState) -> str:
    gs = _deserialize_gs(state["game_state"])
    if gs.public_state.phase == GamePhase.ended:
        return "ended"
    return "day"


def _route_after_day(state: GraphState) -> str:
    gs = _deserialize_gs(state["game_state"])
    if gs.public_state.phase == GamePhase.ended:
        return "ended"
    return "vote"


def _route_after_vote(state: GraphState) -> str:
    gs = _deserialize_gs(state["game_state"])
    if gs.public_state.phase == GamePhase.ended or state.get("cycle_complete", False):
        return "ended"
    return "night"


# ── Graph builder ─────────────────────────────────────────────────────────────


def build_main_graph() -> StateGraph:
    """Build a LangGraph StateGraph for the main werewolf game loop.

    Nodes: night, day, vote
    Edges: night → day → vote → (night|ended)
    """
    graph_builder = StateGraph(GraphState)

    graph_builder.add_node("night", _graph_night)
    graph_builder.add_node("day", _graph_day)
    graph_builder.add_node("vote", _graph_vote)

    graph_builder.set_entry_point("night")

    graph_builder.add_conditional_edges(
        "night", _route_after_night, {"day": "day", "ended": END}
    )
    graph_builder.add_conditional_edges(
        "day", _route_after_day, {"vote": "vote", "ended": END}
    )
    graph_builder.add_conditional_edges(
        "vote", _route_after_vote, {"night": "night", "ended": END}
    )

    return graph_builder.compile()
