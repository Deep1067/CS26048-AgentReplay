import statistics
from dataclasses import asdict, dataclass
from typing import Any, Literal

from agent_replay.detector.config import DetectorConfig
from agent_replay.models import Event
from agent_replay.storage import SQLiteStorage


@dataclass
class Flag:
    rule_name: str
    severity: Literal["info", "warning", "danger"]
    message: str
    culprit_seqs: list[int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Rule:
    """Base class for rule-based detectors."""

    def evaluate(
        self,
        session_id: str,
        events: list[Event],
        storage: SQLiteStorage,
        config: DetectorConfig,
    ) -> list[Flag]:
        raise NotImplementedError


class RepeatedToolCallsRule(Rule):
    """Detects repeated identical tool calls (same tool name and arguments)."""

    def evaluate(
        self,
        session_id: str,
        events: list[Event],
        storage: SQLiteStorage,
        config: DetectorConfig,
    ) -> list[Flag]:
        flags = []
        seen_patterns = set()
        current_pattern = None
        current_events = []

        def evaluate_run() -> None:
            if len(current_events) < config.max_repeated_tool_calls:
                return
            pattern = current_pattern
            if pattern in seen_patterns:
                return
            seen_patterns.add(pattern)
            flags.append(
                Flag(
                    rule_name="repeated_tool_calls",
                    severity="danger",
                    message=(
                        f"Tool '{current_pattern[0]}' was called {len(current_events)} times "
                        "consecutively with identical arguments."
                    ),
                    culprit_seqs=[event.seq for event in current_events],
                )
            )

        for event in events:
            pattern = (event.name, event.args_json) if event.type == "tool_call" else None
            if pattern != current_pattern:
                evaluate_run()
                current_pattern = pattern
                current_events = []
            if pattern is not None:
                current_events.append(event)

        evaluate_run()

        return flags


class HighCostSessionRule(Rule):
    """Detects sessions whose total cost is significantly higher than historical median."""

    def evaluate(
        self,
        session_id: str,
        events: list[Event],
        storage: SQLiteStorage,
        config: DetectorConfig,
    ) -> list[Flag]:
        flags = []
        all_sessions = storage.list_sessions()
        if len(all_sessions) < config.min_sessions_for_cost_median:
            return flags

        costs = [s.total_cost_usd for s in all_sessions if s.total_cost_usd > 0]
        if not costs:
            return flags

        median_cost = statistics.median(costs)
        current_session_cost = sum(e.cost_usd for e in events)

        if median_cost > 0 and current_session_cost >= (
            median_cost * config.cost_multiplier_over_median
        ):
            flags.append(
                Flag(
                    rule_name="high_cost_session",
                    severity="warning",
                    message=(
                        f"Session cost (${current_session_cost:.6f}) is "
                        f"{current_session_cost / median_cost:.1f}x higher than the "
                        f"historical median (${median_cost:.6f})."
                    ),
                    culprit_seqs=[e.seq for e in events if e.cost_usd > 0],
                )
            )

        return flags


class LongDurationSessionRule(Rule):
    """Detects unusually long sessions or runaway call counts."""

    def evaluate(
        self,
        session_id: str,
        events: list[Event],
        storage: SQLiteStorage,
        config: DetectorConfig,
    ) -> list[Flag]:
        flags = []
        total_duration_ms = sum(e.duration_ms for e in events)

        if total_duration_ms > config.max_duration_ms:
            flags.append(
                Flag(
                    rule_name="long_duration_session",
                    severity="warning",
                    message=(
                        f"Session duration ({total_duration_ms:.0f} ms) exceeded "
                        f"threshold of {config.max_duration_ms:.0f} ms."
                    ),
                    culprit_seqs=[],
                )
            )

        if len(events) > config.max_events_per_session:
            flags.append(
                Flag(
                    rule_name="runaway_events",
                    severity="danger",
                    message=(
                        f"Session event count ({len(events)}) exceeded "
                        f"threshold of {config.max_events_per_session} events."
                    ),
                    culprit_seqs=[e.seq for e in events[config.max_events_per_session :]],
                )
            )

        return flags
