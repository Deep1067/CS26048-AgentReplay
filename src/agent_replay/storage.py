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
                for column, definition in {
                    "provider": "TEXT",
                    "model": "TEXT",
                    "tokens_total": "INTEGER",
                    "cached_tokens": "INTEGER",
                    "cost_status": "TEXT NOT NULL DEFAULT 'unavailable'",
                    "cost_currency": "TEXT",
                }.items():
                    if column not in columns:
                        self._conn.execute(f"ALTER TABLE events ADD COLUMN {column} {definition};")
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
                self._conn.execute("""
                    CREATE TABLE IF NOT EXISTS experiments (
                        experiment_id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        baseline_session_id TEXT NOT NULL,
                        fork_session_id TEXT NOT NULL,
                        result_json TEXT NOT NULL
                    );
                """)
                self._conn.execute("""
                    CREATE TABLE IF NOT EXISTS evaluations (
                        evaluation_id TEXT PRIMARY KEY,
                        evaluated_at TEXT NOT NULL,
                        target_type TEXT NOT NULL,
                        session_id TEXT,
                        experiment_id TEXT,
                        criteria_json TEXT NOT NULL,
                        result_json TEXT NOT NULL,
                        suite_id TEXT,
                        suite_version INTEGER
                    );
                """)
                evaluation_columns = {
                    row["name"]
                    for row in self._conn.execute("PRAGMA table_info(evaluations);").fetchall()
                }
                if "suite_id" not in evaluation_columns:
                    self._conn.execute("ALTER TABLE evaluations ADD COLUMN suite_id TEXT;")
                if "suite_version" not in evaluation_columns:
                    self._conn.execute("ALTER TABLE evaluations ADD COLUMN suite_version INTEGER;")
                self._conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_evaluations_target
                    ON evaluations (session_id, experiment_id, evaluated_at);
                """)
                self._conn.execute("""
                    CREATE TABLE IF NOT EXISTS evaluation_suites (
                        suite_id TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        description TEXT NOT NULL,
                        criteria_json TEXT NOT NULL,
                        evaluator_version TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (suite_id, version)
                    );
                """)
                self._conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_evaluation_suites_name
                    ON evaluation_suites (name, suite_id, version);
                """)
                self._conn.execute("""
                    CREATE TABLE IF NOT EXISTS replay_validations (
                        validation_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        validated_at TEXT NOT NULL,
                        validation_version TEXT NOT NULL,
                        status TEXT NOT NULL,
                        result_json TEXT NOT NULL
                    );
                """)
                self._conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_replay_validations_session
                    ON replay_validations (session_id, validated_at);
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
                        started_at, duration_ms, tokens_in, tokens_out, cost_usd,
                        provider, model, tokens_total, cached_tokens, cost_status, cost_currency
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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
                        event.provider,
                        event.model,
                        event.tokens_total,
                        event.cached_tokens,
                        event.cost_status,
                        event.cost_currency,
                    ),
                )
        return event

    def get_events(self, session_id: str) -> list[Event]:
        with self._lock:
            cursor = self._conn.execute(
                """
                     SELECT session_id, seq, type, name, args_json, result_json, error,
                         error_type, started_at, duration_ms, tokens_in, tokens_out, cost_usd,
                         provider, model, tokens_total, cached_tokens, cost_status, cost_currency
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
                        provider=row["provider"],
                        model=row["model"],
                        tokens_total=row["tokens_total"],
                        cached_tokens=row["cached_tokens"],
                        cost_status=(
                            "estimated"
                            if row["cost_status"] in (None, "unavailable") and row["cost_usd"]
                            else (row["cost_status"] or "unavailable")
                        ),
                        cost_currency=row["cost_currency"],
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

    def get_session_metadata(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT metadata_json FROM sessions WHERE session_id = ?;",
                (session_id,),
            ).fetchone()
        if not row or not row["metadata_json"]:
            return {}
        try:
            metadata = json.loads(row["metadata_json"])
        except (TypeError, ValueError):
            return {}
        return metadata if isinstance(metadata, dict) else {}

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

    def create_experiment(
        self,
        experiment_id: str,
        baseline_session_id: str,
        fork_session_id: str,
        result: dict[str, Any],
    ) -> None:
        created_at = datetime.now(UTC).isoformat()
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO experiments (
                        experiment_id, created_at, baseline_session_id, fork_session_id,
                        result_json
                    ) VALUES (?, ?, ?, ?, ?);
                    """,
                    (
                        experiment_id,
                        created_at,
                        baseline_session_id,
                        fork_session_id,
                        json.dumps(result),
                    ),
                )

    def get_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT experiment_id, created_at, baseline_session_id, fork_session_id,
                    result_json
                FROM experiments WHERE experiment_id = ?;
                """,
                (experiment_id,),
            ).fetchone()
        if not row:
            return None
        try:
            result = json.loads(row["result_json"])
        except (TypeError, ValueError):
            return None
        if not isinstance(result, dict):
            return None
        return {
            "experiment_id": row["experiment_id"],
            "created_at": row["created_at"],
            "baseline_session_id": row["baseline_session_id"],
            "fork_session_id": row["fork_session_id"],
            "result": result,
        }

    def list_experiments(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT experiment_id, created_at, baseline_session_id, fork_session_id
                FROM experiments ORDER BY created_at DESC;
                """
            ).fetchall()
        return [
            {
                "experiment_id": row["experiment_id"],
                "created_at": row["created_at"],
                "baseline_session_id": row["baseline_session_id"],
                "fork_session_id": row["fork_session_id"],
            }
            for row in rows
        ]

    def create_evaluation(
        self,
        evaluation_id: str,
        target_type: str,
        session_id: str | None,
        experiment_id: str | None,
        criteria: dict[str, Any],
        result: dict[str, Any],
        suite_id: str | None = None,
        suite_version: int | None = None,
    ) -> dict[str, Any]:
        evaluated_at = result["evaluated_at"]
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO evaluations (
                        evaluation_id, evaluated_at, target_type, session_id, experiment_id,
                        criteria_json, result_json, suite_id, suite_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        evaluation_id,
                        evaluated_at,
                        target_type,
                        session_id,
                        experiment_id,
                        json.dumps(criteria),
                        json.dumps(result),
                        suite_id,
                        suite_version,
                    ),
                )
        return {
            "evaluation_id": evaluation_id,
            "evaluated_at": evaluated_at,
            "target_type": target_type,
            "session_id": session_id,
            "experiment_id": experiment_id,
            "criteria": criteria,
            "result": result,
            "suite_id": suite_id,
            "suite_version": suite_version,
        }

    def list_evaluations(
        self,
        session_id: str | None = None,
        experiment_id: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions = []
        parameters: list[str] = []
        if session_id is not None:
            conditions.append("session_id = ?")
            parameters.append(session_id)
        if experiment_id is not None:
            conditions.append("experiment_id = ?")
            parameters.append(experiment_id)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT evaluation_id, evaluated_at, target_type, session_id, experiment_id,
                criteria_json, result_json, suite_id, suite_version
                FROM evaluations {where}
                ORDER BY evaluated_at DESC, evaluation_id DESC;
                """,
                parameters,
            ).fetchall()
        evaluations = []
        for row in rows:
            try:
                criteria = json.loads(row["criteria_json"])
                result = json.loads(row["result_json"])
            except (TypeError, ValueError):
                continue
            evaluations.append(
                {
                    "evaluation_id": row["evaluation_id"],
                    "evaluated_at": row["evaluated_at"],
                    "target_type": row["target_type"],
                    "session_id": row["session_id"],
                    "experiment_id": row["experiment_id"],
                    "criteria": criteria,
                    "result": result,
                    "suite_id": row["suite_id"],
                    "suite_version": row["suite_version"],
                }
            )
        return evaluations

    def create_evaluation_suite(
        self,
        suite_id: str,
        version: int,
        name: str,
        description: str,
        criteria: dict[str, Any],
        evaluator_version: str,
    ) -> dict[str, Any]:
        created_at = datetime.now(UTC).isoformat()
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO evaluation_suites (
                        suite_id, version, name, description, criteria_json,
                        evaluator_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        suite_id,
                        version,
                        name,
                        description,
                        json.dumps(criteria),
                        evaluator_version,
                        created_at,
                    ),
                )
        return {
            "suite_id": suite_id,
            "version": version,
            "name": name,
            "description": description,
            "criteria": criteria,
            "evaluator_version": evaluator_version,
            "created_at": created_at,
        }

    def get_evaluation_suite(
        self, suite_id: str, version: int | None = None
    ) -> dict[str, Any] | None:
        with self._lock:
            if version is None:
                row = self._conn.execute(
                    """
                    SELECT suite_id, version, name, description, criteria_json,
                        evaluator_version, created_at
                    FROM evaluation_suites WHERE suite_id = ?
                    ORDER BY version DESC LIMIT 1;
                    """,
                    (suite_id,),
                ).fetchone()
            else:
                row = self._conn.execute(
                    """
                    SELECT suite_id, version, name, description, criteria_json,
                        evaluator_version, created_at
                    FROM evaluation_suites WHERE suite_id = ? AND version = ?;
                    """,
                    (suite_id, version),
                ).fetchone()
        if not row:
            return None
        try:
            criteria = json.loads(row["criteria_json"])
        except (TypeError, ValueError):
            return None
        return {
            "suite_id": row["suite_id"],
            "version": row["version"],
            "name": row["name"],
            "description": row["description"],
            "criteria": criteria,
            "evaluator_version": row["evaluator_version"],
            "created_at": row["created_at"],
        }

    def list_evaluation_suites(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT suite_id, MAX(version) AS version
                FROM evaluation_suites GROUP BY suite_id
                ORDER BY suite_id;
                """
            ).fetchall()
        suites = []
        for row in rows:
            suite = self.get_evaluation_suite(row["suite_id"], row["version"])
            if suite is not None:
                suites.append(suite)
        return suites

    def list_evaluation_suite_versions(self, suite_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT version FROM evaluation_suites
                WHERE suite_id = ? ORDER BY version DESC;
                """,
                (suite_id,),
            ).fetchall()
        versions = []
        for row in rows:
            suite = self.get_evaluation_suite(suite_id, row["version"])
            if suite is not None:
                versions.append(suite)
        return versions

    def create_replay_validation(
        self,
        validation_id: str,
        session_id: str,
        validated_at: str,
        validation_version: str,
        status: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO replay_validations (
                        validation_id, session_id, validated_at, validation_version,
                        status, result_json
                    ) VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    (
                        validation_id,
                        session_id,
                        validated_at,
                        validation_version,
                        status,
                        json.dumps(result),
                    ),
                )
        return {
            "validation_id": validation_id,
            "session_id": session_id,
            "validated_at": validated_at,
            "validation_version": validation_version,
            "status": status,
            "result": result,
        }

    def list_replay_validations(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT validation_id, session_id, validated_at, validation_version,
                    status, result_json
                FROM replay_validations
                WHERE session_id = ?
                ORDER BY validated_at DESC, validation_id DESC;
                """,
                (session_id,),
            ).fetchall()
        validations = []
        for row in rows:
            try:
                result = json.loads(row["result_json"])
            except (TypeError, ValueError):
                continue
            validations.append(
                {
                    "validation_id": row["validation_id"],
                    "session_id": row["session_id"],
                    "validated_at": row["validated_at"],
                    "validation_version": row["validation_version"],
                    "status": row["status"],
                    "result": result,
                }
            )
        return validations
