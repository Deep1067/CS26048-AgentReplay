"""Scenario 1: Looping / Repeated Identical Tool Calls

Demonstrates a real failure mode where an agent receives an ambiguous or missing entity query
and gets stuck repeatedly issuing identical queries to search_docs or query_db.
The agent-replay detector catches and flags this session.
"""

from agent_replay.interceptors.tool_interceptor import record_tool
from agent_replay.recorder import record_session
from agent_replay.session_service import SessionService
from agent_replay.storage import SQLiteStorage
from agents.tools import search_docs

recorded_search = record_tool("search_docs")(search_docs)


def run_looping_agent(storage: SQLiteStorage) -> None:
    session_id = "demo_scenario_1_loop"
    storage.delete_session(session_id)
    print(f"\n--- Running Scenario 1: Looping Agent (Session: {session_id}) ---")

    with record_session(session_id, storage=storage):
        for attempt in range(1, 4):
            print(f"Agent Attempt {attempt}: querying 'non_existent_feature_xyz'")
            _ = recorded_search(query="non_existent_feature_xyz")

    service = SessionService(storage=storage)
    details = service.get_session_details(session_id)
    if details:
        dur = details["total_duration_ms"]
        print(f"\nSession recorded: {details['event_count']} events, Duration: {dur}ms")
        print(f"Detected Anomaly Flags: {len(details['flags'])}")
        for flag in details["flags"]:
            print(f" -> [{flag['severity'].upper()}] {flag['rule_name']}: {flag['message']}")
            print(f"    Culprit events: {flag['culprit_seqs']}")


if __name__ == "__main__":
    storage = SQLiteStorage()
    run_looping_agent(storage)
