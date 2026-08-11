import sqlite3
from datetime import UTC, datetime


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Enable safe ZIP document formats and author productivity ledgers."""
    del schema
    connection.commit()
    connection.execute("PRAGMA foreign_keys=OFF")
    try:
        connection.executescript(
            """
            CREATE TABLE source_documents_v21 (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
                source_filename TEXT NOT NULL CHECK(length(source_filename) BETWEEN 1 AND 255),
                source_format TEXT NOT NULL CHECK(source_format IN ('txt', 'markdown', 'pdf', 'docx', 'epub')),
                source_sha256 TEXT NOT NULL CHECK(length(source_sha256) = 64),
                content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
                source_encoding TEXT NOT NULL CHECK(length(source_encoding) BETWEEN 1 AND 40),
                encoding_confidence REAL NOT NULL CHECK(encoding_confidence BETWEEN 0 AND 1),
                import_state TEXT NOT NULL CHECK(import_state IN ('ready', 'needs_review')),
                source_spans_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(source_spans_json)),
                duplicate_of_id TEXT REFERENCES source_documents_v21(id) ON DELETE SET NULL,
                content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 20000000),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO source_documents_v21 SELECT * FROM source_documents;
            DROP TABLE source_documents;
            ALTER TABLE source_documents_v21 RENAME TO source_documents;
            CREATE INDEX idx_source_documents_hash_created ON source_documents(content_sha256, created_at, id);

            CREATE TABLE reference_works_v21 (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
                source_filename TEXT NOT NULL CHECK(length(source_filename) BETWEEN 1 AND 255),
                source_format TEXT NOT NULL CHECK(source_format IN ('txt', 'markdown', 'pdf', 'docx', 'epub')),
                rights_basis TEXT NOT NULL CHECK(rights_basis IN ('self_owned', 'authorized', 'public_domain')),
                total_characters INTEGER NOT NULL CHECK(total_characters BETWEEN 1 AND 20000000),
                segment_target_characters INTEGER NOT NULL CHECK(segment_target_characters BETWEEN 100000 AND 1000000),
                content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
                source_sha256 TEXT NOT NULL CHECK(length(source_sha256) = 64),
                source_encoding TEXT NOT NULL CHECK(length(source_encoding) BETWEEN 1 AND 40),
                encoding_confidence REAL NOT NULL CHECK(encoding_confidence BETWEEN 0 AND 1),
                import_state TEXT NOT NULL CHECK(import_state IN ('ready', 'needs_review')),
                source_spans_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(source_spans_json)),
                duplicate_of_id TEXT REFERENCES reference_works_v21(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO reference_works_v21 SELECT * FROM reference_works;
            DROP TABLE reference_works;
            ALTER TABLE reference_works_v21 RENAME TO reference_works;
            CREATE INDEX idx_reference_works_hash_created ON reference_works(content_sha256, created_at, id);

            CREATE TABLE IF NOT EXISTS chapter_annotations (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
                chapter_revision INTEGER NOT NULL CHECK(chapter_revision >= 0),
                content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
                start_char INTEGER NOT NULL CHECK(start_char >= 0),
                end_char INTEGER NOT NULL CHECK(end_char > start_char),
                selected_text TEXT NOT NULL CHECK(length(selected_text) BETWEEN 1 AND 1000),
                context_before TEXT NOT NULL DEFAULT '' CHECK(length(context_before) <= 200),
                context_after TEXT NOT NULL DEFAULT '' CHECK(length(context_after) <= 200),
                comment TEXT NOT NULL CHECK(length(comment) BETWEEN 1 AND 2000),
                status TEXT NOT NULL CHECK(status IN ('open', 'resolved', 'stale')),
                revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chapter_annotations_chapter_status ON chapter_annotations(chapter_id, status, created_at);

            CREATE TABLE IF NOT EXISTS author_ideas (
                id TEXT PRIMARY KEY,
                project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
                title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 160),
                content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 5000),
                tags_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(tags_json)),
                status TEXT NOT NULL CHECK(status IN ('inbox', 'planned', 'applied', 'archived')),
                target_kind TEXT CHECK(target_kind IS NULL OR target_kind IN ('chapter_brief', 'source_card', 'character')),
                target_id TEXT,
                revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_author_ideas_project_status ON author_ideas(project_id, status, updated_at DESC);

            CREATE TABLE IF NOT EXISTS story_relationships (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                source_entity_id TEXT NOT NULL REFERENCES story_entities(id) ON DELETE CASCADE,
                target_entity_id TEXT NOT NULL REFERENCES story_entities(id) ON DELETE CASCADE,
                relation_type TEXT NOT NULL CHECK(length(relation_type) BETWEEN 1 AND 80),
                summary TEXT NOT NULL DEFAULT '' CHECK(length(summary) <= 1000),
                status TEXT NOT NULL CHECK(status IN ('active', 'historical')),
                source_chapter_id TEXT REFERENCES chapters(id) ON DELETE SET NULL,
                revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK(source_entity_id <> target_entity_id)
            );
            CREATE INDEX IF NOT EXISTS idx_story_relationships_project ON story_relationships(project_id, status, created_at);
            """
        )
        connection.commit()
    finally:
        connection.execute("PRAGMA foreign_keys=ON")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise sqlite3.IntegrityError("v21 foreign key check failed")
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (21, "document_formats_and_author_productivity", datetime.now(UTC).isoformat()),
    )
