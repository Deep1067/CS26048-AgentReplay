import json
import logging
from pathlib import Path

from agent_replay.config import PRICES_PATH

logger = logging.getLogger(__name__)


class PriceEngine:
    """Calculates token costs for models based on prices.json."""

    def __init__(self, prices_path: str | Path | None = None):
        self.prices_path = Path(prices_path or PRICES_PATH)
        self.prices = self._load_prices()

    def _load_prices(self) -> dict[str, dict[str, float]]:
        if not self.prices_path.exists():
            logger.warning("prices.json not found at %s. Using default pricing.", self.prices_path)
            return {"default": {"input_cost_per_million": 0.10, "output_cost_per_million": 0.40}}
        try:
            with open(self.prices_path, encoding="utf-8") as f:
                data = json.load(f)
                return data.get("models", {})
        except Exception as e:
            logger.error("Failed to load prices from %s: %s", self.prices_path, e)
            return {"default": {"input_cost_per_million": 0.10, "output_cost_per_million": 0.40}}

    def _match_model(self, model_name: str) -> dict[str, float]:
        clean_name = model_name.lower().replace("models/", "").strip()
        if clean_name in self.prices:
            return self.prices[clean_name]

        for key, rates in self.prices.items():
            if key != "default" and (key in clean_name or clean_name in key):
                return rates

        return self.prices.get(
            "default", {"input_cost_per_million": 0.10, "output_cost_per_million": 0.40}
        )

    def calculate_cost(self, model_name: str, tokens_in: int, tokens_out: int) -> float:
        rates = self._match_model(model_name)
        cost_in = (tokens_in * rates.get("input_cost_per_million", 0.0)) / 1_000_000.0
        cost_out = (tokens_out * rates.get("output_cost_per_million", 0.0)) / 1_000_000.0
        return round(cost_in + cost_out, 8)

    def save_prices(self, prices: dict[str, dict[str, float]]) -> None:
        self.prices = prices
        with self.prices_path.open("w", encoding="utf-8") as file:
            json.dump({"models": prices}, file, indent=2)
            file.write("\n")


_GLOBAL_PRICE_ENGINE: PriceEngine | None = None


def get_price_engine() -> PriceEngine:
    global _GLOBAL_PRICE_ENGINE
    if _GLOBAL_PRICE_ENGINE is None:
        _GLOBAL_PRICE_ENGINE = PriceEngine()
    return _GLOBAL_PRICE_ENGINE
