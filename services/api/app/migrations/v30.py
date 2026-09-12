from datetime import UTC, datetime
from sqlite3 import Connection

from app.chapter_production.schema import CHAPTER_PRODUCTION_SCHEMA_SQL


def upgrade(connection: Connection, _schema: str) -> None:
    """Install the durable ChapterProduction aggregate."""

    connection.executescript(CHAPTER_PRODUCTION_SCHEMA_SQL)
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (30, "chapter_production_workbench", datetime.now(UTC).isoformat()),
    )
