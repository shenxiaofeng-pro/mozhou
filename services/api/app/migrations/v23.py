import sqlite3
from datetime import UTC, datetime


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add an explicit lifecycle to project reference applications."""
    del schema
    columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(reference_pattern_applications)"
        ).fetchall()
    }
    if "lifecycle_state" not in columns:
        connection.execute(
            """
            ALTER TABLE reference_pattern_applications
            ADD COLUMN lifecycle_state TEXT NOT NULL DEFAULT 'active'
                CHECK(lifecycle_state IN ('draft', 'active', 'archived'))
            """
        )
    if "lifecycle_revision" not in columns:
        connection.execute(
            """
            ALTER TABLE reference_pattern_applications
            ADD COLUMN lifecycle_revision INTEGER NOT NULL DEFAULT 0
                CHECK(lifecycle_revision >= 0)
            """
        )
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (23, "reference_application_lifecycle", datetime.now(UTC).isoformat()),
    )
