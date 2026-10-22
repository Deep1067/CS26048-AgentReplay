import sqlite3

import pytest

from agent_replay.storage import SQLiteStorage


def test_explicit_db_path_selects_local_storage_when_turso_is_configured(monkeypatch, tmp_path):
    database_path = tmp_path / "isolated.db"
    monkeypatch.setenv("DB_PATH", str(database_path))
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://configured.example")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "test-only-token")

    storage = SQLiteStorage()

    assert not storage.is_remote
    assert storage.db_path == str(database_path)
    assert database_path.exists()
    storage._conn.close()


@pytest.mark.parametrize(
    ("configured_variable", "missing_variable"),
    [
        ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"),
        ("TURSO_AUTH_TOKEN", "TURSO_DATABASE_URL"),
    ],
)
def test_partial_turso_configuration_fails_clearly(
    monkeypatch, tmp_path, configured_variable, missing_variable
):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.setattr("agent_replay.storage.DB_PATH", str(tmp_path / "default.db"))
    monkeypatch.setenv(configured_variable, "configured")
    monkeypatch.delenv(missing_variable, raising=False)

    with pytest.raises(RuntimeError, match="TURSO_DATABASE_URL and TURSO_AUTH_TOKEN"):
        SQLiteStorage()


def test_vercel_requires_turso_persistence(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("DB_PATH", raising=False)

    with pytest.raises(RuntimeError, match="Vercel storage requires both"):
        SQLiteStorage()


def test_vercel_rejects_db_path_override_even_when_turso_is_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ephemeral.db"))
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://configured.example")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "test-only-token")

    with pytest.raises(RuntimeError, match="DB_PATH cannot select local SQLite on Vercel"):
        SQLiteStorage()


def test_legacy_sqlite_schema_is_migrated_on_startup(tmp_path):
    database_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            metadata_json TEXT
        );
        CREATE TABLE events (
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
            UNIQUE (session_id, seq)
        );
        CREATE TABLE evaluations (
            evaluation_id TEXT PRIMARY KEY,
            evaluated_at TEXT NOT NULL,
            target_type TEXT NOT NULL,
            session_id TEXT,
            experiment_id TEXT,
            criteria_json TEXT NOT NULL,
            result_json TEXT NOT NULL
        );
        """
    )
    connection.close()

    storage = SQLiteStorage(db_path=database_path)
    event_columns = {
        row["name"] for row in storage._conn.execute("PRAGMA table_info(events);").fetchall()
    }
    evaluation_columns = {
        row["name"] for row in storage._conn.execute("PRAGMA table_info(evaluations);").fetchall()
    }

    assert {
        "error_type",
        "provider",
        "model",
        "tokens_total",
        "cached_tokens",
        "cost_status",
        "cost_currency",
    } <= event_columns
    assert {"suite_id", "suite_version"} <= evaluation_columns
    storage.check_health()
    storage._conn.close()
