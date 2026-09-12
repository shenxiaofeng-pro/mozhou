import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

_JOB_KINDS = """
    'chapter_brief', 'chapter_draft', 'reference_segment_map',
    'reference_book_reduce', 'reference_fusion', 'review', 'sandbox_ai_round',
    'research_extraction', 'comic_season_plan', 'comic_episode_script',
    'topic_decision'
"""

_TOPIC_FIELDS = (
    "target_platform",
    "target_audience",
    "subgenre",
    "premise",
    "core_desire",
    "long_term_promise",
    "first_three_chapter_promise",
    "constraints",
    "forbidden_elements",
    "reference_purpose",
    "reality_anchor",
    "first_ten_chapter_goal",
)

_GENRE_LABELS = {
    "historical_rebirth": "历史重生",
    "urban_rebirth": "都市重生",
    "eastern_fantasy": "东方玄幻",
    "western_fantasy": "西方奇幻",
}


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _legacy_topic_content(project: sqlite3.Row, blueprint: sqlite3.Row | None) -> dict[str, object]:
    blueprint_content: dict[str, object] = {}
    idea = str(project["title"])
    if blueprint is not None:
        parsed = json.loads(str(blueprint["content_json"]))
        if not isinstance(parsed, dict):
            raise sqlite3.IntegrityError("invalid legacy book blueprint")
        blueprint_content = parsed
        idea = str(blueprint["idea"])

    def text(key: str) -> str:
        value = blueprint_content.get(key, "")
        if not isinstance(value, str):
            raise sqlite3.IntegrityError("invalid legacy book blueprint field")
        return value

    return {
        "target_platform": "",
        "target_audience": text("target_audience"),
        "subgenre": _GENRE_LABELS.get(str(project["genre"]), str(project["genre"])),
        "premise": idea,
        "core_desire": text("core_desire"),
        "long_term_promise": text("long_term_promise"),
        "first_three_chapter_promise": "",
        "constraints": [],
        "forbidden_elements": [],
        "reference_purpose": "",
        "reality_anchor": f"{project['rebirth_year']} · {project['rebirth_location']}",
        "first_ten_chapter_goal": "",
    }


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add versioned human topic decisions and isolated AI topic candidates."""
    original_row_factory = connection.row_factory
    connection.row_factory = sqlite3.Row
    connection.commit()
    connection.execute("PRAGMA foreign_keys=OFF")
    try:
        connection.executescript(
            f"""
            CREATE TABLE jobs_v24 (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                chapter_id TEXT REFERENCES chapters(id) ON DELETE CASCADE,
                parent_job_id TEXT REFERENCES jobs_v24(id) ON DELETE CASCADE,
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
            INSERT INTO jobs_v24 SELECT * FROM jobs;
            DROP TABLE jobs;
            ALTER TABLE jobs_v24 RENAME TO jobs;
            CREATE INDEX idx_jobs_project_updated ON jobs(project_id, updated_at DESC, id DESC);
            CREATE INDEX idx_jobs_queue ON jobs(state, created_at, id);
            CREATE INDEX idx_jobs_lease ON jobs(state, lease_expires_at);

            CREATE TABLE job_chunks_v24 (
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
            INSERT INTO job_chunks_v24 SELECT * FROM job_chunks;
            DROP TABLE job_chunks;
            ALTER TABLE job_chunks_v24 RENAME TO job_chunks;
            CREATE INDEX idx_job_chunks_job_state ON job_chunks(job_id, state, ordinal);
            """
        )
        connection.executescript(schema)
        projects = connection.execute(
            """
            SELECT p.*, b.id AS blueprint_id, b.idea, b.content_json
            FROM projects p
            LEFT JOIN book_blueprints b ON b.project_id = p.id
            WHERE NOT EXISTS (
                SELECT 1 FROM topic_decisions t WHERE t.project_id = p.id
            )
            ORDER BY p.created_at, p.id
            """
        ).fetchall()
        locks = _json({field: False for field in _TOPIC_FIELDS})
        field_versions = _json({field: 1 for field in _TOPIC_FIELDS})
        for project in projects:
            blueprint = project if project["blueprint_id"] is not None else None
            timestamp = str(project["updated_at"])
            connection.execute(
                """
                INSERT INTO topic_decisions (
                    id, project_id, content_json, locks_json, field_versions_json,
                    rejection_reasons_json, source_template_id, source_job_id,
                    source_candidate_ids_json, revision, confirmed_revision,
                    plan_stale, onboarding_required, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, '{}', NULL, NULL, '[]', 0, NULL, 0, 0, ?, ?)
                """,
                (
                    str(uuid4()),
                    project["id"],
                    _json(_legacy_topic_content(project, blueprint)),
                    locks,
                    field_versions,
                    timestamp,
                    timestamp,
                ),
            )
        connection.commit()
    finally:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.row_factory = original_row_factory
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise sqlite3.IntegrityError("v24 foreign key check failed")
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (24, "topic_decisions", datetime.now(UTC).isoformat()),
    )
