from typing import Any

from agent_replay.storage import SQLiteStorage


class SessionService:
    """Service for computing per-session totals and aggregated metrics."""

    def __init__(self, storage: SQLiteStorage | None = None):
        self.storage = storage or SQLiteStorage()

    def get_session_details(self, session_id: str) -> dict[str, Any] | None:
        summary = self.storage.get_session(session_id)
        if not summary:
            return None

        events = self.storage.get_events(session_id)
        total_tokens_in = sum(e.tokens_in for e in events)
        total_tokens_out = sum(e.tokens_out for e in events)
        total_cost_usd = sum(e.cost_usd for e in events)
        total_duration_ms = sum(e.duration_ms for e in events)

        tool_calls_count = sum(1 for e in events if e.type == "tool_call")
        model_calls_count = sum(1 for e in events if e.type == "model_call")

        return {
            "session_id": session_id,
            "started_at": summary.started_at,
            "event_count": len(events),
            "tool_calls_count": tool_calls_count,
            "model_calls_count": model_calls_count,
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "total_cost_usd": round(total_cost_usd, 6),
            "total_duration_ms": round(total_duration_ms, 2),
            "has_errors": summary.has_errors,
            "events": [e.to_dict() for e in events],
        }
