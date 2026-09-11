import sqlite3
from datetime import UTC, datetime

_JOB_KINDS = """
    'chapter_brief', 'chapter_draft', 'reference_segment_map',
    'reference_book_reduce', 'reference_fusion', 'review', 'sandbox_ai_round',
    'research_extraction', 'comic_season_plan', 'comic_episode_script',
    'topic_decision', 'pattern_adaptation'
"""

_AI_TASK_TYPES = """
    'chapter_brief', 'chapter_draft', 'reference_analysis', 'review',
    'sandbox', 'research', 'comic_season_plan', 'comic_episode_script',
    'pattern_adaptation'
"""


def _add_creative_safety_column(connection: sqlite3.Connection, table: str) -> None:
    columns = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
    if "creative_safety_json" not in columns:
        connection.execute(
            f"ALTER TABLE {table} ADD COLUMN creative_safety_json TEXT "
            "CHECK(creative_safety_json IS NULL OR json_valid(creative_safety_json))"
        )


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add the dedicated pattern-adaptation job and provider task routes."""
    del schema
    connection.commit()
    connection.execute("PRAGMA foreign_keys=OFF")
    try:
        for table in ("generation_runs", "fact_change_sets", "text_change_sets"):
            _add_creative_safety_column(connection, table)
        connection.executescript(
            f"""
            CREATE TABLE jobs_v28 (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                chapter_id TEXT REFERENCES chapters(id) ON DELETE CASCADE,
                parent_job_id TEXT REFERENCES jobs_v28(id) ON DELETE CASCADE,
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
            INSERT INTO jobs_v28 (
                id, project_id, chapter_id, parent_job_id, kind, state,
                idempotency_key, input_json, progress_current, progress_total,
                current_step, estimated_calls, completed_calls, provider, model,
                lease_owner, lease_expires_at, heartbeat_at, error_code, error_message,
                created_at, updated_at, started_at, completed_at, provider_profile_id,
                workflow
            )
            SELECT
                id, project_id, chapter_id, parent_job_id, kind, state,
                idempotency_key, input_json, progress_current, progress_total,
                current_step, estimated_calls, completed_calls, provider, model,
                lease_owner, lease_expires_at, heartbeat_at, error_code, error_message,
                created_at, updated_at, started_at, completed_at, provider_profile_id,
                workflow
            FROM jobs;
            DROP TABLE jobs;
            ALTER TABLE jobs_v28 RENAME TO jobs;
            CREATE INDEX idx_jobs_project_updated ON jobs(project_id, updated_at DESC, id DESC);
            CREATE INDEX idx_jobs_queue ON jobs(state, created_at, id);
            CREATE INDEX idx_jobs_lease ON jobs(state, lease_expires_at);

            CREATE TABLE job_chunks_v28 (
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
            INSERT INTO job_chunks_v28 (
                id, job_id, kind, ordinal, state, idempotency_key, input_json,
                attempt_count, error_code, error_message, created_at, updated_at
            )
            SELECT
                id, job_id, kind, ordinal, state, idempotency_key, input_json,
                attempt_count, error_code, error_message, created_at, updated_at
            FROM job_chunks;
            DROP TABLE job_chunks;
            ALTER TABLE job_chunks_v28 RENAME TO job_chunks;
            CREATE INDEX idx_job_chunks_job_state ON job_chunks(job_id, state, ordinal);

            CREATE TABLE ai_task_defaults_v28 (
                task_type TEXT PRIMARY KEY CHECK(task_type IN ({_AI_TASK_TYPES})),
                profile_id TEXT NOT NULL REFERENCES ai_provider_profiles(id) ON DELETE CASCADE,
                revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
                updated_at TEXT NOT NULL
            );
            INSERT INTO ai_task_defaults_v28 (task_type, profile_id, revision, updated_at)
            SELECT task_type, profile_id, revision, updated_at FROM ai_task_defaults;
            DROP TABLE ai_task_defaults;
            ALTER TABLE ai_task_defaults_v28 RENAME TO ai_task_defaults;
            """
        )
        connection.commit()
    finally:
        connection.execute("PRAGMA foreign_keys=ON")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise sqlite3.IntegrityError("v28 foreign key check failed")
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (28, "pattern_adaptation_job_routing", datetime.now(UTC).isoformat()),
    )
