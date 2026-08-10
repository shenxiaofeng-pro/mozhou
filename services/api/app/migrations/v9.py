import hashlib
import sqlite3
from datetime import UTC, datetime

GLOBAL_REFERENCE_SCHEMA = """
CREATE TABLE reference_works_v9 (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
    source_filename TEXT NOT NULL CHECK(length(source_filename) BETWEEN 1 AND 255),
    source_format TEXT NOT NULL CHECK(source_format IN ('txt', 'markdown', 'pdf')),
    rights_basis TEXT NOT NULL CHECK(rights_basis IN ('self_owned', 'authorized', 'public_domain')),
    total_characters INTEGER NOT NULL CHECK(total_characters BETWEEN 1 AND 20000000),
    segment_target_characters INTEGER NOT NULL CHECK(segment_target_characters BETWEEN 100000 AND 1000000),
    content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
    source_encoding TEXT NOT NULL CHECK(length(source_encoding) BETWEEN 1 AND 40),
    encoding_confidence REAL NOT NULL CHECK(encoding_confidence BETWEEN 0 AND 1),
    import_state TEXT NOT NULL CHECK(import_state IN ('ready', 'needs_review')),
    duplicate_of_id TEXT REFERENCES reference_works_v9(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE reference_segments_v9 (
    id TEXT PRIMARY KEY,
    reference_work_id TEXT NOT NULL REFERENCES reference_works_v9(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK(ordinal > 0),
    start_char INTEGER NOT NULL CHECK(start_char >= 0),
    end_char INTEGER NOT NULL CHECK(end_char > start_char),
    character_count INTEGER NOT NULL CHECK(character_count > 0),
    chapter_start TEXT CHECK(chapter_start IS NULL OR length(chapter_start) <= 120),
    chapter_end TEXT CHECK(chapter_end IS NULL OR length(chapter_end) <= 120),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK(end_char - start_char = character_count),
    UNIQUE(reference_work_id, ordinal)
);

CREATE TABLE project_reference_works_v9 (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    reference_work_id TEXT NOT NULL REFERENCES reference_works_v9(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY(project_id, reference_work_id)
);
"""


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _migrate_project_owned_works(connection: sqlite3.Connection) -> None:
    legacy_works = connection.execute(
        "SELECT * FROM reference_works ORDER BY created_at, id"
    ).fetchall()
    contents_by_work: dict[str, str] = {}
    for row in connection.execute(
        "SELECT reference_work_id, content FROM reference_segments ORDER BY reference_work_id, ordinal"
    ):
        contents_by_work[str(row[0])] = contents_by_work.get(str(row[0]), "") + str(row[1])

    connection.executescript(GLOBAL_REFERENCE_SCHEMA)
    for row in legacy_works:
        values = tuple(row)
        work_id = str(values[0])
        project_id = str(values[1])
        content = contents_by_work.get(work_id, "")
        created_at = str(values[8])
        connection.execute(
            """
            INSERT INTO reference_works_v9 (
                id, title, source_filename, source_format, rights_basis,
                total_characters, segment_target_characters, content_sha256,
                source_encoding, encoding_confidence, import_state,
                duplicate_of_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'utf-8', 1.0, 'ready', NULL, ?, ?)
            """,
            (
                work_id,
                values[2],
                values[3],
                values[4],
                values[5],
                values[6],
                values[7],
                hashlib.sha256(content.encode("utf-8")).hexdigest(),
                created_at,
                created_at,
            ),
        )
        connection.execute(
            "INSERT INTO project_reference_works_v9 VALUES (?, ?, ?)",
            (project_id, work_id, created_at),
        )

    connection.execute(
        """
        INSERT INTO reference_segments_v9 (
            id, reference_work_id, ordinal, start_char, end_char,
            character_count, chapter_start, chapter_end, content, created_at
        )
        SELECT id, reference_work_id, ordinal, start_char, end_char,
               character_count, chapter_start, chapter_end, content, created_at
        FROM reference_segments
        """
    )
    connection.execute("DROP TABLE reference_segments")
    connection.execute("DROP TABLE reference_works")
    connection.execute("ALTER TABLE reference_works_v9 RENAME TO reference_works")
    connection.execute("ALTER TABLE reference_segments_v9 RENAME TO reference_segments")
    connection.execute("ALTER TABLE project_reference_works_v9 RENAME TO project_reference_works")


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Promote project-owned reference texts into reusable global library assets."""
    if "project_id" in _columns(connection, "reference_works"):
        _migrate_project_owned_works(connection)
    connection.executescript(schema)
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (9, "global_reference_library", datetime.now(UTC).isoformat()),
    )
