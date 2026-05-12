from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base
from app.state.schemas import GamePhase


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


class TestCreateGame:
    def test_create_game_returns_200(self, client):
        resp = client.post("/games", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "game_id" in data
        assert data["public_state"]["phase"] == "setup"
        assert len(data["players"]) == 6

    def test_create_game_has_truth_state(self, client):
        resp = client.post("/games", json={})
        data = resp.json()
        assert "truth_state" in data
        assert len(data["truth_state"]["wolf_team"]) == 2

    def test_create_game_custom_names(self, client):
        names = ["狼1", "预2", "女3", "民4", "民5", "狼6"]
        resp = client.post("/games", json={"player_names": names})
        assert resp.status_code == 200
        data = resp.json()
        assert [p["name"] for p in data["players"]] == names

    def test_create_game_invalid_name_count(self, client):
        resp = client.post("/games", json={"player_names": ["A"]})
        assert resp.status_code == 422  # Pydantic validation error


class TestGetGame:
    def test_get_game_existing(self, client):
        create_resp = client.post("/games", json={})
        game_id = create_resp.json()["game_id"]
        resp = client.get(f"/games/{game_id}")
        assert resp.status_code == 200
        assert resp.json()["game_id"] == game_id

    def test_get_game_nonexistent(self, client):
        resp = client.get("/games/nonexistent")
        assert resp.status_code == 404


class TestRunCycle:
    def test_run_cycle_returns_200(self, client):
        create_resp = client.post("/games", json={})
        game_id = create_resp.json()["game_id"]
        resp = client.post(f"/games/{game_id}/run-cycle")
        assert resp.status_code == 200
        data = resp.json()
        assert data["public_state"]["round"] >= 1

    def test_run_cycle_nonexistent(self, client):
        resp = client.post("/games/nonexistent/run-cycle")
        assert resp.status_code == 404

    def test_run_cycle_produces_events(self, client):
        create_resp = client.post("/games", json={})
        game_id = create_resp.json()["game_id"]
        client.post(f"/games/{game_id}/run-cycle")
        resp = client.get(f"/games/{game_id}/events")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) > 1  # More than just game_initialized

    def test_run_multiple_cycles(self, client):
        create_resp = client.post("/games", json={})
        game_id = create_resp.json()["game_id"]
        client.post(f"/games/{game_id}/run-cycle")
        resp = client.post(f"/games/{game_id}/run-cycle")
        if resp.status_code == 200:
            data = resp.json()
            assert data["public_state"]["round"] >= 2


class TestRunUntilFinished:
    def test_run_until_finished_returns_200(self, client):
        create_resp = client.post("/games", json={})
        game_id = create_resp.json()["game_id"]
        resp = client.post(
            f"/games/{game_id}/run-until-finished",
            json={"max_cycles": 50},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["public_state"]["phase"] == "ended"
        assert data["winner"] is not None

    def test_run_until_finished_nonexistent(self, client):
        resp = client.post(
            "/games/nonexistent/run-until-finished",
            json={"max_cycles": 50},
        )
        assert resp.status_code == 404

    def test_run_until_finished_default_body(self, client):
        create_resp = client.post("/games", json={})
        game_id = create_resp.json()["game_id"]
        resp = client.post(f"/games/{game_id}/run-until-finished")
        assert resp.status_code == 200
        assert resp.json()["public_state"]["phase"] == "ended"


class TestListEvents:
    def test_list_events_returns_200(self, client):
        create_resp = client.post("/games", json={})
        game_id = create_resp.json()["game_id"]
        resp = client.get(f"/games/{game_id}/events")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_events_nonexistent(self, client):
        resp = client.get("/games/nonexistent/events")
        assert resp.status_code == 404

    def test_list_events_structured(self, client):
        create_resp = client.post("/games", json={})
        game_id = create_resp.json()["game_id"]
        client.post(f"/games/{game_id}/run-cycle")
        resp = client.get(f"/games/{game_id}/events")
        data = resp.json()
        assert len(data) > 0
        for evt in data:
            assert "sequence" in evt
            assert "event" in evt
            assert "type" in evt["event"]

    def test_events_after_run_until_finished(self, client):
        create_resp = client.post("/games", json={})
        game_id = create_resp.json()["game_id"]
        client.post(f"/games/{game_id}/run-until-finished", json={"max_cycles": 50})
        resp = client.get(f"/games/{game_id}/events")
        data = resp.json()
        event_types = [e["event"]["type"] for e in data]
        assert "game_initialized" in event_types
        assert "night_resolved" in event_types


class TestHealth:
    def test_health_still_works(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
