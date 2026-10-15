import json
import math
import uuid
from typing import Any

from agent_replay.detector.engine import DetectorEngine
from agent_replay.recorder import record_session
from agent_replay.replay.engine import replay_session
from agent_replay.storage import SQLiteStorage
from scenarios.scenario_2_malformed_response import agent_workflow

DEFAULT_SUBSTITUTE_RESULT = {"status": "ok", "balance": 500.0}


def _outcome(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _recorded_token_counts(event: Any) -> tuple[int | None, int | None]:
    if event.tokens_total is not None:
        return event.tokens_in, event.tokens_out
    return (
        event.tokens_in if event.tokens_in else None,
        event.tokens_out if event.tokens_out else None,
    )


def _event_payload(event: Any) -> dict[str, Any]:
    return event.to_dict()


def _decode_json(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _is_supported_baseline(events: list[Any]) -> bool:
    if not events or events[0].seq != 1:
        return False
    first = events[0]
    if first.type != "tool_call" or first.name != "query_user_account":
        return False
    if _decode_json(first.args_json) != {"args": [], "kwargs": {"user_id": 101}}:
        return False
    return all(
        event.seq == index
        and event.type == "tool_call"
        and event.name in {"query_user_account", "calculate_credit"}
        for index, event in enumerate(events, start=1)
    )


def list_supported_baselines(storage: SQLiteStorage) -> list[dict[str, Any]]:
    baselines = []
    for summary in storage.list_sessions():
        events = storage.get_events(summary.session_id)
        if not _is_supported_baseline(events):
            continue
        baselines.append(
            {
                "session_id": summary.session_id,
                "started_at": summary.started_at,
                "event_count": len(events),
                "substitutable_events": [
                    {
                        "seq": events[0].seq,
                        "type": events[0].type,
                        "name": events[0].name,
                        "args": _decode_json(events[0].args_json),
                        "recorded_result": _decode_json(events[0].result_json),
                        "error": events[0].error,
                    }
                ],
            }
        )
    return baselines


def validate_substitute_result(result: Any) -> None:
    if not isinstance(result, dict):
        raise ValueError("The substituted tool response must be a JSON object.")
    status = result.get("status")
    if status == "error":
        if "message" in result and not isinstance(result["message"], str):
            raise ValueError("An error response message must be a string.")
        return
    balance = result.get("balance")
    if (
        status != "ok"
        or isinstance(balance, bool)
        or not isinstance(balance, (int, float))
        or not math.isfinite(balance)
    ):
        raise ValueError(
            'Use a supported response: {"status":"ok","balance": number} '
            'or {"status":"error","message":"reason"}.'
        )


def _event_diff(baseline: list[Any], forked: list[Any]) -> dict[str, list[dict[str, Any]]]:
    baseline_by_seq = {event.seq: event for event in baseline}
    forked_by_seq = {event.seq: event for event in forked}
    changed = []

    for seq in sorted(set(baseline_by_seq) & set(forked_by_seq)):
        original = baseline_by_seq[seq]
        fork = forked_by_seq[seq]
        if (
            original.type,
            original.name,
            original.args_json,
            original.result_json,
            original.error,
        ) != (
            fork.type,
            fork.name,
            fork.args_json,
            fork.result_json,
            fork.error,
        ):
            changed.append(
                {
                    "seq": seq,
                    "original": _event_payload(original),
                    "forked": _event_payload(fork),
                }
            )

    added = [
        _event_payload(forked_by_seq[seq])
        for seq in sorted(set(forked_by_seq) - set(baseline_by_seq))
    ]
    removed = [
        _event_payload(baseline_by_seq[seq])
        for seq in sorted(set(baseline_by_seq) - set(forked_by_seq))
    ]
    return {"changed": changed, "added": added, "removed": removed}


def _metrics(baseline: list[Any], forked: list[Any]) -> dict[str, Any]:
    baseline_duration = sum(event.duration_ms for event in baseline)
    forked_duration = sum(event.duration_ms for event in forked)
    baseline_models = [event for event in baseline if event.type == "model_call"]
    forked_models = [event for event in forked if event.type == "model_call"]
    baseline_usage = [_recorded_token_counts(event) for event in baseline_models]
    forked_usage = [_recorded_token_counts(event) for event in forked_models]
    usage_available = bool(baseline_models and forked_models) and all(
        input_count is not None and output_count is not None
        for input_count, output_count in baseline_usage + forked_usage
    )
    cost_available = bool(baseline_models or forked_models) and all(
        event.cost_status != "unavailable" for event in baseline_models + forked_models
    )
    cost_status = (
        "estimated"
        if any(event.cost_status == "estimated" for event in baseline_models + forked_models)
        else "actual"
    )
    return {
        "event_count_delta": len(forked) - len(baseline),
        "duration_ms": {
            "baseline": round(baseline_duration, 2),
            "forked": round(forked_duration, 2),
            "delta": round(forked_duration - baseline_duration, 2),
            "available": True,
            "label": (
                "recorded per-event durations; substitution is zero-duration and values are "
                "not a benchmark"
            ),
        },
        "tokens": {
            "available": usage_available,
            "baseline_in": sum(input_count for input_count, _ in baseline_usage)
            if usage_available
            else None,
            "baseline_out": sum(output_count for _, output_count in baseline_usage)
            if usage_available
            else None,
            "forked_in": sum(input_count for input_count, _ in forked_usage)
            if usage_available
            else None,
            "forked_out": sum(output_count for _, output_count in forked_usage)
            if usage_available
            else None,
        },
        "cost_usd_estimate": {
            "available": cost_available,
            "status": cost_status if cost_available else "unavailable",
            "baseline": round(sum(event.cost_usd for event in baseline_models), 8)
            if cost_available
            else None,
            "forked": round(sum(event.cost_usd for event in forked_models), 8)
            if cost_available
            else None,
            "delta": round(
                sum(event.cost_usd for event in forked_models)
                - sum(event.cost_usd for event in baseline_models),
                8,
            )
            if cost_available
            else None,
            "label": "provider-rate estimate from recorded model usage",
        },
    }


def run_counterfactual_experiment(
    storage: SQLiteStorage,
    baseline_session_id: str | None = None,
    substitute_seq: int = 1,
    substitute_result: Any = None,
) -> dict[str, Any]:
    experiment_id = f"experiment_{uuid.uuid4().hex[:12]}"
    created_baseline = baseline_session_id is None
    if created_baseline:
        baseline_session_id = f"{experiment_id}_baseline"
    forked_session_id = f"{experiment_id}_fork"
    if substitute_result is None:
        substitute_result = DEFAULT_SUBSTITUTE_RESULT
    if substitute_seq != 1:
        raise ValueError(
            "This guided workflow supports substituting event #1 (query_user_account) only."
        )
    validate_substitute_result(substitute_result)

    if created_baseline:
        with record_session(
            baseline_session_id,
            storage=storage,
            metadata={"experiment_id": experiment_id, "role": "baseline"},
        ):
            baseline_outcome = agent_workflow()
    else:
        baseline_events = storage.get_events(baseline_session_id)
        if not _is_supported_baseline(baseline_events):
            raise ValueError(
                "This session is not eligible. Guided experiments currently support "
                "the recorded scenario-2 account workflow."
            )
        if not any(event.seq == substitute_seq for event in baseline_events):
            raise ValueError("The selected substitution event is not in the baseline session.")

    with replay_session(baseline_session_id, storage=storage, mode="strict"):
        strict_outcome = agent_workflow()
    if not created_baseline:
        baseline_outcome = strict_outcome

    with replay_session(
        baseline_session_id,
        storage=storage,
        mode="forked",
        substitute_seq=substitute_seq,
        substitute_result=substitute_result,
        forked_session_id=forked_session_id,
    ):
        forked_outcome = agent_workflow()

    baseline_events = storage.get_events(baseline_session_id)
    forked_events = storage.get_events(forked_session_id)
    baseline_details = DetectorEngine().evaluate_session(
        baseline_session_id, baseline_events, storage
    )
    forked_details = DetectorEngine().evaluate_session(forked_session_id, forked_events, storage)
    storage.set_setting(
        f"experiment:{experiment_id}",
        {
            "experiment_id": experiment_id,
            "baseline_session_id": baseline_session_id,
            "forked_session_id": forked_session_id,
        },
    )

    result = {
        "experiment_id": experiment_id,
        "mode": "forked_runtime_execution",
        "evidence": {
            "baseline": (
                "recorded workflow run"
                if created_baseline
                else "workflow reconstructed by strict replay"
            ),
            "strict_replay": (
                "reconstructed from recorded tool responses; no downstream tools executed"
            ),
            "forked": "supported workflow executed after the selected tool-response substitution",
        },
        "trace_validation_note": (
            "POST /api/replay validates a trace; this result ran the supported workflow."
        ),
        "parent_session_id": baseline_session_id,
        "fork_session_id": forked_session_id,
        "substitution": {
            "seq": substitute_seq,
            "result": substitute_result,
        },
        "outcomes": {
            "baseline": _outcome(baseline_outcome),
            "strict_replay": _outcome(strict_outcome),
            "forked": _outcome(forked_outcome),
        },
        "events": {
            "baseline": [_event_payload(event) for event in baseline_events],
            "forked": [_event_payload(event) for event in forked_events],
            **_event_diff(baseline_events, forked_events),
        },
        "metrics": _metrics(baseline_events, forked_events),
        "flags": {
            "baseline": [flag.to_dict() for flag in baseline_details],
            "forked": [flag.to_dict() for flag in forked_details],
        },
        "fork_metadata": storage.get_session_metadata(forked_session_id),
    }
    storage.create_experiment(
        experiment_id=experiment_id,
        baseline_session_id=baseline_session_id,
        fork_session_id=forked_session_id,
        result=result,
    )
    return result
