import sqlite3
from datetime import UTC, datetime


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Link a materialized reference card to its exactly-once source job."""
    # Some supported v2 fixtures only contain the tables introduced by that
    # version. Complete the frozen business schema before altering the card table.
    connection.executescript(schema)
    connection.execute(
        """
        ALTER TABLE reference_pattern_cards
        ADD COLUMN source_job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX idx_reference_pattern_cards_source_job
        ON reference_pattern_cards(source_job_id)
        WHERE source_job_id IS NOT NULL
        """
    )
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (5, "reference_job_provenance", datetime.now(UTC).isoformat()),
    )
