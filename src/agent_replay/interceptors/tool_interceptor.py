import functools
import inspect
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from agent_replay.context import get_current_session_id, get_current_storage
from agent_replay.models import Event
from agent_replay.replay.context import get_current_replay_engine


def _safe_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj)
    except (TypeError, ValueError):
        try:
            return json.dumps(str(obj))
        except Exception:
            return '"{}"'


def record_tool(tool_name: str | None = None) -> Callable:
    """Decorator to intercept and record tool calls within an active session,

    or replay recorded tool responses when a ReplayEngine is active.
    """

    def decorator(fn: Callable) -> Callable:
        name = tool_name or getattr(fn, "name", None) or fn.__name__

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                engine = get_current_replay_engine()
                if engine:
                    call_args = {"args": args, "kwargs": kwargs} if kwargs else list(args)
                    return engine.handle_tool_call(name, call_args, fn, *args, **kwargs)

                session_id = get_current_session_id()
                storage = get_current_storage()
                if not session_id or not storage:
                    return await fn(*args, **kwargs)

                call_args = {"args": args, "kwargs": kwargs} if kwargs else list(args)
                args_json = _safe_json_dumps(call_args)
                start_iso = datetime.now(UTC).isoformat()
                t0 = time.perf_counter()

                result = None
                error_msg = None
                error_type = None
                try:
                    result = await fn(*args, **kwargs)
                    return result
                except Exception as e:
                    error_msg = str(e)
                    error_type = type(e).__name__
                    raise
                finally:
                    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
                    res_json = _safe_json_dumps(result) if error_msg is None else None
                    event = Event(
                        session_id=session_id,
                        seq=0,
                        type="tool_call",
                        name=name,
                        args_json=args_json,
                        result_json=res_json,
                        error=error_msg,
                        error_type=error_type,
                        started_at=start_iso,
                        duration_ms=duration_ms,
                    )
                    storage.save_event(event)

            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            engine = get_current_replay_engine()
            if engine:
                call_args = {"args": args, "kwargs": kwargs} if kwargs else list(args)
                return engine.handle_tool_call(name, call_args, fn, *args, **kwargs)

            session_id = get_current_session_id()
            storage = get_current_storage()
            if not session_id or not storage:
                return fn(*args, **kwargs)

            call_args = {"args": args, "kwargs": kwargs} if kwargs else list(args)
            args_json = _safe_json_dumps(call_args)
            start_iso = datetime.now(UTC).isoformat()
            t0 = time.perf_counter()

            result = None
            error_msg = None
            error_type = None
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as e:
                error_msg = str(e)
                error_type = type(e).__name__
                raise
            finally:
                duration_ms = round((time.perf_counter() - t0) * 1000, 2)
                res_json = _safe_json_dumps(result) if error_msg is None else None
                event = Event(
                    session_id=session_id,
                    seq=0,
                    type="tool_call",
                    name=name,
                    args_json=args_json,
                    result_json=res_json,
                    error=error_msg,
                    error_type=error_type,
                    started_at=start_iso,
                    duration_ms=duration_ms,
                )
                storage.save_event(event)

        return sync_wrapper

    return decorator
