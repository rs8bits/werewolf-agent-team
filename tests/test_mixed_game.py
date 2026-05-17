from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base
from app.services.game_session import GameSessionService
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


def _create_mixed_game(client, human_seats: list[int], seed: int = 42):
    resp = client.post(
        "/games",
        json={
            "player_count": 6,
            "human_seats": human_seats,
            "seed": seed,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _run_cycle(client, game_id: str):
    resp = client.post(f"/games/{game_id}/run-cycle")
    return resp


def _submit_action(client, game_id: str, seat_no: int, action: dict):
    resp = client.post(
        f"/games/{game_id}/players/{seat_no}/actions",
        json=action,
    )
    return resp


def _pending(game_state: dict) -> dict | None:
    return game_state.get("runtime_state", {}).get("pending_human_action")


class TestCreateMixedGame:
    def test_create_mixed_game_sets_player_types(self, client):
        data = _create_mixed_game(client, human_seats=[1, 3])
        players = data["players"]
        assert players[0]["player_type"] == "human"
        assert players[1]["player_type"] == "ai"
        assert players[2]["player_type"] == "human"
        assert players[3]["player_type"] == "ai"
        assert len(players) == 6

    def test_create_mixed_game_no_human_seats_is_pure_ai(self, client):
        resp = client.post("/games", json={"player_count": 6, "seed": 42})
        assert resp.status_code == 200
        for p in resp.json()["players"]:
            assert p["player_type"] == "ai"

    def test_create_mixed_game_12_player_rejected(self, client):
        resp = client.post(
            "/games",
            json={"player_count": 12, "human_seats": [1]},
        )
        assert resp.status_code == 422

    def test_create_mixed_game_duplicate_seats_rejected(self, client):
        resp = client.post(
            "/games",
            json={"player_count": 6, "human_seats": [1, 1]},
        )
        assert resp.status_code == 400

    def test_create_mixed_game_out_of_range_seat_rejected(self, client):
        resp = client.post(
            "/games",
            json={"player_count": 6, "human_seats": [0]},
        )
        assert resp.status_code == 400

        resp = client.post(
            "/games",
            json={"player_count": 6, "human_seats": [7]},
        )
        assert resp.status_code == 400


class TestPlayerView:
    def test_player_view_has_own_role(self, client):
        data = _create_mixed_game(client, human_seats=[1], seed=42)
        game_id = data["game_id"]
        resp = client.get(f"/games/{game_id}/players/1/view")
        assert resp.status_code == 200
        view = resp.json()
        assert view["viewer_seat_no"] == 1
        assert "own_role" in view
        assert "own_camp" in view

    def test_player_view_no_truth_state(self, client):
        data = _create_mixed_game(client, human_seats=[1], seed=42)
        game_id = data["game_id"]
        resp = client.get(f"/games/{game_id}/players/1/view")
        assert resp.status_code == 200
        view = resp.json()
        assert "truth_state" not in view

    def test_player_view_players_have_no_role_or_camp(self, client):
        data = _create_mixed_game(client, human_seats=[1], seed=42)
        game_id = data["game_id"]
        resp = client.get(f"/games/{game_id}/players/1/view")
        assert resp.status_code == 200
        view = resp.json()
        for p in view["players"]:
            assert "role" not in p
            assert "camp" not in p
            assert "seat_no" in p
            assert "name" in p
            assert "player_type" in p
            assert "alive" in p

    def test_player_view_nonexistent_seat(self, client):
        data = _create_mixed_game(client, human_seats=[1], seed=42)
        game_id = data["game_id"]
        resp = client.get(f"/games/{game_id}/players/99/view")
        assert resp.status_code == 404

    def test_player_view_nonexistent_game(self, client):
        resp = client.get("/games/nonexistent/players/1/view")
        assert resp.status_code == 404

    def test_ai_player_view_also_works(self, client):
        data = _create_mixed_game(client, human_seats=[1], seed=42)
        game_id = data["game_id"]
        resp = client.get(f"/games/{game_id}/players/2/view")
        assert resp.status_code == 200
        assert resp.json()["viewer_seat_no"] == 2


class TestRunCycleBlocked:
    def test_run_cycle_blocks_on_human_action(self, client):
        data = _create_mixed_game(client, human_seats=[1, 2], seed=42)
        game_id = data["game_id"]
        resp = _run_cycle(client, game_id)
        assert resp.status_code == 200
        body = resp.json()
        p = _pending(body)
        assert p is not None, f"Expected pending_human_action, got None. runtime_state={body.get('runtime_state')}"
        assert p["seat_no"] >= 1
        assert p["action_type"] in (
            "werewolf_kill", "seer_check", "witch_save", "witch_poison", "speak", "vote"
        )
        assert len(p["available_actions"]) > 0
        assert "private_info" in p

    def test_run_cycle_twice_with_pending_no_duplicate(self, client):
        data = _create_mixed_game(client, human_seats=[1], seed=42)
        game_id = data["game_id"]
        resp1 = _run_cycle(client, game_id)
        assert resp1.status_code == 200
        events_before = len(resp1.json()["public_state"]["public_events"])

        resp2 = _run_cycle(client, game_id)
        assert resp2.status_code == 200
        events_after = len(resp2.json()["public_state"]["public_events"])
        assert events_after == events_before  # No new events


class TestSubmitHumanAction:
    def test_submit_then_continue(self, client):
        data = _create_mixed_game(client, human_seats=[1], seed=42)
        game_id = data["game_id"]
        # First run blocks
        resp = _run_cycle(client, game_id)
        p = _pending(resp.json())
        assert p is not None

        # Submit action
        action_type = p["action_type"]
        action = _make_action_for_pending(p)
        submit_resp = _submit_action(client, game_id, p["seat_no"], action)
        assert submit_resp.status_code == 200, submit_resp.text

    def test_submit_wrong_seat(self, client):
        data = _create_mixed_game(client, human_seats=[1, 2], seed=42)
        game_id = data["game_id"]
        resp = _run_cycle(client, game_id)
        p = _pending(resp.json())
        assert p is not None

        # Submit from wrong seat
        wrong_seat = p["seat_no"] + 1
        if wrong_seat > 6:
            wrong_seat = 1
        action = {"action": {"action_type": "speak", "content": "hello"}, "reasoning_summary": ""}
        submit_resp = _submit_action(client, game_id, wrong_seat, action)
        assert submit_resp.status_code in (409, 400), submit_resp.text

    def test_submit_wrong_action_type(self, client):
        data = _create_mixed_game(client, human_seats=[1], seed=42)
        game_id = data["game_id"]
        resp = _run_cycle(client, game_id)
        p = _pending(resp.json())
        assert p is not None

        # Submit an action_type not in available_actions
        valid = set(p["available_actions"])
        wrong_type = "vote" if "vote" not in valid else "werewolf_kill"
        if wrong_type in valid:
            wrong_type = "speak"
        action = {
            "action": {"action_type": wrong_type, "target_seat_no": 2},
            "reasoning_summary": "",
        }
        submit_resp = _submit_action(client, game_id, p["seat_no"], action)
        # Should fail if the action type is truly not available
        if wrong_type not in valid:
            assert submit_resp.status_code in (409, 400, 422), (
                f"Expected 409/400/422, got {submit_resp.status_code}: {submit_resp.text}"
            )

    def test_submit_no_pending(self, client):
        data = _create_mixed_game(client, human_seats=[], seed=42)
        game_id = data["game_id"]
        action = {"action": {"action_type": "speak", "content": "hi"}, "reasoning_summary": ""}
        resp = _submit_action(client, game_id, 1, action)
        assert resp.status_code == 409, resp.text

    def test_submit_invalid_body(self, client):
        data = _create_mixed_game(client, human_seats=[1], seed=42)
        game_id = data["game_id"]
        resp = _run_cycle(client, game_id)
        p = _pending(resp.json())
        assert p is not None
        resp = _submit_action(client, game_id, p["seat_no"], {"not": "valid"})
        assert resp.status_code in (422, 400), resp.text

    def test_submit_invalid_target_keeps_pending(self, client):
        data = _create_mixed_game(client, human_seats=[1, 2, 3, 4, 5, 6], seed=42)
        game_id = data["game_id"]
        resp = _run_cycle(client, game_id)
        p = _pending(resp.json())
        assert p is not None
        assert p["action_type"] == "werewolf_kill"

        bad_action = {
            "action": {"action_type": "werewolf_kill", "target_seat_no": 99},
            "reasoning_summary": "",
        }
        submit_resp = _submit_action(client, game_id, p["seat_no"], bad_action)
        assert submit_resp.status_code == 400, submit_resp.text

        get_resp = client.get(f"/games/{game_id}")
        assert get_resp.status_code == 200
        still_pending = _pending(get_resp.json())
        assert still_pending is not None
        assert still_pending["seat_no"] == p["seat_no"]
        assert still_pending["action_type"] == p["action_type"]


class TestMixedFullCycle:
    def test_mixed_game_cycle_with_human_speech_and_vote(self, client):
        data = _create_mixed_game(client, human_seats=[1, 2, 3], seed=42)
        game_id = data["game_id"]

        # Run cycle, handle each block
        for _ in range(30):
            resp = _run_cycle(client, game_id)
            body = resp.json()
            p = _pending(body)
            if p is None:
                if body["public_state"]["phase"] == "ended":
                    break
                if body.get("runtime_state", {}).get("mixed_stage") == "idle":
                    continue
            action = _make_action_for_pending(p)
            submit_resp = _submit_action(client, game_id, p["seat_no"], action)
            assert submit_resp.status_code == 200, (
                f"Submit failed: {submit_resp.text}\n"
                f"Pending: {p}\nAction: {action}"
            )

    def test_mixed_game_speech_events_generated(self, client):
        data = _create_mixed_game(client, human_seats=[1], seed=42)
        game_id = data["game_id"]

        # Keep running/submitting until we see a speech event or game ends
        speech_seen = False
        for _ in range(20):
            resp = _run_cycle(client, game_id)
            body = resp.json()
            p = _pending(body)
            if p is None:
                if body["public_state"]["phase"] == "ended":
                    break
                continue
            action = _make_action_for_pending(p)
            submit_resp = _submit_action(client, game_id, p["seat_no"], action)
            assert submit_resp.status_code == 200, submit_resp.text
            events = submit_resp.json()["public_state"]["public_events"]
            for evt in events:
                if evt.get("type") == "speech":
                    speech_seen = True
        assert speech_seen, "Expected at least one speech event"

    def test_mixed_game_vote_cast_events_generated(self, client):
        data = _create_mixed_game(client, human_seats=[1], seed=42)
        game_id = data["game_id"]

        vote_seen = False
        for _ in range(30):
            resp = _run_cycle(client, game_id)
            body = resp.json()
            p = _pending(body)
            if p is None:
                if body["public_state"]["phase"] == "ended":
                    break
                continue
            action = _make_action_for_pending(p)
            submit_resp = _submit_action(client, game_id, p["seat_no"], action)
            assert submit_resp.status_code == 200, submit_resp.text
            events = submit_resp.json()["public_state"]["public_events"]
            for evt in events:
                if evt.get("type") == "vote_cast":
                    vote_seen = True
        assert vote_seen, "Expected at least one vote_cast event"

    def test_mixed_game_run_until_finished_stops_on_blocked(self, client):
        data = _create_mixed_game(client, human_seats=[1], seed=42)
        game_id = data["game_id"]
        resp = client.post(
            f"/games/{game_id}/run-until-finished",
            json={"max_cycles": 50},
        )
        assert resp.status_code == 200
        body = resp.json()
        p = _pending(body)
        # Either blocked with a pending action or game ended
        assert p is not None or body["public_state"]["phase"] == "ended"


class TestMixedPersistence:
    def test_pending_state_survives_reload(self, client):
        data = _create_mixed_game(client, human_seats=[1], seed=42)
        game_id = data["game_id"]
        resp = _run_cycle(client, game_id)
        p1 = _pending(resp.json())
        assert p1 is not None

        # Fetch the game fresh
        get_resp = client.get(f"/games/{game_id}")
        assert get_resp.status_code == 200
        p2 = _pending(get_resp.json())
        assert p2 is not None
        assert p2["seat_no"] == p1["seat_no"]
        assert p2["action_type"] == p1["action_type"]

    def test_pure_ai_game_still_works(self, client):
        resp = client.post("/games", json={"player_count": 6, "seed": 42})
        game_id = resp.json()["game_id"]
        resp = client.post(f"/games/{game_id}/run-until-finished", json={"max_cycles": 50})
        assert resp.status_code == 200
        assert resp.json()["public_state"]["phase"] == "ended"
        assert resp.json()["winner"] is not None

    def test_pure_ai_cycle_still_works(self, client):
        resp = client.post("/games", json={"player_count": 6, "seed": 42})
        game_id = resp.json()["game_id"]
        resp = _run_cycle(client, game_id)
        assert resp.status_code == 200
        assert resp.json()["public_state"]["round"] >= 1
        p = _pending(resp.json())
        assert p is None  # Pure AI should not block


# ── Test helpers ──────────────────────────────────────────────────────────


def _make_action_for_pending(pending: dict | None) -> dict:
    assert pending is not None, "Cannot make action for None pending"
    action_type = pending["action_type"]
    available = pending["available_actions"]
    seat_no = pending["seat_no"]
    private = pending.get("private_info", {})

    if "speak" in available or action_type == "speak":
        return {
            "action": {"action_type": "speak", "content": f"我是{pending['seat_no']}号，先发言。"},
            "reasoning_summary": "",
        }

    if "vote" in available or action_type == "vote":
        return {
            "action": {"action_type": "vote", "target_seat_no": None},
            "reasoning_summary": "",
        }

    if "werewolf_kill" in available or action_type == "werewolf_kill":
        return {
            "action": {"action_type": "werewolf_kill", "target_seat_no": _other_seat(seat_no, 6)},
            "reasoning_summary": "",
        }

    if "seer_check" in available or action_type == "seer_check":
        return {
            "action": {"action_type": "seer_check", "target_seat_no": _other_seat(seat_no, 6)},
            "reasoning_summary": "",
        }

    if "witch_save" in available or action_type == "witch_save":
        target = private.get("pending_wolf_kill_target") or _other_seat(seat_no, 6)
        return {
            "action": {"action_type": "witch_save", "target_seat_no": target},
            "reasoning_summary": "",
        }

    if "witch_poison" in available or action_type == "witch_poison":
        return {
            "action": {"action_type": "witch_poison", "target_seat_no": _other_seat(seat_no, 6)},
            "reasoning_summary": "",
        }

    raise ValueError(f"Unknown action type: {action_type}, available: {available}")


def _other_seat(seat_no: int, max_seat: int = 6) -> int:
    return seat_no % max_seat + 1
