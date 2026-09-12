import sqlite3
from datetime import UTC, datetime

_JOB_KINDS = """
    'chapter_brief', 'chapter_draft', 'reference_segment_map',
    'reference_book_reduce', 'reference_fusion', 'review', 'sandbox_ai_round'
"""


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add recoverable AI sandbox rounds and a dedicated provider route."""
    del schema
    connection.commit()
    connection.execute("PRAGMA foreign_keys=OFF")
    try:
        connection.executescript(
            f"""
            CREATE TABLE jobs_v19 (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                chapter_id TEXT REFERENCES chapters(id) ON DELETE CASCADE,
                parent_job_id TEXT REFERENCES jobs_v19(id) ON DELETE CASCADE,
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
            INSERT INTO jobs_v19 SELECT
                id, project_id, chapter_id, parent_job_id, kind, state,
                idempotency_key, input_json, progress_current, progress_total,
                current_step, estimated_calls, completed_calls, provider, model,
                lease_owner, lease_expires_at, heartbeat_at, error_code, error_message,
                created_at, updated_at, started_at, completed_at, provider_profile_id, workflow
            FROM jobs;
            DROP TABLE jobs;
            ALTER TABLE jobs_v19 RENAME TO jobs;
            CREATE INDEX idx_jobs_project_updated ON jobs(project_id, updated_at DESC, id DESC);
            CREATE INDEX idx_jobs_queue ON jobs(state, created_at, id);
            CREATE INDEX idx_jobs_lease ON jobs(state, lease_expires_at);

            CREATE TABLE job_chunks_v19 (
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
            INSERT INTO job_chunks_v19 SELECT * FROM job_chunks;
            DROP TABLE job_chunks;
            ALTER TABLE job_chunks_v19 RENAME TO job_chunks;
            CREATE INDEX idx_job_chunks_job_state ON job_chunks(job_id, state, ordinal);

            CREATE TABLE ai_task_defaults_v19 (
                task_type TEXT PRIMARY KEY CHECK(task_type IN (
                    'chapter_brief', 'chapter_draft', 'reference_analysis', 'review', 'sandbox'
                )),
                profile_id TEXT NOT NULL REFERENCES ai_provider_profiles(id) ON DELETE CASCADE,
                revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
                updated_at TEXT NOT NULL
            );
            INSERT INTO ai_task_defaults_v19 SELECT * FROM ai_task_defaults;
            DROP TABLE ai_task_defaults;
            ALTER TABLE ai_task_defaults_v19 RENAME TO ai_task_defaults;
            """
        )
        run_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(sandbox_runs)")
        }
        if "execution_mode" not in run_columns:
            connection.execute(
                "ALTER TABLE sandbox_runs ADD COLUMN execution_mode TEXT NOT NULL "
                "DEFAULT 'rules' CHECK(execution_mode IN ('rules', 'ai'))"
            )
        round_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(sandbox_rounds)")
        }
        if "origin" not in round_columns:
            connection.execute(
                "ALTER TABLE sandbox_rounds ADD COLUMN origin TEXT NOT NULL "
                "DEFAULT 'rules' CHECK(origin IN ('rules', 'ai'))"
            )
        if "model_proposals_json" not in round_columns:
            connection.execute(
                "ALTER TABLE sandbox_rounds ADD COLUMN model_proposals_json TEXT NOT NULL "
                "DEFAULT '[]' CHECK(json_valid(model_proposals_json))"
            )
        if "rejected_proposals_json" not in round_columns:
            connection.execute(
                "ALTER TABLE sandbox_rounds ADD COLUMN rejected_proposals_json TEXT NOT NULL "
                "DEFAULT '[]' CHECK(json_valid(rejected_proposals_json))"
            )
        if "job_id" not in round_columns:
            connection.execute(
                "ALTER TABLE sandbox_rounds ADD COLUMN job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL"
            )
        connection.commit()
    finally:
        connection.execute("PRAGMA foreign_keys=ON")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise sqlite3.IntegrityError("v19 foreign key check failed")
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (19, "ai_narrative_sandbox", datetime.now(UTC).isoformat()),
    )
