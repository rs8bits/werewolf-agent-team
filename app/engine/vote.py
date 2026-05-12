from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from app.engine.death import kill_player
from app.state.schemas import GameState


class Vote(BaseModel):
    voter_seat_no: int = Field(ge=1)
    target_seat_no: int | None = Field(default=None, ge=1)


class VoteResult(BaseModel):
    eliminated_seat_no: int | None = None
    tied_seats: list[int] = Field(default_factory=list)
    vote_counts: dict[int, int] = Field(default_factory=dict)


def tally_votes(game_state: GameState, votes: list[Vote]) -> VoteResult:
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
            counter[v.target_seat_no] += 1

    if not counter:
        return VoteResult()

    max_count = max(counter.values())
    top_seats = [seat for seat, count in counter.items() if count == max_count]

    if len(top_seats) == 1:
        return VoteResult(eliminated_seat_no=top_seats[0], vote_counts=dict(counter))
    return VoteResult(tied_seats=top_seats, vote_counts=dict(counter))


def apply_vote_result(game_state: GameState, result: VoteResult) -> None:
    if result.eliminated_seat_no is not None:
        kill_player(game_state, result.eliminated_seat_no, reason="vote_elimination")
