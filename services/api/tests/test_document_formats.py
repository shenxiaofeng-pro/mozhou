import io
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.manuscript.importer import preview_manuscript_file
from app.manuscript.service import ManuscriptService
from app.safe_import import UnsafeImportError, parse_reference_file

ROWS = [
    {
        "volume_id": "v1",
        "volume_title": "第一卷 归来",
        "chapter_id": "c1",
        "chapter_title": "第一章 列车",
        "content": "列车驶入南平站。\n\n他记得明天的价格。",
    },
    {
        "volume_id": "v1",
        "volume_title": "第一卷 归来",
        "chapter_id": "c2",
        "chapter_title": "第二章 首单",
        "content": "他在纸上写下第一笔货款。",
    },
]


def test_docx_and_epub_export_can_be_safely_reimported_with_structure() -> None:
    rows = cast(Any, ROWS)
    for format, payload in (
        ("docx", ManuscriptService._build_docx("南平归来", rows)),
        ("epub", ManuscriptService._build_epub("南平归来", rows)),
    ):
        parsed = parse_reference_file(f"book.{format}", payload)
        assert parsed.source_format == format
        preview = preview_manuscript_file(f"book.{format}", payload)
        assert preview.chapter_count == 2
        chapters = [chapter for volume in preview.volumes for chapter in volume.chapters]
        assert [chapter.title for chapter in chapters] == ["第一章 列车", "第二章 首单"]
        assert chapters[0].content == ROWS[0]["content"]


def test_zip_slip_and_active_docx_content_are_rejected() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("../escape.xml", "bad")
    with pytest.raises(UnsafeImportError, match="zip_unsafe_path"):
        parse_reference_file("bad.docx", output.getvalue())

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("word/vbaProject.bin", b"macro")
    with pytest.raises(UnsafeImportError, match="active_docx_content"):
        parse_reference_file("macro.docx", output.getvalue())


def test_binary_export_endpoint_returns_downloadable_files(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "南平归来",
                "genre": "urban_rebirth",
                "rebirth_year": 1992,
                "rebirth_location": "南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        chapter_id = workspace["chapters"][0]["id"]
        client.patch(
            f"/api/chapters/{chapter_id}", json={"content": "第一章正文。", "expected_revision": 0}
        )
        for format, media_type in (
            ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ("epub", "application/epub+zip"),
        ):
            response = client.get(f"/api/projects/{project_id}/manuscript-export/{format}")
            assert response.status_code == 200
            assert response.headers["content-type"] == media_type
            assert response.content.startswith(b"PK")
            assert len(response.headers["x-content-sha256"]) == 64
