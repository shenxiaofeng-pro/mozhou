import sqlite3
from datetime import UTC, datetime


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Record raw-file identity, page provenance and reusable analysis assets."""
    columns = _columns(connection, "reference_works")
    if "source_sha256" not in columns:
        connection.execute("ALTER TABLE reference_works ADD COLUMN source_sha256 TEXT")
        connection.execute("UPDATE reference_works SET source_sha256 = content_sha256")
    if "source_spans_json" not in columns:
        connection.execute(
            "ALTER TABLE reference_works ADD COLUMN source_spans_json TEXT NOT NULL DEFAULT '[]'"
        )
    connection.executescript(schema)
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (10, "safe_reference_imports", datetime.now(UTC).isoformat()),
    )
