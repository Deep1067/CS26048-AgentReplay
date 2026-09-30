import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gemini-1.5-flash")
DB_PATH = os.getenv("DB_PATH", str(PROJECT_ROOT / "agent_replay.db"))
PRICES_PATH = os.getenv("PRICES_PATH", str(PROJECT_ROOT / "prices.json"))
