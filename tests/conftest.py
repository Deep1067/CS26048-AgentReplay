import os
import shutil
import tempfile
import uuid
from pathlib import Path

_test_id = uuid.uuid4().hex
_temporary_settings = [
    Path(tempfile.gettempdir()) / f"agent-replay-test-prices-{_test_id}.json",
    Path(tempfile.gettempdir()) / f"agent-replay-test-detector-{_test_id}.json",
]
_project_root = Path(__file__).resolve().parents[1]
shutil.copyfile(_project_root / "prices.json", _temporary_settings[0])
_detector_config = _project_root / "detector_config.json"
if _detector_config.exists():
    shutil.copyfile(_detector_config, _temporary_settings[1])

os.environ["PYTHON_DOTENV_DISABLED"] = "true"
os.environ["DB_PATH"] = ":memory:"
os.environ["PRICES_PATH"] = str(_temporary_settings[0])
os.environ["DETECTOR_CONFIG_PATH"] = str(_temporary_settings[1])

for _name in (
    "TURSO_DATABASE_URL",
    "TURSO_AUTH_TOKEN",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "LIVE_RUN_AUTH_TOKEN",
    "CONFIG_MUTATIONS_AUTH_TOKEN",
    "APP_AUTH_USERNAME",
    "APP_AUTH_PASSWORD",
    "ALLOW_LOOPBACK_PRIVILEGED_ACTIONS",
    "LIVE_RUN_ENABLED",
    "CONFIG_MUTATIONS_ENABLED",
    "VERCEL",
):
    os.environ.pop(_name, None)


def pytest_sessionfinish(session, exitstatus):
    del session, exitstatus
    for path in _temporary_settings:
        path.unlink(missing_ok=True)
