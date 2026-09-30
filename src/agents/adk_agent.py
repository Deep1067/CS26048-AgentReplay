from google import genai
from google.genai import types

from agent_replay.config import DEFAULT_MODEL, GEMINI_API_KEY
from agent_replay.interceptors.model_interceptor import record_model_call
from agent_replay.interceptors.tool_interceptor import record_tool
from agents.tools import calculator, query_db, search_docs

# Decorated tools using the universal @record_tool interceptor
recorded_search_docs = record_tool("search_docs")(search_docs)
recorded_query_db = record_tool("query_db")(query_db)
recorded_calculator = record_tool("calculator")(calculator)

TOOL_MAP = {
    "search_docs": recorded_search_docs,
    "query_db": recorded_query_db,
    "calculator": recorded_calculator,
}


class GoogleADKAgent:
    """Agent built using the official Google GenAI SDK (ADK) with native function calling.

    Demonstrates that agent-replay is completely framework-agnostic.
    """

    def __init__(
        self,
        model_name: str | None = None,
        api_key: str | None = None,
        client: genai.Client | None = None,
    ):
        self.model_name = model_name or DEFAULT_MODEL
        key = api_key or GEMINI_API_KEY
        if client:
            self.client = client
        elif key and key != "your_gemini_key_here":
            self.client = genai.Client(api_key=key)
        else:
            self.client = None

    def run_turn(self, prompt: str, max_steps: int = 5) -> str:
        """Executes a multi-step tool-calling loop using Google GenAI SDK."""
        if not self.client:
            return "Simulated response: Gemini API key not configured."

        chat = self.client.chats.create(
            model=self.model_name,
            config=types.GenerateContentConfig(
                tools=[recorded_search_docs, recorded_query_db, recorded_calculator],
                temperature=0.0,
            ),
        )

        for _ in range(max_steps):
            response = record_model_call(
                self.model_name,
                chat.send_message,
                prompt,
            )

            # Check if model requested function/tool calls
            tool_calls = response.function_calls
            if not tool_calls:
                return response.text or ""

            # Execute tool calls
            for call in tool_calls:
                fn_name = call.name
                fn_args = dict(call.args or {})
                if fn_name in TOOL_MAP:
                    tool_fn = TOOL_MAP[fn_name]
                    tool_result = tool_fn(**fn_args)
                    # Feed tool response back into conversation
                    prompt = types.Part.from_function_response(
                        name=fn_name,
                        response={"result": tool_result},
                    )

        return "Max execution steps reached."
