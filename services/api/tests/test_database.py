import sqlite3
from contextlib import closing
from hashlib import sha256
from pathlib import Path

import pytest

import app.database as database_module
from app.database import (
    Database,
    DatabaseIntegrityError,
    DatabaseMigrationError,
    UnsupportedDatabaseVersionError,
)
from app.migrations import MIGRATIONS, Migration


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
        "chapter_events",
        "chapters",
        "fact_change_sets",
        "fact_changes",
        "future_knowledge",
        "generation_runs",
        "job_artifacts",
        "job_attempts",
        "job_chunks",
        "job_events",
        "jobs",
        "project_recovery_points",
        "projects",
        "reference_pattern_applications",
        "reference_pattern_cards",
        "reference_segments",
        "reference_works",
        "run_events",
        "schema_migrations",
        "source_cards",
        "story_entities",
        "story_facts",
        "story_threads",
        "timeline_events",
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

    backups = list((tmp_path / "backups").glob("mozhou-before-v7-*.db"))
    assert len(backups) == 1
    assert list((tmp_path / "backups").iterdir()) == backups
    with closing(sqlite3.connect(database_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (7,)
    with closing(sqlite3.connect(backups[0])) as connection:
        assert connection.execute("SELECT value FROM markers").fetchone() == ("升级前内容",)

    database.initialize()

    assert list((tmp_path / "backups").glob("mozhou-before-v7-*.db")) == backups


@pytest.mark.parametrize("source_version", [1, 2])
def test_database_runs_v1_and_v2_fixtures_to_v6_without_losing_data(
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
        assert connection.execute("PRAGMA user_version").fetchone() == (7,)

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
    ]
    assert len(list((tmp_path / "backups").glob("mozhou-before-v7-*.db"))) == 1


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

    backups = list((tmp_path / "backups").glob("mozhou-before-v7-*.db"))
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
