import sqlite3
from datetime import UTC, datetime
from uuid import uuid4


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add manuscript hierarchy, reversible directory events, and serial goals."""
    connection.executescript(schema)
    chapter_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(chapters)")
    }
    if "volume_id" not in chapter_columns:
        connection.execute(
            "ALTER TABLE chapters ADD COLUMN volume_id TEXT "
            "REFERENCES manuscript_volumes(id) ON DELETE RESTRICT"
        )
    if "sort_key" not in chapter_columns:
        connection.execute(
            "ALTER TABLE chapters ADD COLUMN sort_key INTEGER NOT NULL DEFAULT 0"
        )
    if "deleted_at" not in chapter_columns:
        connection.execute("ALTER TABLE chapters ADD COLUMN deleted_at TEXT")
    timestamp = datetime.now(UTC).isoformat()
    projects = connection.execute(
        "SELECT id FROM projects ORDER BY created_at, id"
    ).fetchall()
    for project in projects:
        project_id = str(project[0])
        volume_numbers = [
            int(row[0])
            for row in connection.execute(
                "SELECT DISTINCT volume_number FROM chapters "
                "WHERE project_id = ? ORDER BY volume_number",
                (project_id,),
            ).fetchall()
        ] or [1]
        for ordinal, volume_number in enumerate(volume_numbers, start=1):
            existing = connection.execute(
                "SELECT id FROM manuscript_volumes "
                "WHERE project_id = ? AND volume_number = ?",
                (project_id, volume_number),
            ).fetchone()
            volume_id = str(existing[0]) if existing is not None else str(uuid4())
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO manuscript_volumes (
                        id, project_id, volume_number, title, sort_key,
                        revision, deleted_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 0, NULL, ?, ?)
                    """,
                    (
                        volume_id,
                        project_id,
                        volume_number,
                        f"第{volume_number}卷",
                        ordinal * 1024,
                        timestamp,
                        timestamp,
                    ),
                )
            connection.execute(
                """
                UPDATE chapters
                SET volume_id = ?, sort_key = CASE
                    WHEN sort_key <= 0 THEN chapter_number * 1024 ELSE sort_key END
                WHERE project_id = ? AND volume_number = ?
                """,
                (volume_id, project_id, volume_number),
            )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_chapters_volume_sort "
        "ON chapters(volume_id, deleted_at, sort_key, id)"
    )
    if {"project_id", "chapter_number"} <= chapter_columns:
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_chapters_project_active_number "
            "ON chapters(project_id, deleted_at, chapter_number)"
        )
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (15, "manuscript_hierarchy_and_serial_goals", timestamp),
    )
