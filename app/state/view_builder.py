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
    sheriff_seat_no: int | None = Field(default=None, ge=1)
    private_info: dict[str, Any] = Field(default_factory=dict)
    available_actions: list[str] = Field(default_factory=list)


# ── Action helpers ─────────────────────────────────────────────────────────────


def _night_actions(role: Role) -> list[str]:
    mapping: dict[Role, list[str]] = {
        Role.werewolf: ["werewolf_kill"],
        Role.seer: ["seer_check"],
        Role.witch: ["witch_save", "witch_poison"],
        Role.guard: ["guard_protect"],
        Role.villager: [],
        Role.hunter: [],
        Role.idiot: [],
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


_PRIVATE_EVENT_TYPES = {"night_action", "night_kill_info"}

_SPEECH_EVENT_TYPES = {"speech", "pk_speech", "sheriff_speech", "sheriff_pk_speech"}


def _sanitize_public_event(event: dict[str, Any]) -> dict[str, Any]:
    """Remove internal reasoning fields from agent-visible public events.

    reasoning_summary is for spectator / persistence logs only and must
    never enter any Agent's PlayerView.public_events.
    """
    event = {
        key: value
        for key, value in event.items()
        if key != "reasoning_summary"
    }
    if event.get("type") == "night_resolved":
        return {
            key: value
            for key, value in event.items()
            if key not in {"seer_result", "death_reasons"}
        }
    return event


def _compress_old_speeches(
    events: list[dict[str, Any]],
    current_round: int,
    retention_rounds: int,
) -> list[dict[str, Any]]:
    """Compress speech events older than retention_rounds into per-round summaries.

    Non-speech events and recent speeches pass through unchanged.
    """
    if retention_rounds < 0:
        retention_rounds = 0
    threshold = current_round - retention_rounds

    result: list[dict[str, Any]] = []
    summary_events: dict[int, dict[str, Any]] = {}
    summary_parts: dict[int, list[str]] = {}

    def _summary_round(event: dict[str, Any]) -> int:
        event_round = event.get("round", current_round)
        return event_round if isinstance(event_round, int) else current_round

    def _append_summary(event: dict[str, Any]) -> None:
        r = _summary_round(event)
        seat = event.get("seat_no", "?")
        content = str(event.get("content", ""))
        short = content[:60].rstrip() + ("…" if len(content) > 60 else "")
        if r not in summary_events:
            summary_events[r] = {
                "type": "round_summary",
                "round": r,
                "content": "",
            }
            summary_parts[r] = []
            result.append(summary_events[r])
        summary_parts[r].append(f"{seat}号: {short}")
        summary_events[r]["content"] = f"第{r}轮发言摘要：" + "；".join(summary_parts[r])

    for event in events:
        event_type = event.get("type")
        event_round = _summary_round(event)

        if event_type in _SPEECH_EVENT_TYPES and event_round <= threshold:
            _append_summary(event)
        else:
            result.append(event)

    return result


def _visible_public_events(game_state: GameState) -> list[dict[str, Any]]:
    events = [
        _sanitize_public_event(event)
        for event in game_state.public_state.public_events
        if event.get("private") is not True and event.get("type") not in _PRIVATE_EVENT_TYPES
    ]
    retention = game_state.rule_config.speech_retention_rounds
    return _compress_old_speeches(events, game_state.public_state.round, retention)


def _private_info(game_state: GameState, seat_no: int, role: Role) -> dict[str, Any]:
    runtime = game_state.runtime_state
    info: dict[str, Any] = {
        "sheriff_seat_no": game_state.sheriff_seat_no,
        "idiot_revealed": seat_no in runtime.idiot_revealed_seats,
    }

    if role == Role.seer:
        info["seer_checks"] = [
            {
                "round": record.round,
                "target_seat_no": record.target_seat_no,
                "result": record.result.value,
            }
            for record in runtime.seer_checks
            if record.seer_seat_no == seat_no
        ]

    if role == Role.witch:
        info.update(
            {
                "pending_wolf_kill_target": runtime.pending_wolf_kill_target,
                "witch_save_available": not runtime.witch_save_used,
                "witch_poison_available": not runtime.witch_poison_used,
            }
        )

    if role == Role.guard:
        info.update(
            {
                "guard_last_target": runtime.guard_last_target,
                "guard_can_self_guard": game_state.rule_config.guard_can_self_guard,
                "guard_can_guard_same_target_consecutively": (
                    game_state.rule_config.guard_can_guard_same_target_consecutively
                ),
            }
        )

    if role == Role.hunter:
        info["hunter_can_shoot"] = seat_no not in runtime.hunter_shot_used_seats

    return info


def build_player_view(
    game_state: GameState,
    seat_no: int,
    *,
    available_actions_override: list[str] | None = None,
    private_info_override: dict[str, Any] | None = None,
) -> PlayerView:
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
    if viewer.role == Role.witch:
        if game_state.rule_config.witch_save_once and game_state.runtime_state.witch_save_used:
            actions = [action for action in actions if action != "witch_save"]
        if game_state.rule_config.witch_poison_once and game_state.runtime_state.witch_poison_used:
            actions = [action for action in actions if action != "witch_poison"]

    if available_actions_override is not None:
        actions = available_actions_override

    private_info = _private_info(game_state, seat_no, viewer.role)
    if private_info_override:
        private_info.update(private_info_override)

    return PlayerView(
        game_id=game_state.game_id,
        viewer_seat_no=seat_no,
        round=game_state.public_state.round,
        phase=game_state.public_state.phase,
        players=visible_players,
        public_events=_visible_public_events(game_state),
        own_role=viewer.role,
        own_camp=viewer.camp,
        known_wolf_team=known_wolf_team,
        sheriff_seat_no=game_state.sheriff_seat_no,
        private_info=private_info,
        available_actions=actions,
    )
