from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent_replay.config import USD_TO_INR
from agent_replay.detector.config import DetectorConfig
from agent_replay.detector.engine import DetectorEngine
from agent_replay.pricing import get_price_engine
from agent_replay.replay.engine import ReplayEngine
from agent_replay.replay.exceptions import ReplayDivergenceError
from agent_replay.session_service import SessionService
from agent_replay.storage import SQLiteStorage


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


def create_app(storage: SQLiteStorage | None = None) -> FastAPI:
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

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        """Get full timeline events and aggregate totals for a specific session."""
        details = session_service.get_session_details(session_id)
        if not details:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
        return details

    @app.get("/api/prices")
    def get_prices() -> dict[str, Any]:
        """Get the current pricing configuration."""
        return _price_response()

    @app.put("/api/prices")
    def update_prices(update: PriceUpdate) -> dict[str, Any]:
        """Save INR per 1K pricing values back to prices.json."""
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
