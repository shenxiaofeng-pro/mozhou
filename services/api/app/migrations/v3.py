import sqlite3
from datetime import UTC, datetime

MIGRATION_NAMES = (
    (1, "initial_schema"),
    (2, "chapter_brief_and_ai_provenance"),
    (3, "migration_history"),
)


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add an auditable migration ledger and backfill the known migration chain."""
    del schema
    connection.execute(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY CHECK(version > 0),
            name TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL
        )
        """
    )
    applied_at = datetime.now(UTC).isoformat()
    connection.executemany(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        [(version, name, applied_at) for version, name in MIGRATION_NAMES],
    )
