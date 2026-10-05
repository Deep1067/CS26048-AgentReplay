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


def _extract_tokens(response: LLMResult) -> tuple[int, int]:
    tokens_in = 0
    tokens_out = 0

    if response.llm_output and "token_usage" in response.llm_output:
        usage = response.llm_output["token_usage"]
        tokens_in = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        tokens_out = usage.get("completion_tokens") or usage.get("output_tokens") or 0

    if tokens_in == 0 and tokens_out == 0:
        for gen_list in response.generations:
            for gen in gen_list:
                msg = getattr(gen, "message", None)
                if msg and hasattr(msg, "usage_metadata") and msg.usage_metadata:
                    meta = msg.usage_metadata
                    tokens_in = meta.get("input_tokens") or meta.get("prompt_token_count") or 0
                    tokens_out = (
                        meta.get("output_tokens") or meta.get("candidates_token_count") or 0
                    )
                    break
    return int(tokens_in), int(tokens_out)


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
        cost_usd = get_price_engine().calculate_cost(run_data["model_name"], tokens_in, tokens_out)

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
            cost_usd=cost_usd,
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
    tokens_in = 0
    tokens_out = 0

    try:
        result = fn(*args, **kwargs)
        if hasattr(result, "usage_metadata") and result.usage_metadata:
            meta = result.usage_metadata
            tokens_in = getattr(meta, "prompt_token_count", 0) or 0
            tokens_out = getattr(meta, "candidates_token_count", 0) or 0
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

        cost_usd = get_price_engine().calculate_cost(model_name, tokens_in, tokens_out)
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
            cost_usd=cost_usd,
        )
        storage.save_event(event)
