from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.state.schemas import Camp, GamePhase, GameState, PlayerType, Role


# ── View models ────────────────────────────────────────────────────────────────


class VisiblePlayer(BaseModel):
    """Public view of a player — no role or camp exposed."""

    seat_no: int = Field(ge=1)
    name: str
    player_type: PlayerType
    alive: bool
    can_vote: bool


class PlayerView(BaseModel):
    """Private view for a specific player. Must NOT contain TruthState."""

    game_id: str
    viewer_seat_no: int = Field(ge=1)
    round: int = Field(ge=0)
    phase: GamePhase
    players: list[VisiblePlayer]
    public_events: list[dict[str, Any]]
    own_role: Role
    own_camp: Camp
    known_wolf_team: list[int] = Field(default_factory=list)
    available_actions: list[str] = Field(default_factory=list)


# ── Action helpers ─────────────────────────────────────────────────────────────


def _night_actions(role: Role) -> list[str]:
    mapping: dict[Role, list[str]] = {
        Role.werewolf: ["werewolf_kill"],
        Role.seer: ["seer_check"],
        Role.witch: ["witch_save", "witch_poison"],
        Role.villager: [],
    }
    return mapping.get(role, [])


def _available_actions(
    role: Role, phase: GamePhase, alive: bool, can_vote: bool
) -> list[str]:
    if phase in (GamePhase.setup, GamePhase.ended):
        return []
    if not alive:
        return []
    if phase == GamePhase.night:
        return _night_actions(role)
    if phase == GamePhase.day:
        return ["speak"]
    if phase == GamePhase.vote:
        return ["vote"] if (alive and can_vote) else []
    return []


# ── Builder ────────────────────────────────────────────────────────────────────


def _find_player(game_state: GameState, seat_no: int):
    for p in game_state.players:
        if p.seat_no == seat_no:
            return p
    raise ValueError(
        f"Player with seat_no={seat_no} not found. "
        f"Valid seat numbers: {sorted(p.seat_no for p in game_state.players)}"
    )


def build_player_view(game_state: GameState, seat_no: int) -> PlayerView:
    viewer = _find_player(game_state, seat_no)

    visible_players = [
        VisiblePlayer(
            seat_no=p.seat_no,
            name=p.name,
            player_type=p.player_type,
            alive=p.status.alive,
            can_vote=p.status.can_vote,
        )
        for p in game_state.players
    ]

    known_wolf_team: list[int] = []
    if viewer.camp == Camp.werewolf:
        known_wolf_team = list(game_state.truth_state.wolf_team)

    actions = _available_actions(
        role=viewer.role,
        phase=game_state.public_state.phase,
        alive=viewer.status.alive,
        can_vote=viewer.status.can_vote,
    )

    return PlayerView(
        game_id=game_state.game_id,
        viewer_seat_no=seat_no,
        round=game_state.public_state.round,
        phase=game_state.public_state.phase,
        players=visible_players,
        public_events=list(game_state.public_state.public_events),
        own_role=viewer.role,
        own_camp=viewer.camp,
        known_wolf_team=known_wolf_team,
        available_actions=actions,
    )
