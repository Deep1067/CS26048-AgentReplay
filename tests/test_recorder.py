import json

import pytest

from agent_replay.interceptors.model_interceptor import record_model_call
from agent_replay.interceptors.tool_interceptor import record_tool
from agent_replay.models import Event
from agent_replay.recorder import record_session
from agent_replay.storage import SQLiteStorage


@pytest.fixture
def storage():
    """In-memory SQLite storage for isolated test runs."""
    return SQLiteStorage(db_path=":memory:")


def test_storage_create_and_query_events(storage):
    session_id = storage.create_session("sess_test_1")
    assert session_id == "sess_test_1"

    ev1 = Event(
        session_id=session_id,
        seq=1,
        type="tool_call",
        name="calculator",
        args_json=json.dumps({"expr": "2+2"}),
        result_json=json.dumps({"result": 4}),
        duration_ms=5.2,
    )
    storage.save_event(ev1)

    ev2 = Event(
        session_id=session_id,
        seq=2,
        type="model_call",
        name="gemini-1.5-flash",
        args_json=json.dumps({"prompt": "Hello"}),
        result_json=json.dumps({"text": "Hi"}),
        tokens_in=10,
        tokens_out=5,
        duration_ms=120.0,
    )
    storage.save_event(ev2)

    events = storage.get_events(session_id)
    assert len(events) == 2
    assert events[0].seq == 1
    assert events[0].name == "calculator"
    assert events[1].seq == 2
    assert events[1].type == "model_call"
    assert events[1].tokens_in == 10


def test_tool_interceptor_normal_and_sequential(storage):
    @record_tool(tool_name="mock_search")
    def mock_search(query: str):
        return f"Results for: {query}"

    with record_session("session_tools_1", storage=storage) as sid:
        assert sid == "session_tools_1"
        res1 = mock_search("pricing")
        assert res1 == "Results for: pricing"

        res2 = mock_search("refunds")
        assert res2 == "Results for: refunds"

    events = storage.get_events("session_tools_1")
    assert len(events) == 2
    assert events[0].seq == 1
    assert events[0].name == "mock_search"
    assert "pricing" in events[0].args_json
    assert "Results for: pricing" in events[0].result_json
    assert events[0].duration_ms >= 0

    assert events[1].seq == 2
    assert "refunds" in events[1].args_json


def test_tool_interceptor_exception_handling(storage):
    @record_tool(tool_name="failing_tool")
    def failing_tool():
        raise ValueError("Database connection failed")

    with record_session("session_err", storage=storage) as sid:
        assert sid == "session_err"
        with pytest.raises(ValueError, match="Database connection failed"):
            failing_tool()

    events = storage.get_events("session_err")
    assert len(events) == 1
    assert events[0].seq == 1
    assert events[0].error == "Database connection failed"
    assert events[0].result_json is None

    session = storage.get_session("session_err")
    assert session is not None
    assert session.has_errors is True


@pytest.mark.asyncio
async def test_async_tool_interceptor(storage):
    import asyncio

    @record_tool(tool_name="async_fetch")
    async def async_fetch(url: str):
        await asyncio.sleep(0.01)
        return {"status": 200, "url": url}

    with record_session("session_async", storage=storage):
        res = await async_fetch("https://example.com")
        assert res["status"] == 200

    events = storage.get_events("session_async")
    assert len(events) == 1
    assert events[0].name == "async_fetch"
    assert events[0].duration_ms >= 5.0


def test_concurrent_seq_allocation(storage):
    import threading

    session_id = "session_concurrent"
    storage.create_session(session_id)
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            storage.save_event(
                Event(
                    session_id=session_id,
                    seq=0,
                    type="tool_call",
                    name=f"tool_{i}",
                    args_json=json.dumps({"i": i}),
                    result_json=json.dumps({"ok": True}),
                    duration_ms=1.0,
                )
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    events = storage.get_events(session_id)
    assert len(events) == 20
    assert [event.seq for event in events] == list(range(1, 21))


def test_record_model_call(storage):
    class MockUsage:
        prompt_token_count = 120
        candidates_token_count = 45

    class MockResponse:
        usage_metadata = MockUsage()
        content = "Agent response"

    def mock_llm_call(prompt: str):
        return MockResponse()

    with record_session("session_model", storage=storage):
        resp = record_model_call("gemini-test", mock_llm_call, "Explain gravity")
        assert resp.content == "Agent response"

    events = storage.get_events("session_model")
    assert len(events) == 1
    assert events[0].type == "model_call"
    assert events[0].name == "gemini-test"
    assert events[0].tokens_in == 120
    assert events[0].tokens_out == 45
