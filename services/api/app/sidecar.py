import argparse
import json
import os
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import uvicorn

STARTUP_STATUS_ENV = "MOZHOU_STARTUP_STATUS_FILE"


@dataclass(frozen=True)
class SidecarArguments:
    host: str
    port: int


@dataclass(frozen=True)
class StartupFailure:
    code: str
    message: str


def _valid_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def parse_args(argv: Sequence[str] | None = None) -> SidecarArguments:
    parser = argparse.ArgumentParser(description="Mozhou local API sidecar")
    parser.add_argument("--port", type=_valid_port, required=True)
    namespace = parser.parse_args(argv)
    return SidecarArguments(host="127.0.0.1", port=namespace.port)


def wait_for_parent_disconnect(
    stream: BinaryIO,
    terminate: Callable[[int], object],
) -> None:
    try:
        while stream.read(1):
            pass
    finally:
        terminate(0)


def start_parent_disconnect_watchdog() -> None:
    watchdog = threading.Thread(
        target=wait_for_parent_disconnect,
        args=(sys.stdin.buffer, os._exit),
        name="mozhou-parent-watchdog",
        daemon=True,
    )
    watchdog.start()


def startup_failure_for(error: BaseException) -> StartupFailure:
    from app.database import (
        DatabaseBackupError,
        DatabaseIntegrityError,
        DatabaseMigrationError,
        UnsupportedDatabaseVersionError,
    )

    if isinstance(error, DatabaseIntegrityError):
        return StartupFailure(
            code="database_integrity",
            message="数据库完整性检查未通过，原文件没有被修改。请保留数据目录并从备份恢复。",
        )
    if isinstance(error, UnsupportedDatabaseVersionError):
        return StartupFailure(
            code="database_newer_than_app",
            message="数据库来自更高版本的墨舟。请安装对应或更新版本，不要覆盖现有数据。",
        )
    if isinstance(error, DatabaseBackupError):
        return StartupFailure(
            code="upgrade_backup_failed",
            message="升级前安全备份失败，数据库没有升级。请检查磁盘空间和目录权限后重试。",
        )
    if isinstance(error, DatabaseMigrationError):
        return StartupFailure(
            code="database_migration_failed",
            message="数据库升级未完成，原文件保持不变。请保留备份并导出诊断信息。",
        )
    return StartupFailure(
        code="local_api_startup_failed",
        message="本地服务启动失败。请保留数据目录并导出诊断信息后重试。",
    )


def write_startup_failure(path: Path | None, failure: StartupFailure) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"format": "mozhou-startup-status", "code": failure.code, "message": failure.message},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    except OSError:
        return


def main(argv: Sequence[str] | None = None) -> None:
    arguments = parse_args(argv)
    start_parent_disconnect_watchdog()
    startup_status_value = os.environ.get(STARTUP_STATUS_ENV)
    startup_status_path = Path(startup_status_value) if startup_status_value else None
    if startup_status_path is not None:
        try:
            startup_status_path.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        from app.config import LegacyDatabaseMigrationError, default_database_path
        from app.database import (
            Database,
            DatabaseBackupError,
            DatabaseIntegrityError,
            DatabaseMigrationError,
            UnsupportedDatabaseVersionError,
        )

        Database(default_database_path()).initialize()
    except (
        DatabaseBackupError,
        DatabaseIntegrityError,
        DatabaseMigrationError,
        LegacyDatabaseMigrationError,
        OSError,
        UnsupportedDatabaseVersionError,
    ) as error:
        write_startup_failure(startup_status_path, startup_failure_for(error))
        raise SystemExit(1) from None
    from app.runtime import create_runtime_app

    uvicorn.run(
        create_runtime_app(),
        host=arguments.host,
        port=arguments.port,
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
