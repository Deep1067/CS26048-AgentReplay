import json

from fastapi.testclient import TestClient

from agent_replay.api import create_app
from agent_replay.evaluation import evaluate_session, validate_criteria
from agent_replay.models import Event
from agent_replay.replay.experiment import run_counterfactual_experiment
from agent_replay.storage import SQLiteStorage


def make_event(
    result: object | None,
    *,
    seq: int = 1,
    name: str = "tool",
    error: str | None = None,
    error_type: str | None = None,
    event_type: str = "tool_call",
    **values: object,
) -> Event:
    return Event(
        session_id="session",
        seq=seq,
        type=event_type,
        name=name,
        args_json="{}",
        result_json=json.dumps(result) if result is not None else None,
        error=error,
        error_type=error_type,
        **values,
    )


def test_evaluator_passes_expected_nested_values_fields_and_phrases():
    evaluation = evaluate_session(
        "session",
        [make_event({"answer": {"value": 42}, "text": "Found the answer"})],
        {
            "expected_output": {"answer": {"value": 42}},
            "required_fields": ["answer.value"],
            "required_phrases": ["the answer"],
        },
    )

    assert evaluation["status"] == "passed"
    assert evaluation["evaluators"]["expected_output"]["status"] == "passed"
    assert evaluation["evaluators"]["required_information"]["status"] == "passed"
    assert evaluation["evaluators"]["execution_errors"]["status"] == "passed"
    assert evaluation["evaluators"]["expected_output"]["evidence"][0]["seq"] == 1
    assert evaluation["evaluators"]["expected_output"]["version"] == "1.0"

    bool_mismatch = evaluate_session(
        "session",
        [make_event({"enabled": 1})],
        {"expected_output": {"enabled": True}},
    )
    assert bool_mismatch["evaluators"]["expected_output"]["status"] == "failed"


def test_evaluator_fails_wrong_values_missing_fields_and_error_payloads():
    evaluation = evaluate_session(
        "session",
        [make_event({"status": "error", "message": "database timeout"})],
        {
            "expected_output": {"status": "ok"},
            "required_fields": ["credit_limit"],
        },
    )

    assert evaluation["status"] == "failed"
    assert evaluation["evaluators"]["expected_output"]["status"] == "failed"
    assert evaluation["evaluators"]["required_information"]["missing_fields"] == ["credit_limit"]
    assert evaluation["evaluators"]["execution_errors"]["status"] == "failed"


def test_allowing_recorded_errors_is_explicit_and_does_not_hide_them():
    evaluation = evaluate_session(
        "session",
        [make_event(None, error="timeout")],
        {"allow_tool_errors": True},
    )

    assert evaluation["status"] == "partial"
    assert "not an overall quality pass" in evaluation["status_explanation"]
    assert evaluation["evaluators"]["execution_errors"]["status"] == "passed"
    assert "1 event(s)" in evaluation["evaluators"]["execution_errors"]["explanation"]

    model_error = evaluate_session(
        "session",
        [make_event(None, error="provider failed", event_type="model_call")],
        {"allow_tool_errors": True},
    )
    assert model_error["evaluators"]["execution_errors"]["status"] == "failed"

    no_quality_criteria = evaluate_session("clean", [make_event({"ok": True})], {})
    assert no_quality_criteria["status"] == "partial"
    assert "not configured" in no_quality_criteria["status_explanation"]


def test_evaluator_reports_unavailable_and_partial_without_false_passes():
    no_events = evaluate_session("empty", [], {"expected_output": {"answer": 1}})
    assert no_events["status"] == "unavailable"
    assert no_events["evaluators"]["expected_output"]["status"] == "unavailable"
    assert no_events["evaluators"]["execution_errors"]["status"] == "unavailable"

    partial = evaluate_session(
        "session",
        [make_event({"ok": True})],
        {"max_tokens": 100},
    )
    assert partial["status"] == "partial"
    assert (
        partial["evaluators"]["efficiency"]["thresholds"]["total_tokens"]["status"] == "unavailable"
    )


def test_evaluator_detects_replay_divergence_recorded_as_an_event_error():
    evaluation = evaluate_session(
        "session",
        [make_event(None, error="Replay diverged at event #1", error_type="ReplayDivergenceError")],
        {},
    )

    assert evaluation["evaluators"]["execution_errors"]["status"] == "failed"
    assert (
        evaluation["evaluators"]["execution_errors"]["evidence"][0]["error_type"]
        == "ReplayDivergenceError"
    )


def test_criteria_reject_unsupported_or_invalid_values():
    invalid_criteria = [
        [],
        {"arbitrary_code": "raise Exception()"},
        {"expected_output": ["not", "an", "object"]},
        {"expected_output": {"empty": {}}},
        {"required_fields": ["valid", 4]},
        {"allow_tool_errors": "yes"},
        {"max_tokens": -1},
        {"max_cost_usd": float("inf")},
    ]
    for criteria in invalid_criteria:
        try:
            validate_criteria(criteria)
        except ValueError:
            continue
        raise AssertionError(f"Invalid criteria was accepted: {criteria!r}")
    assert validate_criteria({"max_tokens": 0})["max_tokens"] == 0


def test_api_persists_repeated_experiment_evaluations_and_compares_same_criteria():
    storage = SQLiteStorage(db_path=":memory:")
    experiment = run_counterfactual_experiment(storage)
    client = TestClient(create_app(storage=storage))
    criteria = {
        "expected_output": {"credit_limit": 1250.0},
        "required_fields": ["credit_limit"],
    }
    endpoint = f"/api/experiments/{experiment['experiment_id']}/evaluations"

    first = client.post(endpoint, json={"criteria": criteria})
    second = client.post(endpoint, json={"criteria": criteria})

    assert first.status_code == second.status_code == 200
    first_record = first.json()
    result = first_record["result"]
    assert first_record["target_type"] == "experiment"
    assert first_record["experiment_id"] == experiment["experiment_id"]
    assert result["baseline"]["session_id"] == experiment["parent_session_id"]
    assert result["fork"]["session_id"] == experiment["fork_session_id"]
    assert result["baseline"]["status"] == "failed"
    assert result["fork"]["status"] == "passed"
    assert result["replay_validity"]["status"] == "passed"
    assert "expected_output" in result["comparison"]["improvements"]
    assert result["baseline"]["evaluators"]["execution_errors"]["status"] == "failed"
    assert result["fork"]["evaluators"]["execution_errors"]["status"] == "passed"

    history = client.get(endpoint)
    assert history.status_code == 200
    assert len(history.json()["evaluations"]) == 2
    assert history.json()["evaluations"][0]["criteria"] == first_record["criteria"]


def test_session_evaluation_api_validates_and_persists_history():
    storage = SQLiteStorage(db_path=":memory:")
    storage.create_session("playground_run")
    storage.save_event(
        Event(
            session_id="playground_run",
            seq=1,
            type="model_call",
            name="configured-model",
            args_json="{}",
            result_json=json.dumps({"text": "A real recorded answer"}),
            tokens_in=3,
            tokens_out=4,
            tokens_total=7,
            duration_ms=12,
            cost_usd=0.001,
            cost_status="estimated",
        )
    )
    client = TestClient(create_app(storage=storage))

    response = client.post(
        "/api/evaluations/sessions/playground_run",
        json={"criteria": {"required_fields": ["text"], "max_tokens": 10}},
    )
    invalid = client.post(
        "/api/evaluations/sessions/playground_run",
        json={"criteria": {"required_fields": "text"}},
    )

    assert response.status_code == 200
    record = response.json()
    assert record["target_type"] == "session"
    assert record["session_id"] == "playground_run"
    assert record["result"]["evaluators"]["efficiency"]["metrics"]["cost_usd"] == {
        "value": 0.001,
        "status": "estimated",
        "label": "recorded provider-rate estimate, not provider-confirmed billing",
    }
    assert invalid.status_code == 422
    assert len(client.get("/api/evaluations?session_id=playground_run").json()["evaluations"]) == 1
    assert (
        client.post(
            "/api/evaluations/sessions/missing",
            json={"criteria": {}},
        ).status_code
        == 404
    )


def test_session_evaluation_records_replay_divergence_and_incomplete_validation():
    storage = SQLiteStorage(db_path=":memory:")
    storage.create_session("replay-check")
    storage.save_event(
        Event(
            session_id="replay-check",
            seq=1,
            type="tool_call",
            name="lookup",
            args_json=json.dumps({"id": 4}),
            result_json=json.dumps({"value": "recorded"}),
        )
    )
    client = TestClient(create_app(storage=storage))
    endpoint = "/api/evaluations/sessions/replay-check"

    diverged = client.post(
        endpoint,
        json={
            "criteria": {"expected_output": {"value": "recorded"}},
            "replay_calls": [{"type": "tool_call", "name": "different", "args": {"id": 4}}],
        },
    )
    incomplete = client.post(
        endpoint,
        json={"criteria": {"expected_output": {"value": "recorded"}}, "replay_calls": []},
    )

    assert diverged.status_code == 200
    assert diverged.json()["result"]["status"] == "failed"
    assert diverged.json()["result"]["replay_validity"]["status"] == "diverged"
    assert diverged.json()["result"]["evaluators"]["replay_divergence"]["status"] == "failed"
    assert diverged.json()["result"]["replay_validity"]["evidence"][0]["seq"] == 1
    assert incomplete.status_code == 200
    assert incomplete.json()["result"]["status"] == "partial"
    assert incomplete.json()["result"]["replay_validity"]["status"] == "incomplete"


def test_experiment_evaluation_uses_saved_event_snapshot_when_session_was_deleted():
    storage = SQLiteStorage(db_path=":memory:")
    experiment = run_counterfactual_experiment(storage)
    storage.delete_session(experiment["parent_session_id"])
    client = TestClient(create_app(storage=storage))

    response = client.post(
        f"/api/experiments/{experiment['experiment_id']}/evaluations",
        json={"criteria": {"expected_output": {"credit_limit": 1250.0}}},
    )

    assert response.status_code == 200
    record = response.json()
    assert record["result"]["baseline"]["status"] == "failed"
    assert any("snapshot" in item for item in record["result"]["limitations"])
