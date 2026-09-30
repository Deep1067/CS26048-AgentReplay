from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent_replay.pricing import get_price_engine
from agent_replay.session_service import SessionService
from agent_replay.storage import SQLiteStorage


def create_app(storage: SQLiteStorage | None = None) -> FastAPI:
    app = FastAPI(
        title="agent-replay",
        description="A logging proxy and replay engine for AI agent tool and model calls.",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    actual_storage = storage or SQLiteStorage()
    session_service = SessionService(storage=actual_storage)

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
        engine = get_price_engine()
        return {"models": engine.prices}

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
