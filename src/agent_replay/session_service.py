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


def cost_summary(events: list[Any]) -> tuple[float | None, str]:
    """Aggregate model-call costs only when every relevant cost is available."""
    model_events = [event for event in events if event.type == "model_call"]
    if not model_events or any(event.cost_status == "unavailable" for event in model_events):
        return None, "unavailable"
    status = (
        "estimated" if any(event.cost_status == "estimated" for event in model_events) else "actual"
    )
    return round(sum(event.cost_usd for event in model_events), 8), status


def token_usage_summary(events: list[Any]) -> tuple[int | None, int | None, bool]:
    model_events = [event for event in events if event.type == "model_call"]
    if not model_events or any(
        event.tokens_total is None and not event.tokens_in and not event.tokens_out
        for event in model_events
    ):
        return None, None, False
    return (
        sum(event.tokens_in for event in model_events),
        sum(event.tokens_out for event in model_events),
        True,
    )


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
        model_events = [event for event in events if event.type == "model_call"]
        total_tokens_in, total_tokens_out, usage_available = token_usage_summary(events)
        total_cost_usd, cost_status = cost_summary(events)
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
            "total_cost_usd": total_cost_usd,
            "cost_status": cost_status,
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
                "tokens": usage_available,
                "cost": total_cost_usd is not None,
            },
            "model_usage": [
                {
                    "seq": event.seq,
                    "provider": event.provider or "unknown",
                    "model": event.model or event.name,
                    "tokens_in": (
                        event.tokens_in
                        if event.tokens_in or event.tokens_out or event.tokens_total is not None
                        else None
                    ),
                    "tokens_out": (
                        event.tokens_out
                        if event.tokens_in or event.tokens_out or event.tokens_total is not None
                        else None
                    ),
                    "cost_usd": (event.cost_usd if event.cost_status != "unavailable" else None),
                    "cost_status": event.cost_status,
                }
                for event in model_events
            ],
            "flags": [f.to_dict() for f in flags],
            "events": enriched_events,
        }
