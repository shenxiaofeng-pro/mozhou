import json
import sqlite3
from contextlib import closing
from hashlib import sha256
from pathlib import Path

import pytest

import app.database as database_module
from app.database import (
    SCHEMA,
    Database,
    DatabaseIntegrityError,
    DatabaseMigrationError,
    UnsupportedDatabaseVersionError,
)
from app.migrations import MIGRATIONS, Migration, v9, v12


def test_database_initializes_required_tables(tmp_path: Path) -> None:
    database = Database(tmp_path / "mozhou.db")

    database.initialize()

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = ? ORDER BY name",
            ("table",),
        ).fetchall()

    assert [row["name"] for row in rows] == [
        "ai_provider_profiles",
        "ai_task_defaults",
        "book_blueprints",
        "chapter_events",
        "chapter_versions",
        "chapters",
        "context_directives",
        "context_packets",
        "fact_change_sets",
        "fact_changes",
        "future_knowledge",
        "generation_runs",
        "job_artifacts",
        "job_attempts",
        "job_chunks",
        "job_events",
        "jobs",
        "originality_reports",
        "project_recovery_points",
        "project_reference_works",
        "projects",
        "reference_analysis_cache",
        "reference_analysis_cache_sources",
        "reference_blueprint_versions",
        "reference_pattern_applications",
        "reference_pattern_cards",
        "reference_segments",
        "reference_works",
        "review_findings",
        "rolling_chapter_plans",
        "run_events",
        "schema_migrations",
        "source_cards",
        "source_documents",
        "story_entities",
        "story_facts",
        "story_threads",
        "text_change_sets",
        "text_changes",
        "timeline_events",
        "volume_plans",
    ]


def test_database_adds_brief_columns_to_existing_chapter_table(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.db"
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute(
            "CREATE TABLE chapters (id TEXT PRIMARY KEY, content TEXT NOT NULL DEFAULT '')"
        )
        connection.execute("INSERT INTO chapters (id, content) VALUES (?, ?)", ("chapter-1", "原稿"))
        connection.commit()

    database = Database(database_path)
    database.initialize()

    with database.connect() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(chapters)").fetchall()
        }
        row = connection.execute(
            "SELECT content, opening_hook, state_change, ending_cliffhanger FROM chapters"
        ).fetchone()

    assert {"opening_hook", "state_change", "ending_cliffhanger"} <= columns
    assert row is not None
    assert dict(row) == {
        "content": "原稿",
        "opening_hook": "",
        "state_change": "",
        "ending_cliffhanger": "",
    }


def test_database_adds_ai_provenance_to_existing_generation_table(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-runs.db"
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("CREATE TABLE generation_runs (id TEXT PRIMARY KEY)")
        connection.commit()

    database = Database(database_path)
    database.initialize()

    with database.connect() as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(generation_runs)").fetchall()
        }

    assert {"provider", "model"} <= columns


def test_database_upgrade_creates_one_backup_and_records_schema_version(tmp_path: Path) -> None:
    database_path = tmp_path / "mozhou.db"
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE markers (value TEXT NOT NULL)")
        connection.execute("INSERT INTO markers (value) VALUES (?)", ("升级前内容",))
        connection.commit()

    database = Database(database_path)
    database.initialize()

    backups = list((tmp_path / "backups").glob("mozhou-before-v14-*.db"))
    assert len(backups) == 1
    assert list((tmp_path / "backups").iterdir()) == backups
    with closing(sqlite3.connect(database_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (14,)
    with closing(sqlite3.connect(backups[0])) as connection:
        assert connection.execute("SELECT value FROM markers").fetchone() == ("升级前内容",)

    database.initialize()

    assert list((tmp_path / "backups").glob("mozhou-before-v14-*.db")) == backups


@pytest.mark.parametrize("source_version", [1, 2])
def test_database_runs_v1_and_v2_fixtures_to_v14_without_losing_data(
    tmp_path: Path,
    source_version: int,
) -> None:
    database_path = tmp_path / f"v{source_version}.db"
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("CREATE TABLE markers (value TEXT NOT NULL)")
        connection.execute("INSERT INTO markers (value) VALUES (?)", (f"v{source_version} 原稿",))
        if source_version == 1:
            connection.execute(
                "CREATE TABLE chapters (id TEXT PRIMARY KEY, content TEXT NOT NULL DEFAULT '')"
            )
            connection.execute("CREATE TABLE generation_runs (id TEXT PRIMARY KEY)")
        else:
            connection.execute(
                """
                CREATE TABLE chapters (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL DEFAULT '',
                    reader_promise TEXT NOT NULL DEFAULT '',
                    opening_hook TEXT NOT NULL DEFAULT '',
                    state_change TEXT NOT NULL DEFAULT '',
                    emotional_payoff TEXT NOT NULL DEFAULT '',
                    ending_cliffhanger TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE generation_runs (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL DEFAULT 'demo',
                    model TEXT NOT NULL DEFAULT 'replay-v1'
                )
                """
            )
        connection.execute("INSERT INTO chapters (id, content) VALUES (?, ?)", ("chapter-1", "原稿"))
        connection.execute("INSERT INTO generation_runs (id) VALUES (?)", ("run-1",))
        connection.execute(f"PRAGMA user_version={source_version}")
        connection.commit()

    Database(database_path).initialize()

    with closing(sqlite3.connect(database_path)) as connection:
        chapter = connection.execute(
            "SELECT content, opening_hook, state_change, ending_cliffhanger FROM chapters"
        ).fetchone()
        generation = connection.execute(
            "SELECT provider, model FROM generation_runs"
        ).fetchone()
        history = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert connection.execute("SELECT value FROM markers").fetchone() == (
            f"v{source_version} 原稿",
        )
        assert connection.execute("PRAGMA user_version").fetchone() == (14,)

    assert chapter == ("原稿", "", "", "")
    assert generation == ("demo", "replay-v1")
    assert history == [
        (1, "initial_schema"),
        (2, "chapter_brief_and_ai_provenance"),
        (3, "migration_history"),
        (4, "durable_ai_jobs"),
        (5, "reference_job_provenance"),
        (6, "ai_provider_profiles"),
        (7, "ai_task_defaults"),
        (8, "context_packets"),
        (9, "global_reference_library"),
        (10, "safe_reference_imports"),
        (11, "global_reality_sources"),
            (12, "versioned_originality_blueprints"),
            (13, "book_director_planning"),
            (14, "review_versions_and_change_sets"),
        ]
    assert len(list((tmp_path / "backups").glob("mozhou-before-v14-*.db"))) == 1


def test_v9_migrates_project_reference_text_to_global_asset_without_loss() -> None:
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(
            """
            CREATE TABLE projects (id TEXT PRIMARY KEY);
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                applied_at TEXT NOT NULL
            );
            CREATE TABLE reference_works (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                source_filename TEXT NOT NULL,
                source_format TEXT NOT NULL,
                rights_basis TEXT NOT NULL,
                total_characters INTEGER NOT NULL,
                segment_target_characters INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE reference_segments (
                id TEXT PRIMARY KEY,
                reference_work_id TEXT NOT NULL REFERENCES reference_works(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL,
                start_char INTEGER NOT NULL,
                end_char INTEGER NOT NULL,
                character_count INTEGER NOT NULL,
                chapter_start TEXT,
                chapter_end TEXT,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO projects(id) VALUES ('project-1');
            INSERT INTO reference_works VALUES (
                'work-1', 'project-1', '旧库参考', 'legacy.txt', 'txt',
                'self_owned', 4, 500000, '2026-08-01T00:00:00Z'
            );
            INSERT INTO reference_segments VALUES (
                'segment-1', 'work-1', 1, 0, 4, 4, NULL, NULL,
                '原文四字', '2026-08-01T00:00:00Z'
            );
            """
        )

        v9.upgrade(connection, SCHEMA)

        work_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(reference_works)").fetchall()
        }
        migrated_work = connection.execute(
            "SELECT id, content_sha256, source_encoding, import_state FROM reference_works"
        ).fetchone()
        migrated_link = connection.execute(
            "SELECT project_id, reference_work_id FROM project_reference_works"
        ).fetchone()
        migrated_content = connection.execute(
            "SELECT content FROM reference_segments WHERE id = 'segment-1'"
        ).fetchone()

    assert "project_id" not in work_columns
    assert migrated_work is not None
    assert tuple(migrated_work) == (
        "work-1",
        sha256("原文四字".encode()).hexdigest(),
        "utf-8",
        "ready",
    )
    assert migrated_link is not None
    assert tuple(migrated_link) == ("project-1", "work-1")
    assert migrated_content is not None
    assert tuple(migrated_content) == ("原文四字",)


def test_v12_turns_legacy_application_into_unchecked_versioned_blueprint() -> None:
    dimension = {
        "summary": "先保住家庭收入",
        "source_segment_ids": ["segment-1"],
        "transferable_logic": "先验证小目标",
        "adaptation_risk": "重组人物与场景",
    }
    proposal = {
        key: dimension
        for key in (
            "era",
            "core_desire",
            "conflict_causality",
            "resource_system",
            "key_scene_sequence",
            "ending",
        )
    } | {
        "shared_patterns": ["先验证信息差"],
        "differences": ["资源不同"],
        "relationship_recomposition": "重组为师徒竞争",
        "originality_risks": [],
    }
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(
            """
            CREATE TABLE projects (id TEXT PRIMARY KEY);
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                applied_at TEXT NOT NULL
            );
            CREATE TABLE reference_pattern_cards (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                proposal_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE reference_pattern_applications (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                pattern_card_id TEXT NOT NULL,
                selected_dimensions_json TEXT NOT NULL,
                dimensions_json TEXT NOT NULL,
                relationship_recomposition TEXT NOT NULL,
                application_note TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO projects(id) VALUES ('project-1');
            """
        )
        connection.execute(
            "INSERT INTO reference_pattern_cards VALUES (?, ?, ?, ?)",
            (
                "card-1",
                "project-1",
                json.dumps(proposal, ensure_ascii=False),
                "2026-08-10T00:00:00Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO reference_pattern_applications VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "application-1",
                "project-1",
                "card-1",
                '["era"]',
                json.dumps({"era": {
                    "summary": dimension["summary"],
                    "transferable_logic": dimension["transferable_logic"],
                }}, ensure_ascii=False),
                "重组为师徒竞争",
                "迁移旧蓝图",
                "2026-08-10T00:00:00Z",
            ),
        )

        v12.upgrade(connection, SCHEMA)

        migrated = connection.execute(
            """
            SELECT blueprint_json, originality_status, revision, updated_at
            FROM reference_pattern_applications WHERE id = 'application-1'
            """
        ).fetchone()
        version = connection.execute(
            """
            SELECT blueprint_revision, changed_dimensions_json
            FROM reference_blueprint_versions WHERE application_id = 'application-1'
            """
        ).fetchone()

    assert migrated is not None
    blueprint = json.loads(migrated["blueprint_json"])
    assert blueprint["dimensions"]["era"]["mode"] == "preserve"
    assert blueprint["dimensions"]["era"]["source"]["source_segment_ids"] == [
        "segment-1"
    ]
    assert migrated["originality_status"] == "needs_check"
    assert migrated["revision"] == 0
    assert migrated["updated_at"] == "2026-08-10T00:00:00Z"
    assert version is not None
    assert tuple(version) == (0, '["era"]')


def test_failed_migration_keeps_original_database_and_readable_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "migration-failure.db"
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("CREATE TABLE markers (value TEXT NOT NULL)")
        connection.execute("INSERT INTO markers (value) VALUES ('不可丢失的原稿')")
        connection.execute("PRAGMA user_version=1")
        connection.commit()
    original_sha256 = sha256(database_path.read_bytes()).hexdigest()

    def fail_migration(connection: sqlite3.Connection, schema: str) -> None:
        del schema
        connection.execute("CREATE TABLE should_never_reach_original (value TEXT)")
        raise RuntimeError("injected migration failure")

    failing_migration = Migration(
        version=2,
        name="injected_failure",
        upgrade=fail_migration,
    )
    monkeypatch.setattr(
        database_module,
        "MIGRATIONS",
        (MIGRATIONS[0], failing_migration, MIGRATIONS[2]),
    )

    with pytest.raises(DatabaseMigrationError, match="v1.*v2"):
        Database(database_path).initialize()

    assert sha256(database_path.read_bytes()).hexdigest() == original_sha256
    with closing(sqlite3.connect(database_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)
        assert connection.execute("SELECT value FROM markers").fetchone() == (
            "不可丢失的原稿",
        )
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'should_never_reach_original'"
        ).fetchone() is None

    backups = list((tmp_path / "backups").glob("mozhou-before-v14-*.db"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert connection.execute("SELECT value FROM markers").fetchone() == (
            "不可丢失的原稿",
        )
    assert not list(tmp_path.glob(".mozhou-migrate-*.db*"))


def test_database_rejects_newer_schema_without_modifying_it(tmp_path: Path) -> None:
    database_path = tmp_path / "future.db"
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("CREATE TABLE markers (value TEXT NOT NULL)")
        connection.execute("PRAGMA user_version=99")
        connection.commit()

    with pytest.raises(UnsupportedDatabaseVersionError):
        Database(database_path).initialize()

    with closing(sqlite3.connect(database_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (99,)
    assert not (tmp_path / "backups").exists()


def test_database_rejects_corrupt_file_without_replacing_it(tmp_path: Path) -> None:
    database_path = tmp_path / "corrupt.db"
    original_content = b"this is not a sqlite database"
    database_path.write_bytes(original_content)

    with pytest.raises(DatabaseIntegrityError):
        Database(database_path).initialize()

    assert database_path.read_bytes() == original_content
    assert not (tmp_path / "backups").exists()
