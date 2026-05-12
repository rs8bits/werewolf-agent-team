from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from app.state.schemas import PlayerType, Role


class RoleCount(BaseModel):
    role: Role
    count: int = Field(ge=1)


class SeatConfig(BaseModel):
    seat_no: int = Field(ge=1)
    role: Role
    player_type: PlayerType = PlayerType.ai


class RoleSetup(BaseModel):
    player_count: int = Field(ge=1)
    role_counts: list[RoleCount] = Field(min_length=1)

    @model_validator(mode="after")
    def role_counts_must_match_player_count(self) -> "RoleSetup":
        total = sum(role_count.count for role_count in self.role_counts)
        if total != self.player_count:
            raise ValueError(
                f"Role counts total {total}, expected player_count {self.player_count}"
            )
        return self

    def seat_configs(
        self, player_type: PlayerType = PlayerType.ai
    ) -> list[SeatConfig]:
        seats: list[SeatConfig] = []
        seat_no = 1
        for rc in self.role_counts:
            for _ in range(rc.count):
                seats.append(
                    SeatConfig(seat_no=seat_no, role=rc.role, player_type=player_type)
                )
                seat_no += 1
        return seats


# ── Presets ──────────────────────────────────────────────────────────────────

SIX_PLAYER_ROLE_COUNTS = (
    RoleCount(role=Role.werewolf, count=2),
    RoleCount(role=Role.seer, count=1),
    RoleCount(role=Role.witch, count=1),
    RoleCount(role=Role.villager, count=2),
)

TWELVE_PLAYER_ROLE_COUNTS = (
    RoleCount(role=Role.werewolf, count=4),
    RoleCount(role=Role.seer, count=1),
    RoleCount(role=Role.witch, count=1),
    RoleCount(role=Role.hunter, count=1),
    RoleCount(role=Role.idiot, count=1),
    RoleCount(role=Role.villager, count=4),
)

SUPPORTED_COUNTS: dict[int, tuple[RoleCount, ...]] = {
    6: SIX_PLAYER_ROLE_COUNTS,
    12: TWELVE_PLAYER_ROLE_COUNTS,
}


def six_player_setup() -> RoleSetup:
    return RoleSetup(
        player_count=6,
        role_counts=[role_count.model_copy(deep=True) for role_count in SIX_PLAYER_ROLE_COUNTS],
    )


def twelve_player_setup() -> RoleSetup:
    return RoleSetup(
        player_count=12,
        role_counts=[role_count.model_copy(deep=True) for role_count in TWELVE_PLAYER_ROLE_COUNTS],
    )


def get_role_setup(player_count: int) -> RoleSetup:
    counts = SUPPORTED_COUNTS.get(player_count)
    if counts is None:
        raise ValueError(
            f"Unsupported player count: {player_count}. "
            f"Currently supported: {sorted(SUPPORTED_COUNTS.keys())}"
        )
    return RoleSetup(
        player_count=player_count,
        role_counts=[role_count.model_copy(deep=True) for role_count in counts],
    )
