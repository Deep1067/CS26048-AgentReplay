import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_replay.config import DB_PATH
from agent_replay.models import Event, SessionSummary


class SQLiteStorage:
    """Thread-safe SQLite storage for agent recording sessions and events."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(db_path or DB_PATH)
        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            if self.db_path != ":memory:":
                conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    metadata_json TEXT
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    started_at TEXT NOT NULL,
                    duration_ms REAL NOT NULL,
                    tokens_in INTEGER DEFAULT 0,
                    tokens_out INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0.0,
                    FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE,
                    UNIQUE (session_id, seq)
                );
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_session_seq
                ON events (session_id, seq);
            """)

    def create_session(self, session_id: str, metadata: dict[str, Any] | None = None) -> str:
        conn = self._get_connection()
        now = datetime.now(UTC).isoformat()
        meta_json = json.dumps(metadata or {})
        with conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO sessions (session_id, started_at, metadata_json)
                VALUES (?, ?, ?);
            """,
                (session_id, now, meta_json),
            )
        return session_id

    def get_next_seq(self, session_id: str) -> int:
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE session_id = ?;",
            (session_id,),
        )
        return int(cursor.fetchone()[0])

    def save_event(self, event: Event) -> Event:
        conn = self._get_connection()
        self.create_session(event.session_id)
        if event.seq <= 0:
            event.seq = self.get_next_seq(event.session_id)
        if not event.started_at:
            event.started_at = datetime.now(UTC).isoformat()

        with conn:
            conn.execute(
                """
                INSERT INTO events (
                    session_id, seq, type, name, args_json, result_json, error,
                    started_at, duration_ms, tokens_in, tokens_out, cost_usd
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
                (
                    event.session_id,
                    event.seq,
                    event.type,
                    event.name,
                    event.args_json,
                    event.result_json,
                    event.error,
                    event.started_at,
                    event.duration_ms,
                    event.tokens_in,
                    event.tokens_out,
                    event.cost_usd,
                ),
            )
        return event

    def get_events(self, session_id: str) -> list[Event]:
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT session_id, seq, type, name, args_json, result_json, error,
                   started_at, duration_ms, tokens_in, tokens_out, cost_usd
            FROM events
            WHERE session_id = ?
            ORDER BY seq ASC;
        """,
            (session_id,),
        )
        events = []
        for row in cursor.fetchall():
            events.append(
                Event(
                    session_id=row["session_id"],
                    seq=row["seq"],
                    type=row["type"],
                    name=row["name"],
                    args_json=row["args_json"],
                    result_json=row["result_json"],
                    error=row["error"],
                    started_at=row["started_at"],
                    duration_ms=row["duration_ms"],
                    tokens_in=row["tokens_in"],
                    tokens_out=row["tokens_out"],
                    cost_usd=row["cost_usd"],
                )
            )
        return events

    def list_sessions(self) -> list[SessionSummary]:
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT
                s.session_id,
                s.started_at,
                COUNT(e.id) AS event_count,
                COALESCE(SUM(e.cost_usd), 0.0) AS total_cost_usd,
                COALESCE(SUM(e.duration_ms), 0.0) AS total_duration_ms,
                MAX(CASE WHEN e.error IS NOT NULL AND e.error != '' THEN 1 ELSE 0 END) AS has_errors
            FROM sessions s
            LEFT JOIN events e ON s.session_id = e.session_id
            GROUP BY s.session_id, s.started_at
            ORDER BY s.started_at DESC;
        """)
        summaries = []
        for row in cursor.fetchall():
            summaries.append(
                SessionSummary(
                    session_id=row["session_id"],
                    started_at=row["started_at"],
                    event_count=row["event_count"],
                    total_cost_usd=round(row["total_cost_usd"], 6),
                    total_duration_ms=round(row["total_duration_ms"], 2),
                    has_errors=bool(row["has_errors"]),
                )
            )
        return summaries

    def get_session(self, session_id: str) -> SessionSummary | None:
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT
                s.session_id,
                s.started_at,
                COUNT(e.id) AS event_count,
                COALESCE(SUM(e.cost_usd), 0.0) AS total_cost_usd,
                COALESCE(SUM(e.duration_ms), 0.0) AS total_duration_ms,
                MAX(CASE WHEN e.error IS NOT NULL AND e.error != '' THEN 1 ELSE 0 END) AS has_errors
            FROM sessions s
            LEFT JOIN events e ON s.session_id = e.session_id
            WHERE s.session_id = ?
            GROUP BY s.session_id, s.started_at;
        """,
            (session_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return SessionSummary(
            session_id=row["session_id"],
            started_at=row["started_at"],
            event_count=row["event_count"],
            total_cost_usd=round(row["total_cost_usd"], 6),
            total_duration_ms=round(row["total_duration_ms"], 2),
            has_errors=bool(row["has_errors"]),
        )
