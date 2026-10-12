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
    assert data["events"][0]["status"] == "success"
    assert data["successful_events"] == 1
    assert data["failed_events"] == 0
    assert data["slowest_event"]["name"] == "calculator"
    assert data["tool_stats"]["calculator"]["event_count"] == 1


def test_api_session_not_found(client):
    res = client.get("/api/sessions/non_existent_session")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_api_filtered_events_and_analytics(client):
    storage = SQLiteStorage(db_path=":memory:")
    storage.create_session("analytics")
    storage.save_event(
        Event(
            session_id="analytics",
            seq=1,
            type="tool_call",
            name="search",
            args_json="{}",
            error="upstream unavailable",
            duration_ms=12,
        )
    )
    storage.save_event(
        Event(
            session_id="analytics",
            seq=2,
            type="tool_call",
            name="search",
            args_json="{}",
            error="bad response",
            error_type="ValueError",
            duration_ms=30,
        )
    )
    test_client = TestClient(create_app(storage=storage))

    filtered = test_client.get("/api/sessions/analytics/events?status=exception")
    assert filtered.status_code == 200
    assert len(filtered.json()["events"]) == 1
    assert filtered.json()["events"][0]["dependency"]["explicit"] is False

    analytics = test_client.get("/api/sessions/analytics/analytics")
    assert analytics.status_code == 200
    assert analytics.json()["successful_events"] == 0
    assert analytics.json()["failed_events"] == 2
    assert analytics.json()["slowest_event"]["seq"] == 2
    assert analytics.json()["tool_stats"]["search"]["failure_count"] == 2
    assert analytics.json()["metrics_available"]["cost"] is False


def test_api_events_missing_session(client):
    res = client.get("/api/sessions/missing/events")
    assert res.status_code == 404


def test_api_empty_session_has_explicit_unavailable_analytics():
    storage = SQLiteStorage(db_path=":memory:")
    storage.create_session("empty")
    test_client = TestClient(create_app(storage=storage))

    details = test_client.get("/api/sessions/empty").json()
    assert details["event_count"] == 0
    assert details["slowest_event"] is None
    assert details["tool_stats"] == {}
    assert details["metrics_available"] == {"tokens": False, "cost": False}


def test_api_provider_status_never_exposes_keys(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    data = client.get("/api/providers").json()
    assert all(provider["configured"] is False for provider in data["providers"])
    assert all("key" not in provider for provider in data["providers"])


def test_api_playground_missing_key_is_explicit_and_recorded(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    res = client.post(
        "/api/playground/chat",
        json={"provider": "openai", "prompt": "hello"},
    )
    assert res.status_code == 503
    assert "not configured" in res.json()["detail"]
    sessions = client.get("/api/sessions").json()
    assert any(item["session_id"].startswith("playground_") for item in sessions)


def test_api_usage_groups_model_events(client):
    data = client.get("/api/usage").json()
    assert "groups" in data
    assert "sessions" in data
    assert isinstance(data["groups"], list)


def test_api_usage_filters_and_preserves_unavailable_cost():
    storage = SQLiteStorage(db_path=":memory:")
    storage.create_session("usage-session")
    storage.save_event(
        Event(
            session_id="usage-session",
            seq=1,
            type="model_call",
            name="unknown-model",
            model="unknown-model",
            provider="test-provider",
            args_json="{}",
            tokens_in=12,
            tokens_out=8,
        )
    )
    test_client = TestClient(create_app(storage=storage))

    res = test_client.get("/api/usage?provider=test-provider&model=unknown-model")

    assert res.status_code == 200
    assert res.json()["groups"][0]["cost_usd"] is None
    assert res.json()["sessions"][0]["cost_usd"] is None
    assert test_client.get("/api/usage?provider=missing").json() == {
        "groups": [],
        "sessions": [],
    }


def test_api_playground_records_provider_success(monkeypatch):
    from agent_replay import api as api_module
    from agent_replay.providers import ProviderResponse

    storage = SQLiteStorage(db_path=":memory:")
    monkeypatch.setattr(
        api_module,
        "call_provider",
        lambda provider, prompt, model: ProviderResponse(
            text="hello back",
            provider=provider,
            model=model or "test-model",
            usage={"input_tokens": 3, "output_tokens": 5},
        ),
    )
    test_client = TestClient(create_app(storage=storage))

    res = test_client.post(
        "/api/playground/chat",
        json={"provider": "openai", "prompt": "hello", "model": "test-model"},
    )

    assert res.status_code == 200
    assert res.json()["text"] == "hello back"
    events = storage.get_events(res.json()["session_id"])
    assert events[0].provider == "openai"
    assert events[0].tokens_total == 8


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


def test_api_replay_rejects_unknown_substitution_event(client):
    res = client.post(
        "/api/replay",
        json={
            "session_id": "sess_api_test",
            "mode": "forked",
            "substitute_seq": 99,
            "substitute_result": {"result": 99},
        },
    )

    assert res.status_code == 400
    assert res.json()["detail"] == "Substitution event was not found."


def test_api_counterfactual_experiment(client):
    res = client.post("/api/experiments/counterfactual")

    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "forked_runtime_execution"
    assert data["outcomes"]["baseline"].startswith("Agent Halted:")
    assert data["outcomes"]["forked"] == {"credit_limit": 1250.0}
    assert data["fork_metadata"]["forked_from"] == data["parent_session_id"]
    assert data["events"]["added"][0]["name"] == "calculate_credit"


def test_api_cost_over_time(client):
    res = client.get("/api/cost-over-time")

    assert res.status_code == 200
    assert res.json()["points"][0]["session_id"] == "sess_api_test"


def test_api_updates_prices_in_inr(tmp_path, monkeypatch):
    from agent_replay import api as api_module
    from agent_replay.pricing import PriceEngine

    engine = PriceEngine(tmp_path / "prices.json")
    monkeypatch.setattr(api_module, "get_price_engine", lambda: engine)
    app = create_app(
        storage=SQLiteStorage(db_path=":memory:"),
        config_mutations_enabled=True,
    )
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
    app = create_app(
        storage=SQLiteStorage(db_path=":memory:"),
        config_mutations_enabled=True,
    )
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


def test_api_config_mutations_disabled_do_not_change_configuration(client):
    original_prices = client.get("/api/prices").json()
    original_detector = client.get("/api/detector-config").json()

    price_res = client.put(
        "/api/prices",
        json={"models": {"untrusted-model": {"input_inr_per_1k": 1, "output_inr_per_1k": 1}}},
    )
    detector_res = client.put(
        "/api/detector-config",
        json={
            "max_repeated_tool_calls": 1,
            "cost_multiplier_over_median": 1,
            "min_sessions_for_cost_median": 1,
            "max_duration_ms": 1,
            "max_events_per_session": 1,
        },
    )

    assert price_res.status_code == 403
    assert detector_res.status_code == 403
    assert client.get("/api/prices").json() == original_prices
    assert client.get("/api/detector-config").json() == original_detector


def test_api_live_run_disabled_by_default(client):
    res = client.post("/api/live/run", json={"scenario_id": "scenario_1_loop"})
    assert res.status_code == 503
    assert res.json()["detail"] == "Live execution is not enabled on this server."


def test_api_live_run_success_and_step_cap(client):
    app = create_app(
        storage=SQLiteStorage(db_path=":memory:"),
        live_run_enabled=True,
    )
    test_client = TestClient(app)
    res = test_client.post(
        "/api/live/run",
        json={"scenario_id": "scenario_1_loop"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "step_limit_reached"
    assert data["event_count"] == 5
    assert "live_run_scenario_1_loop_" in data["session_id"]


def test_api_live_run_timeout(client):
    app = create_app(
        storage=SQLiteStorage(db_path=":memory:"),
        live_run_enabled=True,
    )
    test_client = TestClient(app)
    res = test_client.post(
        "/api/live/run",
        json={
            "scenario_id": "scenario_1_loop",
            "timeout_seconds": 0.05,
            "simulate_delay_seconds": 0.2,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "timed_out"
    assert "timed out after 0.05s" in data["message"]
