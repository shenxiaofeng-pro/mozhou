import sqlite3
from datetime import UTC, datetime


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add the editable book-director planning domain and job workflow labels."""
    connection.executescript(schema)
    job_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(jobs)")}
    if "workflow" not in job_columns:
        connection.execute(
            "ALTER TABLE jobs ADD COLUMN workflow TEXT NOT NULL DEFAULT '' "
            "CHECK(length(workflow) <= 80)"
        )
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (13, "book_director_planning", datetime.now(UTC).isoformat()),
    )
