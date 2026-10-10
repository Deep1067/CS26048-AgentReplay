import json

import pytest
from fastapi.testclient import TestClient

from agent_replay.api import create_app
from agent_replay.models import Event
from agent_replay.storage import SQLiteStorage


@pytest.fixture
def client():
    storage = SQLiteStorage(db_path=":memory:")
    storage.create_session("sess_api_test")
    ev = Event(
        session_id="sess_api_test",
        seq=1,
        type="tool_call",
        name="calculator",
        args_json=json.dumps({"expression": "10+5"}),
        result_json=json.dumps({"result": 15}),
        duration_ms=4.5,
    )
    storage.save_event(ev)

    app = create_app(storage=storage)
    return TestClient(app)


def test_api_list_sessions(client):
    res = client.get("/api/sessions")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["session_id"] == "sess_api_test"
    assert data[0]["event_count"] == 1


def test_api_get_session_details(client):
    res = client.get("/api/sessions/sess_api_test")
    assert res.status_code == 200
    data = res.json()
    assert data["session_id"] == "sess_api_test"
    assert data["tool_calls_count"] == 1
    assert len(data["events"]) == 1
    assert data["events"][0]["name"] == "calculator"


def test_api_session_not_found(client):
    res = client.get("/api/sessions/non_existent_session")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_api_prices(client):
    res = client.get("/api/prices")
    assert res.status_code == 200
    data = res.json()
    assert "models" in data
    assert "gemini-1.5-flash" in data["models"]


def test_api_serve_index(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "agent-replay" in res.text


def test_api_cors_allows_localhost_only(client):
    allowed = client.get("/api/sessions", headers={"Origin": "http://localhost"})
    blocked = client.get("/api/sessions", headers={"Origin": "https://example.com"})

    assert allowed.headers["access-control-allow-origin"] == "http://localhost"
    assert "access-control-allow-origin" not in blocked.headers


def test_api_replay_returns_matched_events(client):
    res = client.post("/api/replay", json={"session_id": "sess_api_test"})

    assert res.status_code == 200
    data = res.json()
    assert data["events"] == [
        {
            "id": 1,
            "type": "tool_call",
            "name": "calculator",
            "status": "matched",
            "recorded_result": {"result": 15},
        }
    ]
    assert data["halted"] is False


def test_api_replay_reports_divergence(client):
    res = client.post(
        "/api/replay",
        json={
            "session_id": "sess_api_test",
            "calls": [{"type": "tool_call", "name": "other_tool", "args": {}}],
        },
    )

    assert res.status_code == 200
    event = res.json()["events"][0]
    assert event["status"] == "diverged"
    assert event["recorded"]["name"] == "calculator"
    assert event["requested"]["name"] == "other_tool"
    assert res.json()["halted"] is True


def test_api_replay_reports_tool_substitution(client):
    res = client.post(
        "/api/replay",
        json={
            "session_id": "sess_api_test",
            "mode": "forked",
            "substitute_seq": 1,
            "substitute_result": {"result": 99},
        },
    )

    assert res.status_code == 200
    assert res.json()["events"][0]["status"] == "substituted"


def test_api_cost_over_time(client):
    res = client.get("/api/cost-over-time")

    assert res.status_code == 200
    assert res.json()["points"][0]["session_id"] == "sess_api_test"


def test_api_updates_prices_in_inr(tmp_path, monkeypatch):
    from agent_replay import api as api_module
    from agent_replay.pricing import PriceEngine

    engine = PriceEngine(tmp_path / "prices.json")
    monkeypatch.setattr(api_module, "get_price_engine", lambda: engine)
    app = create_app(storage=SQLiteStorage(db_path=":memory:"))
    test_client = TestClient(app)

    res = test_client.put(
        "/api/prices",
        json={"models": {"test-model": {"input_inr_per_1k": 8.3, "output_inr_per_1k": 16.6}}},
    )

    assert res.status_code == 200
    assert res.json()["models"]["test-model"] == {
        "input_inr_per_1k": 8.3,
        "output_inr_per_1k": 16.6,
    }
    assert engine.prices["test-model"]["input_cost_per_million"] == 100.0


def test_api_updates_detector_config(tmp_path, monkeypatch):
    from agent_replay.detector import config as detector_config

    monkeypatch.setattr(detector_config, "DETECTOR_CONFIG_PATH", tmp_path / "detector.json")
    app = create_app(storage=SQLiteStorage(db_path=":memory:"))
    test_client = TestClient(app)
    update = {
        "max_repeated_tool_calls": 5,
        "cost_multiplier_over_median": 4.0,
        "min_sessions_for_cost_median": 3,
        "max_duration_ms": 120000.0,
        "max_events_per_session": 40,
    }

    res = test_client.put("/api/detector-config", json=update)

    assert res.status_code == 200
    assert res.json() == update


def test_api_get_live_scenarios(client):
    res = client.get("/api/live/scenarios")
    assert res.status_code == 200
    scenarios = res.json()
    assert "scenario_1_loop" in scenarios
    assert "scenario_2_recovery" in scenarios
    assert "live_langgraph_support" in scenarios


def test_api_live_run_unauthorized(client):
    # Missing header
    res = client.post("/api/live/run", json={"scenario_id": "scenario_1_loop"})
    assert res.status_code == 401

    # Invalid header
    res = client.post(
        "/api/live/run",
        json={"scenario_id": "scenario_1_loop"},
        headers={"X-Demo-Key": "wrong_key"},
    )
    assert res.status_code == 401


def test_api_live_run_success_and_step_cap(client):
    from agent_replay.config import DEMO_API_KEY

    res = client.post(
        "/api/live/run",
        json={"scenario_id": "scenario_1_loop"},
        headers={"X-Demo-Key": DEMO_API_KEY},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "step_limit_reached"
    assert data["event_count"] == 5
    assert "live_run_scenario_1_loop_" in data["session_id"]


def test_api_live_run_timeout(client):
    from agent_replay.config import DEMO_API_KEY

    res = client.post(
        "/api/live/run",
        json={
            "scenario_id": "scenario_1_loop",
            "timeout_seconds": 0.05,
            "simulate_delay_seconds": 0.2,
        },
        headers={"X-Demo-Key": DEMO_API_KEY},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "timed_out"
    assert "timed out after 0.05s" in data["message"]
