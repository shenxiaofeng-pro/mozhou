import sqlite3
from pathlib import Path

import pytest

from app.database import (
    Database,
    DatabaseIntegrityError,
    UnsupportedDatabaseVersionError,
)


def test_database_initializes_required_tables(tmp_path: Path) -> None:
    database = Database(tmp_path / "mozhou.db")

    database.initialize()

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = ? ORDER BY name",
            ("table",),
        ).fetchall()

    assert [row["name"] for row in rows] == [
        "chapter_events",
        "chapters",
        "fact_change_sets",
        "fact_changes",
        "future_knowledge",
        "generation_runs",
        "project_recovery_points",
        "projects",
        "reference_pattern_applications",
        "reference_pattern_cards",
        "reference_segments",
        "reference_works",
        "run_events",
        "source_cards",
        "story_entities",
        "story_facts",
        "story_threads",
        "timeline_events",
    ]


def test_database_adds_brief_columns_to_existing_chapter_table(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE chapters (id TEXT PRIMARY KEY, content TEXT NOT NULL DEFAULT '')"
        )
        connection.execute("INSERT INTO chapters (id, content) VALUES (?, ?)", ("chapter-1", "原稿"))

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
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE generation_runs (id TEXT PRIMARY KEY)")

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
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE markers (value TEXT NOT NULL)")
        connection.execute("INSERT INTO markers (value) VALUES (?)", ("升级前内容",))

    database = Database(database_path)
    database.initialize()

    backups = list((tmp_path / "backups").glob("mozhou-before-v2-*.db"))
    assert len(backups) == 1
    assert list((tmp_path / "backups").iterdir()) == backups
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (2,)
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("SELECT value FROM markers").fetchone() == ("升级前内容",)

    database.initialize()

    assert list((tmp_path / "backups").glob("mozhou-before-v2-*.db")) == backups


def test_database_rejects_newer_schema_without_modifying_it(tmp_path: Path) -> None:
    database_path = tmp_path / "future.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE markers (value TEXT NOT NULL)")
        connection.execute("PRAGMA user_version=99")

    with pytest.raises(UnsupportedDatabaseVersionError):
        Database(database_path).initialize()

    with sqlite3.connect(database_path) as connection:
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
