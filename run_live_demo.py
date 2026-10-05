"""Record a live LangGraph session into SQLite and print session totals.

Requires GEMINI_API_KEY in .env. Does not print the key.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8")

from agent_replay.config import DEFAULT_MODEL, GEMINI_API_KEY  # noqa: E402
from agent_replay.recorder import record_session  # noqa: E402
from agent_replay.session_service import SessionService  # noqa: E402
from agent_replay.storage import SQLiteStorage  # noqa: E402
from agents.langgraph_agent import build_langgraph_agent  # noqa: E402

SESSION_ID = f"live_demo_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
PROMPT = (
    "Find Alice total order value from the database and tell me her refund "
    "eligibility based on the refund policy."
)


def main() -> int:
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_key_here":
        print("GEMINI_API_KEY is not set. Add it to .env and retry.")
        return 1

    storage = SQLiteStorage()
    agent = build_langgraph_agent()

    print(f"\nRunning live agent session with model: {DEFAULT_MODEL}")
    print(f"Session ID: {SESSION_ID}")
    print(f"Prompt: {PROMPT}\n{'=' * 60}")

    with record_session(SESSION_ID, storage=storage, metadata={"prompt": PROMPT}):
        result = agent.invoke({"messages": [{"role": "user", "content": PROMPT}]})
        final_answer = result["messages"][-1].content
        print(f"\nAgent Final Answer:\n{final_answer}")

    print("=" * 60)
    details = SessionService(storage=storage).get_session_details(SESSION_ID)
    if not details:
        print("Session was not recorded.")
        return 1

    print("\nSession Summary:")
    print(
        f"  Events recorded : {details['event_count']} "
        f"({details['tool_calls_count']} tool calls, {details['model_calls_count']} model calls)"
    )
    print(
        f"  Total tokens    : {details['total_tokens_in']} in / "
        f"{details['total_tokens_out']} out"
    )
    print(f"  Total cost      : ${details['total_cost_usd']:.6f}")
    print(f"  Total duration  : {details['total_duration_ms']:.0f} ms")
    flags = details.get("flags", [])
    print(f"  Anomaly flags   : {len(flags)}")
    for flag in flags:
        print(f"  -> [{flag['severity'].upper()}] {flag['rule_name']}: {flag['message']}")

    print("\nView session timeline: uvicorn agent_replay.api:app --reload --port 8000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
