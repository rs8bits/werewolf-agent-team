from __future__ import annotations

from collections import Counter
from enum import Enum

from app.agents.schemas import ActionType, AgentDecision
from app.engine import (
    NightActionSet,
    Vote,
    apply_vote_result,
    check_winner,
    resolve_night,
    tally_votes,
)
from app.engine.death import find_player, kill_player
from app.graph.main_graph import (
    Agent,
    _alive_seats,
    _build_action_view,
    _log_event,
    _publish_pending_night_announcement,
    _store_or_publish_night_announcement,
)
from app.state.schemas import (
    GamePhase,
    GameState,
    PendingHumanAction,
    PlayerType,
    Role,
)
from app.state.view_builder import build_player_view


class MixedResult(str, Enum):
    blocked = "blocked"
    cycle_complete = "cycle_complete"
    ended = "ended"


def _apply_human_decision(
    game_state: GameState, expected_action_type: str
) -> AgentDecision | None:
    rt = game_state.runtime_state
    if rt.submitted_human_decision is None:
        return None
    decision = AgentDecision.model_validate(rt.submitted_human_decision)
    if decision.action.action_type.value != expected_action_type:
        return None
    rt.submitted_human_decision = None
    return decision


def _block_for_human(
    game_state: GameState,
    seat_no: int,
    action_type: str,
    phase: GamePhase,
    *,
    extra_private_info: dict | None = None,
    force_available_actions: list[str] | None = None,
) -> MixedResult:
    view = build_player_view(game_state, seat_no)
    private_info = view.private_info
    if extra_private_info:
        private_info = {**private_info, **extra_private_info}
    available = force_available_actions if force_available_actions is not None else view.available_actions
    game_state.runtime_state.pending_human_action = PendingHumanAction(
        seat_no=seat_no,
        action_type=action_type,
        round=game_state.public_state.round,
        phase=phase,
        available_actions=available,
        private_info=private_info,
    )
    return MixedResult.blocked


def _is_human(game_state: GameState, seat_no: int) -> bool:
    player = find_player(game_state, seat_no)
    return player.player_type == PlayerType.human


def _majority_wolf_target(game_state: GameState) -> int | None:
    rt = game_state.runtime_state
    if not rt.mixed_wolf_targets:
        return None
    targets = list(rt.mixed_wolf_targets.values())
    if not targets:
        return None
    counter = Counter(targets)
    max_count = max(counter.values())
    top = [t for t, c in counter.items() if c == max_count]
    return min(top)


def _start_sheriff_election(game_state: GameState) -> None:
    rt = game_state.runtime_state
    rt.mixed_stage = "sheriff_run"
    rt.mixed_cursor = 0
    rt.mixed_sheriff_candidates = []
    rt.mixed_sheriff_votes = {}
    rt.mixed_sheriff_round = 0


def _continue_after_sheriff_election(game_state: GameState) -> None:
    rt = game_state.runtime_state
    _publish_pending_night_announcement(game_state)
    rt.mixed_stage = "night_post_deaths"
    rt.mixed_cursor = 0
    rt.mixed_death_effect_stage = rt.mixed_death_effect_stage or "badge"


# ── Mixed hunter shot helper ───────────────────────────────────────────────


def _maybe_trigger_hunter_shot_mixed(
    game_state: GameState,
    agents: dict[int, Agent],
    dead_seat: int,
    death_reason: str,
) -> MixedResult | int | None:
    player = find_player(game_state, dead_seat)
    if player.role != Role.hunter:
        return None
    rt = game_state.runtime_state
    if dead_seat in rt.hunter_shot_used_seats:
        return None
    if (
        death_reason == "witch_poison"
        and not game_state.rule_config.hunter_can_shoot_when_poisoned
    ):
        _log_event(game_state, "hunter_no_shot", seat_no=dead_seat, reason=death_reason)
        return None

    decision = None
    if rt.submitted_human_decision is not None:
        d = AgentDecision.model_validate(rt.submitted_human_decision)
        if d.action.action_type == ActionType.hunter_shoot:
            decision = d
            rt.submitted_human_decision = None

    if decision is None:
        if _is_human(game_state, dead_seat):
            alive = _alive_seats(game_state)
            rt.pending_human_action = PendingHumanAction(
                seat_no=dead_seat,
                action_type=ActionType.hunter_shoot.value,
                round=game_state.public_state.round,
                phase=game_state.public_state.phase,
                available_actions=[ActionType.hunter_shoot.value],
                private_info={
                    "hunter_can_shoot": True,
                    "hunter_shoot_candidates": [s for s in alive if s != dead_seat],
                },
            )
            return MixedResult.blocked
        decision = agents[dead_seat].decide(
            _build_action_view(game_state, dead_seat, ActionType.hunter_shoot)
        )

    action = decision.action
    target = getattr(action, "target_seat_no", None)
    alive = _alive_seats(game_state)
    rt.hunter_shot_used_seats.append(dead_seat)
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
    return target


# ── Mixed sheriff badge transfer ────────────────────────────────────────────


def _maybe_transfer_sheriff_badge_mixed(
    game_state: GameState,
    agents: dict[int, Agent],
    dead_seat: int,
) -> MixedResult | None:
    if game_state.sheriff_seat_no != dead_seat:
        return None

    alive = _alive_seats(game_state)
    if not alive:
        game_state.sheriff_seat_no = None
        _log_event(game_state, "sheriff_badge_destroyed", from_seat_no=dead_seat)
        return None

    rt = game_state.runtime_state
    decision = None
    if rt.submitted_human_decision is not None:
        d = AgentDecision.model_validate(rt.submitted_human_decision)
        if d.action.action_type == ActionType.sheriff_assign:
            decision = d
            rt.submitted_human_decision = None

    if decision is None:
        if _is_human(game_state, dead_seat):
            rt.pending_human_action = PendingHumanAction(
                seat_no=dead_seat,
                action_type=ActionType.sheriff_assign.value,
                round=game_state.public_state.round,
                phase=game_state.public_state.phase,
                available_actions=[ActionType.sheriff_assign.value],
                private_info={"sheriff_assign_candidates": alive},
            )
            return MixedResult.blocked
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
    return None


# ── Cycle reset helper ─────────────────────────────────────────────────────


def _reset_for_next_cycle(game_state: GameState) -> None:
    rt = game_state.runtime_state
    rt.mixed_stage = "idle"
    rt.mixed_cursor = 0
    rt.mixed_wolf_targets = {}
    rt.mixed_seer_target = None
    rt.mixed_witch_save_target = None
    rt.mixed_witch_poison_target = None
    rt.mixed_votes = {}
    rt.mixed_death_queue = []
    rt.mixed_death_reasons = {}
    rt.mixed_death_effect_stage = None
    rt.mixed_sheriff_candidates = []
    rt.mixed_sheriff_votes = {}
    rt.mixed_sheriff_round = 0
    rt.mixed_pk_tied_seats = []
    rt.mixed_pk_votes = {}


# ── Step functions ─────────────────────────────────────────────────────────


def _step_night_wolves(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state
    wolf_seats = [
        p.seat_no for p in game_state.players
        if p.status.alive and p.role == Role.werewolf
    ]

    if rt.mixed_cursor >= len(wolf_seats):
        target = _majority_wolf_target(game_state)
        rt.pending_wolf_kill_target = target
        rt.mixed_stage = "night_seer"
        rt.mixed_cursor = 0
        return None

    seat_no = wolf_seats[rt.mixed_cursor]
    decision = _apply_human_decision(game_state, ActionType.werewolf_kill.value)

    if decision is None:
        if _is_human(game_state, seat_no):
            return _block_for_human(game_state, seat_no, ActionType.werewolf_kill.value, GamePhase.night)
        view = build_player_view(game_state, seat_no)
        decision = agents[seat_no].decide(view)

    action = decision.action
    if action.action_type == ActionType.werewolf_kill:
        rt.mixed_wolf_targets[seat_no] = action.target_seat_no
        _log_event(game_state, "night_action", seat_no=seat_no,
                   action_type=ActionType.werewolf_kill.value,
                   target_seat_no=action.target_seat_no,
                   reasoning_summary=decision.reasoning_summary)

    rt.mixed_cursor += 1
    return None


def _step_night_seer(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state
    seer_seats = [
        p.seat_no for p in game_state.players
        if p.status.alive and p.role == Role.seer
    ]

    if not seer_seats or rt.mixed_cursor >= 1:
        rt.mixed_stage = "night_witch"
        rt.mixed_cursor = 0
        return None

    seat_no = seer_seats[0]
    decision = _apply_human_decision(game_state, ActionType.seer_check.value)

    if decision is None:
        if _is_human(game_state, seat_no):
            return _block_for_human(game_state, seat_no, ActionType.seer_check.value, GamePhase.night)
        view = build_player_view(game_state, seat_no)
        decision = agents[seat_no].decide(view)

    action = decision.action
    if action.action_type == ActionType.seer_check:
        rt.mixed_seer_target = action.target_seat_no
        _log_event(game_state, "night_action", seat_no=seat_no,
                   action_type=ActionType.seer_check.value,
                   target_seat_no=action.target_seat_no,
                   reasoning_summary=decision.reasoning_summary)

    rt.mixed_cursor = 1
    return None


def _step_night_witch(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state
    witch_seats = [
        p.seat_no for p in game_state.players
        if p.status.alive and p.role == Role.witch
    ]

    if not witch_seats or rt.mixed_cursor >= 1:
        rt.mixed_stage = "night_resolve"
        rt.mixed_cursor = 0
        return None

    seat_no = witch_seats[0]
    rt.pending_wolf_kill_target = _majority_wolf_target(game_state)

    human_decision = None
    if rt.submitted_human_decision is not None:
        decision = AgentDecision.model_validate(rt.submitted_human_decision)
        at = decision.action.action_type.value
        if at in (ActionType.witch_save.value, ActionType.witch_poison.value):
            human_decision = decision
            rt.submitted_human_decision = None

    if human_decision is None:
        if _is_human(game_state, seat_no):
            view = build_player_view(game_state, seat_no)
            if not view.available_actions:
                rt.mixed_cursor = 1
                return None
            return _block_for_human(game_state, seat_no, view.available_actions[0], GamePhase.night)
        view = build_player_view(game_state, seat_no)
        if not view.available_actions:
            rt.mixed_cursor = 1
            return None
        human_decision = agents[seat_no].decide(view)

    action = human_decision.action
    target = getattr(action, "target_seat_no", None)
    _log_event(game_state, "night_action", seat_no=seat_no,
               action_type=action.action_type.value,
               target_seat_no=target,
               reasoning_summary=human_decision.reasoning_summary)

    if action.action_type == ActionType.witch_save:
        rt.mixed_witch_save_target = target
    elif action.action_type == ActionType.witch_poison:
        rt.mixed_witch_poison_target = target

    rt.mixed_cursor = 1
    return None


def _step_night_resolve(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state

    wolf_kill_target = _majority_wolf_target(game_state)
    actions = NightActionSet(
        wolf_kill_target=wolf_kill_target,
        witch_save_target=rt.mixed_witch_save_target,
        witch_poison_target=rt.mixed_witch_poison_target,
        seer_check_target=rt.mixed_seer_target,
        guard_target=None,
    )
    event_start_index = len(game_state.public_state.public_events)
    result = resolve_night(game_state, actions)
    rt.pending_wolf_kill_target = None

    _store_or_publish_night_announcement(
        game_state,
        event_start_index=event_start_index,
        deaths=result.deaths,
        death_reasons=result.death_reasons,
        seer_result=result.seer_result.value if result.seer_result else None,
    )

    rt.mixed_death_queue = list(result.deaths)
    rt.mixed_death_reasons = dict(result.death_reasons)
    rt.mixed_death_effect_stage = "badge"
    rt.mixed_stage = "night_post_deaths"
    rt.mixed_cursor = 0
    return None


def _step_night_post_deaths(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state

    if (
        game_state.rule_config.enable_sheriff
        and not rt.sheriff_election_done
    ):
        _start_sheriff_election(game_state)
        return None

    if rt.mixed_cursor >= len(rt.mixed_death_queue):
        winner = check_winner(game_state)
        if winner is not None:
            _publish_pending_night_announcement(game_state)
            game_state.winner = winner
            game_state.public_state.phase = GamePhase.ended
            return MixedResult.ended

        _publish_pending_night_announcement(game_state)
        rt.mixed_stage = "day_speech"
        rt.mixed_cursor = 0
        return None

    dead_seat = rt.mixed_death_queue[rt.mixed_cursor]
    death_reason = rt.mixed_death_reasons.get(dead_seat, "night_death")
    effect_stage = rt.mixed_death_effect_stage or "badge"

    if effect_stage == "badge":
        badge_result = _maybe_transfer_sheriff_badge_mixed(game_state, agents, dead_seat)
        if badge_result == MixedResult.blocked:
            return MixedResult.blocked
        rt.mixed_death_effect_stage = "hunter"
        return None

    if effect_stage == "hunter":
        shot_result = _maybe_trigger_hunter_shot_mixed(
            game_state, agents, dead_seat, death_reason
        )
        if shot_result == MixedResult.blocked:
            return MixedResult.blocked
        if isinstance(shot_result, int) and shot_result is not None:
            rt.mixed_death_queue.append(shot_result)
            rt.mixed_death_reasons[shot_result] = "hunter_shot"

        rt.mixed_death_effect_stage = "badge"
        rt.mixed_cursor += 1
        return None

    return None


# ── Sheriff election stages ────────────────────────────────────────────────


def _step_sheriff_run(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state
    game_state.public_state.phase = GamePhase.day

    alive = _alive_seats(game_state)

    if rt.mixed_cursor >= len(alive):
        if not rt.mixed_sheriff_candidates:
            rt.sheriff_election_done = True
            _log_event(game_state, "sheriff_elected", sheriff_seat_no=None, reason="no_candidates")
            _continue_after_sheriff_election(game_state)
            return None
        rt.mixed_stage = "sheriff_vote_1"
        rt.mixed_cursor = 0
        rt.mixed_sheriff_round = 1
        return None

    seat_no = alive[rt.mixed_cursor]
    decision = _apply_human_decision(game_state, ActionType.run_for_sheriff.value)

    if decision is None:
        if _is_human(game_state, seat_no):
            return _block_for_human(
                game_state, seat_no, ActionType.run_for_sheriff.value, GamePhase.day,
                force_available_actions=[ActionType.run_for_sheriff.value],
            )
        decision = agents[seat_no].decide(
            _build_action_view(game_state, seat_no, ActionType.run_for_sheriff)
        )

    action = decision.action
    run = bool(getattr(action, "run", False))
    _log_event(game_state, "sheriff_run", seat_no=seat_no, run=run,
               reasoning_summary=decision.reasoning_summary)
    if run:
        content = getattr(action, "content", None) or "我参与警长竞选，希望大家结合发言投票。"
        _log_event(game_state, "sheriff_speech", seat_no=seat_no, run=run,
                   content=content, reasoning_summary=decision.reasoning_summary)

    if action.action_type == ActionType.run_for_sheriff and run:
        rt.mixed_sheriff_candidates.append(seat_no)

    rt.mixed_cursor += 1
    return None


def _step_sheriff_vote(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state
    game_state.public_state.phase = GamePhase.day

    alive = _alive_seats(game_state)
    election_round = rt.mixed_sheriff_round
    allowed = (
        set(rt.mixed_pk_tied_seats) if election_round == 2
        else set(rt.mixed_sheriff_candidates)
    )

    if rt.mixed_cursor >= len(alive):
        votes: list[Vote] = []
        for seat_no, target in rt.mixed_sheriff_votes.items():
            votes.append(Vote(voter_seat_no=seat_no, target_seat_no=target))
        result = tally_votes(game_state, votes, allowed_targets=allowed)

        if not result.tied_seats:
            elected = result.eliminated_seat_no
            game_state.sheriff_seat_no = elected
            rt.sheriff_election_done = True
            _log_event(game_state, "sheriff_elected", sheriff_seat_no=elected,
                       candidates=rt.mixed_sheriff_candidates,
                       vote_counts=result.vote_counts)
            _continue_after_sheriff_election(game_state)
            return None

        if election_round == 2:
            game_state.sheriff_seat_no = None
            rt.sheriff_election_done = True
            _log_event(game_state, "sheriff_elected", sheriff_seat_no=None,
                       reason="second_tie",
                       candidates=rt.mixed_sheriff_candidates,
                       pk_tied_seats=rt.mixed_pk_tied_seats,
                       vote_counts=result.vote_counts)
            _continue_after_sheriff_election(game_state)
            return None

        # Round 1 tie → PK
        rt.mixed_pk_tied_seats = sorted(result.tied_seats)
        _log_event(game_state, "sheriff_pk_started",
                   tied_seats=rt.mixed_pk_tied_seats,
                   vote_counts=result.vote_counts)
        rt.mixed_stage = "sheriff_pk_speech"
        rt.mixed_cursor = 0
        return None

    seat_no = alive[rt.mixed_cursor]
    decision = _apply_human_decision(game_state, ActionType.sheriff_vote.value)

    if decision is None:
        if _is_human(game_state, seat_no):
            return _block_for_human(
                game_state, seat_no, ActionType.sheriff_vote.value, GamePhase.day,
                extra_private_info={
                    "sheriff_candidates": sorted(allowed),
                    "election_round": election_round,
                },
                force_available_actions=[ActionType.sheriff_vote.value],
            )
        decision = agents[seat_no].decide(
            _build_action_view(game_state, seat_no, ActionType.sheriff_vote,
                               private_info={
                                   "sheriff_candidates": sorted(allowed),
                                   "election_round": election_round,
                               })
        )

    action = decision.action
    target = getattr(action, "target_seat_no", None)
    _log_event(game_state, "sheriff_vote_cast", seat_no=seat_no,
               target_seat_no=target, election_round=election_round,
               reasoning_summary=decision.reasoning_summary)
    if action.action_type == ActionType.sheriff_vote:
        rt.mixed_sheriff_votes[seat_no] = target

    rt.mixed_cursor += 1
    return None


def _step_sheriff_pk_speech(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state
    game_state.public_state.phase = GamePhase.day

    tied = rt.mixed_pk_tied_seats

    if rt.mixed_cursor >= len(tied):
        rt.mixed_stage = "sheriff_vote_2"
        rt.mixed_cursor = 0
        rt.mixed_sheriff_votes = {}
        rt.mixed_sheriff_round = 2
        return None

    seat_no = tied[rt.mixed_cursor]
    if not find_player(game_state, seat_no).status.alive:
        rt.mixed_cursor += 1
        return None

    decision = _apply_human_decision(game_state, ActionType.speak.value)

    if decision is None:
        if _is_human(game_state, seat_no):
            return _block_for_human(
                game_state, seat_no, ActionType.speak.value, GamePhase.day,
                extra_private_info={"sheriff_pk_tied_seats": tied},
            )
        decision = agents[seat_no].decide(
            _build_action_view(game_state, seat_no, ActionType.speak,
                               private_info={"sheriff_pk_tied_seats": tied})
        )

    action = decision.action
    if action.action_type == ActionType.speak:
        _log_event(game_state, "sheriff_pk_speech", seat_no=seat_no,
                   content=action.content, reasoning_summary=decision.reasoning_summary)

    rt.mixed_cursor += 1
    return None


# ── Day speech ─────────────────────────────────────────────────────────────


def _step_day_speech(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state
    game_state.public_state.phase = GamePhase.day

    alive_seats = _alive_seats(game_state)

    if rt.mixed_cursor >= len(alive_seats):
        rt.mixed_stage = "vote"
        rt.mixed_cursor = 0
        return None

    seat_no = alive_seats[rt.mixed_cursor]
    decision = _apply_human_decision(game_state, ActionType.speak.value)

    if decision is None:
        if _is_human(game_state, seat_no):
            return _block_for_human(game_state, seat_no, ActionType.speak.value, GamePhase.day)
        view = build_player_view(game_state, seat_no)
        decision = agents[seat_no].decide(view)

    action = decision.action
    if action.action_type == ActionType.speak:
        _log_event(game_state, "speech", seat_no=seat_no,
                   content=action.content, reasoning_summary=decision.reasoning_summary)

    rt.mixed_cursor += 1
    return None


# ── Vote + PK stages ──────────────────────────────────────────────────────


def _step_vote(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state
    game_state.public_state.phase = GamePhase.vote

    voter_seats = [
        p.seat_no for p in game_state.players
        if p.status.alive and p.status.can_vote
    ]

    if rt.mixed_cursor >= len(voter_seats):
        votes: list[Vote] = []
        for seat_no, target in rt.mixed_votes.items():
            votes.append(Vote(voter_seat_no=seat_no, target_seat_no=target))
        result = tally_votes(game_state, votes)

        # Check for PK
        if result.tied_seats and game_state.rule_config.enable_tie_pk:
            rt.mixed_pk_tied_seats = sorted(result.tied_seats)
            _log_event(game_state, "pk_started",
                       tied_seats=rt.mixed_pk_tied_seats,
                       vote_counts=result.vote_counts)
            rt.mixed_stage = "pk_speech"
            rt.mixed_cursor = 0
            return None

        eliminated = apply_vote_result(game_state, result)

        _log_event(game_state, "vote_resolved",
                   eliminated_seat_no=eliminated,
                   tied_seats=result.tied_seats,
                   vote_counts=result.vote_counts)

        if eliminated is not None:
            rt.mixed_death_queue = [eliminated]
            rt.mixed_death_reasons = {eliminated: "vote_elimination"}
            rt.mixed_death_effect_stage = "badge"
            rt.mixed_stage = "vote_post_deaths"
            rt.mixed_cursor = 0
        else:
            winner = check_winner(game_state)
            if winner is not None:
                game_state.winner = winner
                game_state.public_state.phase = GamePhase.ended
                return MixedResult.ended
            _reset_for_next_cycle(game_state)
            return MixedResult.cycle_complete
        return None

    seat_no = voter_seats[rt.mixed_cursor]
    extra_pi: dict | None = None
    if rt.mixed_pk_tied_seats:
        extra_pi = {"pk_tied_seats": rt.mixed_pk_tied_seats}

    decision = _apply_human_decision(game_state, ActionType.vote.value)

    if decision is None:
        if _is_human(game_state, seat_no):
            return _block_for_human(
                game_state, seat_no, ActionType.vote.value, GamePhase.vote,
                extra_private_info=extra_pi,
            )
        if extra_pi:
            decision = agents[seat_no].decide(
                _build_action_view(game_state, seat_no, ActionType.vote,
                                   private_info=extra_pi)
            )
        else:
            view = build_player_view(game_state, seat_no)
            decision = agents[seat_no].decide(view)

    action = decision.action
    target = getattr(action, "target_seat_no", None)
    if action.action_type == ActionType.vote:
        rt.mixed_votes[seat_no] = target
        _log_event(game_state, "vote_cast", seat_no=seat_no,
                   target_seat_no=target, reasoning_summary=decision.reasoning_summary)

    rt.mixed_cursor += 1
    return None


def _step_pk_speech(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state
    game_state.public_state.phase = GamePhase.vote

    tied = rt.mixed_pk_tied_seats

    if rt.mixed_cursor >= len(tied):
        rt.mixed_stage = "pk_vote"
        rt.mixed_cursor = 0
        rt.mixed_pk_votes = {}
        return None

    seat_no = tied[rt.mixed_cursor]
    if not find_player(game_state, seat_no).status.alive:
        rt.mixed_cursor += 1
        return None

    decision = _apply_human_decision(game_state, ActionType.speak.value)

    if decision is None:
        if _is_human(game_state, seat_no):
            return _block_for_human(
                game_state, seat_no, ActionType.speak.value, GamePhase.vote,
                extra_private_info={"pk_tied_seats": tied},
            )
        decision = agents[seat_no].decide(
            _build_action_view(game_state, seat_no, ActionType.speak,
                               private_info={"pk_tied_seats": tied})
        )

    action = decision.action
    if action.action_type == ActionType.speak:
        _log_event(game_state, "pk_speech", seat_no=seat_no,
                   content=action.content, reasoning_summary=decision.reasoning_summary)

    rt.mixed_cursor += 1
    return None


def _step_pk_vote(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state
    game_state.public_state.phase = GamePhase.vote

    voter_seats = [
        p.seat_no for p in game_state.players
        if p.status.alive and p.status.can_vote
    ]
    tied = set(rt.mixed_pk_tied_seats)

    if rt.mixed_cursor >= len(voter_seats):
        rt.mixed_stage = "pk_resolve"
        rt.mixed_cursor = 0
        return None

    seat_no = voter_seats[rt.mixed_cursor]
    decision = _apply_human_decision(game_state, ActionType.vote.value)

    if decision is None:
        if _is_human(game_state, seat_no):
            return _block_for_human(
                game_state, seat_no, ActionType.vote.value, GamePhase.vote,
                extra_private_info={"pk_tied_seats": sorted(tied)},
            )
        decision = agents[seat_no].decide(
            _build_action_view(game_state, seat_no, ActionType.vote,
                               private_info={"pk_tied_seats": sorted(tied)})
        )

    action = decision.action
    target = getattr(action, "target_seat_no", None)
    _log_event(game_state, "pk_vote_cast", seat_no=seat_no,
               target_seat_no=target, reasoning_summary=decision.reasoning_summary)
    if action.action_type == ActionType.vote:
        rt.mixed_pk_votes[seat_no] = target

    rt.mixed_cursor += 1
    return None


def _step_pk_resolve(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state

    pk_votes = [
        Vote(voter_seat_no=seat_no, target_seat_no=target)
        for seat_no, target in rt.mixed_pk_votes.items()
    ]
    pk_result = tally_votes(
        game_state,
        pk_votes,
        allowed_targets=set(rt.mixed_pk_tied_seats),
    )
    eliminated = None
    if not pk_result.tied_seats and pk_result.eliminated_seat_no is not None:
        eliminated = apply_vote_result(game_state, pk_result)

    _log_event(game_state, "pk_resolved",
               eliminated_seat_no=eliminated,
               tied_seats=pk_result.tied_seats,
               vote_counts=pk_result.vote_counts)

    if eliminated is not None:
        rt.mixed_death_queue = [eliminated]
        rt.mixed_death_reasons = {eliminated: "vote_elimination"}
        rt.mixed_death_effect_stage = "badge"
        rt.mixed_stage = "vote_post_deaths"
        rt.mixed_cursor = 0
    else:
        winner = check_winner(game_state)
        if winner is not None:
            game_state.winner = winner
            game_state.public_state.phase = GamePhase.ended
            return MixedResult.ended
        _reset_for_next_cycle(game_state)
        return MixedResult.cycle_complete
    return None


def _step_vote_post_deaths(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state

    if rt.mixed_cursor >= len(rt.mixed_death_queue):
        winner = check_winner(game_state)
        if winner is not None:
            game_state.winner = winner
            game_state.public_state.phase = GamePhase.ended
            return MixedResult.ended
        _reset_for_next_cycle(game_state)
        return MixedResult.cycle_complete

    dead_seat = rt.mixed_death_queue[rt.mixed_cursor]
    death_reason = rt.mixed_death_reasons.get(dead_seat, "vote_elimination")
    effect_stage = rt.mixed_death_effect_stage or "badge"

    if effect_stage == "badge":
        badge_result = _maybe_transfer_sheriff_badge_mixed(game_state, agents, dead_seat)
        if badge_result == MixedResult.blocked:
            return MixedResult.blocked
        rt.mixed_death_effect_stage = "hunter"
        return None

    if effect_stage != "hunter":
        return None

    shot_result = _maybe_trigger_hunter_shot_mixed(
        game_state, agents, dead_seat, death_reason
    )
    if shot_result == MixedResult.blocked:
        return MixedResult.blocked
    if isinstance(shot_result, int) and shot_result is not None:
        rt.mixed_death_queue.append(shot_result)
        rt.mixed_death_reasons[shot_result] = "hunter_shot"

    rt.mixed_death_effect_stage = "badge"
    rt.mixed_cursor += 1
    return None


# ── Step dispatcher ────────────────────────────────────────────────────────


_STEP_MAP = {
    "night_wolves": _step_night_wolves,
    "night_seer": _step_night_seer,
    "night_witch": _step_night_witch,
    "night_resolve": _step_night_resolve,
    "night_post_deaths": _step_night_post_deaths,
    "sheriff_run": _step_sheriff_run,
    "sheriff_vote_1": _step_sheriff_vote,
    "sheriff_pk_speech": _step_sheriff_pk_speech,
    "sheriff_vote_2": _step_sheriff_vote,
    "day_speech": _step_day_speech,
    "vote": _step_vote,
    "pk_speech": _step_pk_speech,
    "pk_vote": _step_pk_vote,
    "pk_resolve": _step_pk_resolve,
    "vote_post_deaths": _step_vote_post_deaths,
}


def _step_mixed(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state
    stage = rt.mixed_stage

    if game_state.public_state.phase == GamePhase.ended:
        return MixedResult.ended

    if stage == "idle":
        game_state.public_state.phase = GamePhase.night
        game_state.public_state.round += 1
        rt.mixed_stage = "night_wolves"
        rt.mixed_cursor = 0
        rt.mixed_wolf_targets = {}
        rt.mixed_seer_target = None
        rt.mixed_witch_save_target = None
        rt.mixed_witch_poison_target = None
        rt.mixed_votes = {}
        rt.mixed_death_queue = []
        rt.mixed_death_reasons = {}
        rt.mixed_death_effect_stage = None
        return None

    step_fn = _STEP_MAP.get(stage)
    if step_fn is None:
        return MixedResult.blocked
    return step_fn(game_state, agents)


# ── Public entry point ─────────────────────────────────────────────────────


def run_mixed_cycle_until_blocked(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult:
    rt = game_state.runtime_state

    if rt.pending_human_action is not None:
        return MixedResult.blocked

    while True:
        result = _step_mixed(game_state, agents)
        if result is not None:
            return result
