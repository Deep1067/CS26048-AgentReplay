from dataclasses import dataclass


@dataclass
class DetectorConfig:
    """Configurable thresholds for rule-based detection."""

    max_repeated_tool_calls: int = 3
    cost_multiplier_over_median: float = 3.0
    min_sessions_for_cost_median: int = 3
    max_duration_ms: float = 60000.0
    max_events_per_session: int = 25
