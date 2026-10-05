from agent_replay.recorder import record_session
from agent_replay.storage import SQLiteStorage
from agents.langgraph_agent import ALL_TOOLS, build_langgraph_agent, tool_search_docs


def test_tools_schema():
    assert len(ALL_TOOLS) == 3
    tool_names = [t.name for t in ALL_TOOLS]
    assert "tool_search_docs" in tool_names
    assert "tool_query_db" in tool_names
    assert "tool_calculator" in tool_names


def test_agent_graph_build():
    agent = build_langgraph_agent(model_name="gemini-3.8-flash", api_key="test_dummy_key")
    assert agent is not None
    # Verify graph can compile and export nodes
    assert hasattr(agent, "invoke")


def test_langgraph_tools_record_under_session():
    storage = SQLiteStorage(db_path=":memory:")
    with record_session("lg_record", storage=storage):
        result = tool_search_docs.invoke({"query": "refund policy"})
    assert "refund" in result.lower()
    events = storage.get_events("lg_record")
    assert len(events) == 1
    assert events[0].name == "search_docs"
    assert events[0].type == "tool_call"
