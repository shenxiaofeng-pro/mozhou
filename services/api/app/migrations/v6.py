import sqlite3
from datetime import UTC, datetime


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add non-secret model provider profiles."""
    connection.executescript(schema)
    connection.execute("ALTER TABLE jobs ADD COLUMN provider_profile_id TEXT")
    connection.execute("ALTER TABLE job_attempts ADD COLUMN provider_profile_id TEXT")
    connection.execute("ALTER TABLE job_artifacts ADD COLUMN provider_profile_id TEXT")
    connection.execute(
        "ALTER TABLE job_attempts ADD COLUMN duration_ms INTEGER "
        "CHECK(duration_ms IS NULL OR duration_ms >= 0)"
    )
    connection.execute(
        "ALTER TABLE job_attempts ADD COLUMN estimated_cost_microusd INTEGER "
        "CHECK(estimated_cost_microusd IS NULL OR estimated_cost_microusd >= 0)"
    )
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (6, "ai_provider_profiles", datetime.now(UTC).isoformat()),
    )
