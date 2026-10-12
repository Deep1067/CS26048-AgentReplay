import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure root directory is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Load .env
load_dotenv(PROJECT_ROOT / ".env")


def main():
    db_path = PROJECT_ROOT / "agent_replay.db"
    if not db_path.exists():
        print(f"Local database file not found at {db_path}")
        sys.exit(1)

    remote_url = os.getenv("TURSO_DATABASE_URL")
    remote_token = os.getenv("TURSO_AUTH_TOKEN")

    if not remote_url or not remote_token:
        print(
            "Error: TURSO_DATABASE_URL and TURSO_AUTH_TOKEN "
            "environment variables must be set in .env"
        )
        sys.exit(1)

    print(f"Connecting to local SQLite database: {db_path}")
    local_conn = sqlite3.connect(db_path)
    local_conn.row_factory = sqlite3.Row

    print(f"Connecting to remote Turso database at {remote_url}...")
    import turso_serverless

    turso_conn = turso_serverless.connect(remote_url, auth_token=remote_token)
    turso_conn.row_factory = turso_serverless.Row

    # Ensure remote tables exist
    with turso_conn:
        turso_conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                metadata_json TEXT
            );
        """)
        turso_conn.execute("""
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
        turso_conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_session_seq
            ON events (session_id, seq);
        """)
        turso_conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL
            );
        """)

    # Get existing session IDs in Turso
    turso_sessions = {
        row["session_id"]
        for row in turso_conn.execute("SELECT session_id FROM sessions;").fetchall()
    }

    # Fetch local sessions
    local_sessions = local_conn.execute(
        "SELECT * FROM sessions ORDER BY started_at ASC;"
    ).fetchall()

    sessions_imported = 0
    sessions_skipped = 0
    events_imported = 0

    with turso_conn:
        for sess in local_sessions:
            session_id = sess["session_id"]
            if session_id in turso_sessions:
                sessions_skipped += 1
                continue

            # Insert session
            turso_conn.execute(
                "INSERT INTO sessions (session_id, started_at, metadata_json) VALUES (?, ?, ?);",
                (sess["session_id"], sess["started_at"], sess["metadata_json"]),
            )
            sessions_imported += 1

            # Fetch local events for this session
            local_events = local_conn.execute(
                """
                SELECT session_id, seq, type, name, args_json, result_json, error, error_type,
                       started_at, duration_ms, tokens_in, tokens_out, cost_usd
                FROM events
                WHERE session_id = ?
                ORDER BY seq ASC;
                """,
                (session_id,),
            ).fetchall()

            for ev in local_events:
                turso_conn.execute(
                    """
                    INSERT INTO events (
                        session_id, seq, type, name, args_json, result_json, error, error_type,
                        started_at, duration_ms, tokens_in, tokens_out, cost_usd
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        ev["session_id"],
                        ev["seq"],
                        ev["type"],
                        ev["name"],
                        ev["args_json"],
                        ev["result_json"],
                        ev["error"],
                        ev["error_type"],
                        ev["started_at"],
                        ev["duration_ms"],
                        ev["tokens_in"],
                        ev["tokens_out"],
                        ev["cost_usd"],
                    ),
                )
                events_imported += 1

    print("\n--- Summary ---")
    print(f"Sessions imported: {sessions_imported}")
    print(f"Sessions skipped:  {sessions_skipped}")
    print(f"Events imported:   {events_imported}")


if __name__ == "__main__":
    main()
