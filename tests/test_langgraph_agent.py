from agents.langgraph_agent import ALL_TOOLS, build_langgraph_agent


def test_tools_schema():
    assert len(ALL_TOOLS) == 3
    tool_names = [t.name for t in ALL_TOOLS]
    assert "tool_search_docs" in tool_names
    assert "tool_query_db" in tool_names
    assert "tool_calculator" in tool_names


def test_agent_graph_build():
    agent = build_langgraph_agent(model_name="gemini-1.5-flash", api_key="test_dummy_key")
    assert agent is not None
    # Verify graph can compile and export nodes
    assert hasattr(agent, "invoke")
