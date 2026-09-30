import json

import pytest

from agent_replay.interceptors.model_interceptor import record_model_call
from agent_replay.interceptors.tool_interceptor import record_tool
from agent_replay.recorder import record_session
from agent_replay.replay.engine import replay_session
from agent_replay.replay.exceptions import ReplayCompletedError, ReplayDivergenceError
from agent_replay.storage import SQLiteStorage


@pytest.fixture
def storage():
    return SQLiteStorage(db_path=":memory:")


def test_strict_replay_success(storage):
    call_count = {"search": 0, "calc": 0, "model": 0}

    @record_tool(tool_name="search")
    def tool_search(q: str):
        call_count["search"] += 1
        return f"result for {q}"

    @record_tool(tool_name="calc")
    def tool_calc(expr: str):
        call_count["calc"] += 1
        return 42

    def mock_llm():
        call_count["model"] += 1
        return "I found 42"

    # Step 1: Record original session
    with record_session("orig_sess", storage=storage):
        r1 = tool_search("gravity")
        r2 = tool_calc("40+2")
        r3 = record_model_call("gemini-test", mock_llm)

    assert call_count["search"] == 1
    assert call_count["calc"] == 1
    assert call_count["model"] == 1

    # Step 2: Strict replay
    with replay_session("orig_sess", storage=storage, mode="strict"):
        replay_r1 = tool_search("gravity")
        replay_r2 = tool_calc("40+2")
        replay_r3 = record_model_call("gemini-test", mock_llm)

    # In strict replay, underlying live functions must NOT have been called again!
    assert call_count["search"] == 1
    assert call_count["calc"] == 1
    assert call_count["model"] == 1

    # Results match original
    assert replay_r1 == r1
    assert replay_r2 == r2
    assert replay_r3 == r3


def test_strict_replay_divergence_detection(storage):
    @record_tool(tool_name="search")
    def tool_search(q: str):
        return f"result for {q}"

    with record_session("div_sess", storage=storage):
        tool_search("expected query")

    # Replay with divergent query
    with pytest.raises(ReplayDivergenceError) as exc_info:
        with replay_session("div_sess", storage=storage, mode="strict"):
            tool_search("unexpected query")

    err = exc_info.value
    assert err.seq == 1
    assert err.expected_name == "search"
    assert "expected query" in str(err.expected_args)
    assert "unexpected query" in str(err.actual_args)


def test_strict_replay_completed_error(storage):
    @record_tool(tool_name="tool_a")
    def tool_a():
        return "a"

    with record_session("one_event_sess", storage=storage):
        tool_a()

    with pytest.raises(ReplayCompletedError):
        with replay_session("one_event_sess", storage=storage, mode="strict"):
            tool_a()
            # Attempt second call after trace is finished
            tool_a()


def test_forked_replay_with_substitution(storage):
    calls_made = []

    @record_tool(tool_name="get_balance")
    def get_balance(user_id: int):
        calls_made.append(f"get_balance({user_id})")
        return {"balance": 100}

    @record_tool(tool_name="send_alert")
    def send_alert(msg: str):
        calls_made.append(f"send_alert({msg})")
        return "alert_sent"

    def agent_logic():
        bal = get_balance(1)["balance"]
        if bal <= 0:
            return send_alert("Balance zero! Please recharge.")
        return "Balance sufficient"

    # Step 1: Record original run (balance is 100 -> no alert sent)
    with record_session("orig_run", storage=storage):
        outcome = agent_logic()
        assert outcome == "Balance sufficient"

    orig_events = storage.get_events("orig_run")
    assert len(orig_events) == 1
    assert orig_events[0].name == "get_balance"
    calls_made.clear()

    # Step 2: Forked replay substituting seq 1 with {"balance": 0}
    with replay_session(
        "orig_run",
        storage=storage,
        mode="forked",
        substitute_seq=1,
        substitute_result={"balance": 0},
        forked_session_id="forked_run_1",
    ):
        forked_outcome = agent_logic()
        # Agent now receives 0 balance and takes the alternate branch:
        assert forked_outcome == "alert_sent"

    # In forked mode downstream of seq 1, live execution resumed!
    assert "send_alert(Balance zero! Please recharge.)" in calls_made

    # Verify forked events in storage
    forked_events = storage.get_events("forked_run_1")
    assert len(forked_events) == 2
    assert forked_events[0].name == "get_balance"
    assert json.loads(forked_events[0].result_json) == {"balance": 0}
    assert forked_events[1].name == "send_alert"
