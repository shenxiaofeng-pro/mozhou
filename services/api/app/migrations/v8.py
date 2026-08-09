import sqlite3
from datetime import UTC, datetime


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add immutable context packets and chapter-scoped selection directives."""
    connection.executescript(schema)
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (8, "context_packets", datetime.now(UTC).isoformat()),
    )
