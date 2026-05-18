from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import replace

from sqlalchemy.orm import Session

from app.agents.factory import create_agent
from app.agents.scripted_agent import ScriptedAgent
from app.config.role_setups import get_role_setup
from app.config.rule_config import RuleConfig, default_rule_config
from app.config.settings import load_config
from app.engine import initialize_game
from app.graph.main_graph import (
    Agent,
    live_event_sink,
    run_one_cycle,
    run_until_finished,
)
from app.graph.mixed_runner import (
    MixedResult,
    run_mixed_cycle_until_blocked,
)
from app.models import GameEvent, GameSession
from app.llm.client import LLMClient
from app.services.event_bus import game_event_bus
from app.state.schemas import GamePhase, GameState, PlayerType


def _short_uuid() -> str:
    return uuid.uuid4().hex[:8]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class GameSessionService:
    """Service layer: owns DB persistence + runner orchestration."""

    def __init__(self, db: Session):
        self.db = db

    # ── Persistence helpers ───────────────────────────────────────────────

    def _save_game_and_events(self, game_state: GameState) -> None:
        game_id = game_state.game_id

        existing_sequences = {
            row[0]
            for row in (
                self.db.query(GameEvent.sequence)
                .filter(GameEvent.game_id == game_id)
                .all()
            )
        }
        all_events = game_state.public_state.public_events

        for sequence, evt in enumerate(all_events):
            if sequence in existing_sequences:
                continue
            self.db.add(
                GameEvent(
                    game_id=game_id,
                    sequence=sequence,
                    event_json=evt,
                )
            )

        session = (
            self.db.query(GameSession)
            .filter(GameSession.game_id == game_id)
            .first()
        )
        if session is None:
            self.db.add(
                GameSession(
                    game_id=game_id,
                    state_json=game_state.model_dump(),
                )
            )
        else:
            session.state_json = game_state.model_dump()

        self.db.commit()

    def _persist_live_event(self, game_state: GameState, event: dict) -> None:
        game_id = game_state.game_id
        sequence = len(game_state.public_state.public_events) - 1
        exists = (
            self.db.query(GameEvent)
            .filter(GameEvent.game_id == game_id, GameEvent.sequence == sequence)
            .first()
            is not None
        )
        if not exists:
            self.db.add(
                GameEvent(
                    game_id=game_id,
                    sequence=sequence,
                    event_json=event,
                )
            )

        session = (
            self.db.query(GameSession)
            .filter(GameSession.game_id == game_id)
            .first()
        )
        if session is not None:
            session.state_json = game_state.model_dump()
        self.db.commit()

        game_event_bus.publish(
            game_id,
            {
                "type": "event",
                "game_id": game_id,
                "sequence": sequence,
                "event": event,
                "game": game_state.model_dump(),
            },
        )

    def _publish_state(self, game_state: GameState, status: str) -> None:
        game_event_bus.publish(
            game_state.game_id,
            {
                "type": "state",
                "status": status,
                "game": game_state.model_dump(),
            },
        )

    def _load_game_state(self, game_id: str) -> GameState | None:
        row = (
            self.db.query(GameSession)
            .filter(GameSession.game_id == game_id)
            .first()
        )
        if row is None:
            return None
        return GameState.model_validate(row.state_json)

    def _build_agents(self, game_state: GameState) -> dict[int, Agent]:
        agents: dict[int, Agent] = {}
        if game_state.agent_mode == "llm":
            config = load_config()
            if game_state.model:
                config = replace(config, model=game_state.model)
            llm_client = LLMClient(config=config)
            for p in game_state.players:
                if p.player_type == PlayerType.human:
                    continue
                agents[p.seat_no] = create_agent(p.role, llm_client)
            return agents

        for p in game_state.players:
            if p.player_type == PlayerType.human:
                continue
            agents[p.seat_no] = ScriptedAgent(role=p.role)
        return agents

    # ── Public API ────────────────────────────────────────────────────────

    def create_game(
        self,
        player_names: list[str] | None = None,
        player_count: int = 6,
        agent_mode: str = "scripted",
        model: str | None = None,
        rule_config: RuleConfig | None = None,
        seed: int | None = None,
        human_seats: list[int] | None = None,
    ) -> tuple[GameState, dict[int, str]]:
        if agent_mode not in {"scripted", "llm"}:
            raise ValueError("agent_mode must be 'scripted' or 'llm'")
        human_tokens: dict[int, str] = {}
        if human_seats is not None:
            if player_count not in (6,):
                raise ValueError(
                    f"Human-mixed games only support player_count=6, got {player_count}"
                )
            seen: set[int] = set()
            for seat in human_seats:
                if not (1 <= seat <= player_count):
                    raise ValueError(
                        f"human_seat {seat} out of range [1, {player_count}]"
                    )
                if seat in seen:
                    raise ValueError(
                        f"Duplicate human_seat {seat}"
                    )
                seen.add(seat)
                human_tokens[seat] = secrets.token_urlsafe(24)
        setup = get_role_setup(player_count)
        rules = rule_config or default_rule_config(player_count)
        if agent_mode == "llm":
            config = load_config()
            if model:
                config = replace(config, model=model)
            LLMClient(config=config)
        game_id = _short_uuid()
        player_types: list[PlayerType] | None = None
        if human_seats is not None:
            human_set = set(human_seats)
            player_types = [
                PlayerType.human if (i + 1) in human_set else PlayerType.ai
                for i in range(player_count)
            ]
        game_state = initialize_game(
            game_id,
            setup,
            player_names=player_names,
            player_types=player_types,
            rule_config=rules,
            agent_mode=agent_mode,
            model=model,
            seed=seed,
        )
        # Store token hashes in runtime_state (never persist plaintext tokens)
        if human_tokens:
            game_state.runtime_state.seat_token_hashes = {
                seat: _sha256(token) for seat, token in human_tokens.items()
            }
        self._save_game_and_events(game_state)
        return game_state, human_tokens

    def get_game(self, game_id: str) -> GameState | None:
        return self._load_game_state(game_id)

    def _has_human(self, game_state: GameState) -> bool:
        return any(p.player_type == PlayerType.human for p in game_state.players)

    def _run_mixed_until_blocked_or_ended(
        self,
        game_state: GameState,
        agents: dict[int, Agent],
        *,
        max_cycles: int = 50,
    ) -> MixedResult:
        completed_cycles = 0
        while True:
            result = run_mixed_cycle_until_blocked(game_state, agents)
            if result != MixedResult.cycle_complete:
                return result
            completed_cycles += 1
            if completed_cycles >= max_cycles:
                return result

    def _validate_seat_token(
        self, game_state: GameState, seat_no: int, token: str | None
    ) -> None:
        hashes = game_state.runtime_state.seat_token_hashes
        expected_hash = hashes.get(seat_no)
        if expected_hash is None:
            return  # Not a token-protected seat (old game or non-human seat)
        if token is None or not secrets.compare_digest(_sha256(token), expected_hash):
            raise PermissionError("无权访问该座位")

    def get_player_view(
        self, game_id: str, seat_no: int, token: str | None = None
    ) -> dict | None:
        from app.state.view_builder import build_player_view

        game_state = self._load_game_state(game_id)
        if game_state is None:
            return None
        if not any(p.seat_no == seat_no for p in game_state.players):
            return None
        self._validate_seat_token(game_state, seat_no, token)
        view = build_player_view(game_state, seat_no)
        return view.model_dump()

    def submit_human_action(
        self, game_id: str, seat_no: int, decision_data: dict,
        token: str | None = None,
    ) -> GameState:
        from app.agents.schemas import AgentDecision

        game_state = self._load_game_state(game_id)
        if game_state is None:
            raise ValueError(f"对局不存在: {game_id}")

        self._validate_seat_token(game_state, seat_no, token)

        rt = game_state.runtime_state
        pending = rt.pending_human_action
        if pending is None:
            raise ValueError("当前没有等待真人操作")
        if pending.seat_no != seat_no:
            raise ValueError(
                f"当前等待 {pending.seat_no} 号操作，收到 {seat_no} 号"
            )

        decision = AgentDecision.model_validate(decision_data)
        action_type = decision.action.action_type.value

        if action_type not in pending.available_actions:
            raise ValueError(
                f"操作类型 {action_type} 不在可用操作 {pending.available_actions} 中"
            )

        self._validate_human_action_target(game_state, decision)

        rt.submitted_human_decision = decision.model_dump()
        rt.pending_human_action = None

        agents = self._build_agents(game_state)
        self._publish_state(game_state, "running")
        with live_event_sink(self._persist_live_event):
            self._run_mixed_until_blocked_or_ended(game_state, agents)
        self._save_game_and_events(game_state)
        self._publish_state(game_state, "idle")
        return game_state

    def _validate_human_action_target(
        self, game_state: GameState, decision
    ) -> None:
        target = getattr(decision.action, "target_seat_no", None)
        if target is None:
            return

        player = next((p for p in game_state.players if p.seat_no == target), None)
        if player is None:
            raise ValueError(f"target_seat_no={target} 不存在")
        if not player.status.alive:
            raise ValueError(f"target_seat_no={target} 已死亡")

    def run_cycle(self, game_id: str) -> GameState:
        game_state = self._load_game_state(game_id)
        if game_state is None:
            raise ValueError(f"对局不存在: {game_id}")
        agents = self._build_agents(game_state)
        self._publish_state(game_state, "running")
        with live_event_sink(self._persist_live_event):
            if self._has_human(game_state):
                run_mixed_cycle_until_blocked(game_state, agents)
            else:
                run_one_cycle(game_state, agents)
        self._save_game_and_events(game_state)
        self._publish_state(game_state, "idle")
        return game_state

    def run_until_finished(
        self, game_id: str, max_cycles: int = 50
    ) -> GameState:
        game_state = self._load_game_state(game_id)
        if game_state is None:
            raise ValueError(f"对局不存在: {game_id}")
        agents = self._build_agents(game_state)
        self._publish_state(game_state, "running")
        with live_event_sink(self._persist_live_event):
            if self._has_human(game_state):
                self._run_mixed_until_blocked_or_ended(
                    game_state, agents, max_cycles=max_cycles
                )
            else:
                run_until_finished(game_state, agents, max_cycles=max_cycles)
        self._save_game_and_events(game_state)
        self._publish_state(game_state, "idle")
        return game_state

    def list_events(self, game_id: str) -> list[dict]:
        session = (
            self.db.query(GameSession)
            .filter(GameSession.game_id == game_id)
            .first()
        )
        rows = (
            self.db.query(GameEvent)
            .filter(GameEvent.game_id == game_id)
            .order_by(GameEvent.sequence, GameEvent.id)
            .all()
        )
        created_at_by_sequence: dict[int, str | None] = {}
        for row in rows:
            created_at_by_sequence.setdefault(
                row.sequence,
                row.created_at.isoformat() if row.created_at else None,
            )

        if session is not None:
            public_state = session.state_json.get("public_state", {})
            events = public_state.get("public_events", [])
            return [
                {
                    "sequence": sequence,
                    "event": event,
                    "created_at": created_at_by_sequence.get(sequence),
                }
                for sequence, event in enumerate(events)
            ]

        seen_sequences: set[int] = set()
        result = []
        for row in rows:
            if row.sequence in seen_sequences:
                continue
            seen_sequences.add(row.sequence)
            result.append(
                {
                    "sequence": row.sequence,
                    "event": row.event_json,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            )
        return result
