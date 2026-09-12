import sqlite3
from datetime import UTC, datetime

from app.pattern_adaptation.schema import PATTERN_ADAPTATION_SCHEMA_SQL


def upgrade(connection: sqlite3.Connection, _schema: str) -> None:
    """Add AI pattern-adaptation candidates and a revision-bound originality gate."""
    connection.executescript(PATTERN_ADAPTATION_SCHEMA_SQL)
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (27, "pattern_adaptation_originality_gate", datetime.now(UTC).isoformat()),
    )
