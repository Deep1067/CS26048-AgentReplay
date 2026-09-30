import json
import math
import re
import sqlite3

MOCK_DOCS = {
    "pricing": (
        "Gemini 1.5 Flash costs $0.075 per 1M input tokens and $0.30 per 1M output tokens. "
        "Gemini 1.5 Pro costs $3.50 per 1M input tokens and $10.50 per 1M output tokens."
    ),
    "refund_policy": (
        "Full refunds are available within 30 days of purchase for unused credits. "
        "Contact support@example.com with order ID."
    ),
    "database_schema": (
        "The users table contains (id, name, email, plan, balance). "
        "The orders table contains (id, user_id, amount, status)."
    ),
    "deployment": (
        "Agent-replay runs on FastAPI backend with SQLite storage. "
        "Replay engine supports STRICT and FORKED modes."
    ),
}


def search_docs(query: str) -> str:
    """Searches the documentation database for keywords and returns relevant snippets."""
    query_lower = query.lower()
    matches = []
    keywords = [word for word in query_lower.split() if len(word) > 2]
    for topic, text in MOCK_DOCS.items():
        if any(w in text.lower() or w in topic.lower() for w in keywords):
            matches.append(f"[{topic}]: {text}")
    if not matches:
        return f"No documentation found matching '{query}'."
    return "\n\n".join(matches)


def create_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name TEXT,
            email TEXT,
            plan TEXT,
            balance REAL
        );
    """)
    cursor.execute("""
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            amount REAL,
            status TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
    """)
    cursor.executemany(
        """
        INSERT INTO users (id, name, email, plan, balance) VALUES (?, ?, ?, ?, ?);
    """,
        [
            (1, "Alice Smith", "alice@example.com", "enterprise", 250.00),
            (2, "Bob Jones", "bob@example.com", "pro", 45.50),
            (3, "Charlie Brown", "charlie@example.com", "free", 0.00),
        ],
    )
    cursor.executemany(
        """
        INSERT INTO orders (id, user_id, amount, status) VALUES (?, ?, ?, ?);
    """,
        [
            (101, 1, 150.00, "completed"),
            (102, 1, 99.00, "completed"),
            (103, 2, 45.50, "pending"),
        ],
    )
    conn.commit()
    return conn


_DB_CONN = None


def get_shared_db() -> sqlite3.Connection:
    global _DB_CONN
    if _DB_CONN is None:
        _DB_CONN = create_db_connection()
    return _DB_CONN


def query_db(sql: str) -> str:
    """Executes a SQL query on the in-memory SQLite database and returns JSON formatted string."""
    conn = get_shared_db()
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        if sql.strip().upper().startswith("SELECT"):
            columns = [col[0] for col in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            result = [dict(zip(columns, row)) for row in rows]
            return json.dumps(result)
        else:
            conn.commit()
            return json.dumps({"rows_affected": cursor.rowcount})
    except Exception as e:
        return json.dumps({"error": str(e)})


def calculator(expression: str) -> str:
    """Safely evaluates a mathematical expression (e.g. '150 * 0.18 + 45')."""
    clean_expr = expression.strip()
    if not re.match(r"^[\d\s\+\-\*\/\(\)\.\,\%]+$", clean_expr):
        return json.dumps({"error": "Invalid characters in expression."})
    try:
        val = eval(clean_expr, {"__builtins__": {}}, {"math": math})
        return json.dumps({"expression": clean_expr, "result": val})
    except Exception as e:
        return json.dumps({"error": f"Evaluation error: {str(e)}"})
