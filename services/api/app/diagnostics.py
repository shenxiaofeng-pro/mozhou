from __future__ import annotations

import json
import platform
import shutil
import sqlite3
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Literal
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from pydantic import BaseModel, Field

from app.database import CURRENT_SCHEMA_VERSION, Database

APP_VERSION = "0.1.0"
LOG_FILE_MAX_BYTES = 2 * 1024 * 1024
DIAGNOSTIC_LOG_LIMIT = 200
LOW_DISK_WARNING_BYTES = 512 * 1024 * 1024


class DiagnosticCheck(BaseModel):
    key: str
    status: Literal["ok", "warning", "error"]
    message: str


class DiagnosticSummary(BaseModel):
    generated_at: str
    app_version: str
    schema_version: int
    operating_system: str
    architecture: str
    python_version: str
    database_bytes: int = Field(ge=0)
    free_disk_bytes: int = Field(ge=0)
    counts: dict[str, int]
    checks: list[DiagnosticCheck]


class StructuredEventLog:
    """Small bounded JSONL log that never accepts request bodies or arbitrary metadata."""

    def __init__(self, data_directory: Path) -> None:
        self.directory = data_directory / "logs"
        self.path = self.directory / "mozhou.jsonl"
        self.previous_path = self.directory / "mozhou.previous.jsonl"
        self._lock = Lock()

    def request_completed(
        self,
        *,
        request_id: str,
        method: str,
        route: str,
        status_code: int,
        duration_ms: int,
    ) -> None:
        level = "error" if status_code >= 500 else "warning" if status_code >= 400 else "info"
        self._append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": level,
                "event": "request_completed",
                "request_id": request_id,
                "method": method,
                "route": route,
                "status_code": status_code,
                "duration_ms": max(0, duration_ms),
            }
        )

    def system_event(self, *, event: str, level: str, code: str) -> None:
        self._append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": level if level in {"info", "warning", "error"} else "error",
                "event": event[:80],
                "code": code[:80],
            }
        )

    def recent_lines(self, limit: int = DIAGNOSTIC_LOG_LIMIT) -> list[str]:
        bounded_limit = max(0, min(limit, DIAGNOSTIC_LOG_LIMIT))
        if bounded_limit == 0:
            return []
        lines: list[str] = []
        for path in (self.previous_path, self.path):
            try:
                lines.extend(path.read_text(encoding="utf-8").splitlines())
            except FileNotFoundError:
                continue
            except OSError:
                return []
        return lines[-bounded_limit:]

    def _append(self, payload: Mapping[str, object]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size + len(encoded.encode("utf-8")) > LOG_FILE_MAX_BYTES:
                    self.previous_path.unlink(missing_ok=True)
                    self.path.replace(self.previous_path)
                with self.path.open("a", encoding="utf-8") as output:
                    output.write(encoded)
            except OSError:
                # Logging must never turn a recoverable application operation into data loss.
                return


class DiagnosticService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.events = StructuredEventLog(database.path.parent)

    def summary(self) -> DiagnosticSummary:
        checks: list[DiagnosticCheck] = []
        counts: dict[str, int] = {}
        schema_version = 0
        try:
            with self.database.connect() as connection:
                quick_check = connection.execute("PRAGMA quick_check").fetchall()
                schema_row = connection.execute("PRAGMA user_version").fetchone()
                schema_version = int(schema_row[0]) if schema_row is not None else 0
                quick_check_ok = len(quick_check) == 1 and quick_check[0][0] == "ok"
                checks.append(
                    DiagnosticCheck(
                        key="database_integrity",
                        status="ok" if quick_check_ok else "error",
                        message=(
                            "数据库完整性检查通过"
                            if quick_check_ok
                            else "数据库完整性检查未通过，请保留原文件并从备份恢复"
                        ),
                    )
                )
                for table, label in (
                    ("projects", "projects"),
                    ("chapters", "chapters"),
                    ("reference_works", "reference_works"),
                    ("jobs", "jobs"),
                ):
                    row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                    counts[label] = int(row[0]) if row is not None else 0
                for row in connection.execute(
                    "SELECT state, COUNT(*) AS count FROM jobs GROUP BY state"
                ).fetchall():
                    counts[f"jobs_{row['state']}"] = int(row["count"])
        except (OSError, sqlite3.DatabaseError):
            checks.append(
                DiagnosticCheck(
                    key="database_integrity",
                    status="error",
                    message="数据库无法完成只读检查，请保留原文件并从备份恢复",
                )
            )

        try:
            free_disk_bytes = shutil.disk_usage(self.database.path.parent).free
        except OSError:
            free_disk_bytes = 0
        disk_status: Literal["ok", "warning", "error"] = (
            "ok" if free_disk_bytes >= LOW_DISK_WARNING_BYTES else "warning"
        )
        checks.append(
            DiagnosticCheck(
                key="free_disk",
                status=disk_status,
                message=(
                    "可用磁盘空间充足"
                    if disk_status == "ok"
                    else "可用磁盘空间低于 512 MiB，请先释放空间再继续写作"
                ),
            )
        )
        checks.append(
            DiagnosticCheck(
                key="schema_compatibility",
                status="ok" if schema_version == CURRENT_SCHEMA_VERSION else "error",
                message=(
                    "数据库结构版本与应用一致"
                    if schema_version == CURRENT_SCHEMA_VERSION
                    else "数据库结构版本与应用不一致，请勿覆盖原库"
                ),
            )
        )
        try:
            database_bytes = self.database.path.stat().st_size
        except OSError:
            database_bytes = 0
        return DiagnosticSummary(
            generated_at=datetime.now(UTC).isoformat(),
            app_version=APP_VERSION,
            schema_version=schema_version,
            operating_system=platform.system() or sys.platform,
            architecture=platform.machine() or "unknown",
            python_version=platform.python_version(),
            database_bytes=database_bytes,
            free_disk_bytes=free_disk_bytes,
            counts=counts,
            checks=checks,
        )

    def bundle(self) -> tuple[str, bytes]:
        summary = self.summary()
        buffer = BytesIO()
        with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as archive:
            archive.writestr(
                "diagnostics.json",
                summary.model_dump_json(indent=2),
            )
            archive.writestr(
                "recent-events.jsonl",
                "\n".join(self.events.recent_lines()) + "\n",
            )
            archive.writestr(
                "README.txt",
                (
                    "墨舟本地诊断包\n"
                    "仅包含应用/系统版本、数据库完整性和数量统计、脱敏请求事件。\n"
                    "不包含正文、章纲、参考原文、作品名、文件路径、API Key 或会话令牌。\n"
                ),
            )
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return f"mozhou-diagnostics-{timestamp}.zip", buffer.getvalue()


def safe_route_template(scope: Mapping[str, object]) -> str:
    route = scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template.startswith("/"):
        return template[:240]
    return "/unmatched"


def request_timer() -> tuple[str, float]:
    return str(uuid4()), monotonic()


def elapsed_milliseconds(started_at: float) -> int:
    return round((monotonic() - started_at) * 1000)


def classify_sqlite_operational_error(error: sqlite3.OperationalError) -> tuple[int, str, str]:
    message = str(error).lower()
    if any(marker in message for marker in ("database or disk is full", "disk full", "readonly")):
        return 507, "存储空间不足或数据目录不可写；正文仍保留在编辑器中，请释放空间后重试", "storage_unavailable"
    if any(marker in message for marker in ("database is locked", "database table is locked", "busy")):
        return 503, "本地数据库暂时忙，请稍后重试；不要关闭仍未保存的正文", "database_busy"
    return 500, "本地数据库操作失败，请导出诊断包并保留现有数据文件", "database_error"
