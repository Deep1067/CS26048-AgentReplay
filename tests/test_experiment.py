from agent_replay.replay.experiment import run_counterfactual_experiment
from agent_replay.storage import SQLiteStorage


def test_counterfactual_experiment_records_failure_and_fork():
    storage = SQLiteStorage(db_path=":memory:")

    result = run_counterfactual_experiment(storage)

    baseline_events = storage.get_events(result["parent_session_id"])
    forked_events = storage.get_events(result["fork_session_id"])

    assert len(baseline_events) == 1
    assert baseline_events[0].name == "query_user_account"
    assert '"status": "error"' in baseline_events[0].result_json
    assert result["outcomes"]["baseline"].startswith("Agent Halted:")
    assert result["outcomes"]["strict_replay"] == result["outcomes"]["baseline"]
    assert result["outcomes"]["forked"] == {"credit_limit": 1250.0}
    assert result["fork_metadata"]["forked_from"] == result["parent_session_id"]
    assert result["fork_metadata"]["forked_at_seq"] == 1
    assert len(forked_events) == 2
    assert result["events"]["changed"]
    assert result["events"]["added"][0]["name"] == "calculate_credit"
    assert result["events"]["removed"] == []
    assert result["metrics"]["duration_ms"]["available"] is True
    assert "synthetic scenario" in result["metrics"]["duration_ms"]["label"]
    assert result["metrics"]["tokens"]["available"] is False
    assert result["metrics"]["cost_usd_estimate"]["available"] is False


def test_repeated_experiments_have_equivalent_comparisons():
    storage = SQLiteStorage(db_path=":memory:")

    first = run_counterfactual_experiment(storage)
    second = run_counterfactual_experiment(storage)

    assert first["outcomes"] == second["outcomes"]
    assert first["substitution"] == second["substitution"]
    assert (
        first["events"]["changed"][0]["original"]["result_json"]
        == second["events"]["changed"][0]["original"]["result_json"]
    )
    assert [event["name"] for event in first["events"]["added"]] == ["calculate_credit"]
    assert [event["name"] for event in second["events"]["added"]] == ["calculate_credit"]
    assert first["metrics"]["event_count_delta"] == second["metrics"]["event_count_delta"] == 1
