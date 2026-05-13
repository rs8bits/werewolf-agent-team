from __future__ import annotations

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
from app.models import GameEvent, GameSession
from app.llm.client import LLMClient
from app.services.event_bus import game_event_bus
from app.state.schemas import GameState


def _short_uuid() -> str:
    return uuid.uuid4().hex[:8]


class GameSessionService:
    """Service layer: owns DB persistence + runner orchestration."""

    def __init__(self, db: Session):
        self.db = db

    # ── Persistence helpers ───────────────────────────────────────────────

    def _save_game_and_events(self, game_state: GameState) -> None:
        game_id = game_state.game_id

        existing_count = (
            self.db.query(GameEvent)
            .filter(GameEvent.game_id == game_id)
            .count()
        )
        all_events = game_state.public_state.public_events
        new_events = all_events[existing_count:]

        for i, evt in enumerate(new_events):
            self.db.add(
                GameEvent(
                    game_id=game_id,
                    sequence=existing_count + i,
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
                agents[p.seat_no] = create_agent(p.role, llm_client)
            return agents

        for p in game_state.players:
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
    ) -> GameState:
        if agent_mode not in {"scripted", "llm"}:
            raise ValueError("agent_mode must be 'scripted' or 'llm'")
        setup = get_role_setup(player_count)
        rules = rule_config or default_rule_config(player_count)
        if agent_mode == "llm":
            config = load_config()
            if model:
                config = replace(config, model=model)
            LLMClient(config=config)
        game_id = _short_uuid()
        game_state = initialize_game(
            game_id,
            setup,
            player_names=player_names,
            rule_config=rules,
            agent_mode=agent_mode,
            model=model,
            seed=seed,
        )
        self._save_game_and_events(game_state)
        return game_state

    def get_game(self, game_id: str) -> GameState | None:
        return self._load_game_state(game_id)

    def run_cycle(self, game_id: str) -> GameState:
        game_state = self._load_game_state(game_id)
        if game_state is None:
            raise ValueError(f"对局不存在: {game_id}")
        agents = self._build_agents(game_state)
        self._publish_state(game_state, "running")
        with live_event_sink(self._persist_live_event):
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
            run_until_finished(game_state, agents, max_cycles=max_cycles)
        self._save_game_and_events(game_state)
        self._publish_state(game_state, "idle")
        return game_state

    def list_events(self, game_id: str) -> list[dict]:
        rows = (
            self.db.query(GameEvent)
            .filter(GameEvent.game_id == game_id)
            .order_by(GameEvent.sequence)
            .all()
        )
        return [
            {
                "sequence": r.sequence,
                "event": r.event_json,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
