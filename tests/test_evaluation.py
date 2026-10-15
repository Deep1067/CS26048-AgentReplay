import json

import pytest
from fastapi.testclient import TestClient

from agent_replay.api import create_app
from agent_replay.evaluation import evaluate_session, validate_criteria
from agent_replay.models import Event
from agent_replay.replay.experiment import _metrics, run_counterfactual_experiment
from agent_replay.session_service import token_usage_summary
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


def test_deterministic_assertions_cover_values_membership_metrics_and_evidence():
    tool = make_event({"items": ["a", "b"]}, seq=1)
    model = make_event(
        {"text": "The workflow worked"},
        seq=2,
        event_type="model_call",
        tokens_in=2,
        tokens_out=4,
        tokens_total=6,
        cost_usd=0.001,
        cost_status="estimated",
    )
    result = evaluate_session(
        "assertions",
        [tool, model],
        {
            "assertions": [
                {
                    "name": "Expected output phrase",
                    "source": "output",
                    "path": "text",
                    "operator": "contains",
                    "expected": "worked",
                },
                {
                    "name": "Recorded array length",
                    "source": "event_result",
                    "path": "items",
                    "event_seq": 1,
                    "operator": "length_eq",
                    "expected": 2,
                },
                {
                    "name": "No recorded error",
                    "source": "event_error",
                    "event_seq": 1,
                    "operator": "not_exists",
                },
                {
                    "name": "Minimum tokens",
                    "source": "metric",
                    "path": "total_tokens",
                    "operator": "gte",
                    "expected": 6,
                },
            ]
        },
    )

    assertion_results = result["evaluators"]["assertions"]["results"]
    assert result["evaluators"]["assertions"]["status"] == "passed"
    assert all(assertion["status"] == "passed" for assertion in assertion_results)
    assert assertion_results[0]["evidence"] == [
        {"session_id": "assertions", "seq": 2, "type": "model_call", "name": "tool"}
    ]


def test_missing_and_partial_token_usage_remains_unavailable_across_views():
    missing = make_event(None, event_type="model_call")
    partial = make_event(None, event_type="model_call", tokens_in=3)

    assert token_usage_summary([missing]) == (None, None, False)
    assert token_usage_summary([partial]) == (3, None, False)

    evaluation = evaluate_session("missing-usage", [missing], {"max_tokens": 1})
    assert evaluation["evaluators"]["efficiency"]["metrics"]["total_tokens"] == {
        "value": None,
        "status": "unavailable",
    }

    comparison = _metrics([missing], [partial])
    assert comparison["tokens"]["available"] is False
    assert comparison["tokens"]["baseline_in"] is None
    assert comparison["tokens"]["forked_out"] is None

    known_zero = make_event(
        None,
        event_type="model_call",
        tokens_in=0,
        tokens_out=0,
        tokens_total=0,
    )
    assert token_usage_summary([known_zero]) == (0, 0, True)


def test_assertions_never_pass_on_missing_data_or_incompatible_json_types():
    missing = evaluate_session(
        "missing",
        [make_event({"enabled": 1})],
        {
            "assertions": [
                {
                    "name": "Missing path",
                    "source": "output",
                    "path": "not_present",
                    "operator": "exists",
                },
                {
                    "name": "Boolean is not numeric",
                    "source": "output",
                    "path": "enabled",
                    "operator": "eq",
                    "expected": True,
                },
            ]
        },
    )

    checks = missing["evaluators"]["assertions"]["results"]
    assert checks[0]["status"] == "failed"
    assert checks[1]["status"] == "failed"
    assert missing["evaluators"]["assertions"]["status"] == "failed"

    unavailable = evaluate_session(
        "empty",
        [],
        {
            "assertions": [
                {
                    "name": "Unavailable output",
                    "source": "output",
                    "path": "answer",
                    "operator": "eq",
                    "expected": "yes",
                }
            ]
        },
    )
    assert unavailable["evaluators"]["assertions"]["status"] == "unavailable"


def test_suite_evaluation_and_replay_history_survive_storage_reopen(tmp_path):
    database_path = tmp_path / "phase3-history.sqlite"
    storage = SQLiteStorage(db_path=database_path)
    storage.create_session("persisted")
    storage.save_event(
        Event(
            session_id="persisted",
            seq=1,
            type="tool_call",
            name="lookup",
            args_json="{}",
            result_json='{"answer":"recorded"}',
        )
    )
    client = TestClient(create_app(storage=storage))
    suite = client.post(
        "/api/evaluation-suites",
        json={
            "name": "Saved answer",
            "criteria": {"expected_output": {"answer": "recorded"}},
        },
    ).json()
    evaluation = client.post(
        "/api/evaluations/sessions/persisted",
        json={"suite_id": suite["suite_id"], "suite_version": suite["version"]},
    )
    validation = client.post("/api/sessions/persisted/replay-validations", json={})
    assert evaluation.status_code == validation.status_code == 200

    reloaded = SQLiteStorage(db_path=database_path)
    assert reloaded.get_evaluation_suite(suite["suite_id"], 1) == suite
    assert (
        reloaded.list_evaluations(session_id="persisted")[0]["evaluation_id"]
        == (evaluation.json()["evaluation_id"])
    )
    assert (
        reloaded.list_replay_validations("persisted")[0]["validation_id"]
        == (validation.json()["validation_id"])
    )


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


def test_evaluation_suite_versions_are_immutable_and_reusable_for_experiments():
    storage = SQLiteStorage(db_path=":memory:")
    client = TestClient(create_app(storage=storage))
    created = client.post(
        "/api/evaluation-suites",
        json={
            "name": "Expected credit limit",
            "description": "Check the recorded outcome",
            "criteria": {
                "assertions": [
                    {
                        "name": "credit limit",
                        "source": "output",
                        "path": "credit_limit",
                        "operator": "eq",
                        "expected": 1250,
                    }
                ]
            },
        },
    )
    assert created.status_code == 200
    suite = created.json()

    updated = client.put(
        f"/api/evaluation-suites/{suite['suite_id']}",
        json={
            "current_version": 1,
            "name": "Expected credit limit",
            "description": "Require the recorded field",
            "criteria": {"required_fields": ["credit_limit"]},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert (
        client.get(f"/api/evaluation-suites/{suite['suite_id']}?version=1").json()["criteria"]
        == suite["criteria"]
    )
    assert (
        len(client.get(f"/api/evaluation-suites/{suite['suite_id']}/versions").json()["versions"])
        == 2
    )
    assert (
        client.put(
            f"/api/evaluation-suites/{suite['suite_id']}",
            json={
                "current_version": 1,
                "name": "Stale update",
                "description": "",
                "criteria": {},
            },
        ).status_code
        == 409
    )

    experiment = run_counterfactual_experiment(storage)
    evaluation = client.post(
        f"/api/experiments/{experiment['experiment_id']}/evaluations",
        json={"suite_id": suite["suite_id"], "suite_version": 1},
    )
    assert evaluation.status_code == 200, evaluation.text
    record = evaluation.json()
    assert record["suite_id"] == suite["suite_id"]
    assert record["suite_version"] == 1
    assert record["criteria"] == suite["criteria"]
    assert (
        record["result"]["comparison"]["criteria_statuses"]["assertion:assertion-1"]["fork"]
        == "passed"
    )


@pytest.mark.parametrize(
    "assertion",
    [
        {"name": "bad source", "source": [], "path": "x", "operator": "eq", "expected": 1},
        {"name": "bad operator", "source": "output", "path": "x", "operator": {}, "expected": 1},
    ],
)
def test_malformed_assertions_return_validation_errors(assertion):
    storage = SQLiteStorage(db_path=":memory:")
    client = TestClient(create_app(storage=storage))
    response = client.post(
        "/api/evaluation-suites",
        json={
            "name": "Invalid",
            "description": "",
            "criteria": {"assertions": [assertion]},
        },
    )
    assert response.status_code == 422
    assert "assertions[0]" in response.json()["detail"]


def test_standalone_strict_replay_validation_persists_attempts_and_empty_calls():
    storage = SQLiteStorage(db_path=":memory:")
    storage.create_session("strict-check")
    storage.save_event(
        Event(
            session_id="strict-check",
            seq=1,
            type="tool_call",
            name="lookup",
            args_json='{"id":1}',
            result_json='{"value":"recorded"}',
        )
    )
    client = TestClient(create_app(storage=storage))
    endpoint = "/api/sessions/strict-check/replay-validations"

    complete = client.post(endpoint, json={})
    incomplete = client.post(endpoint, json={"calls": []})
    diverged = client.post(
        endpoint,
        json={"calls": [{"type": "tool_call", "name": "other", "args": {"id": 1}}]},
    )

    assert complete.status_code == 200
    assert complete.json()["status"] == "passed"
    assert complete.json()["result"]["events"][0]["status"] == "matched"
    assert incomplete.status_code == 200
    assert incomplete.json()["status"] == "partial"
    assert incomplete.json()["result"]["events"][0]["status"] == "not_checked"
    assert diverged.status_code == 200
    assert diverged.json()["status"] == "failed"
    history = client.get(endpoint)
    assert history.status_code == 200
    assert len(history.json()["validations"]) == 3
    assert {record["validation_id"] for record in history.json()["validations"]} == {
        complete.json()["validation_id"],
        incomplete.json()["validation_id"],
        diverged.json()["validation_id"],
    }
