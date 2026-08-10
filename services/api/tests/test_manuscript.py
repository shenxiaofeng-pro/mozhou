from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import Database
from app.main import create_app
from app.manuscript.importer import preview_manuscript_file
from app.manuscript.service import ManuscriptService
from app.models import ConfirmManuscriptImportRequest, Genre
from app.repository import ProjectRepository
from app.review.repository import ReviewRepository


def test_preview_recognizes_markdown_volumes_chapter_variants_and_preamble() -> None:
    payload = (
        "# 闽北春潮\n\n"
        "这是作者保留的题记。\n\n"
        "## 第一卷 起潮\n\n"
        "### 第一章 回到九八年\n\n"
        "列车驶入南平站。\n\n"
        "### 章二 工牌\n\n"
        "父亲的工牌被收走。\n\n"
        "## 卷2 竹海\n\n"
        "### Chapter 3 First order\n\n"
        "第一笔订单落在桌上。\n"
    ).encode()

    preview = preview_manuscript_file("旧稿.md", payload)

    assert preview.inferred_project_title == "闽北春潮"
    assert preview.source_encoding == "utf-8"
    assert preview.chapter_count == 3
    assert [volume.title for volume in preview.volumes] == ["第一卷 起潮", "卷2 竹海"]
    assert [chapter.title for volume in preview.volumes for chapter in volume.chapters] == [
        "第一章 回到九八年",
        "章二 工牌",
        "Chapter 3 First order",
    ]
    assert preview.unrecognized_text == "这是作者保留的题记。"
    assert preview.warnings == ["unrecognized_preamble"]


def test_preview_supports_gb18030_no_volume_empty_and_headingless_files() -> None:
    gb18030 = "第一章 归来\n正文甲\n\n第二章 空章\n".encode("gb18030")
    preview = preview_manuscript_file("南平旧稿.txt", gb18030)

    assert preview.source_encoding == "gb18030"
    assert len(preview.volumes) == 1
    assert preview.volumes[0].title == "正文"
    assert preview.volumes[0].chapters[1].warnings == ["empty_chapter"]

    headingless = preview_manuscript_file("散稿.txt", "没有标题，但正文不能丢。".encode())
    assert headingless.chapter_count == 1
    assert headingless.volumes[0].chapters[0].heading_confidence == 0.35
    assert "low_heading_confidence" in headingless.volumes[0].chapters[0].warnings
    assert headingless.warnings == ["no_chapter_headings"]


def test_preview_splits_an_oversized_chapter_without_losing_text() -> None:
    content = "甲" * 1_000_000 + "\n\n" + "乙" * 700_000
    preview = preview_manuscript_file(
        "超长.txt",
        f"第一章 超长章\n{content}".encode(),
    )

    chapters = preview.volumes[0].chapters
    assert len(chapters) == 2
    assert "oversized_chapter_split" in chapters[0].warnings
    assert "".join(chapter.content for chapter in chapters) == content


def test_preview_confirmation_is_atomic_and_markdown_export_preserves_order(
    tmp_path: Path,
) -> None:
    manuscript = (
        "# 旧厂新生\n"
        "题记会由作者决定是否并入。\n"
        "## 第一卷 名单\n"
        "### 第一章 归来\n"
        "列车驶入南平。\n"
        "### 第二章 工牌\n"
        "父亲握紧工牌。\n"
        "## 第二卷 竹海\n"
        "### 第三章 订单\n"
        "订单落地。\n"
    ).encode()
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        before = client.get("/api/projects").json()
        preview_response = client.post(
            "/api/manuscript-imports/preview",
            params={"source_filename": "旧厂新生.md"},
            content=manuscript,
            headers={"Content-Type": "text/markdown"},
        )
        after_preview = client.get("/api/projects").json()
        preview = preview_response.json()
        preview["volumes"][0]["title"] = "第一卷 停产名单"
        request = {
            "title": preview["inferred_project_title"],
            "genre": "urban_rebirth",
            "rebirth_year": 1998,
            "rebirth_location": "福建南平",
            "source_filename": preview["source_filename"],
            "source_sha256": preview["source_sha256"],
            "source_encoding": preview["source_encoding"],
            "warnings": preview["warnings"],
            "volumes": preview["volumes"],
            "unrecognized_text": preview["unrecognized_text"],
            "unrecognized_action": "prepend_first_chapter",
            "confirm_warnings": True,
        }
        imported_response = client.post("/api/manuscript-imports", json=request)
        imported = imported_response.json()
        exported = client.get(
            f"/api/projects/{imported['project']['id']}/manuscript-export"
        ).json()
        versions = client.get(
            f"/api/chapters/{imported['chapters'][0]['id']}/versions"
        ).json()

    assert preview_response.status_code == 200
    assert before == after_preview == []
    assert imported_response.status_code == 201
    assert [volume["title"] for volume in imported["manuscript_volumes"]] == [
        "第一卷 停产名单",
        "第二卷 竹海",
    ]
    assert imported["chapters"][0]["content"].startswith("题记会由作者决定是否并入。")
    assert [chapter["chapter_number"] for chapter in imported["chapters"]] == [1, 2, 3]
    assert versions[0]["source"] == "initial"
    assert versions[0]["content"] == imported["chapters"][0]["content"]
    assert exported["filename"] == "旧厂新生.md"
    assert exported["content"].index("第一卷 停产名单") < exported["content"].index("第二卷 竹海")
    assert exported["content"].index("第一章 归来") < exported["content"].index("第二章 工牌")
    assert "列车驶入南平。" in exported["content"]


def test_import_failure_rolls_back_the_entire_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database(tmp_path / "atomic.db")
    database.initialize()
    projects = ProjectRepository(database)
    service = ManuscriptService(database, projects)
    preview = preview_manuscript_file(
        "故障稿.txt",
        "第一章 一\n正文一\n第二章 二\n正文二".encode(),
    )
    request = ConfirmManuscriptImportRequest(
        title="故障稿",
        genre=Genre.URBAN_REBIRTH,
        rebirth_year=1998,
        rebirth_location="福建南平",
        source_filename=preview.source_filename,
        source_sha256=preview.source_sha256,
        source_encoding=preview.source_encoding,
        warnings=preview.warnings,
        volumes=preview.volumes,
        unrecognized_text=preview.unrecognized_text,
        confirm_warnings=True,
    )
    original = ReviewRepository.append_chapter_version
    calls = 0

    def fail_on_second_version(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected import failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(ReviewRepository, "append_chapter_version", fail_on_second_version)

    with pytest.raises(RuntimeError, match="injected import failure"):
        service.confirm_import(request)
    assert projects.list_projects() == []
