"""Deterministic, evidence-backed evaluation for recorded Agent Replay sessions."""

import json
import math
from datetime import UTC, datetime
from typing import Any

from agent_replay.models import Event

EVALUATOR_VERSION = "1.0"
_SUPPORTED_CRITERIA = {
    "expected_output",
    "required_fields",
    "required_phrases",
    "allow_tool_errors",
    "max_latency_ms",
    "max_tokens",
    "max_cost_usd",
}


def validate_criteria(criteria: Any) -> dict[str, Any]:
    if not isinstance(criteria, dict):
        raise ValueError("Evaluation criteria must be a JSON object.")
    unknown = set(criteria) - _SUPPORTED_CRITERIA
    if unknown:
        raise ValueError(f"Unsupported evaluation criteria: {', '.join(sorted(unknown))}.")

    expected = criteria.get("expected_output")
    if expected is not None and not isinstance(expected, dict):
        raise ValueError("expected_output must be a JSON object of expected values.")
    if expected is not None and _contains_empty_object(expected):
        raise ValueError("expected_output must contain at least one expected value.")
    for name in ("required_fields", "required_phrases"):
        values = criteria.get(name, [])
        if not isinstance(values, list) or any(
            not isinstance(item, str) or not item.strip() for item in values
        ):
            raise ValueError(f"{name} must be a list of non-empty strings.")
    allow_tool_errors = criteria.get("allow_tool_errors", False)
    if not isinstance(allow_tool_errors, bool):
        raise ValueError("allow_tool_errors must be a boolean.")

    for name in ("max_latency_ms", "max_tokens", "max_cost_usd"):
        value = criteria.get(name)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"{name} must be a finite non-negative number.")

    return {
        "expected_output": expected,
        "required_fields": criteria.get("required_fields", []),
        "required_phrases": criteria.get("required_phrases", []),
        "allow_tool_errors": allow_tool_errors,
        "max_latency_ms": criteria.get("max_latency_ms"),
        "max_tokens": criteria.get("max_tokens"),
        "max_cost_usd": criteria.get("max_cost_usd"),
    }


def _contains_empty_object(value: Any) -> bool:
    if isinstance(value, dict):
        return not value or any(_contains_empty_object(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_empty_object(item) for item in value)
    return False


def _decode_result(raw: str | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def _evidence(session_id: str, events: list[Event]) -> list[dict[str, Any]]:
    if not events:
        return []
    event = events[-1]
    return [{"session_id": session_id, "seq": event.seq, "type": event.type, "name": event.name}]


def _matches_expected(actual: Any, expected: Any, path: str = "") -> list[dict[str, Any]]:
    differences = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [{"path": path or "$", "expected": expected, "actual": actual}]
        for key, expected_value in expected.items():
            child_path = f"{path}.{key}" if path else key
            if key not in actual:
                differences.append({"path": child_path, "expected": expected_value, "actual": None})
            else:
                differences.extend(_matches_expected(actual[key], expected_value, child_path))
    elif not _json_values_equal(actual, expected):
        differences.append({"path": path or "$", "expected": expected, "actual": actual})
    return differences


def _json_values_equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return actual == expected
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(
                _json_values_equal(actual_value, expected_value)
                for actual_value, expected_value in zip(actual, expected, strict=True)
            )
        )
    return type(actual) is type(expected) and actual == expected


def _get_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _string_values(child)]
    if isinstance(value, list):
        return [item for child in value for item in _string_values(child)]
    return []


def _has_error(event: Event) -> bool:
    if event.error or event.error_type or event.result_json is None:
        return True
    result = _decode_result(event.result_json)
    if not isinstance(result, dict):
        return False
    status = result.get("status")
    return (
        (isinstance(status, str) and status.casefold() in {"error", "failed"})
        or result.get("success") is False
        or bool(result.get("error"))
    )


def _evaluate_session(
    session_id: str, events: list[Event], criteria: dict[str, Any]
) -> dict[str, Any]:
    output_event = events[-1] if events else None
    output = _decode_result(output_event.result_json) if output_event else None
    output_available = output_event is not None and output_event.result_json is not None
    evidence = _evidence(session_id, events)
    results: dict[str, dict[str, Any]] = {}
    active_statuses = []

    expected = criteria["expected_output"]
    if expected is None:
        results["expected_output"] = {
            "status": "not_configured",
            "explanation": "No expected output values were configured.",
            "evidence": evidence,
            "limitations": [],
        }
    elif not output_available:
        results["expected_output"] = {
            "status": "unavailable",
            "explanation": "The trace has no recorded result for its final event.",
            "evidence": evidence,
            "limitations": ["A recorded final output is required."],
        }
        active_statuses.append("unavailable")
    else:
        differences = _matches_expected(output, expected)
        results["expected_output"] = {
            "status": "failed" if differences else "passed",
            "explanation": (
                f"{len(differences)} expected value(s) did not match."
                if differences
                else "All configured expected output values matched."
            ),
            "evidence": evidence,
            "differences": differences,
            "limitations": [],
        }
        active_statuses.append(results["expected_output"]["status"])

    required_fields = criteria["required_fields"]
    required_phrases = criteria["required_phrases"]
    if not required_fields and not required_phrases:
        results["required_information"] = {
            "status": "not_configured",
            "explanation": "No required fields or phrases were configured.",
            "evidence": evidence,
            "limitations": [],
        }
    elif not output_available:
        results["required_information"] = {
            "status": "unavailable",
            "explanation": "Required information cannot be checked without a recorded output.",
            "evidence": evidence,
            "limitations": ["A recorded final output is required."],
        }
        active_statuses.append("unavailable")
    else:
        missing_fields = [
            field for field in required_fields if _get_path(output, field) in (None, "")
        ]
        text = "\n".join(_string_values(output)).casefold()
        missing_phrases = [phrase for phrase in required_phrases if phrase.casefold() not in text]
        status = "failed" if missing_fields or missing_phrases else "passed"
        results["required_information"] = {
            "status": status,
            "explanation": (
                f"Missing fields: {', '.join(missing_fields)}. "
                f"Missing phrases: {', '.join(missing_phrases)}."
                if status == "failed"
                else "All configured fields and phrases were found in the recorded output."
            ).strip(),
            "evidence": evidence,
            "missing_fields": missing_fields,
            "missing_phrases": missing_phrases,
            "limitations": [],
        }
        active_statuses.append(status)

    if not events:
        results["execution_errors"] = {
            "status": "unavailable",
            "explanation": "The session has no recorded events to inspect.",
            "evidence": [],
            "limitations": ["No error or replay-divergence evidence is available."],
        }
        active_statuses.append("unavailable")
    else:
        error_events = [event for event in events if _has_error(event)]
        blocking_errors = [
            event
            for event in error_events
            if not (criteria["allow_tool_errors"] and event.type == "tool_call")
        ]
        status = "passed" if not blocking_errors else "failed"
        results["execution_errors"] = {
            "status": status,
            "explanation": (
                f"Found {len(error_events)} event(s) with recorded errors or failure results."
                if error_events
                else "No recorded event errors or failure results were found."
            )
            + (
                " Errors are allowed by the configured criteria."
                if error_events and not blocking_errors
                else ""
            ),
            "evidence": [
                {
                    "session_id": session_id,
                    "seq": event.seq,
                    "type": event.type,
                    "name": event.name,
                    "error": event.error,
                    "error_type": event.error_type,
                }
                for event in error_events
            ],
            "limitations": [],
        }
        active_statuses.append(status)

    model_events = [event for event in events if event.type == "model_call"]
    token_events = [
        event
        for event in model_events
        if event.tokens_total is not None or event.tokens_in or event.tokens_out
    ]
    tokens_available = bool(model_events) and len(token_events) == len(model_events)
    total_tokens = (
        sum(
            event.tokens_total
            if event.tokens_total is not None
            else event.tokens_in + event.tokens_out
            for event in model_events
        )
        if tokens_available
        else None
    )
    costs_available = bool(model_events) and all(
        event.cost_status != "unavailable" for event in model_events
    )
    total_cost = (
        round(sum(event.cost_usd for event in model_events), 8) if costs_available else None
    )
    cost_status = (
        "estimated"
        if costs_available and any(event.cost_status == "estimated" for event in model_events)
        else "actual"
        if costs_available
        else "unavailable"
    )
    latency = round(sum(event.duration_ms for event in events), 2) if events else None

    thresholds: dict[str, dict[str, Any]] = {}
    efficiency_failures = []
    configured_thresholds = {
        "max_latency_ms": (latency, "latency_ms"),
        "max_tokens": (total_tokens, "total_tokens"),
        "max_cost_usd": (total_cost, "cost_usd"),
    }
    for threshold_name, (observed, metric_name) in configured_thresholds.items():
        limit = criteria[threshold_name]
        if limit is None:
            continue
        if observed is None:
            thresholds[metric_name] = {
                "status": "unavailable",
                "limit": limit,
                "observed": None,
                "explanation": f"{metric_name} is unavailable in the recorded trace.",
            }
        else:
            passed = observed <= limit
            thresholds[metric_name] = {
                "status": "passed" if passed else "failed",
                "limit": limit,
                "observed": observed,
                "explanation": f"Observed {metric_name} {observed}; configured maximum is {limit}.",
            }
            if not passed:
                efficiency_failures.append(metric_name)
    efficiency_status = (
        "failed"
        if efficiency_failures
        else "not_configured"
        if not thresholds
        else "unavailable"
        if all(value["status"] == "unavailable" for value in thresholds.values())
        else "partial"
        if any(value["status"] == "unavailable" for value in thresholds.values())
        else "passed"
    )
    if thresholds:
        active_statuses.append(efficiency_status)

    results["efficiency"] = {
        "status": efficiency_status,
        "explanation": (
            f"Threshold exceeded for: {', '.join(efficiency_failures)}."
            if efficiency_failures
            else "Efficiency values are measurements, not answer-quality scores."
        ),
        "evidence": [
            {"session_id": session_id, "seq": event.seq, "type": event.type, "name": event.name}
            for event in model_events
        ],
        "metrics": {
            "latency_ms": {
                "value": latency,
                "status": "recorded_sum" if latency is not None else "unavailable",
                "label": "sum of recorded event durations; not wall-clock benchmark latency",
            },
            "total_tokens": {
                "value": total_tokens,
                "status": "recorded" if tokens_available else "unavailable",
            },
            "cost_usd": {
                "value": total_cost,
                "status": cost_status,
                "label": "recorded provider-rate estimate, not provider-confirmed billing",
            },
        },
        "thresholds": thresholds,
        "limitations": [
            "Per-event durations may not equal wall-clock latency, especially for parallel calls."
        ],
    }

    quality_configured = expected is not None or bool(required_fields) or bool(required_phrases)
    if "failed" in active_statuses:
        overall = "failed"
    elif "unavailable" in active_statuses or "partial" in active_statuses:
        overall = (
            "partial"
            if any(status in {"passed", "failed"} for status in active_statuses)
            else "unavailable"
        )
    elif not quality_configured:
        overall = "partial"
    elif active_statuses and all(status == "passed" for status in active_statuses):
        overall = "passed"
    else:
        overall = "unavailable"
    status_explanation = {
        "failed": "At least one configured check failed; inspect each evaluator for evidence.",
        "partial": (
            "Some evidence or task-quality criteria are unavailable or not configured; "
            "this is not an overall quality pass."
        ),
        "passed": "All configured checks had evidence and passed.",
        "unavailable": (
            "The trace does not contain enough evidence to evaluate the configured criteria."
        ),
    }[overall]

    evaluator_names = {
        "expected_output": "Expected output values",
        "required_information": "Required information",
        "execution_errors": "Recorded execution errors",
        "efficiency": "Execution efficiency thresholds",
    }
    for evaluator_name, evaluator_result in results.items():
        evaluator_result["name"] = evaluator_names[evaluator_name]
        evaluator_result["version"] = EVALUATOR_VERSION

    return {
        "session_id": session_id,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "status": overall,
        "status_explanation": status_explanation,
        "replay_validity": {
            "status": "unavailable",
            "explanation": "Strict replay was not run as part of this recorded-output evaluation.",
        },
        "recorded_output": {
            "available": output_available,
            "value": output if output_available else None,
            "evidence": evidence,
        },
        "evaluators": results,
    }


def evaluate_session(
    session_id: str, events: list[Event], criteria: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate a trace using only configured criteria and recorded event evidence."""
    return _evaluate_session(session_id, events, validate_criteria(criteria))


def compare_evaluations(baseline: dict[str, Any], fork: dict[str, Any]) -> dict[str, Any]:
    differences = {}
    improvements = []
    regressions = []
    unchanged = []
    for name in ("expected_output", "required_information", "execution_errors", "efficiency"):
        base = baseline["evaluators"][name]
        variant = fork["evaluators"][name]
        pair = {"baseline": base["status"], "fork": variant["status"]}
        differences[name] = pair
        ranking = {"passed": 2, "partial": 1, "unavailable": 0, "not_configured": 0, "failed": 0}
        if ranking[variant["status"]] > ranking[base["status"]]:
            improvements.append(name)
        elif ranking[variant["status"]] < ranking[base["status"]]:
            regressions.append(name)
        else:
            unchanged.append(name)
    return {
        "criteria_statuses": differences,
        "improvements": improvements,
        "regressions": regressions,
        "unchanged": unchanged,
        "note": "Status comparison only; no weighted aggregate score is calculated.",
    }
