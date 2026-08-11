import sqlite3
from datetime import UTC, datetime

_JOB_KINDS = """
    'chapter_brief', 'chapter_draft', 'reference_segment_map',
    'reference_book_reduce', 'reference_fusion', 'review', 'sandbox_ai_round',
    'research_extraction'
"""


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add evidence-linked, review-gated research sessions."""
    del schema
    connection.commit()
    connection.execute("PRAGMA foreign_keys=OFF")
    try:
        connection.executescript(
            f"""
            CREATE TABLE jobs_v20 (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                chapter_id TEXT REFERENCES chapters(id) ON DELETE CASCADE,
                parent_job_id TEXT REFERENCES jobs_v20(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK(kind IN ({_JOB_KINDS})),
                state TEXT NOT NULL CHECK(state IN (
                    'queued', 'running', 'pause_requested', 'cancelled',
                    'succeeded', 'failed', 'interrupted'
                )),
                idempotency_key TEXT NOT NULL CHECK(length(idempotency_key) BETWEEN 1 AND 200),
                input_json TEXT NOT NULL CHECK(json_valid(input_json)),
                progress_current INTEGER NOT NULL DEFAULT 0 CHECK(progress_current >= 0),
                progress_total INTEGER NOT NULL DEFAULT 0 CHECK(progress_total >= 0),
                current_step TEXT NOT NULL DEFAULT '' CHECK(length(current_step) <= 300),
                estimated_calls INTEGER NOT NULL DEFAULT 0 CHECK(estimated_calls >= 0),
                completed_calls INTEGER NOT NULL DEFAULT 0 CHECK(completed_calls >= 0),
                provider TEXT NOT NULL CHECK(length(provider) BETWEEN 1 AND 40),
                model TEXT NOT NULL CHECK(length(model) BETWEEN 1 AND 100),
                lease_owner TEXT CHECK(lease_owner IS NULL OR length(lease_owner) BETWEEN 1 AND 100),
                lease_expires_at TEXT,
                heartbeat_at TEXT,
                error_code TEXT CHECK(error_code IS NULL OR length(error_code) <= 100),
                error_message TEXT CHECK(error_message IS NULL OR length(error_message) <= 1000),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                provider_profile_id TEXT,
                workflow TEXT NOT NULL DEFAULT '' CHECK(length(workflow) <= 80),
                UNIQUE(project_id, kind, idempotency_key),
                CHECK(progress_total = 0 OR progress_current <= progress_total)
            );
            INSERT INTO jobs_v20 SELECT * FROM jobs;
            DROP TABLE jobs;
            ALTER TABLE jobs_v20 RENAME TO jobs;
            CREATE INDEX idx_jobs_project_updated ON jobs(project_id, updated_at DESC, id DESC);
            CREATE INDEX idx_jobs_queue ON jobs(state, created_at, id);
            CREATE INDEX idx_jobs_lease ON jobs(state, lease_expires_at);

            CREATE TABLE job_chunks_v20 (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK(kind IN ({_JOB_KINDS})),
                ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
                state TEXT NOT NULL CHECK(state IN (
                    'queued', 'running', 'cancelled', 'succeeded', 'failed', 'interrupted'
                )),
                idempotency_key TEXT NOT NULL CHECK(length(idempotency_key) BETWEEN 1 AND 200),
                input_json TEXT NOT NULL CHECK(json_valid(input_json)),
                attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
                error_code TEXT CHECK(error_code IS NULL OR length(error_code) <= 100),
                error_message TEXT CHECK(error_message IS NULL OR length(error_message) <= 1000),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(job_id, ordinal),
                UNIQUE(job_id, idempotency_key)
            );
            INSERT INTO job_chunks_v20 SELECT * FROM job_chunks;
            DROP TABLE job_chunks;
            ALTER TABLE job_chunks_v20 RENAME TO job_chunks;
            CREATE INDEX idx_job_chunks_job_state ON job_chunks(job_id, state, ordinal);

            CREATE TABLE ai_task_defaults_v20 (
                task_type TEXT PRIMARY KEY CHECK(task_type IN (
                    'chapter_brief', 'chapter_draft', 'reference_analysis', 'review',
                    'sandbox', 'research'
                )),
                profile_id TEXT NOT NULL REFERENCES ai_provider_profiles(id) ON DELETE CASCADE,
                revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
                updated_at TEXT NOT NULL
            );
            INSERT INTO ai_task_defaults_v20 SELECT * FROM ai_task_defaults;
            DROP TABLE ai_task_defaults;
            ALTER TABLE ai_task_defaults_v20 RENAME TO ai_task_defaults;

            CREATE TABLE IF NOT EXISTS research_sessions (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
                question TEXT NOT NULL CHECK(length(question) BETWEEN 1 AND 1000),
                era_start INTEGER NOT NULL CHECK(era_start BETWEEN -3000 AND 2100),
                era_end INTEGER NOT NULL CHECK(era_end BETWEEN -3000 AND 2100),
                region TEXT NOT NULL CHECK(length(region) BETWEEN 1 AND 120),
                material_type TEXT NOT NULL CHECK(length(material_type) BETWEEN 1 AND 80),
                mode TEXT NOT NULL CHECK(mode IN ('local', 'ai')),
                state TEXT NOT NULL CHECK(state IN ('queued', 'running', 'ready', 'failed', 'cancelled')),
                source_set_sha256 TEXT NOT NULL CHECK(length(source_set_sha256) = 64),
                job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
                invalid_ai_findings INTEGER NOT NULL DEFAULT 0 CHECK(invalid_ai_findings >= 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK(era_end >= era_start)
            );
            CREATE INDEX IF NOT EXISTS idx_research_sessions_project_created
            ON research_sessions(project_id, created_at DESC, id DESC);

            CREATE TABLE IF NOT EXISTS research_sources (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES research_sessions(id) ON DELETE CASCADE,
                source_document_id TEXT REFERENCES source_documents(id) ON DELETE SET NULL,
                label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 255),
                source_format TEXT NOT NULL CHECK(length(source_format) BETWEEN 1 AND 40),
                content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 20000000),
                content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
                source_spans_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(source_spans_json)),
                ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
                created_at TEXT NOT NULL,
                UNIQUE(session_id, ordinal)
            );

            CREATE TABLE IF NOT EXISTS research_findings (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES research_sessions(id) ON DELETE CASCADE,
                research_source_id TEXT NOT NULL REFERENCES research_sources(id) ON DELETE CASCADE,
                source_document_id TEXT REFERENCES source_documents(id) ON DELETE SET NULL,
                category TEXT NOT NULL CHECK(category IN (
                    'historical_event', 'local_system', 'industry_rule',
                    'price_technology', 'controversy'
                )),
                title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
                summary TEXT NOT NULL CHECK(length(summary) BETWEEN 1 AND 1200),
                evidence_excerpt TEXT NOT NULL CHECK(length(evidence_excerpt) BETWEEN 1 AND 4000),
                evidence_sha256 TEXT NOT NULL CHECK(length(evidence_sha256) = 64),
                start_char INTEGER NOT NULL CHECK(start_char >= 0),
                end_char INTEGER NOT NULL CHECK(end_char > start_char),
                page_number_start INTEGER CHECK(page_number_start IS NULL OR page_number_start > 0),
                page_number_end INTEGER CHECK(page_number_end IS NULL OR page_number_end >= page_number_start),
                applicable_year_start INTEGER NOT NULL CHECK(applicable_year_start BETWEEN -3000 AND 2100),
                applicable_year_end INTEGER NOT NULL CHECK(applicable_year_end BETWEEN -3000 AND 2100),
                region TEXT NOT NULL CHECK(length(region) BETWEEN 1 AND 120),
                confidence TEXT NOT NULL CHECK(confidence IN ('high', 'medium', 'low')),
                conflict_key TEXT NOT NULL DEFAULT '' CHECK(length(conflict_key) <= 200),
                origin TEXT NOT NULL CHECK(origin IN ('local', 'ai')),
                state TEXT NOT NULL CHECK(state IN ('candidate', 'approved', 'rejected')),
                source_card_id TEXT REFERENCES source_cards(id) ON DELETE SET NULL,
                revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(session_id, research_source_id, start_char, end_char, category, title),
                CHECK(applicable_year_end >= applicable_year_start)
            );
            CREATE INDEX IF NOT EXISTS idx_research_findings_session_state
            ON research_findings(session_id, state, created_at, id);
            """
        )
        connection.commit()
    finally:
        connection.execute("PRAGMA foreign_keys=ON")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise sqlite3.IntegrityError("v20 foreign key check failed")
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (20, "research_agent", datetime.now(UTC).isoformat()),
    )
