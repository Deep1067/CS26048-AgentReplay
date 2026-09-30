from contextvars import ContextVar
from typing import Any

_CURRENT_REPLAY_ENGINE: ContextVar[Any | None] = ContextVar("current_replay_engine", default=None)


def get_current_replay_engine() -> Any | None:
    return _CURRENT_REPLAY_ENGINE.get()


def set_current_replay_engine(engine: Any | None):
    return _CURRENT_REPLAY_ENGINE.set(engine)
