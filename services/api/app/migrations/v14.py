import hashlib
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add durable reviews, chapter versions, and author-controlled text changes."""
    connection.executescript(schema)
    timestamp = datetime.now(UTC).isoformat()
    chapter_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(chapters)")
    }
    revision_expression = "c.revision" if "revision" in chapter_columns else "0"
    rows = connection.execute(
        f"""
        SELECT c.id, {revision_expression}, c.content
        FROM chapters c
        WHERE NOT EXISTS (
            SELECT 1 FROM chapter_versions v WHERE v.chapter_id = c.id
        )
        ORDER BY c.rowid
        """
    ).fetchall()
    connection.executemany(
        """
        INSERT INTO chapter_versions (
            id, chapter_id, version_number, chapter_revision, content,
            content_sha256, source, source_id, parent_version_id,
            is_candidate, created_at
        ) VALUES (?, ?, 1, ?, ?, ?, 'initial', NULL, NULL, 0, ?)
        """,
        [
            (
                str(uuid4()),
                row[0],
                row[1],
                row[2],
                hashlib.sha256(str(row[2]).encode("utf-8")).hexdigest(),
                timestamp,
            )
            for row in rows
        ],
    )
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (14, "review_versions_and_change_sets", timestamp),
    )
