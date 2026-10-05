"""Scenario 2: Tool Failure & Recovery via Forked Replay

Demonstrates:
1. Live run: Tool returns a database error or unexpected null balance. Agent fails.
2. Strict replay: Reproduces the failure deterministically with 0 live API calls ($0 cost).
3. Forked replay: Substitutes the tool response at seq #1. Downstream execution recovers!
"""

from agent_replay.interceptors.tool_interceptor import record_tool
from agent_replay.recorder import record_session
from agent_replay.replay.engine import replay_session
from agent_replay.storage import SQLiteStorage


@record_tool("query_user_account")
def query_user_account(user_id: int):
    # Simulates a database outage returning an error
    return {"status": "error", "message": "Database timeout connecting to replica."}


@record_tool("calculate_credit")
def calculate_credit(balance: float):
    if balance is None:
        raise ValueError("Cannot calculate credit on None balance")
    return {"credit_limit": balance * 2.5}


def agent_workflow():
    account = query_user_account(user_id=101)
    if account.get("status") == "error":
        return f"Agent Halted: {account.get('message')}"
    return calculate_credit(account.get("balance"))


def run_scenario(storage: SQLiteStorage | None = None) -> None:
    storage = storage or SQLiteStorage()
    session_id = "demo_scenario_2_failure"
    forked_session = "demo_scenario_2_recovered"
    storage.delete_session(session_id)
    storage.delete_session(forked_session)

    print(f"\n=== Step 1: Live Run with Tool Failure (Session: {session_id}) ===")
    with record_session(session_id, storage=storage):
        live_result = agent_workflow()
        print(f"Outcome: {live_result}")

    print("\n=== Step 2: Strict Deterministic Replay (Zero Cost, No Live DB) ===")
    with replay_session(session_id, storage=storage, mode="strict"):
        strict_result = agent_workflow()
        print(f"Replayed Outcome: {strict_result}")
        assert strict_result == live_result
        print("✓ Verified: Failure reproduced identically without re-invoking real services!")

    print("\n=== Step 3: Forked Replay with Response Substitution at Seq #1 ===")
    with replay_session(
        session_id,
        storage=storage,
        mode="forked",
        substitute_seq=1,
        substitute_result={"status": "ok", "balance": 500.0},
        forked_session_id=forked_session,
    ):
        recovered_result = agent_workflow()
        print(f"Recovered Outcome: {recovered_result}")
        assert recovered_result["credit_limit"] == 1250.0
        print("✓ Verified: Agent recovered successfully following response substitution!")


if __name__ == "__main__":
    run_scenario()
