import sqlite3
from pathlib import Path

import pytest

from app.config import default_database_path, platform_data_directory


@pytest.mark.parametrize(
    ("platform_name", "environment", "expected_relative_path"),
    [
        ("darwin", {}, Path("Library/Application Support/com.lingjing.mozhou")),
        ("win32", {"LOCALAPPDATA": "/local-app-data"}, Path("/local-app-data/Mozhou")),
        ("linux", {"XDG_DATA_HOME": "/xdg-data"}, Path("/xdg-data/mozhou")),
    ],
)
def test_platform_data_directory_uses_operating_system_conventions(
    platform_name: str,
    environment: dict[str, str],
    expected_relative_path: Path,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    expected = expected_relative_path if expected_relative_path.is_absolute() else home / expected_relative_path

    assert platform_data_directory(platform_name, home, environment) == expected


def test_default_database_path_is_stable_across_working_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    first_working_directory = tmp_path / "first"
    second_working_directory = tmp_path / "second"
    first_working_directory.mkdir()
    second_working_directory.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("MOZHOU_DATA_DIR", raising=False)
    monkeypatch.delenv("MOZHOU_LEGACY_DATA_DIR", raising=False)

    monkeypatch.chdir(first_working_directory)
    first_path = default_database_path()
    monkeypatch.chdir(second_working_directory)
    second_path = default_database_path()

    expected = home / "Library" / "Application Support" / "com.lingjing.mozhou" / "mozhou.db"
    assert first_path == expected
    assert second_path == expected


def test_default_database_path_copies_legacy_database_without_removing_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    working_directory = tmp_path / "work"
    legacy_database = working_directory / ".mozhou-data" / "mozhou.db"
    legacy_database.parent.mkdir(parents=True)
    with sqlite3.connect(legacy_database) as connection:
        connection.execute("CREATE TABLE markers (value TEXT NOT NULL)")
        connection.execute("INSERT INTO markers (value) VALUES (?)", ("旧作品仍在",))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("MOZHOU_DATA_DIR", raising=False)
    monkeypatch.delenv("MOZHOU_LEGACY_DATA_DIR", raising=False)
    monkeypatch.chdir(working_directory)

    target_database = default_database_path()

    assert target_database.exists()
    assert legacy_database.exists()
    with sqlite3.connect(target_database) as connection:
        row = connection.execute("SELECT value FROM markers").fetchone()
    assert row == ("旧作品仍在",)


def test_explicit_data_directory_does_not_implicitly_import_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    working_directory = tmp_path / "work"
    legacy_database = working_directory / ".mozhou-data" / "mozhou.db"
    legacy_database.parent.mkdir(parents=True)
    with sqlite3.connect(legacy_database) as connection:
        connection.execute("CREATE TABLE markers (value TEXT NOT NULL)")
    selected_directory = tmp_path / "selected"
    monkeypatch.setenv("MOZHOU_DATA_DIR", str(selected_directory))
    monkeypatch.delenv("MOZHOU_LEGACY_DATA_DIR", raising=False)
    monkeypatch.chdir(working_directory)

    selected_database = default_database_path()

    assert selected_database == selected_directory / "mozhou.db"
    assert not selected_database.exists()
    assert legacy_database.exists()
