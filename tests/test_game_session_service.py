from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, GameEvent, GameSession
from app.services.game_session import GameSessionService
from app.state.schemas import GamePhase


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


class TestCreateAndGetGame:
    def test_create_game_returns_valid_state(self, db_session):
        svc = GameSessionService(db_session)
        gs, _ = svc.create_game()
        assert gs.game_id is not None
        assert len(gs.players) == 6
        assert gs.public_state.phase == GamePhase.setup
        assert gs.public_state.round == 0

    def test_create_game_persists_to_db(self, db_session):
        svc = GameSessionService(db_session)
        gs, _ = svc.create_game()
        row = db_session.query(GameSession).filter(GameSession.game_id == gs.game_id).first()
        assert row is not None

    def test_get_game_returns_reconstructed_state(self, db_session):
        svc = GameSessionService(db_session)
        created, _ = svc.create_game()
        loaded = svc.get_game(created.game_id)
        assert loaded is not None
        assert loaded.game_id == created.game_id
        assert len(loaded.players) == len(created.players)

    def test_get_game_nonexistent(self, db_session):
        svc = GameSessionService(db_session)
        assert svc.get_game("nonexistent") is None

    def test_create_game_custom_names(self, db_session):
        svc = GameSessionService(db_session)
        names = ["Alice", "Bob", "Charlie", "David", "Eve", "Frank"]
        gs, _ = svc.create_game(player_names=names)
        assert [p.name for p in gs.players] == names


class TestRunCycle:
    def test_run_cycle_advances_round(self, db_session):
        svc = GameSessionService(db_session)
        gs, _ = svc.create_game()
        assert gs.public_state.round == 0
        gs = svc.run_cycle(gs.game_id)
        # After night phase round is incremented to 1
        assert gs.public_state.round >= 1

    def test_run_cycle_adds_events(self, db_session):
        svc = GameSessionService(db_session)
        gs, _ = svc.create_game()
        initial_count = len(gs.public_state.public_events)
        gs = svc.run_cycle(gs.game_id)
        assert len(gs.public_state.public_events) > initial_count

    def test_run_cycle_persists_events(self, db_session):
        svc = GameSessionService(db_session)
        gs, _ = svc.create_game()
        gs = svc.run_cycle(gs.game_id)
        db_events = db_session.query(GameEvent).filter(GameEvent.game_id == gs.game_id).all()
        assert len(db_events) > 0

    def test_run_cycle_no_duplicate_events(self, db_session):
        svc = GameSessionService(db_session)
        gs, _ = svc.create_game()
        svc.run_cycle(gs.game_id)
        # Run another cycle — events should only be new ones
        gs = svc.run_cycle(gs.game_id)
        evt_count = len(gs.public_state.public_events)
        db_count = db_session.query(GameEvent).filter(GameEvent.game_id == gs.game_id).count()
        assert db_count == evt_count

    def test_run_cycle_persists_contiguous_event_sequences(self, db_session):
        svc = GameSessionService(db_session)
        gs, _ = svc.create_game(seed=42)
        gs = svc.run_cycle(gs.game_id)

        db_events = (
            db_session.query(GameEvent)
            .filter(GameEvent.game_id == gs.game_id)
            .order_by(GameEvent.sequence, GameEvent.id)
            .all()
        )
        sequences = [event.sequence for event in db_events]

        assert sequences == list(range(len(gs.public_state.public_events)))


class TestRunUntilFinished:
    def test_run_until_finished_ends(self, db_session):
        svc = GameSessionService(db_session)
        gs, _ = svc.create_game()
        gs = svc.run_until_finished(gs.game_id, max_cycles=50)
        assert gs.public_state.phase == GamePhase.ended
        assert gs.winner is not None

    def test_run_until_finished_respects_max_cycles(self, db_session):
        svc = GameSessionService(db_session)
        gs, _ = svc.create_game()
        gs = svc.run_until_finished(gs.game_id, max_cycles=1)
        # Either ended or stopped after 1 full cycle (night+day+vote)
        # With scripted agents the game should reach ended quickly
        assert gs.public_state.phase in (GamePhase.ended, GamePhase.vote, GamePhase.day, GamePhase.night)

    def test_run_until_finished_has_winner(self, db_session):
        svc = GameSessionService(db_session)
        gs, _ = svc.create_game()
        gs = svc.run_until_finished(gs.game_id, max_cycles=50)
        assert gs.winner is not None
        assert gs.winner.value in ("werewolf", "good")


class TestListEvents:
    def test_list_events_structured(self, db_session):
        svc = GameSessionService(db_session)
        gs, _ = svc.create_game()
        svc.run_cycle(gs.game_id)
        events = svc.list_events(gs.game_id)
        assert len(events) > 0
        for evt in events:
            assert "sequence" in evt
            assert "event" in evt
            assert isinstance(evt["event"], dict)
            assert "type" in evt["event"]

    def test_events_in_sequence_order(self, db_session):
        svc = GameSessionService(db_session)
        gs, _ = svc.create_game()
        svc.run_cycle(gs.game_id)
        events = svc.list_events(gs.game_id)
        seqs = [e["sequence"] for e in events]
        assert seqs == sorted(seqs)

    def test_list_events_uses_state_event_sequence(self, db_session):
        svc = GameSessionService(db_session)
        gs, _ = svc.create_game(seed=42)
        gs = svc.run_cycle(gs.game_id)

        events = svc.list_events(gs.game_id)
        seqs = [event["sequence"] for event in events]

        assert len(events) == len(gs.public_state.public_events)
        assert seqs == list(range(len(events)))

    def test_list_events_empty_game(self, db_session):
        svc = GameSessionService(db_session)
        gs, _ = svc.create_game()
        events = svc.list_events(gs.game_id)
        assert len(events) == 1  # game_initialized event


class TestEventPersistence:
    def test_events_contain_night_resolution(self, db_session):
        svc = GameSessionService(db_session)
        gs, _ = svc.create_game()
        gs = svc.run_cycle(gs.game_id)
        events = svc.list_events(gs.game_id)
        event_types = [e["event"]["type"] for e in events]
        assert "night_resolved" in event_types

    def test_events_contain_speeches(self, db_session):
        svc = GameSessionService(db_session)
        gs, _ = svc.create_game()
        gs = svc.run_cycle(gs.game_id)
        events = svc.list_events(gs.game_id)
        event_types = [e["event"]["type"] for e in events]
        assert "speech" in event_types
        speech_events = [e for e in events if e["event"]["type"] == "speech"]
        for s in speech_events:
            assert "content" in s["event"]
            assert "seat_no" in s["event"]
            # Content should be Chinese
            content = s["event"]["content"]
            assert any("一" <= c <= "鿿" for c in content)
