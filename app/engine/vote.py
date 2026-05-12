from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from app.engine.death import find_player, kill_player
from app.state.schemas import GameState, Role


class Vote(BaseModel):
    voter_seat_no: int = Field(ge=1)
    target_seat_no: int | None = Field(default=None, ge=1)


class VoteResult(BaseModel):
    eliminated_seat_no: int | None = None
    tied_seats: list[int] = Field(default_factory=list)
    vote_counts: dict[int, float] = Field(default_factory=dict)


def tally_votes(
    game_state: GameState,
    votes: list[Vote],
    *,
    allowed_targets: set[int] | None = None,
) -> VoteResult:
    alive_can_vote: set[int] = {
        p.seat_no for p in game_state.players if p.status.alive and p.status.can_vote
    }
    alive_seats = {p.seat_no for p in game_state.players if p.status.alive}

    counter: Counter[int] = Counter()
    counted_voters: set[int] = set()
    for v in votes:
        if v.voter_seat_no not in alive_can_vote:
            continue
        if v.voter_seat_no in counted_voters:
            continue
        counted_voters.add(v.voter_seat_no)
        if v.target_seat_no is not None and v.target_seat_no in alive_seats:
            if allowed_targets is not None and v.target_seat_no not in allowed_targets:
                continue
            weight = (
                game_state.rule_config.sheriff_vote_weight
                if v.voter_seat_no == game_state.sheriff_seat_no
                else 1.0
            )
            counter[v.target_seat_no] += weight

    if not counter:
        return VoteResult()

    max_count = max(counter.values())
    top_seats = [seat for seat, count in counter.items() if count == max_count]

    if len(top_seats) == 1:
        return VoteResult(eliminated_seat_no=top_seats[0], vote_counts=dict(counter))
    return VoteResult(tied_seats=top_seats, vote_counts=dict(counter))


def apply_vote_result(game_state: GameState, result: VoteResult) -> int | None:
    if result.eliminated_seat_no is not None:
        player = find_player(game_state, result.eliminated_seat_no)
        if (
            player.role == Role.idiot
            and game_state.rule_config.idiot_reveal_on_vote
            and player.seat_no not in game_state.runtime_state.idiot_revealed_seats
        ):
            player.status.can_vote = False
            game_state.runtime_state.idiot_revealed_seats.append(player.seat_no)
            game_state.public_state.public_events.append(
                {"type": "idiot_revealed", "seat_no": player.seat_no}
            )
            return None
        kill_player(game_state, result.eliminated_seat_no, reason="vote_elimination")
        return result.eliminated_seat_no
    return None
