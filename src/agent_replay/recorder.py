import uuid
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from agent_replay.context import _CURRENT_SESSION_ID, _CURRENT_STORAGE
from agent_replay.storage import SQLiteStorage


@contextmanager
def record_session(
    session_id: str | None = None,
    storage: SQLiteStorage | None = None,
    metadata: dict[str, Any] | None = None,
) -> Generator[str, None, None]:
    """Context manager to record all tool and model calls within a session."""
    actual_storage = storage or SQLiteStorage()
    actual_session_id = session_id or f"sess_{uuid.uuid4().hex[:12]}"
    actual_storage.create_session(actual_session_id, metadata=metadata)

    token_sid = _CURRENT_SESSION_ID.set(actual_session_id)
    token_stg = _CURRENT_STORAGE.set(actual_storage)
    try:
        yield actual_session_id
    finally:
        _CURRENT_SESSION_ID.reset(token_sid)
        _CURRENT_STORAGE.reset(token_stg)
