import sqlite3
from datetime import UTC, datetime


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add append-only CraftPattern v2 assets and per-project lifecycle links."""
    connection.executescript(schema)
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (25, "craft_pattern_v2", datetime.now(UTC).isoformat()),
    )
