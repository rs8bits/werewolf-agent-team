from __future__ import annotations

from pydantic import BaseModel, Field

from app.engine.death import find_player, kill_player
from app.state.schemas import Camp, GameState, PlayerState


class NightActionSet(BaseModel):
    wolf_kill_target: int | None = Field(default=None, ge=1)
    witch_save_target: int | None = Field(default=None, ge=1)
    witch_poison_target: int | None = Field(default=None, ge=1)
    seer_check_target: int | None = Field(default=None, ge=1)


class NightResult(BaseModel):
    deaths: list[int] = Field(default_factory=list)
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

    to_die: set[int] = set()

    if wolf_target is not None:
        if witch_save_target is None or witch_save_target.seat_no != wolf_target.seat_no:
            to_die.add(wolf_target.seat_no)

    if witch_poison_target is not None:
        to_die.add(witch_poison_target.seat_no)

    for seat_no in sorted(to_die):
        kill_player(game_state, seat_no, reason="night_death")

    seer_result: Camp | None = None
    if seer_check_target is not None:
        seer_result = seer_check_target.camp

    return NightResult(deaths=sorted(to_die), seer_result=seer_result)
