from contextvars import ContextVar
from typing import Any

_CURRENT_SESSION_ID: ContextVar[str | None] = ContextVar("current_session_id", default=None)
_CURRENT_STORAGE: ContextVar[Any | None] = ContextVar("current_storage", default=None)


def get_current_session_id() -> str | None:
    return _CURRENT_SESSION_ID.get()


def set_current_session_id(session_id: str | None):
    return _CURRENT_SESSION_ID.set(session_id)


def get_current_storage() -> Any | None:
    return _CURRENT_STORAGE.get()


def set_current_storage(storage: Any | None):
    return _CURRENT_STORAGE.set(storage)
