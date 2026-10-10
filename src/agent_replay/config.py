import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gemini-flash-lite-latest")
DB_PATH = os.getenv("DB_PATH", str(PROJECT_ROOT / "agent_replay.db"))
PRICES_PATH = os.getenv("PRICES_PATH", str(PROJECT_ROOT / "prices.json"))
USD_TO_INR = float(os.getenv("USD_TO_INR", "83.0"))
DETECTOR_CONFIG_PATH = os.getenv("DETECTOR_CONFIG_PATH", str(PROJECT_ROOT / "detector_config.json"))
DEMO_API_KEY = os.getenv("DEMO_API_KEY", "demo_secret_key_123")
