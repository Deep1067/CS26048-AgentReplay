from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI

from agent_replay.config import DEFAULT_MODEL, GEMINI_API_KEY
from agent_replay.interceptors.model_interceptor import ReplayModelCallbackHandler
from agent_replay.interceptors.tool_interceptor import record_tool
from agents.tools import calculator, query_db, search_docs

# Wrap raw functions first. Stacking @record_tool on @tool breaks LangChain schema introspection.
_recorded_search = record_tool("search_docs")(search_docs)
_recorded_query = record_tool("query_db")(query_db)
_recorded_calc = record_tool("calculator")(calculator)


@tool
def tool_search_docs(query: str) -> str:
    """Searches company documentation and policies for the given query."""
    return _recorded_search(query)


@tool
def tool_query_db(sql: str) -> str:
    """Executes SQL against in-memory tables (users, orders) and returns JSON results."""
    return _recorded_query(sql)


@tool
def tool_calculator(expression: str) -> str:
    """Evaluates a mathematical expression (e.g. '250 * 0.15')."""
    return _recorded_calc(expression)


ALL_TOOLS = [tool_search_docs, tool_query_db, tool_calculator]


def build_langgraph_agent(model_name: str | None = None, api_key: str | None = None):
    """Builds and compiles a LangGraph ReAct agent with the 3 mock tools."""
    key = api_key or GEMINI_API_KEY
    resolved_model = model_name or DEFAULT_MODEL
    callback = ReplayModelCallbackHandler(model_name=resolved_model)
    model = ChatGoogleGenerativeAI(
        model=resolved_model,
        google_api_key=key if key and key != "your_gemini_key_here" else "dummy_key",
        temperature=0.0,
        callbacks=[callback],
    )
    return create_agent(model=model, tools=ALL_TOOLS)
