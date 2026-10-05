from agent_replay.storage import SQLiteStorage
from agents.adk_agent import TOOL_MAP, GoogleADKAgent


def test_adk_agent_tool_bindings():
    """Verify all 3 tool wrappers are properly bound."""
    assert "search_docs" in TOOL_MAP
    assert "query_db" in TOOL_MAP
    assert "calculator" in TOOL_MAP


def test_adk_agent_returns_without_key():
    """Agent gracefully handles missing API key without making any live calls."""
    agent = GoogleADKAgent(api_key="your_gemini_key_here")
    res = agent.run_turn("What is the refund policy?")
    assert "Gemini API key not configured" in res


def test_scenario_1_execution():
    """Scenario 1: Agent loops with identical tool calls -> detector flags it."""
    from scenarios.scenario_1_loop import run_looping_agent

    storage = SQLiteStorage(db_path=":memory:")
    run_looping_agent(storage)
    run_looping_agent(storage)

    events = storage.get_events("demo_scenario_1_loop")
    assert len(events) == 3
    # All 3 events are identical repeated calls - detector should flag
    assert all(e.name == "search_docs" for e in events)
    assert all(e.args_json == events[0].args_json for e in events)

    from agent_replay.session_service import SessionService

    details = SessionService(storage=storage).get_session_details("demo_scenario_1_loop")
    assert details is not None
    assert len(details["flags"]) == 1


def test_scenario_2_execution():
    """Scenario 2: Live failure -> strict replay -> forked recovery."""
    from scenarios.scenario_2_malformed_response import run_scenario

    run_scenario(SQLiteStorage(db_path=":memory:"))
