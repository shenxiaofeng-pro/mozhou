import hashlib
import json
import sqlite3
from datetime import UTC, datetime


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _generalized_schema() -> str:
    return """
        CREATE TABLE context_packets_v29 (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            chapter_id TEXT REFERENCES chapters(id) ON DELETE CASCADE,
            chapter_revision INTEGER CHECK(chapter_revision IS NULL OR chapter_revision >= 0),
            task_type TEXT CHECK(
                task_type IS NULL OR task_type IN ('chapter_brief', 'chapter_draft')
            ),
            purpose TEXT NOT NULL CHECK(purpose IN (
                'startup', 'expansion', 'field', 'brief', 'draft',
                'candidate_review', 'canon_reconciliation'
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


def _plan_rebase_schema() -> str:
    return """
        CREATE TABLE IF NOT EXISTS creative_plan_dependencies (
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            subject_kind TEXT NOT NULL CHECK(subject_kind IN (
                'book_blueprint', 'volume_plan', 'rolling_plan'
            )),
            subject_id TEXT NOT NULL,
            subject_revision INTEGER NOT NULL CHECK(subject_revision >= 0),
            dependency_snapshot_json TEXT NOT NULL
                CHECK(json_valid(dependency_snapshot_json)),
            dependency_fingerprint_sha256 TEXT NOT NULL
                CHECK(length(dependency_fingerprint_sha256) = 64),
            baseline_state TEXT NOT NULL CHECK(baseline_state IN ('current', 'legacy')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(project_id, subject_kind, subject_id)
        );

        CREATE INDEX IF NOT EXISTS idx_creative_plan_dependencies_project
        ON creative_plan_dependencies(project_id, subject_kind, subject_id);

        CREATE TABLE IF NOT EXISTS plan_rebase_candidates (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            state TEXT NOT NULL CHECK(state IN ('candidate', 'adopted', 'stale', 'rejected')),
            revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
            based_on_dependency_fingerprint_sha256 TEXT NOT NULL
                CHECK(length(based_on_dependency_fingerprint_sha256) = 64),
            target_dependency_fingerprint_sha256 TEXT NOT NULL
                CHECK(length(target_dependency_fingerprint_sha256) = 64),
            impact_json TEXT NOT NULL CHECK(json_valid(impact_json)),
            book_blueprint_json TEXT
                CHECK(book_blueprint_json IS NULL OR json_valid(book_blueprint_json)),
            volume_plans_json TEXT NOT NULL CHECK(json_valid(volume_plans_json)),
            rolling_chapter_plans_json TEXT NOT NULL CHECK(json_valid(rolling_chapter_plans_json)),
            adoption_idempotency_key TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            adopted_at TEXT,
            CHECK((state = 'adopted') = (adopted_at IS NOT NULL)),
            CHECK(
                adoption_idempotency_key IS NULL
                OR length(adoption_idempotency_key) BETWEEN 1 AND 200
            )
        );

        CREATE INDEX IF NOT EXISTS idx_plan_rebase_candidates_project_updated
        ON plan_rebase_candidates(project_id, updated_at DESC, id);
    """


def _upgrade_packet_json(row: sqlite3.Row) -> tuple[str, str, str, str, str]:
    try:
        packet = json.loads(str(row["packet_json"]))
    except (TypeError, ValueError) as error:
        raise sqlite3.IntegrityError("invalid legacy context packet") from error
    if not isinstance(packet, dict):
        raise sqlite3.IntegrityError("invalid legacy context packet")
    task_type = str(row["task_type"])
    purpose = "brief" if task_type == "chapter_brief" else "draft"
    source_fingerprint = str(row["source_fingerprint_sha256"])
    subject = {
        "kind": "chapter",
        "id": str(row["chapter_id"]),
        "revision": int(row["chapter_revision"]),
        "content_sha256": source_fingerprint,
    }
    dependencies = {
        "schema_version": 1,
        "topic": None,
        "writing_pattern_profile": None,
        "writing_pattern_source_availability": None,
        "base_blueprint": None,
        "subject_sha256": source_fingerprint,
    }
    dependency_fingerprint = _sha256_json(dependencies)
    packet.update(
        {
            "purpose": purpose,
            "subject": subject,
            "profile_fingerprint_sha256": None,
            "dependency_snapshot": dependencies,
            "dependency_fingerprint_sha256": dependency_fingerprint,
            "blocking_reasons": ["legacy_dependency_snapshot"],
        }
    )
    return (
        purpose,
        _json(subject),
        _json(dependencies),
        dependency_fingerprint,
        _json(packet),
    )


def upgrade(connection: sqlite3.Connection, _schema: str) -> None:
    """Generalize immutable context packets for every creative purpose."""
    columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(context_packets)")
    }
    if "purpose" not in columns:
        original_row_factory = connection.row_factory
        connection.row_factory = sqlite3.Row
        connection.commit()
        connection.execute("PRAGMA foreign_keys=OFF")
        try:
            rows = connection.execute(
                "SELECT * FROM context_packets ORDER BY created_at, id"
            ).fetchall()
            connection.execute("DROP INDEX IF EXISTS idx_context_packets_chapter_created")
            connection.executescript(_generalized_schema())
            for row in rows:
                purpose, subject_json, dependency_json, dependency_hash, packet_json = (
                    _upgrade_packet_json(row)
                )
                connection.execute(
                    """
                    INSERT INTO context_packets_v29 (
                        id, project_id, chapter_id, chapter_revision, task_type,
                        purpose, subject_json, profile_fingerprint_sha256,
                        dependency_snapshot_json, dependency_fingerprint_sha256,
                        blocking_reasons_json, compiler_version, token_budget,
                        used_tokens, overflow_tokens, packet_sha256,
                        source_fingerprint_sha256, packet_json, rendered_context,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        row["project_id"],
                        row["chapter_id"],
                        row["chapter_revision"],
                        row["task_type"],
                        purpose,
                        subject_json,
                        dependency_json,
                        dependency_hash,
                        _json(["legacy_dependency_snapshot"]),
                        row["compiler_version"],
                        row["token_budget"],
                        row["used_tokens"],
                        row["overflow_tokens"],
                        row["packet_sha256"],
                        row["source_fingerprint_sha256"],
                        packet_json,
                        row["rendered_context"],
                        row["created_at"],
                    ),
                )
            connection.execute("DROP TABLE context_packets")
            connection.execute("ALTER TABLE context_packets_v29 RENAME TO context_packets")
            connection.execute(
                "CREATE INDEX idx_context_packets_chapter_created "
                "ON context_packets(chapter_id, created_at DESC, id DESC)"
            )
            connection.execute(
                "CREATE INDEX idx_context_packets_project_purpose_created "
                "ON context_packets(project_id, purpose, created_at DESC, id DESC)"
            )
            connection.commit()
        finally:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.row_factory = original_row_factory
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise sqlite3.IntegrityError("v29 foreign key check failed")
    connection.executescript(_plan_rebase_schema())
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (29, "unified_creative_context_and_plan_rebase", datetime.now(UTC).isoformat()),
    )
