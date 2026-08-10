import sqlite3
from datetime import UTC, datetime


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add immutable narrative sandbox snapshots, branches, runs, and candidates."""
    connection.executescript(schema)
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (17, "narrative_sandbox", datetime.now(UTC).isoformat()),
    )
