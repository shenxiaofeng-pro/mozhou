import sqlite3
from datetime import UTC, datetime


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add local-only closed beta feedback and milestone events."""
    connection.executescript(schema)
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (16, "closed_beta_evaluation", datetime.now(UTC).isoformat()),
    )
