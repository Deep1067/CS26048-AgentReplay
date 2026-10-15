import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

from agent_replay.context import get_current_session_id, get_current_storage
from agent_replay.models import Event
from agent_replay.pricing import get_price_engine
from agent_replay.replay.context import get_current_replay_engine


def _serialize_messages(messages: list[list[BaseMessage]]) -> str:
    serialized = []
    for group in messages:
        group_list = []
        for m in group:
            item = {"role": getattr(m, "type", "unknown"), "content": m.content}
            if hasattr(m, "tool_calls") and m.tool_calls:
                item["tool_calls"] = m.tool_calls
            group_list.append(item)
        serialized.append(group_list)
    return json.dumps(serialized)


def _serialize_generations(generations: list[list[Any]]) -> str:
    res = []
    for gen_list in generations:
        for gen in gen_list:
            item: dict[str, Any] = {"text": gen.text}
            msg = getattr(gen, "message", None)
            if msg:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    item["tool_calls"] = msg.tool_calls
                if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                    item["usage_metadata"] = msg.usage_metadata
            res.append(item)
    return json.dumps(res)


def _usage_count(usage: Any, *keys: str) -> int | None:
    for key in keys:
        value = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


def _extract_tokens(response: LLMResult) -> tuple[int | None, int | None]:
    if response.llm_output and "token_usage" in response.llm_output:
        usage = response.llm_output["token_usage"]
        tokens_in = _usage_count(usage, "prompt_tokens", "input_tokens")
        tokens_out = _usage_count(usage, "completion_tokens", "output_tokens")
        if tokens_in is not None or tokens_out is not None:
            return tokens_in, tokens_out

    for gen_list in response.generations:
        for gen in gen_list:
            msg = getattr(gen, "message", None)
            if msg and hasattr(msg, "usage_metadata") and msg.usage_metadata:
                usage = msg.usage_metadata
                return (
                    _usage_count(usage, "input_tokens", "prompt_token_count"),
                    _usage_count(usage, "output_tokens", "candidates_token_count"),
                )
    return None, None


class ReplayModelCallbackHandler(BaseCallbackHandler):
    """LangChain / LangGraph callback to intercept and record model calls."""

    def __init__(self, model_name: str = "gemini"):
        super().__init__()
        self.default_model_name = model_name
        self._runs: dict[UUID, dict[str, Any]] = {}

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        session_id = get_current_session_id()
        if not session_id:
            return

        model_name = (
            serialized.get("name")
            or kwargs.get("invocation_params", {}).get("model")
            or self.default_model_name
        )
        self._runs[run_id] = {
            "session_id": session_id,
            "model_name": model_name,
            "args_json": _serialize_messages(messages),
            "started_at": datetime.now(UTC).isoformat(),
            "t0": time.perf_counter(),
        }

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        run_data = self._runs.pop(run_id, None)
        storage = get_current_storage()
        if not run_data or not storage:
            return

        duration_ms = round((time.perf_counter() - run_data["t0"]) * 1000, 2)
        tokens_in, tokens_out = _extract_tokens(response)
        result_json = _serialize_generations(response.generations)
        cost = get_price_engine().calculate_known_cost(
            run_data["model_name"], tokens_in, tokens_out
        )

        event = Event(
            session_id=run_data["session_id"],
            seq=0,
            type="model_call",
            name=run_data["model_name"],
            args_json=run_data["args_json"],
            result_json=result_json,
            started_at=run_data["started_at"],
            duration_ms=duration_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost or 0.0,
            provider=run_data.get("provider"),
            model=run_data["model_name"],
            tokens_total=(
                tokens_in + tokens_out if tokens_in is not None and tokens_out is not None else None
            ),
            cost_status="estimated" if cost is not None else "unavailable",
            cost_currency="USD" if cost is not None else None,
        )
        storage.save_event(event)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        run_data = self._runs.pop(run_id, None)
        storage = get_current_storage()
        if not run_data or not storage:
            return

        duration_ms = round((time.perf_counter() - run_data["t0"]) * 1000, 2)
        event = Event(
            session_id=run_data["session_id"],
            seq=0,
            type="model_call",
            name=run_data["model_name"],
            args_json=run_data["args_json"],
            error=str(error),
            error_type=type(error).__name__,
            started_at=run_data["started_at"],
            duration_ms=duration_ms,
        )
        storage.save_event(event)


def record_model_call(model_name: str, fn: Callable, *args: Any, **kwargs: Any) -> Any:
    """Explicit functional wrapper to record direct LLM / model calls or replay them."""
    engine = get_current_replay_engine()
    if engine:
        call_args = list(args) if not kwargs else {"args": args, "kwargs": kwargs}
        return engine.handle_model_call(model_name, call_args, fn, *args, **kwargs)

    session_id = get_current_session_id()
    storage = get_current_storage()
    if not session_id or not storage:
        return fn(*args, **kwargs)

    try:
        args_json = json.dumps({"args": args, "kwargs": kwargs})
    except Exception:
        args_json = json.dumps({"repr": str(args)})

    started_at = datetime.now(UTC).isoformat()
    t0 = time.perf_counter()
    result = None
    error_msg = None
    error_type = None
    tokens_in: int | None = None
    tokens_out: int | None = None

    try:
        result = fn(*args, **kwargs)
        if hasattr(result, "usage_metadata") and result.usage_metadata:
            meta = result.usage_metadata
            tokens_in = _usage_count(meta, "prompt_token_count", "input_tokens")
            tokens_out = _usage_count(meta, "candidates_token_count", "output_tokens")
        return result
    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        raise
    finally:
        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        try:
            res_json = json.dumps(result if error_msg is None else None)
        except Exception:
            res_json = json.dumps(str(result))

        cost = get_price_engine().calculate_known_cost(model_name, tokens_in, tokens_out)
        event = Event(
            session_id=session_id,
            seq=0,
            type="model_call",
            name=model_name,
            args_json=args_json,
            result_json=res_json if error_msg is None else None,
            error=error_msg,
            error_type=error_type,
            started_at=started_at,
            duration_ms=duration_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost or 0.0,
            model=model_name,
            tokens_total=(
                tokens_in + tokens_out if tokens_in is not None and tokens_out is not None else None
            ),
            cost_status="estimated" if cost is not None else "unavailable",
            cost_currency="USD" if cost is not None else None,
        )
        storage.save_event(event)
