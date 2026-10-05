from agent_replay.detector.config import DetectorConfig
from agent_replay.detector.rules import (
    Flag,
    HighCostSessionRule,
    LongDurationSessionRule,
    RepeatedToolCallsRule,
    Rule,
)
from agent_replay.models import Event
from agent_replay.storage import SQLiteStorage


class DetectorEngine:
    """Evaluates sessions against rule-based anomaly detectors."""

    def __init__(
        self,
        config: DetectorConfig | None = None,
        rules: list[Rule] | None = None,
    ):
        self.config = config or DetectorConfig.load()
        self.rules = rules or [
            RepeatedToolCallsRule(),
            HighCostSessionRule(),
            LongDurationSessionRule(),
        ]

    def evaluate_session(
        self,
        session_id: str,
        events: list[Event],
        storage: SQLiteStorage,
    ) -> list[Flag]:
        flags: list[Flag] = []
        for rule in self.rules:
            flags.extend(rule.evaluate(session_id, events, storage, self.config))
        return flags
