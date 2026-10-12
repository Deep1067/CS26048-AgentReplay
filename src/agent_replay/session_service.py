from typing import Any

from agent_replay.detector.engine import DetectorEngine
from agent_replay.storage import SQLiteStorage


def event_status(event: Any) -> str:
    """Return a display status derived only from recorded error fields."""
    if event.error_type:
        return "exception"
    if event.error:
        return "failed"
    return "success"


class SessionService:
    """Service for computing per-session totals and aggregated metrics."""

    def __init__(
        self,
        storage: SQLiteStorage | None = None,
        detector: DetectorEngine | None = None,
    ):
        self.storage = storage or SQLiteStorage()
        self.detector = detector or DetectorEngine()

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
        successful_events = sum(1 for e in events if event_status(e) == "success")
        failed_events = sum(1 for e in events if event_status(e) != "success")
        slowest = max(events, key=lambda event: event.duration_ms, default=None)
        tool_stats: dict[str, dict[str, int]] = {}
        for event in events:
            if event.type != "tool_call":
                continue
            stats = tool_stats.setdefault(event.name, {"event_count": 0, "failure_count": 0})
            stats["event_count"] += 1
            if event_status(event) != "success":
                stats["failure_count"] += 1

        enriched_events = []
        for event in events:
            item = event.to_dict()
            item["status"] = event_status(event)
            item["dependency"] = {
                "kind": "inferred_sequence",
                "predecessor_seq": event.seq - 1 if event.seq > 1 else None,
                "explicit": False,
            }
            enriched_events.append(item)

        flags = self.detector.evaluate_session(session_id, events, self.storage)

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
            "successful_events": successful_events,
            "failed_events": failed_events,
            "slowest_event": (
                {"seq": slowest.seq, "name": slowest.name, "duration_ms": slowest.duration_ms}
                if slowest
                else None
            ),
            "tool_stats": tool_stats,
            "metrics_available": {
                "tokens": any(
                    event.type == "model_call" and (event.tokens_in > 0 or event.tokens_out > 0)
                    for event in events
                ),
                "cost": any(event.cost_usd != 0 for event in events),
            },
            "flags": [f.to_dict() for f in flags],
            "events": enriched_events,
        }
