from __future__ import annotations

from app.state.schemas import GameState, PlayerState


def find_player(game_state: GameState, seat_no: int) -> PlayerState:
    for p in game_state.players:
        if p.seat_no == seat_no:
            return p
    raise ValueError(
        f"Player with seat_no={seat_no} not found. "
        f"Valid seat numbers: {sorted(p.seat_no for p in game_state.players)}"
    )


def kill_player(game_state: GameState, seat_no: int, reason: str) -> None:
    player = find_player(game_state, seat_no)
    if not player.status.alive:
        raise ValueError(f"Player seat_no={seat_no} is already dead")

    player.status.alive = False
    player.status.can_vote = False
    ps = game_state.public_state
    if seat_no in ps.alive_players:
        ps.alive_players.remove(seat_no)
    if seat_no not in ps.dead_players:
        ps.dead_players.append(seat_no)
    ps.public_events.append(
        {"type": "player_death", "seat_no": seat_no, "reason": reason}
    )
