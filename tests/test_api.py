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
