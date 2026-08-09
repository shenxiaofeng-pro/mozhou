import sqlite3
from datetime import UTC, datetime


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add non-secret model provider profiles."""
    connection.executescript(schema)
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (6, "ai_provider_profiles", datetime.now(UTC).isoformat()),
    )
