import json
import os
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
        remote_url = os.getenv("TURSO_DATABASE_URL")
        remote_token = os.getenv("TURSO_AUTH_TOKEN")
        self.is_remote = db_path is None and bool(remote_url and remote_token)
        if self.is_remote:
            import turso_serverless

            self.is_memory = False
            self.db_path = remote_url
            self.use_uri = False
            self._conn = turso_serverless.connect(remote_url, auth_token=remote_token)
            self._conn.row_factory = turso_serverless.Row
        else:
            raw_path = str(db_path or DB_PATH)
            self.is_memory = raw_path == ":memory:" or "mode=memory" in raw_path
            self.db_path = (
                f"file:mem_{id(self)}?mode=memory&cache=shared" if self.is_memory else raw_path
            )
            self.use_uri = self.is_memory
            self._conn = sqlite3.connect(
                self.db_path,
                uri=self.use_uri,
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row

        self._lock = threading.Lock()
        if not self.is_memory and not self.is_remote:
            self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        return self._conn

    def _init_db(self) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        started_at TEXT NOT NULL,
                        metadata_json TEXT
                    );
                """)
                self._conn.execute("""
                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        seq INTEGER NOT NULL,
                        type TEXT NOT NULL,
                        name TEXT NOT NULL,
                        args_json TEXT NOT NULL,
                        result_json TEXT,
                        error TEXT,
                        error_type TEXT,
                        started_at TEXT NOT NULL,
                        duration_ms REAL NOT NULL,
                        tokens_in INTEGER DEFAULT 0,
                        tokens_out INTEGER DEFAULT 0,
                        cost_usd REAL DEFAULT 0.0,
                        FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE,
                        UNIQUE (session_id, seq)
                    );
                """)
                columns = {
                    row["name"]
                    for row in self._conn.execute("PRAGMA table_info(events);").fetchall()
                }
                if "error_type" not in columns:
                    self._conn.execute("ALTER TABLE events ADD COLUMN error_type TEXT;")
                self._conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_events_session_seq
                    ON events (session_id, seq);
                """)
                self._conn.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value_json TEXT NOT NULL
                    );
                """)

    def create_session(self, session_id: str, metadata: dict[str, Any] | None = None) -> str:
        now = datetime.now(UTC).isoformat()
        meta_json = json.dumps(metadata or {})
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO sessions (session_id, started_at, metadata_json)
                    VALUES (?, ?, ?);
                """,
                    (session_id, now, meta_json),
                )
        return session_id

    def get_next_seq(self, session_id: str) -> int:
        cursor = self._conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE session_id = ?;",
            (session_id,),
        )
        return int(cursor.fetchone()[0])

    def save_event(self, event: Event) -> Event:
        if not event.started_at:
            event.started_at = datetime.now(UTC).isoformat()

        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO sessions (session_id, started_at, metadata_json)
                    VALUES (?, ?, ?);
                    """,
                    (event.session_id, event.started_at, "{}"),
                )
                if event.seq <= 0:
                    cursor = self._conn.execute(
                        "SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE session_id = ?;",
                        (event.session_id,),
                    )
                    event.seq = int(cursor.fetchone()[0])
                self._conn.execute(
                    """
                    INSERT INTO events (
                        session_id, seq, type, name, args_json, result_json, error, error_type,
                        started_at, duration_ms, tokens_in, tokens_out, cost_usd
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                    (
                        event.session_id,
                        event.seq,
                        event.type,
                        event.name,
                        event.args_json,
                        event.result_json,
                        event.error,
                        event.error_type,
                        event.started_at,
                        event.duration_ms,
                        event.tokens_in,
                        event.tokens_out,
                        event.cost_usd,
                    ),
                )
        return event

    def get_events(self, session_id: str) -> list[Event]:
        with self._lock:
            cursor = self._conn.execute(
                """
                     SELECT session_id, seq, type, name, args_json, result_json, error,
                         error_type, started_at, duration_ms, tokens_in, tokens_out, cost_usd
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
                        error_type=row["error_type"],
                        started_at=row["started_at"],
                        duration_ms=row["duration_ms"],
                        tokens_in=row["tokens_in"],
                        tokens_out=row["tokens_out"],
                        cost_usd=row["cost_usd"],
                    )
                )
            return events

    def list_sessions(self) -> list[SessionSummary]:
        with self._lock:
            cursor = self._conn.execute("""
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
        with self._lock:
            cursor = self._conn.execute(
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

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute("DELETE FROM sessions WHERE session_id = ?;", (session_id,))

    def get_setting(self, key: str) -> Any | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value_json FROM settings WHERE key = ?;", (key,)
            ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["value_json"])
        except (TypeError, ValueError):
            return None

    def set_setting(self, key: str, value: Any) -> None:
        value_json = json.dumps(value)
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO settings (key, value_json) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json;
                    """,
                    (key, value_json),
                )
