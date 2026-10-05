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
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0

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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
