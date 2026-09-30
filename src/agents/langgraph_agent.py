from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent

from agent_replay.config import DEFAULT_MODEL, GEMINI_API_KEY
from agents.tools import calculator, query_db, search_docs


@tool
def tool_search_docs(query: str) -> str:
    """Searches company documentation and policies for the given query."""
    return search_docs(query)


@tool
def tool_query_db(sql: str) -> str:
    """Executes SQL against in-memory tables (users, orders) and returns JSON results."""
    return query_db(sql)


@tool
def tool_calculator(expression: str) -> str:
    """Evaluates a mathematical expression (e.g. '250 * 0.15')."""
    return calculator(expression)


ALL_TOOLS = [tool_search_docs, tool_query_db, tool_calculator]


def build_langgraph_agent(model_name: str | None = None, api_key: str | None = None):
    """Builds and compiles a LangGraph ReAct agent with the 3 mock tools."""
    key = api_key or GEMINI_API_KEY
    model = ChatGoogleGenerativeAI(
        model=model_name or DEFAULT_MODEL,
        google_api_key=key if key and key != "your_gemini_key_here" else "dummy_key",
        temperature=0.0,
    )
    return create_react_agent(model, ALL_TOOLS)
