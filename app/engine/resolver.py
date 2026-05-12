from __future__ import annotations

from pydantic import BaseModel, Field

from app.engine.death import find_player, kill_player
from app.state.schemas import Camp, GameState, PlayerState, SeerCheckRecord


class NightActionSet(BaseModel):
    wolf_kill_target: int | None = Field(default=None, ge=1)
    witch_save_target: int | None = Field(default=None, ge=1)
    witch_poison_target: int | None = Field(default=None, ge=1)
    seer_check_target: int | None = Field(default=None, ge=1)
    guard_target: int | None = Field(default=None, ge=1)


class NightResult(BaseModel):
    deaths: list[int] = Field(default_factory=list)
    death_reasons: dict[int, str] = Field(default_factory=dict)
    seer_result: Camp | None = None


def _validate_alive_target(
    game_state: GameState, seat_no: int | None, action_name: str
) -> PlayerState | None:
    if seat_no is None:
        return None
    player = find_player(game_state, seat_no)
    if not player.status.alive:
        raise ValueError(f"{action_name} target seat_no={seat_no} is not alive")
    return player


def resolve_night(game_state: GameState, actions: NightActionSet) -> NightResult:
    wolf_target = _validate_alive_target(
        game_state, actions.wolf_kill_target, "wolf_kill"
    )
    witch_save_target = _validate_alive_target(
        game_state, actions.witch_save_target, "witch_save"
    )
    witch_poison_target = _validate_alive_target(
        game_state, actions.witch_poison_target, "witch_poison"
    )
    seer_check_target = _validate_alive_target(
        game_state, actions.seer_check_target, "seer_check"
    )
    guard_target = _validate_alive_target(
        game_state, actions.guard_target, "guard_protect"
    )

    rules = game_state.rule_config
    runtime = game_state.runtime_state

    if guard_target is not None:
        if not rules.guard_can_self_guard:
            guard_seats = [
                player.seat_no
                for player in game_state.players
                if player.status.alive and player.role.value == "guard"
            ]
            if guard_target.seat_no in guard_seats:
                guard_target = None
        if (
            guard_target is not None
            and not rules.guard_can_guard_same_target_consecutively
            and runtime.guard_last_target == guard_target.seat_no
        ):
            guard_target = None

    if guard_target is not None:
        runtime.guard_last_target = guard_target.seat_no

    if witch_save_target is not None:
        if wolf_target is None or witch_save_target.seat_no != wolf_target.seat_no:
            witch_save_target = None
        elif rules.witch_save_once and runtime.witch_save_used:
            witch_save_target = None
        elif (
            not rules.witch_can_self_save_first_night
            and game_state.public_state.round == 1
            and any(
                player.seat_no == witch_save_target.seat_no and player.role.value == "witch"
                for player in game_state.players
            )
        ):
            witch_save_target = None
        else:
            runtime.witch_save_used = True

    if witch_poison_target is not None:
        if rules.witch_poison_once and runtime.witch_poison_used:
            witch_poison_target = None
        else:
            runtime.witch_poison_used = True

    death_reasons: dict[int, str] = {}

    if wolf_target is not None:
        guarded = guard_target is not None and guard_target.seat_no == wolf_target.seat_no
        saved = (
            witch_save_target is not None
            and witch_save_target.seat_no == wolf_target.seat_no
        )
        conflict = guarded and saved and rules.guard_witch_same_target_death
        if conflict:
            death_reasons[wolf_target.seat_no] = "guard_witch_conflict"
        elif not guarded and not saved:
            death_reasons[wolf_target.seat_no] = "wolf_kill"

    if witch_poison_target is not None:
        death_reasons[witch_poison_target.seat_no] = "witch_poison"

    for seat_no in sorted(death_reasons):
        kill_player(game_state, seat_no, reason=death_reasons[seat_no])

    seer_result: Camp | None = None
    if seer_check_target is not None:
        seer_result = seer_check_target.camp
        seer_seats = [
            player.seat_no
            for player in game_state.players
            if player.status.alive and player.role.value == "seer"
        ]
        if seer_seats:
            runtime.seer_checks.append(
                SeerCheckRecord(
                    round=game_state.public_state.round,
                    seer_seat_no=seer_seats[0],
                    target_seat_no=seer_check_target.seat_no,
                    result=seer_result,
                )
            )

    return NightResult(
        deaths=sorted(death_reasons),
        death_reasons=death_reasons,
        seer_result=seer_result,
    )
