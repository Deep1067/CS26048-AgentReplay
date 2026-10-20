import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_replay.api import create_app
from agent_replay.models import Event
from agent_replay.providers import ProviderResponse
from agent_replay.storage import SQLiteStorage


class _RemoteClient:
    def __init__(self, app, host: str, port: int):
        self._transport = httpx.ASGITransport(app=app, client=(host, port))
        self._client = httpx.AsyncClient(transport=self._transport, base_url="http://testserver")

    def request(self, method: str, url: str, **kwargs):
        return asyncio.run(self._client.request(method, url, **kwargs))

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs):
        return self.request("PUT", url, **kwargs)

    def close(self):
        asyncio.run(self._client.aclose())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def _remote_client(app, host: str, port: int):
    return _RemoteClient(app, host, port)


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
    playground_session = next(
        item["session_id"] for item in sessions if item["session_id"].startswith("playground_")
    )
    evaluation = client.post(
        f"/api/evaluations/sessions/{playground_session}",
        json={"criteria": {"expected_output": {"text": "must not pass"}}},
    )
    assert evaluation.status_code == 200
    assert evaluation.json()["result"]["status"] == "failed"


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
        "records": [],
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
    assert res.json()["output_source"] == "real_provider_call"
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


def test_api_guided_experiment_persists_selected_baseline_and_comparison():
    storage = SQLiteStorage(db_path=":memory:")
    storage.create_session("recorded-account-run")
    storage.save_event(
        Event(
            session_id="recorded-account-run",
            seq=1,
            type="tool_call",
            name="query_user_account",
            args_json=json.dumps({"args": [], "kwargs": {"user_id": 101}}),
            result_json=json.dumps(
                {"status": "error", "message": "Database timeout connecting to replica."}
            ),
        )
    )
    test_client = TestClient(create_app(storage=storage))
    original_baseline_event = storage.get_events("recorded-account-run")[0].to_dict()

    baselines = test_client.get("/api/experiments/baselines").json()["baselines"]
    assert baselines[0]["session_id"] == "recorded-account-run"
    assert baselines[0]["substitutable_events"][0]["seq"] == 1

    response = test_client.post(
        "/api/experiments",
        json={
            "baseline_session_id": "recorded-account-run",
            "substitute_seq": 1,
            "substitute_result": {"status": "ok", "balance": 200},
        },
    )

    assert response.status_code == 200
    comparison = response.json()
    assert comparison["parent_session_id"] == "recorded-account-run"
    assert comparison["outcomes"]["strict_replay"].startswith("Agent Halted:")
    assert comparison["outcomes"]["forked"] == {"credit_limit": 500.0}
    assert comparison["evidence"]["strict_replay"].startswith("reconstructed")
    assert storage.get_session_metadata(comparison["fork_session_id"]) == {
        "forked_from": "recorded-account-run",
        "forked_at_seq": 1,
    }

    saved = test_client.get(f"/api/experiments/{comparison['experiment_id']}")
    assert saved.status_code == 200
    assert saved.json()["result"]["events"] == comparison["events"]
    assert storage.get_events("recorded-account-run")[0].to_dict() == original_baseline_event
    assert (
        test_client.get("/api/experiments").json()["experiments"][0]["baseline_session_id"]
        == "recorded-account-run"
    )


def test_api_guided_experiment_rejects_unsupported_baseline_and_substitution(client):
    unsupported = client.post(
        "/api/experiments",
        json={
            "baseline_session_id": "sess_api_test",
            "substitute_seq": 1,
            "substitute_result": {"result": 42},
        },
    )
    assert unsupported.status_code == 422
    assert "not eligible" in unsupported.json()["detail"]

    storage = SQLiteStorage(db_path=":memory:")
    storage.create_session("supported-baseline")
    storage.save_event(
        Event(
            session_id="supported-baseline",
            seq=1,
            type="tool_call",
            name="query_user_account",
            args_json=json.dumps({"args": [], "kwargs": {"user_id": 101}}),
            result_json=json.dumps({"status": "error", "message": "recorded failure"}),
        )
    )
    supported_client = TestClient(create_app(storage=storage))
    invalid_result = supported_client.post(
        "/api/experiments",
        json={
            "baseline_session_id": "supported-baseline",
            "substitute_seq": 1,
            "substitute_result": {"status": "ok"},
        },
    )
    assert invalid_result.status_code == 422


def test_api_cost_over_time(client):
    res = client.get("/api/cost-over-time")

    assert res.status_code == 200
    assert res.json()["points"][0]["session_id"] == "sess_api_test"
    assert res.json()["points"][0]["total_cost_usd"] is None
    assert res.json()["points"][0]["cost_status"] == "unavailable"


def test_api_cost_and_usage_are_attributed_to_session_and_never_default_missing_cost_to_zero():
    storage = SQLiteStorage(db_path=":memory:")
    storage.create_session("priced-playground")
    storage.save_event(
        Event(
            session_id="priced-playground",
            seq=1,
            type="model_call",
            name="known-model",
            model="known-model",
            provider="test-provider",
            args_json="{}",
            tokens_in=12,
            tokens_out=8,
            cost_usd=0.0003,
            cost_status="estimated",
        )
    )
    storage.save_event(
        Event(
            session_id="priced-playground",
            seq=2,
            type="model_call",
            name="known-model",
            model="known-model",
            provider="test-provider",
            args_json="{}",
            tokens_in=4,
            tokens_out=5,
            cost_usd=0.0002,
            cost_status="estimated",
        )
    )
    storage.create_session("unpriced-playground")
    storage.save_event(
        Event(
            session_id="unpriced-playground",
            seq=1,
            type="model_call",
            name="unknown-model",
            model="unknown-model",
            provider="test-provider",
            args_json="{}",
            tokens_in=9,
            tokens_out=2,
        )
    )
    storage.create_session("usage-missing")
    storage.save_event(
        Event(
            session_id="usage-missing",
            seq=1,
            type="model_call",
            name="usage-missing-model",
            model="usage-missing-model",
            provider="test-provider",
            args_json="{}",
        )
    )
    test_client = TestClient(create_app(storage=storage))

    usage = test_client.get("/api/usage").json()

    priced = next(row for row in usage["records"] if row["session_id"] == "priced-playground")
    unpriced = next(row for row in usage["records"] if row["session_id"] == "unpriced-playground")
    missing = next(row for row in usage["records"] if row["session_id"] == "usage-missing")
    assert priced["input_tokens"] == 16
    assert priced["output_tokens"] == 13
    assert priced["event_count"] == 2
    assert priced["cost_usd"] == 0.0005
    assert priced["cost_status"] == "estimated"
    assert unpriced["cost_usd"] is None
    assert unpriced["cost_status"] == "unavailable"
    assert missing["input_tokens"] is None
    assert missing["output_tokens"] is None
    assert missing["usage_available"] is False
    session_rows = {row["session_id"]: row for row in test_client.get("/api/sessions").json()}
    assert session_rows["unpriced-playground"]["total_cost_usd"] is None
    assert session_rows["unpriced-playground"]["cost_status"] == "unavailable"
    assert test_client.get("/api/sessions/priced-playground").json()["total_cost_usd"] == 0.0005
    known_group = next(group for group in usage["groups"] if group["model"] == "known-model")
    assert known_group["sessions"] == 1
    assert known_group["cost_usd"] == 0.0005


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
    capability = client.get("/api/live/status")
    assert capability.status_code == 200
    assert capability.json()["execution_enabled"] is False
    assert capability.json()["instrumented_recording_supported"] is True
    assert "disabled" in capability.json()["message"]

    res = client.post("/api/live/run", json={"scenario_id": "scenario_1_loop"})
    assert res.status_code == 503
    assert res.json()["detail"] == "Live execution is not enabled on this server."


def test_live_model_run_persists_incrementally_and_can_be_evaluated(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "server-only-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "mock-live-model")
    storage = SQLiteStorage(db_path=":memory:")
    app = create_app(storage=storage, live_run_enabled=True)
    client = TestClient(app)
    captured = {}

    def fake_provider(provider, prompt, model):
        captured["prompt"] = prompt
        captured["provider"] = provider
        captured["model"] = model
        return ProviderResponse(
            text="answer with api_key=hiddenvalue123",
            provider=provider,
            model=model,
            usage={"input_tokens": 11, "output_tokens": 5},
        )

    monkeypatch.setattr("agent_replay.api.call_provider", fake_provider)
    response = client.post(
        "/api/live/runs",
        json={
            "provider": "openai",
            "model": "mock-live-model",
            "prompt": "check sk-123456789012345678901234",
        },
    )

    assert response.status_code == 202
    created = response.json()
    run = client.get(f"/api/live/runs/{created['run_id']}").json()
    assert run["status"] == "completed"
    assert run["event_count"] == 1
    assert captured == {
        "prompt": "check sk-123456789012345678901234",
        "provider": "openai",
        "model": "mock-live-model",
    }
    event = run["events"][0]
    assert event["seq"] == 1
    assert event["provider"] == "openai"
    assert event["tokens_in"] == 11
    assert event["tokens_out"] == 5
    assert event["cost_status"] == "unavailable"
    assert "123456789012345678901234" not in event["args_json"]
    assert "hiddenvalue123" not in event["result_json"]
    assert client.get("/api/sessions").json()[0]["session_id"] == created["session_id"]
    assert client.get("/api/live/runs").json()["runs"][0]["status"] == "completed"
    usage = client.get(f"/api/usage?session_id={created['session_id']}").json()
    assert usage["records"][0]["input_tokens"] == 11
    assert usage["records"][0]["output_tokens"] == 5
    assert usage["records"][0]["cost_usd"] is None

    evaluation = client.post(
        f"/api/evaluations/sessions/{created['session_id']}",
        json={"criteria": {"expected_output": {"text": "answer with api_key=[REDACTED]"}}},
    )
    assert evaluation.status_code == 200
    assert evaluation.json()["result"]["status"] == "passed"


def test_live_model_run_enforces_single_process_concurrency(monkeypatch):
    import threading

    monkeypatch.setenv("OPENAI_API_KEY", "server-only-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "mock-live-model")
    storage = SQLiteStorage(db_path=":memory:")
    app = create_app(storage=storage, live_run_enabled=True)
    client = TestClient(app)
    provider_started = threading.Event()
    finish_provider = threading.Event()
    first_response = []

    def blocking_provider(provider, prompt, model):
        provider_started.set()
        if not finish_provider.wait(timeout=5):
            raise RuntimeError("Mock provider timed out.")
        return ProviderResponse("done", provider, model)

    monkeypatch.setattr("agent_replay.api.call_provider", blocking_provider)
    first_request = threading.Thread(
        target=lambda: first_response.append(
            client.post(
                "/api/live/runs",
                json={"provider": "openai", "model": "mock-live-model", "prompt": "first"},
            )
        )
    )
    first_request.start()
    try:
        assert provider_started.wait(timeout=5)
        running = storage.list_sessions()
        assert len(running) == 1
        run_id = running[0].session_id
        assert storage.get_session_metadata(run_id)["run_status"] == "running"
        assert len(storage.get_events(run_id)) == 1

        rejected = client.post(
            "/api/live/runs",
            json={"provider": "openai", "model": "mock-live-model", "prompt": "second"},
        )
        assert rejected.status_code == 429
        assert "already running" in rejected.json()["detail"]
    finally:
        finish_provider.set()
        first_request.join(timeout=5)

    assert not first_request.is_alive()
    assert first_response[0].status_code == 202
    assert storage.get_session_metadata(run_id)["run_status"] == "completed"


def test_live_model_provider_failure_is_persisted_as_failed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-only-test-key")
    storage = SQLiteStorage(db_path=":memory:")
    client = TestClient(create_app(storage=storage, live_run_enabled=True))

    def fail_provider(*_args):
        raise RuntimeError("Provider request failed (429).")

    monkeypatch.setattr("agent_replay.api.call_provider", fail_provider)
    created = client.post(
        "/api/live/runs",
        json={"provider": "anthropic", "prompt": "try once"},
    )

    assert created.status_code == 202
    run = client.get(f"/api/live/runs/{created.json()['run_id']}").json()
    assert run["status"] == "failed"
    assert run["error"] == "Provider request failed (429)."
    assert run["event_count"] == 1
    assert run["events"][0]["result_json"] is None
    assert run["events"][0]["error"] == "Provider request failed (429)."


def test_live_model_run_rejects_unconfigured_provider_and_invalid_inputs(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = TestClient(
        create_app(storage=SQLiteStorage(db_path=":memory:"), live_run_enabled=True)
    )
    unavailable = client.post(
        "/api/live/runs",
        json={"provider": "gemini", "prompt": "task"},
    )
    oversized = client.post(
        "/api/live/runs",
        json={"provider": "openai", "prompt": "x" * 8001},
    )

    assert unavailable.status_code == 503
    assert "No usable model" in unavailable.json()["detail"]
    assert oversized.status_code == 422


def test_remote_provider_execution_requires_server_token(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "server-only-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "mock-live-model")
    monkeypatch.delenv("LIVE_RUN_AUTH_TOKEN", raising=False)
    app = create_app(storage=SQLiteStorage(db_path=":memory:"), live_run_enabled=True)
    client = _remote_client(app, "203.0.113.10", 12345)
    blocked = client.post(
        "/api/live/runs",
        json={"provider": "openai", "prompt": "task"},
    )
    monkeypatch.setenv("LIVE_RUN_AUTH_TOKEN", "remote-test-token")
    monkeypatch.setattr(
        "agent_replay.api.call_provider",
        lambda provider, prompt, model: ProviderResponse("done", provider, model),
    )
    unauthorized = client.post(
        "/api/live/runs",
        json={"provider": "openai", "prompt": "task"},
    )
    authorized = client.post(
        "/api/live/runs",
        headers={"Authorization": "Bearer remote-test-token"},
        json={"provider": "openai", "prompt": "task"},
    )
    client.close()

    assert blocked.status_code == 503
    assert unauthorized.status_code == 401
    assert authorized.status_code == 202


def test_remote_configuration_mutations_require_separate_admin_token(monkeypatch):
    monkeypatch.delenv("CONFIG_MUTATIONS_AUTH_TOKEN", raising=False)
    app = create_app(
        storage=SQLiteStorage(db_path=":memory:"),
        config_mutations_enabled=True,
    )
    client = _remote_client(app, "203.0.113.11", 12345)
    original = client.get("/api/prices").json()
    update = {
        "models": {
            "untrusted-model": {
                "input_inr_per_1k": 1,
                "output_inr_per_1k": 1,
            }
        }
    }

    missing_token = client.put("/api/prices", json=update)
    monkeypatch.setenv("CONFIG_MUTATIONS_AUTH_TOKEN", "separate-admin-token")
    invalid_token = client.put(
        "/api/prices",
        headers={"Authorization": "Bearer invalid-token"},
        json=update,
    )
    final_prices = client.get("/api/prices").json()
    client.close()

    assert missing_token.status_code == 503
    assert invalid_token.status_code == 401
    assert original == final_prices


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
