import sqlite3
from datetime import UTC, datetime


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add the durable AI job runtime without changing legacy generation tables."""
    del schema
    connection.executescript(
        """
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            chapter_id TEXT REFERENCES chapters(id) ON DELETE CASCADE,
            parent_job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN (
                'chapter_brief', 'chapter_draft', 'reference_segment_map',
                'reference_book_reduce', 'reference_fusion', 'review'
            )),
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
            UNIQUE(project_id, kind, idempotency_key),
            CHECK(progress_total = 0 OR progress_current <= progress_total)
        );

        CREATE INDEX idx_jobs_project_updated
        ON jobs(project_id, updated_at DESC, id DESC);

        CREATE INDEX idx_jobs_queue
        ON jobs(state, created_at, id);

        CREATE INDEX idx_jobs_lease
        ON jobs(state, lease_expires_at);

        CREATE TABLE job_chunks (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN (
                'chapter_brief', 'chapter_draft', 'reference_segment_map',
                'reference_book_reduce', 'reference_fusion', 'review'
            )),
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

        CREATE INDEX idx_job_chunks_job_state
        ON job_chunks(job_id, state, ordinal);

        CREATE TABLE job_attempts (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            chunk_id TEXT REFERENCES job_chunks(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL CHECK(ordinal > 0),
            state TEXT NOT NULL CHECK(state IN (
                'running', 'succeeded', 'failed', 'interrupted', 'cancelled'
            )),
            provider TEXT NOT NULL CHECK(length(provider) BETWEEN 1 AND 40),
            model TEXT NOT NULL CHECK(length(model) BETWEEN 1 AND 100),
            input_tokens INTEGER CHECK(input_tokens IS NULL OR input_tokens >= 0),
            output_tokens INTEGER CHECK(output_tokens IS NULL OR output_tokens >= 0),
            error_code TEXT CHECK(error_code IS NULL OR length(error_code) <= 100),
            error_message TEXT CHECK(error_message IS NULL OR length(error_message) <= 1000),
            started_at TEXT NOT NULL,
            completed_at TEXT,
            UNIQUE(job_id, ordinal)
        );

        CREATE INDEX idx_job_attempts_job_chunk
        ON job_attempts(job_id, chunk_id, ordinal);

        CREATE TABLE job_artifacts (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            chunk_id TEXT REFERENCES job_chunks(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(length(kind) BETWEEN 1 AND 100),
            artifact_key TEXT NOT NULL CHECK(length(artifact_key) BETWEEN 1 AND 240),
            content_type TEXT NOT NULL CHECK(content_type IN ('application/json', 'text/plain')),
            payload TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256) = 64),
            metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
            provider TEXT NOT NULL CHECK(length(provider) BETWEEN 1 AND 40),
            model TEXT NOT NULL CHECK(length(model) BETWEEN 1 AND 100),
            created_at TEXT NOT NULL,
            UNIQUE(job_id, artifact_key)
        );

        CREATE INDEX idx_job_artifacts_job_chunk
        ON job_artifacts(job_id, chunk_id, created_at);

        CREATE TABLE job_events (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL CHECK(sequence > 0),
            event_type TEXT NOT NULL CHECK(length(event_type) BETWEEN 1 AND 100),
            from_state TEXT,
            to_state TEXT,
            detail_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(detail_json)),
            created_at TEXT NOT NULL,
            UNIQUE(job_id, sequence)
        );

        CREATE INDEX idx_job_events_job_sequence
        ON job_events(job_id, sequence);
        """
    )
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (4, "durable_ai_jobs", datetime.now(UTC).isoformat()),
    )
