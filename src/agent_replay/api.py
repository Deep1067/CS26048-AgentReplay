import asyncio
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent_replay.config import CONFIG_MUTATIONS_ENABLED, LIVE_RUN_ENABLED, USD_TO_INR
from agent_replay.detector.config import DetectorConfig
from agent_replay.detector.engine import DetectorEngine
from agent_replay.evaluation import (
    EVALUATOR_VERSION,
    compare_evaluations,
    evaluate_session,
    validate_criteria,
)
from agent_replay.models import Event
from agent_replay.pricing import get_price_engine
from agent_replay.providers import call_provider, configured_providers
from agent_replay.replay.engine import ReplayEngine
from agent_replay.replay.exceptions import ReplayCompletedError, ReplayDivergenceError
from agent_replay.replay.experiment import (
    list_supported_baselines,
    run_counterfactual_experiment,
)
from agent_replay.session_service import (
    SessionService,
    cost_summary,
    event_status,
    token_usage_summary,
)
from agent_replay.storage import SQLiteStorage

logger = logging.getLogger(__name__)


class StepLimitExceeded(Exception):
    """Raised when live execution reaches the hard step limit cap."""

    pass


class StepCappedStorage:
    """Storage proxy enforcing a hard cap of N recorded events per session."""

    def __init__(self, target: SQLiteStorage, max_steps: int = 5):
        self.target = target
        self.max_steps = max_steps
        self.step_count = 0
        self.is_remote = getattr(target, "is_remote", False)

    def create_session(self, session_id: str, metadata: dict[str, Any] | None = None) -> str:
        return self.target.create_session(session_id, metadata)

    def get_next_seq(self, session_id: str) -> int:
        return self.target.get_next_seq(session_id)

    def save_event(self, event: Event) -> Event:
        if self.step_count >= self.max_steps:
            raise StepLimitExceeded(f"Hard step cap of {self.max_steps} reached.")
        res = self.target.save_event(event)
        self.step_count += 1
        return res

    def get_events(self, session_id: str) -> list[Event]:
        return self.target.get_events(session_id)

    def list_sessions(self):
        return self.target.list_sessions()

    def get_session(self, session_id: str):
        return self.target.get_session(session_id)

    def delete_session(self, session_id: str) -> None:
        self.target.delete_session(session_id)

    def get_setting(self, key: str) -> Any | None:
        return self.target.get_setting(key)

    def set_setting(self, key: str, value: Any) -> None:
        self.target.set_setting(key, value)


SCENARIOS: dict[str, dict[str, str]] = {
    "scenario_1_loop": {
        "label": "Tool Looping Scenario",
        "description": "Agent repeatedly queries documentation with missing entity parameters",
        "expected_duration": "< 1 sec",
    },
    "scenario_2_recovery": {
        "label": "Tool Failure & Recovery",
        "description": "Database outage simulation with credit limit calculation logic",
        "expected_duration": "< 1 sec",
    },
    "live_langgraph_support": {
        "label": "Live Customer Support Agent (Gemini)",
        "description": "LangGraph agent querying database order value & refund policy via Gemini",
        "expected_duration": "~4.5 sec",
    },
}


class LiveRunRequest(BaseModel):
    scenario_id: str
    timeout_seconds: float | None = None
    simulate_delay_seconds: float | None = None


def _run_scenario_sync(
    scenario_id: str, session_id: str, storage: Any, slow_delay: float = 0.0
) -> None:
    if slow_delay > 0:
        time.sleep(slow_delay)

    if scenario_id == "scenario_1_loop":
        from agent_replay.interceptors.tool_interceptor import record_tool
        from agent_replay.recorder import record_session
        from agents.tools import search_docs

        recorded_search = record_tool("search_docs")(search_docs)
        with record_session(session_id, storage=storage):
            for _ in range(10):
                recorded_search(query="non_existent_feature_xyz")

    elif scenario_id == "scenario_2_recovery":
        from agent_replay.recorder import record_session
        from scenarios.scenario_2_malformed_response import (
            calculate_credit,
            query_user_account,
        )

        with record_session(session_id, storage=storage):
            account = query_user_account(user_id=101)
            if account.get("status") != "error":
                calculate_credit(account.get("balance"))

    elif scenario_id == "live_langgraph_support":
        from agent_replay.recorder import record_session
        from agents.langgraph_agent import build_langgraph_agent

        prompt = (
            "Find Alice total order value from the database and tell me her refund "
            "eligibility based on the refund policy."
        )
        agent = build_langgraph_agent()
        with record_session(session_id, storage=storage, metadata={"prompt": prompt}):
            agent.invoke({"messages": [{"role": "user", "content": prompt}]})


class ReplayCallRequest(BaseModel):
    type: Literal["tool_call", "model_call"]
    name: str
    args: Any = None


class ReplayRequest(BaseModel):
    session_id: str
    mode: Literal["strict", "forked"] = "strict"
    substitute_seq: int | None = None
    substitute_result: Any = None
    calls: list[ReplayCallRequest] | None = None


class PriceRateUpdate(BaseModel):
    input_inr_per_1k: float
    output_inr_per_1k: float


class PriceUpdate(BaseModel):
    models: dict[str, PriceRateUpdate]


class DetectorConfigUpdate(BaseModel):
    max_repeated_tool_calls: int
    cost_multiplier_over_median: float
    min_sessions_for_cost_median: int
    max_duration_ms: float
    max_events_per_session: int


class PlaygroundRequest(BaseModel):
    provider: Literal["openai", "anthropic", "gemini"]
    prompt: str
    model: str | None = None


class ExperimentRequest(BaseModel):
    baseline_session_id: str
    substitute_seq: int
    substitute_result: Any


class EvaluationRequest(BaseModel):
    criteria: dict[str, Any] | None = None
    suite_id: str | None = None
    suite_version: int | None = None
    replay_calls: list[ReplayCallRequest] | None = None


class EvaluationSuiteCreateRequest(BaseModel):
    name: str
    description: str = ""
    criteria: dict[str, Any]


class EvaluationSuiteUpdateRequest(EvaluationSuiteCreateRequest):
    current_version: int


class ReplayValidationRequest(BaseModel):
    calls: list[ReplayCallRequest] | None = None


def _experiment_snapshot_events(session_id: str, raw_events: list[dict[str, Any]]) -> list[Event]:
    events = []
    for raw_event in raw_events:
        event_data = dict(raw_event)
        event_data["session_id"] = session_id
        events.append(Event(**event_data))
    return events


def _suite_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": "output-correctness",
            "name": "Output correctness",
            "description": "Check explicit expected JSON values in a recorded result.",
            "criteria": {"expected_output": {"result": "expected value"}},
        },
        {
            "id": "required-information",
            "name": "Required information",
            "description": "Require selected output fields and phrases.",
            "criteria": {
                "required_fields": ["answer"],
                "required_phrases": [],
            },
        },
        {
            "id": "tool-errors",
            "name": "Tool execution errors",
            "description": "Fail when recorded calls contain an error or failure result.",
            "criteria": {"allow_tool_errors": False},
        },
        {
            "id": "resource-limits",
            "name": "Resource limits",
            "description": "Check available recorded duration, token usage, and estimated cost.",
            "criteria": {
                "max_latency_ms": 5000,
                "max_tokens": 2000,
                "max_cost_usd": 0.02,
            },
        },
    ]


def _decode_json(value: str | None) -> Any:
    if value is None:
        return None
    try:
        import json

        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _price_response() -> dict[str, Any]:
    engine = get_price_engine()
    models = {
        name: {
            "input_inr_per_1k": round(
                rates.get("input_cost_per_million", 0.0) * USD_TO_INR / 1000, 6
            ),
            "output_inr_per_1k": round(
                rates.get("output_cost_per_million", 0.0) * USD_TO_INR / 1000, 6
            ),
        }
        for name, rates in engine.prices.items()
    }
    return {"models": models, "usd_to_inr": USD_TO_INR}


def create_app(
    storage: SQLiteStorage | None = None,
    *,
    live_run_enabled: bool | None = None,
    config_mutations_enabled: bool | None = None,
) -> FastAPI:
    app = FastAPI(
        title="agent-replay",
        description="A logging proxy and replay engine for AI agent tool and model calls.",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost", "http://127.0.0.1"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    actual_storage = storage or SQLiteStorage()
    allow_live_runs = LIVE_RUN_ENABLED if live_run_enabled is None else live_run_enabled
    allow_config_mutations = (
        CONFIG_MUTATIONS_ENABLED if config_mutations_enabled is None else config_mutations_enabled
    )
    price_engine = get_price_engine()
    stored_prices = actual_storage.get_setting("prices")
    if isinstance(stored_prices, dict):
        price_engine.prices = stored_prices

    detector_config = DetectorConfig.load()
    stored_detector_config = actual_storage.get_setting("detector_config")
    if isinstance(stored_detector_config, dict):
        detector_config = DetectorConfig(**stored_detector_config)
    session_service = SessionService(
        storage=actual_storage,
        detector=DetectorEngine(config=detector_config),
    )

    def resolve_evaluation_criteria(
        request: EvaluationRequest,
    ) -> tuple[dict[str, Any], str | None, int | None]:
        suite_id = request.suite_id
        suite_version = request.suite_version
        if suite_id:
            if request.criteria is not None:
                raise HTTPException(
                    status_code=422,
                    detail="Provide either suite_id or criteria, not both.",
                )
            suite = actual_storage.get_evaluation_suite(suite_id, suite_version)
            if suite is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Evaluation suite '{suite_id}' was not found.",
                )
            raw_criteria = suite["criteria"]
            suite_version = suite["version"]
        else:
            if suite_version is not None:
                raise HTTPException(
                    status_code=422,
                    detail="suite_version requires suite_id.",
                )
            if request.criteria is None:
                raise HTTPException(
                    status_code=422,
                    detail="Provide criteria or select a saved evaluation suite.",
                )
            raw_criteria = request.criteria
        try:
            return validate_criteria(raw_criteria), suite_id, suite_version
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    static_dir = Path(__file__).parent / "ui" / "static"

    @app.get("/api/sessions")
    def list_sessions() -> list[dict[str, Any]]:
        """List all recorded sessions with summary metrics."""
        summaries = actual_storage.list_sessions()
        items = []
        for summary in summaries:
            item = summary.to_dict()
            item["total_cost_usd"], item["cost_status"] = cost_summary(
                actual_storage.get_events(summary.session_id)
            )
            items.append(item)
        return items

    @app.get("/api/overview")
    def get_overview() -> dict[str, Any]:
        summaries = actual_storage.list_sessions()
        total_events = sum(item.event_count for item in summaries)
        details = [session_service.get_session_details(item.session_id) for item in summaries]
        all_events = [
            event for item in summaries for event in actual_storage.get_events(item.session_id)
        ]
        return {
            "session_count": len(summaries),
            "event_count": total_events,
            "successful_events": sum(item["successful_events"] for item in details if item),
            "failed_events": sum(item["failed_events"] for item in details if item),
            "total_duration_ms": round(sum(item.total_duration_ms for item in summaries), 2),
            "model_usage_available": token_usage_summary(all_events)[2],
            "recent_sessions": [
                {
                    **item.to_dict(),
                    "total_cost_usd": cost_summary(actual_storage.get_events(item.session_id))[0],
                    "cost_status": cost_summary(actual_storage.get_events(item.session_id))[1],
                }
                for item in summaries[:5]
            ],
        }

    @app.get("/api/providers")
    def get_providers() -> dict[str, Any]:
        return {"providers": configured_providers()}

    @app.get("/api/usage")
    def get_usage(
        provider: str | None = Query(default=None, min_length=1),
        model: str | None = Query(default=None, min_length=1),
        session_id: str | None = Query(default=None, min_length=1),
    ) -> dict[str, Any]:
        grouped_events: dict[str, list[Event]] = {}
        records: list[dict[str, Any]] = []
        sessions: list[dict[str, Any]] = []
        for summary in actual_storage.list_sessions():
            if session_id and summary.session_id != session_id:
                continue
            events = actual_storage.get_events(summary.session_id)
            model_events = [
                event
                for event in events
                if event.type == "model_call"
                and (not provider or (event.provider or "unknown") == provider)
                and (not model or (event.model or event.name) == model)
            ]
            if not model_events:
                continue
            by_model: dict[str, list[Event]] = {}
            for event in model_events:
                key = f"{event.provider or 'unknown'}:{event.model or event.name}"
                grouped_events.setdefault(key, []).append(event)
                by_model.setdefault(key, []).append(event)
            for key, events in by_model.items():
                model_cost, model_cost_status = cost_summary(events)
                input_tokens, output_tokens, usage_available = token_usage_summary(events)
                records.append(
                    {
                        "session_id": summary.session_id,
                        "provider": events[0].provider or "unknown",
                        "model": events[0].model or events[0].name,
                        "event_count": len(events),
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "usage_available": usage_available,
                        "cost_usd": model_cost,
                        "cost_status": model_cost_status,
                    }
                )
            session_cost, session_cost_status = cost_summary(model_events)
            input_tokens, output_tokens, usage_available = token_usage_summary(model_events)
            sessions.append(
                {
                    "session_id": summary.session_id,
                    "models": len(
                        {(event.provider, event.model or event.name) for event in model_events}
                    ),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "usage_available": usage_available,
                    "cost_usd": session_cost,
                    "cost_status": session_cost_status,
                    "cost_available": session_cost is not None,
                }
            )
        groups = []
        for key, events in grouped_events.items():
            model_cost, model_cost_status = cost_summary(events)
            input_tokens, output_tokens, usage_available = token_usage_summary(events)
            groups.append(
                {
                    "provider": events[0].provider or "unknown",
                    "model": events[0].model or events[0].name,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "usage_available": usage_available,
                    "cost_usd": model_cost,
                    "cost_status": model_cost_status,
                    "sessions": len({event.session_id for event in events}),
                }
            )
        return {"groups": groups, "sessions": sessions, "records": records}

    @app.post("/api/playground/chat")
    def playground_chat(request: PlaygroundRequest) -> dict[str, Any]:
        if not request.prompt.strip():
            raise HTTPException(status_code=400, detail="Prompt cannot be empty.")
        session_id = f"playground_{uuid.uuid4().hex[:12]}"
        actual_storage.create_session(session_id, metadata={"provider": request.provider})
        started_at = datetime.now(UTC).isoformat()
        started = time.perf_counter()
        try:
            response = call_provider(request.provider, request.prompt, request.model)
            usage = response.usage or {}
            tokens_in = usage.get("input_tokens") or usage.get("prompt_tokens")
            tokens_out = usage.get("output_tokens") or usage.get("completion_tokens")
            cost = get_price_engine().calculate_known_cost(response.model, tokens_in, tokens_out)
            actual_storage.save_event(
                Event(
                    session_id=session_id,
                    seq=0,
                    type="model_call",
                    name=response.model,
                    model=response.model,
                    provider=response.provider,
                    args_json=json.dumps({"prompt": request.prompt}),
                    result_json=json.dumps({"text": response.text}),
                    started_at=started_at,
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                    tokens_in=tokens_in or 0,
                    tokens_out=tokens_out or 0,
                    tokens_total=(
                        tokens_in + tokens_out
                        if tokens_in is not None and tokens_out is not None
                        else None
                    ),
                    cost_usd=cost or 0.0,
                    cost_status="estimated" if cost is not None else "unavailable",
                    cost_currency="USD" if cost is not None else None,
                )
            )
            return {
                "session_id": session_id,
                "provider": response.provider,
                "model": response.model,
                "text": response.text,
                "output_source": "real_provider_call",
                "usage": response.usage,
                "cost_usd": cost,
                "cost_status": "estimated" if cost is not None else "unavailable",
            }
        except (RuntimeError, ValueError) as exc:
            actual_storage.save_event(
                Event(
                    session_id=session_id,
                    seq=0,
                    type="model_call",
                    name=request.model or request.provider,
                    provider=request.provider,
                    model=request.model,
                    args_json=json.dumps({"prompt": request.prompt}),
                    error=str(exc),
                    error_type=type(exc).__name__,
                    started_at=started_at,
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                )
            )
            raise HTTPException(status_code=503, detail=str(exc)) from None

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        """Get full timeline events and aggregate totals for a specific session."""
        details = session_service.get_session_details(session_id)
        if not details:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
        return details

    @app.get("/api/sessions/{session_id}/events")
    def get_session_events(
        session_id: str,
        tool: str | None = Query(default=None, min_length=1, max_length=200),
        status: Literal["success", "failed", "exception"] | None = None,
        event_type: Literal["tool_call", "model_call"] | None = None,
    ) -> dict[str, Any]:
        """Return a filtered event timeline for one recorded session."""
        if actual_storage.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
        events = actual_storage.get_events(session_id)
        filtered = [
            event
            for event in events
            if (tool is None or event.name == tool)
            and (status is None or event_status(event) == status)
            and (event_type is None or event.type == event_type)
        ]
        return {
            "session_id": session_id,
            "events": [
                {
                    **event.to_dict(),
                    "status": event_status(event),
                    "dependency": {
                        "kind": "inferred_sequence",
                        "predecessor_seq": event.seq - 1 if event.seq > 1 else None,
                        "explicit": False,
                    },
                }
                for event in filtered
            ],
        }

    @app.get("/api/sessions/{session_id}/analytics")
    def get_session_analytics(session_id: str) -> dict[str, Any]:
        """Return summary analytics without requiring clients to process the full trace."""
        details = session_service.get_session_details(session_id)
        if not details:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
        return {
            key: details[key]
            for key in (
                "session_id",
                "event_count",
                "tool_calls_count",
                "model_calls_count",
                "successful_events",
                "failed_events",
                "total_duration_ms",
                "slowest_event",
                "tool_stats",
                "metrics_available",
            )
        }

    @app.get("/api/prices")
    def get_prices() -> dict[str, Any]:
        """Get the current pricing configuration."""
        return _price_response()

    @app.put("/api/prices")
    def update_prices(update: PriceUpdate) -> dict[str, Any]:
        """Save INR per 1K pricing values back to prices.json."""
        if not allow_config_mutations:
            raise HTTPException(
                status_code=403,
                detail="Configuration changes are disabled on this server.",
            )
        if any(
            rate.input_inr_per_1k < 0 or rate.output_inr_per_1k < 0
            for rate in update.models.values()
        ):
            raise HTTPException(status_code=400, detail="Pricing values cannot be negative.")

        prices = {
            name: {
                "input_cost_per_million": rate.input_inr_per_1k * 1000 / USD_TO_INR,
                "output_cost_per_million": rate.output_inr_per_1k * 1000 / USD_TO_INR,
            }
            for name, rate in update.models.items()
        }
        if actual_storage.is_remote:
            get_price_engine().prices = prices
        else:
            get_price_engine().save_prices(prices)
        actual_storage.set_setting("prices", prices)
        return _price_response()

    @app.get("/api/cost-over-time")
    def get_cost_over_time() -> dict[str, Any]:
        """Return session costs ordered chronologically for the cost view."""
        points = []
        for summary in reversed(actual_storage.list_sessions()):
            total_cost, status = cost_summary(actual_storage.get_events(summary.session_id))
            points.append(
                {
                    "session_id": summary.session_id,
                    "started_at": summary.started_at,
                    "total_cost_usd": total_cost,
                    "cost_status": status,
                }
            )
        return {"points": points}

    @app.get("/api/detector-config")
    def get_detector_config() -> dict[str, Any]:
        return vars(session_service.detector.config)

    @app.put("/api/detector-config")
    def update_detector_config(update: DetectorConfigUpdate) -> dict[str, Any]:
        if not allow_config_mutations:
            raise HTTPException(
                status_code=403,
                detail="Configuration changes are disabled on this server.",
            )
        values = update.model_dump()
        if (
            values["max_repeated_tool_calls"] < 1
            or values["cost_multiplier_over_median"] <= 0
            or values["min_sessions_for_cost_median"] < 1
            or values["max_duration_ms"] <= 0
            or values["max_events_per_session"] < 1
        ):
            raise HTTPException(status_code=400, detail="Detector thresholds must be positive.")
        config = DetectorConfig(**values)
        if not actual_storage.is_remote:
            config.save()
        actual_storage.set_setting("detector_config", values)
        session_service.detector.config = config
        return vars(config)

    @app.post("/api/replay")
    def run_replay(request: ReplayRequest) -> dict[str, Any]:
        """Validate a recorded trace and report per-event replay status."""
        events = actual_storage.get_events(request.session_id)
        if not events:
            raise HTTPException(
                status_code=404,
                detail=f"Session '{request.session_id}' has no recorded events.",
            )

        calls = request.calls or [
            ReplayCallRequest(type=event.type, name=event.name, args=_decode_json(event.args_json))
            for event in events
        ]
        if request.substitute_seq is not None:
            substitute_event = next(
                (event for event in events if event.seq == request.substitute_seq), None
            )
            if substitute_event is None:
                raise HTTPException(status_code=400, detail="Substitution event was not found.")
            if request.mode != "forked" or substitute_event.type != "tool_call":
                raise HTTPException(
                    status_code=400,
                    detail="Only tool events can be substituted in forked mode.",
                )
        engine = ReplayEngine(
            session_id=request.session_id,
            storage=actual_storage,
            mode=request.mode,
            substitute_seq=request.substitute_seq,
            substitute_result=request.substitute_result,
        )
        results: list[dict[str, Any]] = []

        for call in calls:
            try:
                event = events[len(results)] if len(results) < len(events) else None
                if engine.is_forked_live and event is not None:
                    expected_args = _decode_json(event.args_json)
                    if (
                        event.type != call.type
                        or event.name != call.name
                        or expected_args != call.args
                    ):
                        raise ReplayDivergenceError(
                            seq=event.seq,
                            expected_type=event.type,
                            expected_name=event.name,
                            expected_args=event.args_json,
                            actual_type=call.type,
                            actual_name=call.name,
                            actual_args=call.args,
                        )
                elif call.type == "tool_call":
                    engine.handle_tool_call(call.name, call.args)
                else:
                    engine.handle_model_call(call.name, call.args)
                status = (
                    "substituted"
                    if event and request.mode == "forked" and event.seq == request.substitute_seq
                    else "matched"
                )
                results.append(
                    {
                        "id": event.seq if event else len(results) + 1,
                        "type": call.type,
                        "name": call.name,
                        "status": status,
                        "recorded_result": _decode_json(event.result_json) if event else None,
                    }
                )
            except ReplayDivergenceError as error:
                results.append(
                    {
                        "id": error.seq,
                        "type": call.type,
                        "name": call.name,
                        "status": "diverged",
                        "recorded": {
                            "type": error.expected_type,
                            "name": error.expected_name,
                            "args": error.expected_args,
                        },
                        "requested": {
                            "type": error.actual_type,
                            "name": error.actual_name,
                            "args": error.actual_args,
                        },
                    }
                )
                break

        return {
            "session_id": request.session_id,
            "mode": request.mode,
            "events": results,
            "halted": any(event["status"] == "diverged" for event in results),
        }

    @app.get("/api/sessions/{session_id}/replay-validations")
    def list_replay_validations(session_id: str) -> dict[str, Any]:
        if not actual_storage.get_session(session_id):
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
        return {"validations": actual_storage.list_replay_validations(session_id)}

    @app.post("/api/sessions/{session_id}/replay-validations")
    def validate_recorded_replay(
        session_id: str, request: ReplayValidationRequest
    ) -> dict[str, Any]:
        if not actual_storage.get_session(session_id):
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
        events = actual_storage.get_events(session_id)
        validation_id = f"replay_validation_{uuid.uuid4().hex[:12]}"
        validated_at = datetime.now(UTC).isoformat()
        if not events:
            result = {
                "session_id": session_id,
                "status": "unavailable",
                "explanation": "This session has no recorded events to replay.",
                "events": [],
                "limitations": ["No trace evidence is available."],
            }
            return actual_storage.create_replay_validation(
                validation_id,
                session_id,
                validated_at,
                "1.0",
                "unavailable",
                result,
            )

        calls = request.calls
        if calls is None:
            calls = [
                ReplayCallRequest(
                    type=event.type,
                    name=event.name,
                    args=_decode_json(event.args_json),
                )
                for event in events
            ]
        replay_engine = ReplayEngine(
            session_id=session_id,
            storage=actual_storage,
            mode="strict",
        )
        event_results: list[dict[str, Any]] = []
        failed = False
        unavailable = False
        for index, call in enumerate(calls):
            event = events[index] if index < len(events) else None
            if event is None:
                event_results.append(
                    {
                        "seq": index + 1,
                        "status": "diverged",
                        "explanation": "Replay requested a call beyond the recorded trace.",
                        "requested": call.model_dump(),
                    }
                )
                failed = True
                break
            try:
                if call.type == "tool_call":
                    replay_engine.handle_tool_call(call.name, call.args)
                else:
                    replay_engine.handle_model_call(call.name, call.args)
                if event.result_json is None:
                    status = "missing_result"
                    unavailable = True
                    explanation = "The event has no recorded result or recorded error."
                else:
                    status = "matched"
                    explanation = "Call matched and strict replay returned its recorded result."
                event_results.append(
                    {
                        "seq": event.seq,
                        "type": event.type,
                        "name": event.name,
                        "status": status,
                        "explanation": explanation,
                        "recorded_result": _decode_json(event.result_json),
                    }
                )
            except ReplayDivergenceError as error:
                event_results.append(
                    {
                        "seq": error.seq,
                        "status": "diverged",
                        "explanation": "Requested call does not match the recorded trace.",
                        "expected": {
                            "type": error.expected_type,
                            "name": error.expected_name,
                            "args": _decode_json(error.expected_args),
                        },
                        "requested": {
                            "type": error.actual_type,
                            "name": error.actual_name,
                            "args": error.actual_args,
                        },
                    }
                )
                failed = True
                break
            except ReplayCompletedError:
                event_results.append(
                    {
                        "seq": event.seq,
                        "status": "diverged",
                        "explanation": (
                            "Replay engine reported that the recorded call sequence was exhausted."
                        ),
                    }
                )
                failed = True
                break
            except Exception as error:
                if event.error:
                    event_results.append(
                        {
                            "seq": event.seq,
                            "type": event.type,
                            "name": event.name,
                            "status": "matched_recorded_error",
                            "explanation": (
                                "Strict replay reproduced the error recorded for this event."
                            ),
                            "error": event.error,
                            "error_type": event.error_type,
                        }
                    )
                else:
                    event_results.append(
                        {
                            "seq": event.seq,
                            "type": event.type,
                            "name": event.name,
                            "status": "replay_error",
                            "explanation": "Strict replay failed unexpectedly.",
                            "error": str(error),
                            "error_type": type(error).__name__,
                        }
                    )
                    failed = True
                    break

        if not failed and len(calls) < len(events):
            unavailable = True
            event_results.extend(
                {
                    "seq": event.seq,
                    "type": event.type,
                    "name": event.name,
                    "status": "not_checked",
                    "explanation": "No replay call was supplied for this recorded event.",
                }
                for event in events[len(calls) :]
            )
        status = "failed" if failed else "partial" if unavailable else "passed"
        result = {
            "session_id": session_id,
            "status": status,
            "explanation": {
                "passed": "Strict replay validated the complete supplied call sequence.",
                "failed": "Strict replay found a divergence or unexpected replay error.",
                "partial": "Some recorded events had missing results or were not checked.",
            }[status],
            "events": event_results,
            "limitations": [
                "Validation uses the existing recorded trace; it does not rerun an agent."
            ],
        }
        return actual_storage.create_replay_validation(
            validation_id,
            session_id,
            validated_at,
            "1.0",
            status,
            result,
        )

    @app.get("/api/evaluations")
    def list_evaluations(
        session_id: str | None = Query(default=None, min_length=1),
        experiment_id: str | None = Query(default=None, min_length=1),
    ) -> dict[str, Any]:
        return {
            "evaluations": actual_storage.list_evaluations(
                session_id=session_id,
                experiment_id=experiment_id,
            )
        }

    @app.get("/api/evaluation-suites/templates")
    def get_evaluation_suite_templates() -> dict[str, Any]:
        return {"templates": _suite_templates()}

    @app.get("/api/evaluation-suites")
    def list_evaluation_suites() -> dict[str, Any]:
        return {"suites": actual_storage.list_evaluation_suites()}

    @app.post("/api/evaluation-suites")
    def create_evaluation_suite(request: EvaluationSuiteCreateRequest) -> dict[str, Any]:
        name = request.name.strip()
        description = request.description.strip()
        if not name or len(name) > 100:
            raise HTTPException(status_code=422, detail="Suite name must be 1 to 100 characters.")
        if len(description) > 500:
            raise HTTPException(
                status_code=422, detail="Suite description must be at most 500 characters."
            )
        try:
            criteria = validate_criteria(request.criteria)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        suite_id = f"suite_{uuid.uuid4().hex[:12]}"
        return actual_storage.create_evaluation_suite(
            suite_id=suite_id,
            version=1,
            name=name,
            description=description,
            criteria=criteria,
            evaluator_version=EVALUATOR_VERSION,
        )

    @app.get("/api/evaluation-suites/{suite_id}/versions")
    def list_evaluation_suite_versions(suite_id: str) -> dict[str, Any]:
        versions = actual_storage.list_evaluation_suite_versions(suite_id)
        if not versions:
            raise HTTPException(
                status_code=404,
                detail=f"Evaluation suite '{suite_id}' was not found.",
            )
        return {"suite_id": suite_id, "versions": versions}

    @app.get("/api/evaluation-suites/{suite_id}")
    def get_evaluation_suite(
        suite_id: str, version: int | None = Query(default=None, ge=1)
    ) -> dict[str, Any]:
        suite = actual_storage.get_evaluation_suite(suite_id, version)
        if suite is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Evaluation suite '{suite_id}' version {version or 'latest'} was not found."
                ),
            )
        return suite

    @app.put("/api/evaluation-suites/{suite_id}")
    def update_evaluation_suite(
        suite_id: str, request: EvaluationSuiteUpdateRequest
    ) -> dict[str, Any]:
        current = actual_storage.get_evaluation_suite(suite_id)
        if current is None:
            raise HTTPException(
                status_code=404,
                detail=f"Evaluation suite '{suite_id}' was not found.",
            )
        if request.current_version != current["version"]:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Suite is now version {current['version']}; reload it before saving changes."
                ),
            )
        name = request.name.strip()
        description = request.description.strip()
        if not name or len(name) > 100:
            raise HTTPException(status_code=422, detail="Suite name must be 1 to 100 characters.")
        if len(description) > 500:
            raise HTTPException(
                status_code=422, detail="Suite description must be at most 500 characters."
            )
        try:
            criteria = validate_criteria(request.criteria)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return actual_storage.create_evaluation_suite(
            suite_id=suite_id,
            version=current["version"] + 1,
            name=name,
            description=description,
            criteria=criteria,
            evaluator_version=EVALUATOR_VERSION,
        )

    @app.post("/api/evaluations/sessions/{session_id}")
    def evaluate_recorded_session(session_id: str, request: EvaluationRequest) -> dict[str, Any]:
        if not actual_storage.get_session(session_id):
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
        criteria, suite_id, suite_version = resolve_evaluation_criteria(request)
        events = actual_storage.get_events(session_id)
        result = evaluate_session(session_id, events, criteria)
        if request.replay_calls is not None:
            replay_checks = []
            for index, call in enumerate(request.replay_calls):
                if index >= len(events):
                    replay_checks.append(
                        {
                            "status": "diverged",
                            "seq": index + 1,
                            "expected": None,
                            "requested": call.model_dump(),
                        }
                    )
                    break
                event = events[index]
                expected = {
                    "type": event.type,
                    "name": event.name,
                    "args": _decode_json(event.args_json),
                }
                requested = call.model_dump()
                if (
                    expected["type"] != call.type
                    or expected["name"] != call.name
                    or expected["args"] != call.args
                ):
                    replay_checks.append(
                        {
                            "status": "diverged",
                            "seq": event.seq,
                            "expected": expected,
                            "requested": requested,
                        }
                    )
                    break
                replay_checks.append(
                    {
                        "status": "matched",
                        "seq": event.seq,
                        "expected": expected,
                        "requested": requested,
                    }
                )
            if not any(item["status"] == "diverged" for item in replay_checks):
                if not events:
                    replay_status = "unavailable"
                elif len(request.replay_calls) < len(events):
                    replay_status = "incomplete"
                    replay_checks.append(
                        {
                            "status": "not_checked",
                            "seq": events[len(request.replay_calls)].seq,
                            "reason": "The replay call sequence ended before the trace did.",
                        }
                    )
                else:
                    replay_status = "passed"
            else:
                replay_status = "diverged"
            replay_explanations = {
                "passed": "Every supplied replay call matched the recorded trace.",
                "incomplete": "Replay call sequence ended before all recorded events were checked.",
                "diverged": "Replay call sequence diverged from the recorded trace.",
                "unavailable": "The session has no events to validate.",
            }
            result["replay_validity"] = {
                "status": replay_status,
                "explanation": replay_explanations[replay_status],
                "evidence": replay_checks,
            }
            replay_evaluator_status = {
                "passed": "passed",
                "incomplete": "partial",
                "diverged": "failed",
                "unavailable": "unavailable",
            }[replay_status]
            result["evaluators"]["replay_divergence"] = {
                "name": "Strict replay divergence",
                "version": result["evaluator_version"],
                "status": replay_evaluator_status,
                "explanation": result["replay_validity"]["explanation"],
                "evidence": replay_checks,
                "limitations": [],
            }
            if replay_evaluator_status == "failed":
                result["status"] = "failed"
                result["status_explanation"] = (
                    "Strict replay diverged from the recorded trace; inspect the mismatched call."
                )
            elif replay_evaluator_status == "partial" and result["status"] == "passed":
                result["status"] = "partial"
                result["status_explanation"] = (
                    "Replay validation was incomplete because not all recorded calls were supplied."
                )
        evaluation_id = f"evaluation_{uuid.uuid4().hex[:12]}"
        result["suite_id"] = suite_id
        result["suite_version"] = suite_version
        record = actual_storage.create_evaluation(
            evaluation_id=evaluation_id,
            target_type="session",
            session_id=session_id,
            experiment_id=None,
            criteria=criteria,
            result=result,
            suite_id=suite_id,
            suite_version=suite_version,
        )
        return record

    @app.get("/api/experiments/baselines")
    def get_experiment_baselines() -> dict[str, Any]:
        return {"baselines": list_supported_baselines(actual_storage)}

    @app.get("/api/experiments")
    def list_experiments() -> dict[str, Any]:
        return {"experiments": actual_storage.list_experiments()}

    @app.get("/api/experiments/{experiment_id}")
    def get_experiment(experiment_id: str) -> dict[str, Any]:
        experiment = actual_storage.get_experiment(experiment_id)
        if not experiment:
            raise HTTPException(status_code=404, detail=f"Experiment '{experiment_id}' not found.")
        return experiment

    @app.get("/api/experiments/{experiment_id}/evaluations")
    def list_experiment_evaluations(experiment_id: str) -> dict[str, Any]:
        if not actual_storage.get_experiment(experiment_id):
            raise HTTPException(status_code=404, detail=f"Experiment '{experiment_id}' not found.")
        return {"evaluations": actual_storage.list_evaluations(experiment_id=experiment_id)}

    @app.post("/api/experiments/{experiment_id}/evaluations")
    def evaluate_experiment(experiment_id: str, request: EvaluationRequest) -> dict[str, Any]:
        experiment = actual_storage.get_experiment(experiment_id)
        if not experiment:
            raise HTTPException(status_code=404, detail=f"Experiment '{experiment_id}' not found.")
        criteria, suite_id, suite_version = resolve_evaluation_criteria(request)

        experiment_result = experiment["result"]
        baseline_id = experiment["baseline_session_id"]
        fork_id = experiment["fork_session_id"]
        baseline_events = actual_storage.get_events(baseline_id)
        fork_events = actual_storage.get_events(fork_id)
        limitations = []
        if not baseline_events:
            baseline_snapshot = experiment_result.get("events", {}).get("baseline", [])
            baseline_events = _experiment_snapshot_events(baseline_id, baseline_snapshot)
            limitations.append(
                "Baseline session events were read from the saved experiment snapshot."
            )
        if not fork_events:
            fork_snapshot = experiment_result.get("events", {}).get("forked", [])
            fork_events = _experiment_snapshot_events(fork_id, fork_snapshot)
            limitations.append("Fork session events were read from the saved experiment snapshot.")

        baseline = evaluate_session(baseline_id, baseline_events, criteria)
        fork = evaluate_session(fork_id, fork_events, criteria)
        result = {
            "experiment_id": experiment_id,
            "suite_id": suite_id,
            "suite_version": suite_version,
            "evaluator_version": baseline["evaluator_version"],
            "evaluated_at": datetime.now(UTC).isoformat(),
            "status": (
                "failed"
                if "failed" in {baseline["status"], fork["status"]}
                else "partial"
                if "partial" in {baseline["status"], fork["status"]}
                else "passed"
                if baseline["status"] == fork["status"] == "passed"
                else "unavailable"
            ),
            "baseline_session_id": baseline_id,
            "fork_session_id": fork_id,
            "replay_validity": {
                "status": "passed",
                "explanation": (
                    "The saved guided experiment completed strict replay before the fork. "
                    "This is replay validity, not a task-quality score."
                ),
                "evidence": experiment_result.get("evidence", {}).get("strict_replay"),
            },
            "baseline": baseline,
            "fork": fork,
            "comparison": compare_evaluations(baseline, fork),
            "limitations": limitations,
        }
        evaluation_id = f"evaluation_{uuid.uuid4().hex[:12]}"
        return actual_storage.create_evaluation(
            evaluation_id=evaluation_id,
            target_type="experiment",
            session_id=None,
            experiment_id=experiment_id,
            criteria=criteria,
            result=result,
            suite_id=suite_id,
            suite_version=suite_version,
        )

    @app.post("/api/experiments")
    def create_guided_experiment(request: ExperimentRequest) -> dict[str, Any]:
        if request.substitute_result is None:
            raise HTTPException(
                status_code=422,
                detail="The replacement tool response must be a JSON object, not null.",
            )
        if not any(
            baseline["session_id"] == request.baseline_session_id
            for baseline in list_supported_baselines(actual_storage)
        ):
            if not actual_storage.get_session(request.baseline_session_id):
                raise HTTPException(
                    status_code=404,
                    detail=f"Baseline session '{request.baseline_session_id}' not found.",
                )
            raise HTTPException(
                status_code=422,
                detail="This session is not eligible. Guided experiments currently support "
                "the recorded scenario-2 account workflow.",
            )
        try:
            return run_counterfactual_experiment(
                actual_storage,
                baseline_session_id=request.baseline_session_id,
                substitute_seq=request.substitute_seq,
                substitute_result=request.substitute_result,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/experiments/counterfactual")
    def run_counterfactual() -> dict[str, Any]:
        """Run the deterministic local failure-and-recovery experiment."""
        return run_counterfactual_experiment(actual_storage)

    @app.get("/api/live/status")
    def get_live_status() -> dict[str, Any]:
        return {
            "execution_enabled": allow_live_runs,
            "instrumented_recording_supported": True,
            "monitoring_mode": "periodic session-list refresh",
            "message": (
                "Server-defined live scenarios are enabled."
                if allow_live_runs
                else "Live scenario execution is disabled by server configuration. "
                "Instrumented agents can still record sessions into this server's storage."
            ),
        }

    @app.get("/api/live/scenarios")
    def get_live_scenarios() -> dict[str, Any]:
        return SCENARIOS

    @app.post("/api/live/run")
    async def run_live_scenario(request: LiveRunRequest) -> dict[str, Any]:
        if not allow_live_runs:
            raise HTTPException(
                status_code=503,
                detail="Live execution is not enabled on this server.",
            )

        if request.scenario_id not in SCENARIOS:
            raise HTTPException(
                status_code=400, detail=f"Unknown scenario_id '{request.scenario_id}'"
            )

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        session_id = f"live_run_{request.scenario_id}_{timestamp}"
        capped_storage = StepCappedStorage(actual_storage, max_steps=5)
        timeout_sec = request.timeout_seconds if request.timeout_seconds is not None else 15.0

        status = "done"
        try:
            if request.simulate_delay_seconds and request.simulate_delay_seconds > 0:
                await asyncio.wait_for(
                    asyncio.sleep(request.simulate_delay_seconds),
                    timeout=timeout_sec,
                )
            await asyncio.wait_for(
                asyncio.to_thread(
                    _run_scenario_sync,
                    request.scenario_id,
                    session_id,
                    capped_storage,
                ),
                timeout=timeout_sec,
            )
        except TimeoutError:
            status = "timed_out"
        except StepLimitExceeded:
            status = "step_limit_reached"
        except Exception:
            logger.exception(
                "Live scenario failed: scenario_id=%s session_id=%s",
                request.scenario_id,
                session_id,
            )
            status = "error"

        details = session_service.get_session_details(session_id)
        event_count = details["event_count"] if details else capped_storage.step_count
        cost_usd = details["total_cost_usd"] if details else None
        cost_status = details["cost_status"] if details else "unavailable"
        cost_inr = round(cost_usd * USD_TO_INR, 4) if cost_usd is not None else None

        if status == "done":
            msg = f"Completed successfully with {event_count} events."
        elif status == "timed_out":
            msg = f"Execution timed out after {timeout_sec}s ({event_count} events recorded)."
        elif status == "step_limit_reached":
            msg = f"Step limit of 5 reached ({event_count} events recorded)."
        else:
            msg = "Execution failed; inspect the recorded session for details."

        return {
            "session_id": session_id,
            "status": status,
            "event_count": event_count,
            "total_cost_usd": cost_usd,
            "total_cost_inr": cost_inr,
            "cost_status": cost_status,
            "message": msg,
        }

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/", include_in_schema=False)
        def serve_index():
            index_path = static_dir / "index.html"
            if index_path.exists():
                return FileResponse(str(index_path))
            return {"message": "agent-replay API active. UI index.html not found."}

    return app


app = create_app()
