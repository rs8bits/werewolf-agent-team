from __future__ import annotations

from app.state.schemas import Camp, GameState, Role


def check_winner(game_state: GameState) -> Camp | None:
    alive_werewolves = any(
        p.status.alive and p.camp == Camp.werewolf for p in game_state.players
    )
    if not alive_werewolves:
        return Camp.good

    gods = {Role.seer, Role.witch, Role.hunter, Role.idiot, Role.guard}
    all_gods_dead = not any(
        p.status.alive and p.role in gods for p in game_state.players
    )
    all_villagers_dead = not any(
        p.status.alive and p.role == Role.villager for p in game_state.players
    )
    if all_gods_dead or all_villagers_dead:
        return Camp.werewolf

    return None
