from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


# ── Enums ────────────────────────────────────────────────────────────────────


class Camp(str, Enum):
    werewolf = "werewolf"
    good = "good"


class Role(str, Enum):
    werewolf = "werewolf"
    seer = "seer"
    witch = "witch"
    villager = "villager"
    # Reserved for future milestones
    hunter = "hunter"
    idiot = "idiot"
    guard = "guard"


class GamePhase(str, Enum):
    setup = "setup"
    night = "night"
    day = "day"
    vote = "vote"
    ended = "ended"


class PlayerType(str, Enum):
    ai = "ai"
    human = "human"


# ── Role ↔ Camp mapping ──────────────────────────────────────────────────────

ROLE_CAMP: dict[Role, Camp] = {
    Role.werewolf: Camp.werewolf,
    Role.seer: Camp.good,
    Role.witch: Camp.good,
    Role.villager: Camp.good,
    Role.hunter: Camp.good,
    Role.idiot: Camp.good,
    Role.guard: Camp.good,
}


def camp_of(role: Role) -> Camp:
    return ROLE_CAMP[role]


# ── Player status ────────────────────────────────────────────────────────────


class PlayerStatus(BaseModel):
    alive: bool = True
    can_vote: bool = True


# ── Player state ─────────────────────────────────────────────────────────────


class PlayerState(BaseModel):
    seat_no: int = Field(ge=1)
    name: str
    player_type: PlayerType
    role: Role
    camp: Camp
    status: PlayerStatus = Field(default_factory=PlayerStatus)

    @model_validator(mode="after")
    def camp_must_match_role(self) -> "PlayerState":
        if self.camp != camp_of(self.role):
            raise ValueError(f"Role {self.role.value} belongs to camp {camp_of(self.role).value}")
        return self


# ── Public state ─────────────────────────────────────────────────────────────


class PublicState(BaseModel):
    round: int = Field(default=0, ge=0)
    phase: GamePhase = GamePhase.setup
    alive_players: list[int] = Field(default_factory=list)
    dead_players: list[int] = Field(default_factory=list)
    public_events: list[dict[str, Any]] = Field(default_factory=list)


# ── Truth state (system-only) ────────────────────────────────────────────────


class TruthState(BaseModel):
    real_identities: dict[int, Role] = Field(default_factory=dict)
    wolf_team: list[int] = Field(default_factory=list)
    night_actions: list[dict[str, Any]] = Field(default_factory=list)


# ── Game state ───────────────────────────────────────────────────────────────


class GameState(BaseModel):
    game_id: str
    public_state: PublicState = Field(default_factory=PublicState)
    players: list[PlayerState] = Field(default_factory=list)
    truth_state: TruthState = Field(default_factory=TruthState)
    winner: Camp | None = None
