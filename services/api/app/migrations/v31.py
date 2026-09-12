import sqlite3
from datetime import UTC, datetime

from app.canon_reconciliation.schema import CANON_RECONCILIATION_SCHEMA_SQL


def _chapter_versions_schema() -> str:
    return """
        CREATE TABLE chapter_versions_v31 (
            id TEXT PRIMARY KEY,
            chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL CHECK(version_number > 0),
            chapter_revision INTEGER NOT NULL CHECK(chapter_revision >= 0),
            content TEXT NOT NULL CHECK(length(content) <= 2000000),
            content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
            source TEXT NOT NULL CHECK(source IN (
                'initial', 'manual_save', 'generation_candidate',
                'generation_apply', 'change_set_apply', 'rollback', 'approval'
            )),
            source_id TEXT,
            parent_version_id TEXT REFERENCES chapter_versions_v31(id) ON DELETE SET NULL,
            is_candidate INTEGER NOT NULL DEFAULT 0 CHECK(is_candidate IN (0, 1)),
            created_at TEXT NOT NULL,
            UNIQUE(chapter_id, version_number)
        );
    """


def _context_packets_schema() -> str:
    return """
        CREATE TABLE context_packets_v31 (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            chapter_id TEXT REFERENCES chapters(id) ON DELETE CASCADE,
            chapter_revision INTEGER CHECK(chapter_revision IS NULL OR chapter_revision >= 0),
            task_type TEXT CHECK(
                task_type IS NULL OR task_type IN ('chapter_brief', 'chapter_draft')
            ),
            purpose TEXT NOT NULL CHECK(purpose IN (
                'startup', 'expansion', 'field', 'brief', 'draft',
                'candidate_review', 'canon_reconciliation', 'preference'
            )),
            subject_json TEXT NOT NULL CHECK(json_valid(subject_json)),
            profile_fingerprint_sha256 TEXT CHECK(
                profile_fingerprint_sha256 IS NULL
                OR length(profile_fingerprint_sha256) = 64
            ),
            dependency_snapshot_json TEXT NOT NULL CHECK(json_valid(dependency_snapshot_json)),
            dependency_fingerprint_sha256 TEXT NOT NULL
                CHECK(length(dependency_fingerprint_sha256) = 64),
            blocking_reasons_json TEXT NOT NULL DEFAULT '[]'
                CHECK(json_valid(blocking_reasons_json)),
            compiler_version TEXT NOT NULL CHECK(length(compiler_version) BETWEEN 1 AND 80),
            token_budget INTEGER NOT NULL CHECK(token_budget BETWEEN 1000 AND 200000),
            used_tokens INTEGER NOT NULL CHECK(used_tokens > 0),
            overflow_tokens INTEGER NOT NULL CHECK(overflow_tokens >= 0),
            packet_sha256 TEXT NOT NULL CHECK(length(packet_sha256) = 64),
            source_fingerprint_sha256 TEXT NOT NULL
                CHECK(length(source_fingerprint_sha256) = 64),
            packet_json TEXT NOT NULL CHECK(length(packet_json) BETWEEN 2 AND 5000000),
            rendered_context TEXT NOT NULL CHECK(length(rendered_context) BETWEEN 2 AND 5000000),
            created_at TEXT NOT NULL,
            CHECK((chapter_id IS NULL) = (chapter_revision IS NULL)),
            UNIQUE(project_id, purpose, packet_sha256)
        );
    """


def _rebuild_constrained_tables(connection: sqlite3.Connection) -> None:
    connection.commit()
    connection.execute("PRAGMA foreign_keys=OFF")
    try:
        connection.execute("DROP INDEX IF EXISTS idx_chapter_versions_source")
        connection.execute("DROP INDEX IF EXISTS idx_chapter_versions_chapter_number")
        connection.executescript(_chapter_versions_schema())
        connection.execute(
            """
            INSERT INTO chapter_versions_v31 (
                id, chapter_id, version_number, chapter_revision, content,
                content_sha256, source, source_id, parent_version_id,
                is_candidate, created_at
            )
            SELECT id, chapter_id, version_number, chapter_revision, content,
                   content_sha256, source, source_id, parent_version_id,
                   is_candidate, created_at
            FROM chapter_versions
            """
        )
        connection.execute("DROP TABLE chapter_versions")
        connection.execute("ALTER TABLE chapter_versions_v31 RENAME TO chapter_versions")
        connection.execute(
            """
            CREATE UNIQUE INDEX idx_chapter_versions_source
            ON chapter_versions(chapter_id, source, source_id)
            WHERE source_id IS NOT NULL AND source IN (
                'generation_candidate', 'generation_apply',
                'change_set_apply', 'approval'
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX idx_chapter_versions_chapter_number
            ON chapter_versions(chapter_id, version_number DESC)
            """
        )

        connection.execute("DROP INDEX IF EXISTS idx_context_packets_chapter_created")
        connection.execute("DROP INDEX IF EXISTS idx_context_packets_project_purpose_created")
        connection.executescript(_context_packets_schema())
        connection.execute(
            """
            INSERT INTO context_packets_v31 (
                id, project_id, chapter_id, chapter_revision, task_type,
                purpose, subject_json, profile_fingerprint_sha256,
                dependency_snapshot_json, dependency_fingerprint_sha256,
                blocking_reasons_json, compiler_version, token_budget,
                used_tokens, overflow_tokens, packet_sha256,
                source_fingerprint_sha256, packet_json, rendered_context,
                created_at
            )
            SELECT id, project_id, chapter_id, chapter_revision, task_type,
                   purpose, subject_json, profile_fingerprint_sha256,
                   dependency_snapshot_json, dependency_fingerprint_sha256,
                   blocking_reasons_json, compiler_version, token_budget,
                   used_tokens, overflow_tokens, packet_sha256,
                   source_fingerprint_sha256, packet_json, rendered_context,
                   created_at
            FROM context_packets
            """
        )
        connection.execute("DROP TABLE context_packets")
        connection.execute("ALTER TABLE context_packets_v31 RENAME TO context_packets")
        connection.execute(
            """
            CREATE INDEX idx_context_packets_chapter_created
            ON context_packets(chapter_id, created_at DESC, id DESC)
            """
        )
        connection.execute(
            """
            CREATE INDEX idx_context_packets_project_purpose_created
            ON context_packets(project_id, purpose, created_at DESC, id DESC)
            """
        )
        connection.commit()
    finally:
        connection.execute("PRAGMA foreign_keys=ON")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise sqlite3.IntegrityError("v31 constrained table rebuild failed")


def upgrade(connection: sqlite3.Connection, _schema: str) -> None:
    """Install approval-driven Canon reconciliation and author preferences."""

    _rebuild_constrained_tables(connection)
    connection.executescript(CANON_RECONCILIATION_SCHEMA_SQL)
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (31, "canon_reconciliation_and_author_preferences", datetime.now(UTC).isoformat()),
    )
