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
from agent_replay.models import Event
from agent_replay.pricing import get_price_engine
from agent_replay.providers import call_provider, configured_providers
from agent_replay.replay.engine import ReplayEngine
from agent_replay.replay.exceptions import ReplayDivergenceError
from agent_replay.replay.experiment import run_counterfactual_experiment
from agent_replay.session_service import SessionService, event_status
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

    static_dir = Path(__file__).parent / "ui" / "static"

    @app.get("/api/sessions")
    def list_sessions() -> list[dict[str, Any]]:
        """List all recorded sessions with summary metrics."""
        summaries = actual_storage.list_sessions()
        return [s.to_dict() for s in summaries]

    @app.get("/api/overview")
    def get_overview() -> dict[str, Any]:
        summaries = actual_storage.list_sessions()
        total_events = sum(item.event_count for item in summaries)
        details = [session_service.get_session_details(item.session_id) for item in summaries]
        model_events = [
            event
            for item in details
            if item
            for event in item["events"]
            if event["type"] == "model_call"
        ]
        return {
            "session_count": len(summaries),
            "event_count": total_events,
            "successful_events": sum(item["successful_events"] for item in details if item),
            "failed_events": sum(item["failed_events"] for item in details if item),
            "total_duration_ms": round(sum(item.total_duration_ms for item in summaries), 2),
            "model_usage_available": any(
                event["tokens_in"] or event["tokens_out"] for event in model_events
            ),
            "recent_sessions": [item.to_dict() for item in summaries[:5]],
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
        grouped: dict[str, dict[str, Any]] = {}
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
            for event in model_events:
                key = f"{event.provider or 'unknown'}:{event.model or event.name}"
                item = grouped.setdefault(
                    key,
                    {
                        "provider": event.provider or "unknown",
                        "model": event.model or event.name,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cost_usd": None,
                        "cost_status": "unavailable",
                        "sessions": 0,
                    },
                )
                item["input_tokens"] += event.tokens_in
                item["output_tokens"] += event.tokens_out
                if event.cost_status != "unavailable":
                    item["cost_usd"] = (item["cost_usd"] or 0.0) + event.cost_usd
                    item["cost_status"] = event.cost_status
                item["sessions"] = item["sessions"] + 1
            available_cost = [
                event.cost_usd for event in model_events if event.cost_status != "unavailable"
            ]
            sessions.append(
                {
                    "session_id": summary.session_id,
                    "models": len(model_events),
                    "input_tokens": sum(event.tokens_in for event in model_events),
                    "output_tokens": sum(event.tokens_out for event in model_events),
                    "cost_usd": round(sum(available_cost), 8) if available_cost else None,
                    "cost_available": any(
                        event.cost_status != "unavailable" for event in model_events
                    ),
                }
            )
        for item in grouped.values():
            if item["cost_usd"] is not None:
                item["cost_usd"] = round(item["cost_usd"], 8)
        return {"groups": list(grouped.values()), "sessions": sessions}

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
        points = [
            {
                "session_id": summary.session_id,
                "started_at": summary.started_at,
                "total_cost_usd": summary.total_cost_usd,
            }
            for summary in reversed(actual_storage.list_sessions())
        ]
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

    @app.post("/api/experiments/counterfactual")
    def run_counterfactual() -> dict[str, Any]:
        """Run the deterministic local failure-and-recovery experiment."""
        return run_counterfactual_experiment(actual_storage)

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
        cost_usd = details["total_cost_usd"] if details else 0.0
        cost_inr = round(cost_usd * USD_TO_INR, 4)

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
