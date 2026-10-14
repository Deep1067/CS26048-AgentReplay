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
    "assertions",
}
_ASSERTION_SOURCES = {"output", "event_result", "event_error", "metric"}
_ASSERTION_OPERATORS = {
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "between",
    "contains",
    "not_contains",
    "length_eq",
    "length_gt",
    "length_lt",
    "includes",
    "not_includes",
    "exists",
    "not_exists",
}
_METRIC_PATHS = {"latency_ms", "total_tokens", "cost_usd"}


def _validate_assertion(assertion: Any, index: int) -> dict[str, Any]:
    if not isinstance(assertion, dict):
        raise ValueError(f"assertions[{index}] must be a JSON object.")
    allowed = {
        "id",
        "name",
        "source",
        "path",
        "operator",
        "expected",
        "event_seq",
        "event_type",
        "event_name",
    }
    unknown = set(assertion) - allowed
    if unknown:
        raise ValueError(
            f"assertions[{index}] has unsupported fields: {', '.join(sorted(unknown))}."
        )
    name = assertion.get("name")
    source = assertion.get("source")
    operator = assertion.get("operator")
    path = assertion.get("path")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"assertions[{index}].name must be a non-empty string.")
    if not isinstance(source, str) or source not in _ASSERTION_SOURCES:
        raise ValueError(f"assertions[{index}].source must be one of {sorted(_ASSERTION_SOURCES)}.")
    if not isinstance(operator, str) or operator not in _ASSERTION_OPERATORS:
        raise ValueError(
            f"assertions[{index}].operator must be one of {sorted(_ASSERTION_OPERATORS)}."
        )
    if source == "event_error" and path is not None:
        raise ValueError(f"assertions[{index}] event_error source does not use a path.")
    if source not in {"event_result", "event_error"} and any(
        assertion.get(key) is not None for key in ("event_seq", "event_type", "event_name")
    ):
        raise ValueError(
            f"assertions[{index}] event selectors are only supported for event sources."
        )
    if source != "event_error" and (not isinstance(path, str) or not path.strip()):
        raise ValueError(f"assertions[{index}].path must be a non-empty string.")
    if source == "metric" and path not in _METRIC_PATHS:
        raise ValueError(
            f"assertions[{index}].path for metric must be one of {sorted(_METRIC_PATHS)}."
        )
    if source in {"event_result", "event_error"} and "event_seq" not in assertion:
        raise ValueError(f"assertions[{index}] {source} currently requires event_seq.")
    event_seq = assertion.get("event_seq")
    if event_seq is not None and (
        isinstance(event_seq, bool) or not isinstance(event_seq, int) or event_seq < 1
    ):
        raise ValueError(f"assertions[{index}].event_seq must be a positive integer.")
    for field in ("event_type", "event_name", "id"):
        value = assertion.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"assertions[{index}].{field} must be a non-empty string.")
    expected = assertion.get("expected")
    if operator not in {"exists", "not_exists"} and "expected" not in assertion:
        raise ValueError(f"assertions[{index}].expected is required for operator '{operator}'.")
    if operator == "between" and (
        not isinstance(expected, list)
        or len(expected) != 2
        or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in expected)
        or any(not math.isfinite(item) for item in expected)
        or expected[0] > expected[1]
    ):
        raise ValueError(f"assertions[{index}].expected for between must be [minimum, maximum].")
    if operator in {"gt", "gte", "lt", "lte"} and (
        isinstance(expected, bool)
        or not isinstance(expected, (int, float))
        or not math.isfinite(expected)
    ):
        raise ValueError(f"assertions[{index}].expected for {operator} must be a number.")
    if operator in {"length_eq", "length_gt", "length_lt"} and (
        isinstance(expected, bool) or not isinstance(expected, int) or expected < 0
    ):
        raise ValueError(
            f"assertions[{index}].expected for {operator} must be a non-negative integer."
        )
    if source == "event_error" and operator not in {
        "eq",
        "ne",
        "contains",
        "not_contains",
        "exists",
        "not_exists",
    }:
        raise ValueError(f"assertions[{index}] uses an unsupported operator for event_error.")
    if operator in {"contains", "not_contains"} and not isinstance(expected, str):
        raise ValueError(f"assertions[{index}].expected for {operator} must be a string.")
    return {
        "id": assertion.get("id") or f"assertion-{index + 1}",
        "name": name.strip(),
        "source": source,
        "path": path,
        "operator": operator,
        **({"expected": expected} if "expected" in assertion else {}),
        "event_seq": event_seq,
        "event_type": assertion.get("event_type"),
        "event_name": assertion.get("event_name"),
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
    assertions = criteria.get("assertions", [])
    if not isinstance(assertions, list):
        raise ValueError("assertions must be a list.")
    normalized_assertions = [
        _validate_assertion(assertion, index) for index, assertion in enumerate(assertions)
    ]
    assertion_ids = [assertion["id"] for assertion in normalized_assertions]
    if len(set(assertion_ids)) != len(assertion_ids):
        raise ValueError("Assertion ids must be unique within a suite.")

    return {
        "expected_output": expected,
        "required_fields": criteria.get("required_fields", []),
        "required_phrases": criteria.get("required_phrases", []),
        "allow_tool_errors": allow_tool_errors,
        "max_latency_ms": criteria.get("max_latency_ms"),
        "max_tokens": criteria.get("max_tokens"),
        "max_cost_usd": criteria.get("max_cost_usd"),
        "assertions": normalized_assertions,
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
    found, current = _lookup_path(value, path)
    return current if found else None


def _lookup_path(value: Any, path: str) -> tuple[bool, Any]:
    if path in {"", "$"}:
        return True, value
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


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


def _assertion_match(actual: Any, expected: Any, operator: str) -> tuple[bool | None, str]:
    if operator in {"exists", "not_exists"}:
        present = actual is not _MISSING
        return (
            present if operator == "exists" else not present,
            "The selected value exists." if present else "The selected value is missing.",
        )
    if actual is _MISSING:
        return None, "The selected value is unavailable because its path is missing."
    if operator in {"eq", "exact"}:
        compatible = type(actual) is type(expected) or (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and isinstance(expected, (int, float))
            and not isinstance(expected, bool)
        )
        if not compatible:
            return False, "The recorded value has an incompatible JSON type."
        matched = _json_values_equal(actual, expected)
        return matched, "The value exactly matches." if matched else "The value does not match."
    if operator == "ne":
        compatible = type(actual) is type(expected) or (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and isinstance(expected, (int, float))
            and not isinstance(expected, bool)
        )
        if not compatible:
            return False, "The recorded value has an incompatible JSON type."
        matched = not _json_values_equal(actual, expected)
        return (
            matched,
            "The value differs as expected."
            if matched
            else "The value equals the forbidden value.",
        )
    if operator in {"gt", "gte", "lt", "lte", "between"}:
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return False, "The recorded value is not numeric."
        if operator == "between":
            matched = expected[0] <= actual <= expected[1]
            return matched, (
                f"The number is within [{expected[0]}, {expected[1]}]."
                if matched
                else f"The number is outside [{expected[0]}, {expected[1]}]."
            )
        matched = {
            "gt": actual > expected,
            "gte": actual >= expected,
            "lt": actual < expected,
            "lte": actual <= expected,
        }[operator]
        return matched, (
            f"The number satisfies {operator} {expected}."
            if matched
            else f"The number does not satisfy {operator} {expected}."
        )
    if operator in {"contains", "not_contains"}:
        if not isinstance(actual, str):
            return False, "The recorded value is not a string."
        matched = expected in actual
        if operator == "not_contains":
            matched = not matched
        return matched, (
            "The string satisfies the configured containment check."
            if matched
            else "The string does not satisfy the configured containment check."
        )
    if operator in {"includes", "not_includes"}:
        if isinstance(actual, list):
            matched = any(_json_values_equal(item, expected) for item in actual)
        elif isinstance(actual, dict) and isinstance(expected, str):
            matched = expected in actual
        else:
            return False, "The recorded value is not an array or object supporting membership."
        if operator == "not_includes":
            matched = not matched
        return matched, (
            "The membership check passed." if matched else "The membership check failed."
        )
    if operator in {"length_eq", "length_gt", "length_lt"}:
        if not isinstance(actual, (str, list, dict)):
            return False, "The recorded value has no supported length."
        size = len(actual)
        matched = {
            "length_eq": size == expected,
            "length_gt": size > expected,
            "length_lt": size < expected,
        }[operator]
        return matched, f"Recorded length is {size}; configured check is {operator} {expected}."
    raise ValueError(f"Unsupported assertion operator '{operator}'.")


_MISSING = object()


def _evaluate_assertions(
    session_id: str,
    events: list[Event],
    criteria: dict[str, Any],
    output: Any,
    output_available: bool,
    metrics: dict[str, Any],
) -> list[dict[str, Any]]:
    evaluated = []
    for assertion in criteria["assertions"]:
        source = assertion["source"]
        target_event: Event | None = None
        if source == "output":
            source_available = output_available
            source_value = output if source_available else _MISSING
            target_event = events[-1] if events else None
        elif source in {"event_result", "event_error"}:
            target_event = next(
                (
                    event
                    for event in events
                    if event.seq == assertion["event_seq"]
                    and (assertion["event_type"] is None or event.type == assertion["event_type"])
                    and (assertion["event_name"] is None or event.name == assertion["event_name"])
                ),
                None,
            )
            source_available = target_event is not None
            if source == "event_result":
                source_available = source_available and target_event.result_json is not None
                source_value = (
                    _decode_result(target_event.result_json)
                    if source_available and target_event
                    else _MISSING
                )
            elif target_event is None:
                source_value = _MISSING
            elif _has_error(target_event):
                source_value = (
                    target_event.error or target_event.error_type or "recorded failure result"
                )
            else:
                source_value = _MISSING
        else:
            metric = metrics[assertion["path"]]
            source_available = metric["value"] is not None
            source_value = metric["value"] if source_available else _MISSING

        if source == "metric":
            found, actual = source_available, source_value
        elif source == "event_error":
            found, actual = source_available, source_value
        else:
            found, actual = (
                _lookup_path(source_value, assertion["path"]) if source_available else (False, None)
            )
        operator = assertion["operator"]
        if not source_available:
            status = "unavailable"
            explanation = "The selected recorded event or metric is unavailable."
        elif not found and operator not in {"exists", "not_exists"}:
            status = "unavailable"
            explanation = "The selected path is missing from the recorded evidence."
        else:
            outcome, explanation = _assertion_match(
                actual if found else _MISSING,
                assertion.get("expected"),
                operator,
            )
            status = "unavailable" if outcome is None else "passed" if outcome else "failed"

        evidence = (
            [
                {
                    "session_id": session_id,
                    "seq": target_event.seq,
                    "type": target_event.type,
                    "name": target_event.name,
                }
            ]
            if target_event is not None
            else []
        )
        expected_value = assertion.get("expected")
        evaluated.append(
            {
                "id": assertion["id"],
                "name": assertion["name"],
                "source": source,
                "path": assertion["path"],
                "operator": operator,
                "expected": expected_value,
                "actual": actual if found else None,
                "status": status,
                "explanation": explanation,
                "evidence": evidence,
            }
        )
    return evaluated


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

    assertion_results = _evaluate_assertions(
        session_id,
        events,
        criteria,
        output,
        output_available,
        results["efficiency"]["metrics"],
    )
    if assertion_results:
        results["assertions"] = {
            "name": "Configured deterministic assertions",
            "version": EVALUATOR_VERSION,
            "status": (
                "failed"
                if any(item["status"] == "failed" for item in assertion_results)
                else "unavailable"
                if all(item["status"] == "unavailable" for item in assertion_results)
                else "partial"
                if any(item["status"] == "unavailable" for item in assertion_results)
                else "passed"
            ),
            "explanation": (
                "Each configured assertion is evaluated independently against recorded evidence."
            ),
            "results": assertion_results,
            "evidence": [
                evidence_item for item in assertion_results for evidence_item in item["evidence"]
            ],
            "limitations": [],
        }
        active_statuses.append(results["assertions"]["status"])

    quality_configured = expected is not None or bool(required_fields) or bool(required_phrases)
    quality_configured = quality_configured or bool(criteria["assertions"])
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
        "assertions": "Configured deterministic assertions",
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
    not_comparable = []
    ranking = {"passed": 2, "partial": 1, "failed": 0}

    def classify_change(name: str, base_status: str, fork_status: str) -> None:
        if base_status == fork_status:
            unchanged.append(name)
        elif base_status not in ranking or fork_status not in ranking:
            not_comparable.append(name)
        elif ranking[fork_status] > ranking[base_status]:
            improvements.append(name)
        elif ranking[fork_status] < ranking[base_status]:
            regressions.append(name)
        else:
            not_comparable.append(name)

    for name in ("expected_output", "required_information", "execution_errors", "efficiency"):
        base = baseline["evaluators"][name]
        variant = fork["evaluators"][name]
        pair = {"baseline": base["status"], "fork": variant["status"]}
        differences[name] = pair
        classify_change(name, pair["baseline"], pair["fork"])
    baseline_assertions = {
        item["id"]: item
        for item in baseline.get("evaluators", {}).get("assertions", {}).get("results", [])
    }
    fork_assertions = {
        item["id"]: item
        for item in fork.get("evaluators", {}).get("assertions", {}).get("results", [])
    }
    for assertion_id in sorted(set(baseline_assertions) | set(fork_assertions)):
        base = baseline_assertions.get(assertion_id)
        variant = fork_assertions.get(assertion_id)
        base_status = base["status"] if base else "unavailable"
        fork_status = variant["status"] if variant else "unavailable"
        differences[f"assertion:{assertion_id}"] = {
            "baseline": base_status,
            "fork": fork_status,
        }
        classify_change(f"assertion:{assertion_id}", base_status, fork_status)
    return {
        "criteria_statuses": differences,
        "improvements": improvements,
        "regressions": regressions,
        "unchanged": unchanged,
        "not_comparable": not_comparable,
        "note": (
            "Status comparison only; unavailable evidence is not treated as an improvement "
            "or a regression, and no weighted aggregate score is calculated."
        ),
    }
