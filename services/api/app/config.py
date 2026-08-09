import os
import sqlite3
import sys
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from uuid import uuid4

MACOS_APPLICATION_ID = "com.lingjing.mozhou"


class LegacyDatabaseMigrationError(RuntimeError):
    """Raised when a legacy database cannot be copied safely."""


def platform_data_directory(
    platform_name: str,
    home: Path,
    environment: Mapping[str, str],
) -> Path:
    if platform_name == "darwin":
        return home / "Library" / "Application Support" / MACOS_APPLICATION_ID
    if platform_name == "win32":
        windows_root = environment.get("LOCALAPPDATA") or environment.get("APPDATA")
        return Path(windows_root) / "Mozhou" if windows_root else home / "AppData" / "Local" / "Mozhou"
    xdg_root = environment.get("XDG_DATA_HOME")
    return Path(xdg_root) / "mozhou" if xdg_root else home / ".local" / "share" / "mozhou"


def migrate_legacy_database(source: Path, target: Path) -> bool:
    source = source.resolve()
    target = target.resolve()
    if source == target or target.exists() or not source.is_file():
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_target = target.with_name(f".{target.name}.migrating-{uuid4().hex}")
    try:
        with (
            closing(sqlite3.connect(source)) as source_connection,
            closing(sqlite3.connect(temporary_target)) as target_connection,
        ):
            source_check = source_connection.execute("PRAGMA quick_check").fetchall()
            if source_check != [("ok",)]:
                raise LegacyDatabaseMigrationError("旧数据库完整性检查未通过")
            source_connection.backup(target_connection)
            target_connection.execute("PRAGMA journal_mode=DELETE").fetchone()
            target_check = target_connection.execute("PRAGMA quick_check").fetchall()
            if target_check != [("ok",)]:
                raise LegacyDatabaseMigrationError("迁移副本完整性检查未通过")

        try:
            os.link(temporary_target, target)
        except FileExistsError:
            return False
        return True
    except LegacyDatabaseMigrationError:
        raise
    except (OSError, sqlite3.DatabaseError) as error:
        raise LegacyDatabaseMigrationError("旧数据库迁移失败，原文件保持不变") from error
    finally:
        temporary_target.unlink(missing_ok=True)
        temporary_target.with_name(f"{temporary_target.name}-wal").unlink(missing_ok=True)
        temporary_target.with_name(f"{temporary_target.name}-shm").unlink(missing_ok=True)


def default_database_path() -> Path:
    configured = os.environ.get("MOZHOU_DATA_DIR")
    data_dir = (
        Path(configured).expanduser()
        if configured
        else platform_data_directory(sys.platform, Path.home(), os.environ)
    )
    database_path = data_dir.resolve() / "mozhou.db"
    configured_legacy_directory = os.environ.get("MOZHOU_LEGACY_DATA_DIR")
    legacy_database_path: Path | None = None
    if configured_legacy_directory:
        legacy_database_path = Path(configured_legacy_directory).expanduser() / "mozhou.db"
    elif configured is None:
        legacy_database_path = Path.cwd() / ".mozhou-data" / "mozhou.db"
    if legacy_database_path is not None:
        migrate_legacy_database(legacy_database_path, database_path)
    return database_path
