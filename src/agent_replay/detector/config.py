import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from agent_replay.config import DETECTOR_CONFIG_PATH


@dataclass
class DetectorConfig:
    """Configurable thresholds for rule-based detection."""

    max_repeated_tool_calls: int = 3
    cost_multiplier_over_median: float = 3.0
    min_sessions_for_cost_median: int = 3
    max_duration_ms: float = 60000.0
    max_events_per_session: int = 25

    @classmethod
    def load(cls, path: str | Path | None = None) -> "DetectorConfig":
        config = cls()
        config_path = Path(path or DETECTOR_CONFIG_PATH)
        if not config_path.exists():
            return config
        try:
            with config_path.open(encoding="utf-8") as file:
                values = json.load(file)
            valid_names = {field.name for field in fields(config)}
            for name, value in values.items():
                if name in valid_names:
                    setattr(config, name, value)
        except (OSError, TypeError, ValueError):
            return config
        return config

    def save(self, path: str | Path | None = None) -> None:
        config_path = Path(path or DETECTOR_CONFIG_PATH)
        with config_path.open("w", encoding="utf-8") as file:
            json.dump(asdict(self), file, indent=2)
            file.write("\n")
