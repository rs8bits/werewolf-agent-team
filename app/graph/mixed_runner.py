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
    _maybe_transfer_sheriff_badge,
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
) -> MixedResult:
    view = build_player_view(game_state, seat_no)
    game_state.runtime_state.pending_human_action = PendingHumanAction(
        seat_no=seat_no,
        action_type=action_type,
        round=game_state.public_state.round,
        phase=phase,
        available_actions=view.available_actions,
        private_info=view.private_info,
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

    # Check for submitted human decision
    decision = None
    if rt.submitted_human_decision is not None:
        d = AgentDecision.model_validate(rt.submitted_human_decision)
        if d.action.action_type == ActionType.hunter_shoot:
            decision = d
            rt.submitted_human_decision = None

    if decision is None:
        if _is_human(game_state, dead_seat):
            # Block for human hunter — override available_actions since
            # build_player_view won't return hunter_shoot for a dead player.
            rt.pending_human_action = PendingHumanAction(
                seat_no=dead_seat,
                action_type=ActionType.hunter_shoot.value,
                round=game_state.public_state.round,
                phase=game_state.public_state.phase,
                available_actions=[ActionType.hunter_shoot.value],
                private_info={"hunter_can_shoot": True},
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
        _log_event(
            game_state,
            "hunter_no_shot",
            seat_no=dead_seat,
            reason="invalid_target",
        )
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


# ── Step functions ─────────────────────────────────────────────────────────


def _step_night_wolves(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state
    wolf_seats = [
        p.seat_no
        for p in game_state.players
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
            return _block_for_human(
                game_state, seat_no, ActionType.werewolf_kill.value, GamePhase.night
            )
        view = build_player_view(game_state, seat_no)
        decision = agents[seat_no].decide(view)

    action = decision.action
    if action.action_type == ActionType.werewolf_kill:
        rt.mixed_wolf_targets[seat_no] = action.target_seat_no
        _log_event(
            game_state,
            "night_action",
            seat_no=seat_no,
            action_type=ActionType.werewolf_kill.value,
            target_seat_no=action.target_seat_no,
            reasoning_summary=decision.reasoning_summary,
        )

    rt.mixed_cursor += 1
    return None


def _step_night_seer(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state
    seer_seats = [
        p.seat_no
        for p in game_state.players
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
            return _block_for_human(
                game_state, seat_no, ActionType.seer_check.value, GamePhase.night
            )
        view = build_player_view(game_state, seat_no)
        decision = agents[seat_no].decide(view)

    action = decision.action
    if action.action_type == ActionType.seer_check:
        rt.mixed_seer_target = action.target_seat_no
        _log_event(
            game_state,
            "night_action",
            seat_no=seat_no,
            action_type=ActionType.seer_check.value,
            target_seat_no=action.target_seat_no,
            reasoning_summary=decision.reasoning_summary,
        )

    rt.mixed_cursor = 1
    return None


def _step_night_witch(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state
    witch_seats = [
        p.seat_no
        for p in game_state.players
        if p.status.alive and p.role == Role.witch
    ]

    if not witch_seats or rt.mixed_cursor >= 1:
        rt.mixed_stage = "night_resolve"
        rt.mixed_cursor = 0
        return None

    seat_no = witch_seats[0]
    # Ensure pending_wolf_kill_target is set for the witch's view
    rt.pending_wolf_kill_target = _majority_wolf_target(game_state)

    # Accept either witch_save or witch_poison from human
    human_decision = None
    if rt.submitted_human_decision is not None:
        decision = AgentDecision.model_validate(rt.submitted_human_decision)
        at = decision.action.action_type.value
        if at in (ActionType.witch_save.value, ActionType.witch_poison.value):
            human_decision = decision
            rt.submitted_human_decision = None

    if human_decision is None:
        if _is_human(game_state, seat_no):
            # Determine available actions for the human witch
            view = build_player_view(game_state, seat_no)
            if not view.available_actions:
                rt.mixed_cursor = 1
                return None
            # Set action_type to first available action (the API validates against available_actions)
            return _block_for_human(
                game_state,
                seat_no,
                view.available_actions[0],
                GamePhase.night,
            )
        view = build_player_view(game_state, seat_no)
        if not view.available_actions:
            rt.mixed_cursor = 1
            return None
        human_decision = agents[seat_no].decide(view)

    action = human_decision.action
    target = getattr(action, "target_seat_no", None)
    _log_event(
        game_state,
        "night_action",
        seat_no=seat_no,
        action_type=action.action_type.value,
        target_seat_no=target,
        reasoning_summary=human_decision.reasoning_summary,
    )

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
    result = resolve_night(game_state, actions)
    rt.pending_wolf_kill_target = None

    _log_event(
        game_state,
        "night_resolved",
        deaths=result.deaths,
        death_reasons=result.death_reasons,
        seer_result=result.seer_result.value if result.seer_result else None,
    )

    rt.mixed_death_queue = list(result.deaths)
    rt.mixed_death_reasons = dict(result.death_reasons)
    rt.mixed_stage = "night_post_deaths"
    rt.mixed_cursor = 0
    return None


def _step_night_post_deaths(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state

    if rt.mixed_cursor >= len(rt.mixed_death_queue):
        # All deaths (and cascades) processed
        winner = check_winner(game_state)
        if winner is not None:
            game_state.winner = winner
            game_state.public_state.phase = GamePhase.ended
            return MixedResult.ended
        rt.mixed_stage = "day_speech"
        rt.mixed_cursor = 0
        return None

    dead_seat = rt.mixed_death_queue[rt.mixed_cursor]
    death_reason = rt.mixed_death_reasons.get(dead_seat, "night_death")

    _maybe_transfer_sheriff_badge(game_state, agents, dead_seat)
    shot_result = _maybe_trigger_hunter_shot_mixed(
        game_state, agents, dead_seat, death_reason
    )
    if shot_result == MixedResult.blocked:
        return MixedResult.blocked
    if isinstance(shot_result, int) and shot_result is not None:
        # Hunter shot killed another player — append to queue for cascade
        rt.mixed_death_queue.append(shot_result)
        rt.mixed_death_reasons[shot_result] = "hunter_shot"

    rt.mixed_cursor += 1
    return None


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
            return _block_for_human(
                game_state, seat_no, ActionType.speak.value, GamePhase.day
            )
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

    rt.mixed_cursor += 1
    return None


def _step_vote(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state
    game_state.public_state.phase = GamePhase.vote

    voter_seats = [
        p.seat_no
        for p in game_state.players
        if p.status.alive and p.status.can_vote
    ]

    if rt.mixed_cursor >= len(voter_seats):
        # Tally and apply votes
        votes: list[Vote] = []
        for seat_no, target in rt.mixed_votes.items():
            votes.append(Vote(voter_seat_no=seat_no, target_seat_no=target))
        result = tally_votes(game_state, votes)
        eliminated = apply_vote_result(game_state, result)

        _log_event(
            game_state,
            "vote_resolved",
            eliminated_seat_no=eliminated,
            tied_seats=result.tied_seats,
            vote_counts=result.vote_counts,
        )

        # Process hunter shot if the eliminated player was a hunter
        if eliminated is not None:
            _maybe_transfer_sheriff_badge(game_state, agents, eliminated)
            rt.mixed_death_queue = [eliminated]
            rt.mixed_death_reasons = {eliminated: "vote_elimination"}
            rt.mixed_stage = "vote_post_deaths"
            rt.mixed_cursor = 0
        else:
            winner = check_winner(game_state)
            if winner is not None:
                game_state.winner = winner
                game_state.public_state.phase = GamePhase.ended
                return MixedResult.ended

            # Reset for next cycle
            rt.mixed_stage = "idle"
            rt.mixed_cursor = 0
            rt.mixed_wolf_targets = {}
            rt.mixed_seer_target = None
            rt.mixed_witch_save_target = None
            rt.mixed_witch_poison_target = None
            rt.mixed_votes = {}
            return MixedResult.cycle_complete
        return None

    seat_no = voter_seats[rt.mixed_cursor]
    decision = _apply_human_decision(game_state, ActionType.vote.value)

    if decision is None:
        if _is_human(game_state, seat_no):
            return _block_for_human(
                game_state, seat_no, ActionType.vote.value, GamePhase.vote
            )
        view = build_player_view(game_state, seat_no)
        decision = agents[seat_no].decide(view)

    action = decision.action
    target = getattr(action, "target_seat_no", None)
    if action.action_type == ActionType.vote:
        rt.mixed_votes[seat_no] = target
        _log_event(
            game_state,
            "vote_cast",
            seat_no=seat_no,
            target_seat_no=target,
            reasoning_summary=decision.reasoning_summary,
        )

    rt.mixed_cursor += 1
    return None


def _step_vote_post_deaths(
    game_state: GameState, agents: dict[int, Agent]
) -> MixedResult | None:
    rt = game_state.runtime_state

    if rt.mixed_cursor >= len(rt.mixed_death_queue):
        # All post-vote deaths processed
        winner = check_winner(game_state)
        if winner is not None:
            game_state.winner = winner
            game_state.public_state.phase = GamePhase.ended
            return MixedResult.ended

        # Reset for next cycle
        rt.mixed_stage = "idle"
        rt.mixed_cursor = 0
        rt.mixed_wolf_targets = {}
        rt.mixed_seer_target = None
        rt.mixed_witch_save_target = None
        rt.mixed_witch_poison_target = None
        rt.mixed_votes = {}
        return MixedResult.cycle_complete

    dead_seat = rt.mixed_death_queue[rt.mixed_cursor]
    death_reason = rt.mixed_death_reasons.get(dead_seat, "vote_elimination")

    shot_result = _maybe_trigger_hunter_shot_mixed(
        game_state, agents, dead_seat, death_reason
    )
    if shot_result == MixedResult.blocked:
        return MixedResult.blocked
    if isinstance(shot_result, int) and shot_result is not None:
        rt.mixed_death_queue.append(shot_result)
        rt.mixed_death_reasons[shot_result] = "hunter_shot"

    rt.mixed_cursor += 1
    return None


# ── Step dispatcher ────────────────────────────────────────────────────────


_STEP_MAP = {
    "night_wolves": _step_night_wolves,
    "night_seer": _step_night_seer,
    "night_witch": _step_night_witch,
    "night_resolve": _step_night_resolve,
    "night_post_deaths": _step_night_post_deaths,
    "day_speech": _step_day_speech,
    "vote": _step_vote,
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
