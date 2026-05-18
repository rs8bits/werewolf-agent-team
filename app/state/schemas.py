from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.config.rule_config import RuleConfig, default_rule_config


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


# ── Runtime state (system-only) ──────────────────────────────────────────────


class SeerCheckRecord(BaseModel):
    round: int = Field(ge=0)
    seer_seat_no: int = Field(ge=1)
    target_seat_no: int = Field(ge=1)
    result: Camp


class PendingHumanAction(BaseModel):
    seat_no: int = Field(ge=1)
    action_type: str
    round: int = Field(ge=0)
    phase: GamePhase
    available_actions: list[str] = Field(default_factory=list)
    private_info: dict[str, Any] = Field(default_factory=dict)


class RuntimeState(BaseModel):
    witch_save_used: bool = False
    witch_poison_used: bool = False
    guard_last_target: int | None = Field(default=None, ge=1)
    pending_wolf_kill_target: int | None = Field(default=None, ge=1)
    seer_checks: list[SeerCheckRecord] = Field(default_factory=list)
    hunter_shot_used_seats: list[int] = Field(default_factory=list)
    idiot_revealed_seats: list[int] = Field(default_factory=list)
    sheriff_election_done: bool = False
    # ── Human-mixed game fields ──────────────────────────────────────────
    pending_human_action: PendingHumanAction | None = None
    submitted_human_decision: dict[str, Any] | None = None
    mixed_stage: str = "idle"
    mixed_cursor: int = 0
    mixed_wolf_targets: dict[int, int] = Field(default_factory=dict)
    mixed_seer_target: int | None = None
    mixed_witch_save_target: int | None = None
    mixed_witch_poison_target: int | None = None
    mixed_votes: dict[int, int | None] = Field(default_factory=dict)
    mixed_death_queue: list[int] = Field(default_factory=list)
    mixed_death_reasons: dict[int, str] = Field(default_factory=dict)
    seat_token_hashes: dict[int, str] = Field(default_factory=dict)


# ── Game state ───────────────────────────────────────────────────────────────


class GameState(BaseModel):
    game_id: str
    agent_mode: str = "scripted"
    model: str | None = None
    rule_config: RuleConfig = Field(default_factory=lambda: default_rule_config(6))
    public_state: PublicState = Field(default_factory=PublicState)
    players: list[PlayerState] = Field(default_factory=list)
    truth_state: TruthState = Field(default_factory=TruthState)
    runtime_state: RuntimeState = Field(default_factory=RuntimeState)
    sheriff_seat_no: int | None = Field(default=None, ge=1)
    winner: Camp | None = None
