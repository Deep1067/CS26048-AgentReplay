import json
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Literal

from agent_replay.models import Event
from agent_replay.pricing import get_price_engine
from agent_replay.replay.context import _CURRENT_REPLAY_ENGINE
from agent_replay.replay.exceptions import ReplayCompletedError, ReplayDivergenceError
from agent_replay.storage import SQLiteStorage


def _normalize_payload(payload: Any) -> Any:
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except Exception:
            return payload
    return payload


def _raise_recorded_error(error: str, error_type: str | None) -> None:
    recorded_type = error_type or "Exception"
    raise Exception(f"{recorded_type}: {error}") from None


def _usage_count(usage: Any, *keys: str) -> int | None:
    for key in keys:
        value = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


class ReplayEngine:
    """Deterministic replay engine supporting STRICT and FORKED modes."""

    def __init__(
        self,
        session_id: str,
        storage: SQLiteStorage,
        mode: Literal["strict", "forked"] = "strict",
        substitute_seq: int | None = None,
        substitute_result: Any | None = None,
        forked_session_id: str | None = None,
    ):
        self.session_id = session_id
        self.storage = storage
        self.mode = mode
        self.substitute_seq = substitute_seq
        self.substitute_result = substitute_result
        self.forked_session_id = forked_session_id

        self.events = self.storage.get_events(session_id)
        self.cursor = 0
        self.is_forked_live = False

        if not self.events:
            raise ValueError(f"No recorded events found for session '{session_id}'.")

        if self.mode == "forked" and self.forked_session_id:
            self.storage.create_session(
                self.forked_session_id,
                metadata={"forked_from": session_id, "forked_at_seq": substitute_seq},
            )

    def handle_tool_call(
        self,
        tool_name: str,
        args: Any,
        live_fn: Callable | None = None,
        *fn_args: Any,
        **fn_kwargs: Any,
    ) -> Any:
        # If in forked mode and downstream of substitution, execute live
        if self.mode == "forked" and self.is_forked_live:
            if not live_fn:
                raise RuntimeError(f"Cannot execute live tool '{tool_name}' without live function.")
            t0 = time.perf_counter()
            start_iso = datetime.now(UTC).isoformat()
            res = live_fn(*fn_args, **fn_kwargs)
            duration_ms = round((time.perf_counter() - t0) * 1000, 2)
            if self.forked_session_id:
                ev = Event(
                    session_id=self.forked_session_id,
                    seq=0,
                    type="tool_call",
                    name=tool_name,
                    args_json=json.dumps(args),
                    result_json=json.dumps(res),
                    started_at=start_iso,
                    duration_ms=duration_ms,
                )
                self.storage.save_event(ev)
            return res

        if self.cursor >= len(self.events):
            raise ReplayCompletedError("tool_call", tool_name)

        expected = self.events[self.cursor]

        if expected.type != "tool_call":
            raise ReplayDivergenceError(
                seq=expected.seq,
                expected_type=expected.type,
                expected_name=expected.name,
                expected_args=expected.args_json,
                actual_type="tool_call",
                actual_name=tool_name,
                actual_args=args,
            )

        if expected.name != tool_name:
            raise ReplayDivergenceError(
                seq=expected.seq,
                expected_type=expected.type,
                expected_name=expected.name,
                expected_args=expected.args_json,
                actual_type="tool_call",
                actual_name=tool_name,
                actual_args=args,
            )

        norm_expected_args = _normalize_payload(expected.args_json)
        # Normalize actual args through JSON round-trip to ensure consistent types (list vs tuple)
        try:
            norm_actual_args = json.loads(json.dumps(args, default=list))
        except Exception:
            norm_actual_args = args
        if norm_expected_args != norm_actual_args:
            raise ReplayDivergenceError(
                seq=expected.seq,
                expected_type=expected.type,
                expected_name=expected.name,
                expected_args=expected.args_json,
                actual_type="tool_call",
                actual_name=tool_name,
                actual_args=args,
            )

        # Match confirmed!
        self.cursor += 1

        # Check if substitution applies here
        if self.mode == "forked" and expected.seq == self.substitute_seq:
            self.is_forked_live = True
            result = self.substitute_result
            if self.forked_session_id:
                ev = Event(
                    session_id=self.forked_session_id,
                    seq=expected.seq,
                    type="tool_call",
                    name=tool_name,
                    args_json=expected.args_json,
                    result_json=json.dumps(result),
                    started_at=datetime.now(UTC).isoformat(),
                    duration_ms=0.0,
                )
                self.storage.save_event(ev)
            return result

        # Replay recorded result
        if self.forked_session_id:
            self.storage.save_event(expected)

        if expected.error is not None:
            _raise_recorded_error(expected.error, expected.error_type)

        if expected.result_json is not None:
            try:
                return json.loads(expected.result_json)
            except Exception:
                return expected.result_json
        return None

    def handle_model_call(
        self,
        model_name: str,
        messages_or_prompt: Any,
        live_fn: Callable | None = None,
        *fn_args: Any,
        **fn_kwargs: Any,
    ) -> Any:
        if self.mode == "forked" and self.is_forked_live:
            if not live_fn:
                raise RuntimeError(
                    f"Cannot execute live model call '{model_name}' without live function."
                )
            t0 = time.perf_counter()
            start_iso = datetime.now(UTC).isoformat()
            res = live_fn(*fn_args, **fn_kwargs)
            duration_ms = round((time.perf_counter() - t0) * 1000, 2)

            meta = getattr(res, "usage_metadata", None)
            tokens_in = _usage_count(meta, "input_tokens", "prompt_token_count") if meta else None
            tokens_out = (
                _usage_count(meta, "output_tokens", "candidates_token_count") if meta else None
            )
            tokens_total = (
                tokens_in + tokens_out if tokens_in is not None and tokens_out is not None else None
            )
            cost_usd = get_price_engine().calculate_known_cost(model_name, tokens_in, tokens_out)
            if self.forked_session_id:
                ev = Event(
                    session_id=self.forked_session_id,
                    seq=0,
                    type="model_call",
                    name=model_name,
                    args_json=json.dumps(_normalize_payload(messages_or_prompt)),
                    result_json=json.dumps(getattr(res, "content", str(res))),
                    started_at=start_iso,
                    duration_ms=duration_ms,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    tokens_total=tokens_total,
                    cost_usd=cost_usd or 0.0,
                    cost_status="estimated" if cost_usd is not None else "unavailable",
                )
                self.storage.save_event(ev)
            return res

        if self.cursor >= len(self.events):
            raise ReplayCompletedError("model_call", model_name)

        expected = self.events[self.cursor]

        if expected.type != "model_call":
            raise ReplayDivergenceError(
                seq=expected.seq,
                expected_type=expected.type,
                expected_name=expected.name,
                expected_args=expected.args_json,
                actual_type="model_call",
                actual_name=model_name,
                actual_args=messages_or_prompt,
            )

        if expected.name != model_name:
            raise ReplayDivergenceError(
                seq=expected.seq,
                expected_type=expected.type,
                expected_name=expected.name,
                expected_args=expected.args_json,
                actual_type="model_call",
                actual_name=model_name,
                actual_args=messages_or_prompt,
            )

        self.cursor += 1

        if self.forked_session_id:
            self.storage.save_event(expected)

        if expected.error is not None:
            _raise_recorded_error(expected.error, expected.error_type)

        try:
            return json.loads(expected.result_json) if expected.result_json else None
        except Exception:
            return expected.result_json


@contextmanager
def replay_session(
    session_id: str,
    storage: SQLiteStorage,
    mode: Literal["strict", "forked"] = "strict",
    substitute_seq: int | None = None,
    substitute_result: Any | None = None,
    forked_session_id: str | None = None,
) -> Generator[ReplayEngine, None, None]:
    engine = ReplayEngine(
        session_id=session_id,
        storage=storage,
        mode=mode,
        substitute_seq=substitute_seq,
        substitute_result=substitute_result,
        forked_session_id=forked_session_id,
    )
    token = _CURRENT_REPLAY_ENGINE.set(engine)
    try:
        yield engine
    finally:
        _CURRENT_REPLAY_ENGINE.reset(token)
