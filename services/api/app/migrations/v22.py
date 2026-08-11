import sqlite3
from datetime import UTC, datetime

_JOB_KINDS = """
    'chapter_brief', 'chapter_draft', 'reference_segment_map',
    'reference_book_reduce', 'reference_fusion', 'review', 'sandbox_ai_round',
    'research_extraction', 'comic_season_plan', 'comic_episode_script'
"""

_AI_TASK_TYPES = """
    'chapter_brief', 'chapter_draft', 'reference_analysis', 'review',
    'sandbox', 'research', 'comic_season_plan', 'comic_episode_script'
"""


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add the isolated, versioned AI comic-drama adaptation domain."""
    del schema
    connection.commit()
    connection.execute("PRAGMA foreign_keys=OFF")
    try:
        connection.executescript(
            f"""
            CREATE TABLE jobs_v22 (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                chapter_id TEXT REFERENCES chapters(id) ON DELETE CASCADE,
                parent_job_id TEXT REFERENCES jobs_v22(id) ON DELETE CASCADE,
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
            INSERT INTO jobs_v22 SELECT * FROM jobs;
            DROP TABLE jobs;
            ALTER TABLE jobs_v22 RENAME TO jobs;
            CREATE INDEX idx_jobs_project_updated ON jobs(project_id, updated_at DESC, id DESC);
            CREATE INDEX idx_jobs_queue ON jobs(state, created_at, id);
            CREATE INDEX idx_jobs_lease ON jobs(state, lease_expires_at);

            CREATE TABLE job_chunks_v22 (
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
            INSERT INTO job_chunks_v22 SELECT * FROM job_chunks;
            DROP TABLE job_chunks;
            ALTER TABLE job_chunks_v22 RENAME TO job_chunks;
            CREATE INDEX idx_job_chunks_job_state ON job_chunks(job_id, state, ordinal);

            CREATE TABLE ai_task_defaults_v22 (
                task_type TEXT PRIMARY KEY CHECK(task_type IN ({_AI_TASK_TYPES})),
                profile_id TEXT NOT NULL REFERENCES ai_provider_profiles(id) ON DELETE CASCADE,
                revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
                updated_at TEXT NOT NULL
            );
            INSERT INTO ai_task_defaults_v22 SELECT * FROM ai_task_defaults;
            DROP TABLE ai_task_defaults;
            ALTER TABLE ai_task_defaults_v22 RENAME TO ai_task_defaults;

            CREATE TABLE IF NOT EXISTS comic_projects (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
                source_chapter_ids_json TEXT NOT NULL CHECK(json_valid(source_chapter_ids_json)),
                source_snapshot_json TEXT NOT NULL CHECK(json_valid(source_snapshot_json)),
                source_snapshot_sha256 TEXT NOT NULL CHECK(length(source_snapshot_sha256) = 64),
                episode_target_count INTEGER NOT NULL CHECK(episode_target_count BETWEEN 1 AND 100),
                episode_duration_seconds INTEGER NOT NULL CHECK(episode_duration_seconds BETWEEN 30 AND 300),
                aspect_ratio TEXT NOT NULL CHECK(aspect_ratio IN ('9:16', '16:9', '1:1')),
                art_style TEXT NOT NULL DEFAULT '' CHECK(length(art_style) <= 500),
                adaptation_mode TEXT NOT NULL CHECK(adaptation_mode IN ('faithful', 'balanced', 'dramatic')),
                narration_preference TEXT NOT NULL DEFAULT '' CHECK(length(narration_preference) <= 500),
                author_requirements TEXT NOT NULL DEFAULT '' CHECK(length(author_requirements) <= 2000),
                state TEXT NOT NULL CHECK(state IN ('draft', 'planning', 'outlined', 'producing', 'completed')),
                season_revision INTEGER NOT NULL DEFAULT 0 CHECK(season_revision >= 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_comic_projects_project_updated
            ON comic_projects(project_id, updated_at DESC, id DESC);

            CREATE TABLE IF NOT EXISTS comic_episodes (
                id TEXT PRIMARY KEY,
                comic_project_id TEXT NOT NULL REFERENCES comic_projects(id) ON DELETE CASCADE,
                episode_number INTEGER NOT NULL CHECK(episode_number > 0),
                title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
                source_chapter_ids_json TEXT NOT NULL CHECK(json_valid(source_chapter_ids_json)),
                outline_state TEXT NOT NULL CHECK(outline_state IN ('candidate', 'approved', 'rejected')),
                script_state TEXT NOT NULL CHECK(script_state IN ('empty', 'candidate', 'approved', 'rejected')),
                outline_revision INTEGER NOT NULL DEFAULT 0 CHECK(outline_revision >= 0),
                script_revision INTEGER NOT NULL DEFAULT 0 CHECK(script_revision >= 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(comic_project_id, episode_number)
            );
            CREATE INDEX IF NOT EXISTS idx_comic_episodes_project_number
            ON comic_episodes(comic_project_id, episode_number, id);

            CREATE TABLE IF NOT EXISTS comic_versions (
                id TEXT PRIMARY KEY,
                comic_project_id TEXT NOT NULL REFERENCES comic_projects(id) ON DELETE CASCADE,
                episode_id TEXT REFERENCES comic_episodes(id) ON DELETE CASCADE,
                target_kind TEXT NOT NULL CHECK(target_kind IN ('season', 'episode_outline', 'episode_script')),
                target_id TEXT NOT NULL,
                version_number INTEGER NOT NULL CHECK(version_number > 0),
                state TEXT NOT NULL CHECK(state IN ('candidate', 'approved', 'rejected')),
                content_json TEXT NOT NULL CHECK(json_valid(content_json)),
                content_sha256 TEXT NOT NULL CHECK(length(content_sha256) = 64),
                source_snapshot_sha256 TEXT NOT NULL CHECK(length(source_snapshot_sha256) = 64),
                job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                UNIQUE(target_kind, target_id, version_number)
            );
            CREATE INDEX IF NOT EXISTS idx_comic_versions_target_state
            ON comic_versions(target_kind, target_id, state, version_number DESC);

            CREATE TABLE IF NOT EXISTS comic_scenes (
                id TEXT PRIMARY KEY,
                comic_project_id TEXT NOT NULL REFERENCES comic_projects(id) ON DELETE CASCADE,
                episode_id TEXT NOT NULL REFERENCES comic_episodes(id) ON DELETE CASCADE,
                script_version_id TEXT NOT NULL REFERENCES comic_versions(id) ON DELETE CASCADE,
                scene_number INTEGER NOT NULL CHECK(scene_number > 0),
                content_json TEXT NOT NULL CHECK(json_valid(content_json)),
                source_chapter_ids_json TEXT NOT NULL CHECK(json_valid(source_chapter_ids_json)),
                created_at TEXT NOT NULL,
                UNIQUE(episode_id, scene_number)
            );
            CREATE INDEX IF NOT EXISTS idx_comic_scenes_episode_number
            ON comic_scenes(episode_id, scene_number, id);
            """
        )
        connection.commit()
    finally:
        connection.execute("PRAGMA foreign_keys=ON")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise sqlite3.IntegrityError("v22 foreign key check failed")
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (22, "ai_comic_drama_workbench", datetime.now(UTC).isoformat()),
    )
