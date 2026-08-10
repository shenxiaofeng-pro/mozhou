import json
import sqlite3
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.diagnostics import StructuredEventLog, classify_sqlite_operational_error
from app.main import create_app


def test_diagnostic_summary_and_bundle_exclude_private_author_data(tmp_path: Path) -> None:
    application = create_app(tmp_path / "private-data" / "mozhou.db")
    secret_title = "只有作者知道的书名"
    secret_content = "绝不能出现在诊断包里的正文"
    secret_token = "authorization-sentinel-do-not-export"
    with TestClient(application) as client:
        created = client.post(
            "/api/projects",
            json={
                "title": secret_title,
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
                "chapter_target_words": 3000,
                "safety_buffer_chapters": 3,
            },
        ).json()
        chapter = created["chapters"][0]
        client.patch(
            f"/api/chapters/{chapter['id']}",
            json={"content": secret_content, "expected_revision": 0},
            headers={"Authorization": f"Bearer {secret_token}"},
        )
        summary = client.get("/api/diagnostics")
        bundle = client.post("/api/diagnostics/bundle")

    assert summary.status_code == 200
    assert summary.json()["schema_version"] == 16
    assert summary.json()["counts"]["projects"] == 1
    assert {item["status"] for item in summary.json()["checks"]} == {"ok"}
    assert bundle.status_code == 200
    assert bundle.headers["content-type"] == "application/zip"

    with ZipFile(BytesIO(bundle.content)) as archive:
        assert set(archive.namelist()) == {
            "README.txt",
            "diagnostics.json",
            "recent-events.jsonl",
        }
        exported = b"\n".join(archive.read(name) for name in archive.namelist()).decode("utf-8")
        events = archive.read("recent-events.jsonl").decode("utf-8").splitlines()

    assert secret_title not in exported
    assert secret_content not in exported
    assert secret_token not in exported
    assert str(tmp_path) not in exported
    assert chapter["id"] not in exported
    assert any(json.loads(line)["route"] == "/api/chapters/{chapter_id}" for line in events)


@pytest.mark.parametrize(
    ("message", "status_code", "code"),
    [
        ("database or disk is full", 507, "storage_unavailable"),
        ("attempt to write a readonly database", 507, "storage_unavailable"),
        ("database is locked", 503, "database_busy"),
        ("unknown sqlite problem", 500, "database_error"),
    ],
)
def test_sqlite_failures_have_safe_actionable_responses(
    message: str,
    status_code: int,
    code: str,
) -> None:
    actual_status, detail, actual_code = classify_sqlite_operational_error(
        sqlite3.OperationalError(message)
    )

    assert actual_status == status_code
    assert actual_code == code
    assert "正文" in detail or "数据库" in detail
    assert message not in detail


def test_structured_log_rotates_and_never_requires_application_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = StructuredEventLog(tmp_path)
    monkeypatch.setattr("app.diagnostics.LOG_FILE_MAX_BYTES", 1)

    log.request_completed(
        request_id="first",
        method="GET",
        route="/api/projects/{project_id}",
        status_code=200,
        duration_ms=12,
    )
    log.request_completed(
        request_id="second",
        method="POST",
        route="/api/diagnostics/bundle",
        status_code=200,
        duration_ms=4,
    )

    lines = log.recent_lines()
    assert [json.loads(line)["request_id"] for line in lines] == ["first", "second"]
    assert log.previous_path.exists()


@pytest.mark.parametrize(
    ("sqlite_message", "expected_status", "expected_code"),
    [
        ("database is locked at /private/author/path", 503, "database_busy"),
        ("database or disk is full at /private/author/path", 507, "storage_unavailable"),
    ],
)
def test_api_sanitizes_operational_database_failures(
    tmp_path: Path,
    sqlite_message: str,
    expected_status: int,
    expected_code: str,
) -> None:
    application = create_app(tmp_path / "mozhou.db")

    def fail_list_projects() -> list[object]:
        raise sqlite3.OperationalError(sqlite_message)

    with TestClient(application) as client:
        application.state.repository.list_projects = fail_list_projects
        response = client.get("/api/projects")

    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code
    assert "/private/author/path" not in response.text
    if expected_status == 503:
        assert response.headers["retry-after"] == "1"
