import sqlite3
from datetime import UTC, datetime


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add immutable writing recipes and project-compiled profile snapshots."""
    connection.executescript(schema)
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (26, "writing_pattern_recipes", datetime.now(UTC).isoformat()),
    )
