from dataclasses import asdict, dataclass
from typing import Any, Literal


@dataclass
class Event:
    session_id: str
    seq: int
    type: Literal["tool_call", "model_call"]
    name: str
    args_json: str
    result_json: str | None = None
    error: str | None = None
    error_type: str | None = None
    started_at: str = ""
    duration_ms: float = 0.0
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float = 0.0
    provider: str | None = None
    model: str | None = None
    tokens_total: int | None = None
    cached_tokens: int | None = None
    cost_status: Literal["actual", "estimated", "unavailable"] = "unavailable"
    cost_currency: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SessionSummary:
    session_id: str
    started_at: str
    event_count: int = 0
    total_cost_usd: float = 0.0
    total_duration_ms: float = 0.0
    has_errors: bool = False
    model_total_cost_usd: float | None = None
    cost_status: Literal["actual", "estimated", "unavailable"] = "unavailable"
    model_call_count: int = 0
    missing_model_usage_count: int = 0
    successful_events: int = 0
    failed_events: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "event_count": self.event_count,
            "total_cost_usd": self.total_cost_usd,
            "total_duration_ms": self.total_duration_ms,
            "has_errors": self.has_errors,
        }
