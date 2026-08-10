import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.ai import AiGatewayManager, build_chapter_context
from app.main import create_app
from app.models import (
    AiProvider,
    AiStatus,
    ReferenceDimensionSynthesis,
    ReferenceSynthesisProposal,
    Workspace,
)
from app.reference_lab import ReferenceAnalysisInput, segment_reference_text


class ReferenceAnalysisStubGateway:
    def status(self) -> AiStatus:
        return AiStatus(
            configured=True,
            provider=AiProvider.OPENAI,
            model="test-reference-model",
            key_source="test",
        )

    def synthesize_references(
        self,
        segments: list[ReferenceAnalysisInput],
        author_focus: str,
    ) -> ReferenceSynthesisProposal:
        assert len({segment.work_id for segment in segments}) == 2
        assert author_focus == "重点比较重生后的资源增长"
        source_ids = [segment.segment_id for segment in segments]

        def dimension(summary: str) -> ReferenceDimensionSynthesis:
            return ReferenceDimensionSynthesis(
                summary=summary,
                source_segment_ids=source_ids,
                transferable_logic="保留功能，重写人物、地点和具体事件。",
                adaptation_risk="不能复用专名与独特场景序列。",
            )

        return ReferenceSynthesisProposal(
            era=dimension("两个样本都用时代转型制造机会窗口。"),
            core_desire=dimension("主角渴望改写家庭与个人命运。"),
            conflict_causality=dimension("信息差先触发行动，再引来旧秩序反制。"),
            resource_system=dimension("资源从知识、人脉逐步转化为组织能力。"),
            key_scene_sequence=dimension("发现机会—小胜验证—强敌注意—阶段反转。"),
            ending=dimension("阶段胜利同时打开更大层级的冲突。"),
            shared_patterns=["信息差必须转化为可见行动"],
            differences=["一个偏家庭生存，一个偏商业扩张"],
            relationship_recomposition="新作改为师徒与竞争者的三角制衡。",
            originality_risks=["避免沿用相同产业、专名和四场景顺序"],
        )


def test_three_million_characters_become_six_complete_segments() -> None:
    content = "甲" * 3_000_000

    segments = segment_reference_text(content, target_characters=500_000)

    assert len(segments) == 6
    assert [(item.start_char, item.end_char) for item in segments] == [
        (0, 500_000),
        (500_000, 1_000_000),
        (1_000_000, 1_500_000),
        (1_500_000, 2_000_000),
        (2_000_000, 2_500_000),
        (2_500_000, 3_000_000),
    ]
    assert sum(item.character_count for item in segments) == len(content)
    assert "".join(item.content for item in segments) == content


def test_segmentation_prefers_nearby_chapter_boundaries() -> None:
    first_heading = "第一章 开端\n"
    second_heading = "第二章 转折\n"
    third_heading = "第三章 反击\n"
    content = (
        first_heading
        + "甲" * (950 - len(first_heading) - 1)
        + "\n"
        + second_heading
        + "乙" * (1900 - 950 - len(second_heading) - 1)
        + "\n"
        + third_heading
        + "丙" * 600
    )

    segments = segment_reference_text(content, target_characters=1_000)

    assert [(item.start_char, item.end_char) for item in segments] == [
        (0, 950),
        (950, 1900),
        (1900, len(content)),
    ]
    assert [(item.chapter_start, item.chapter_end) for item in segments] == [
        ("第一章 开端", "第一章 开端"),
        ("第二章 转折", "第二章 转折"),
        ("第三章 反击", "第三章 反击"),
    ]


def test_project_imports_multiple_reference_works_without_returning_original_text(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "多书结构实验",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        first = client.post(
            f"/api/projects/{project_id}/reference-works",
            json={
                "title": "参考甲",
                "source_filename": "alpha.txt",
                "rights_basis": "self_owned",
                "segment_target_characters": 100_000,
                "content": "甲" * 250_000,
            },
        )
        second = client.post(
            f"/api/projects/{project_id}/reference-works",
            json={
                "title": "参考乙",
                "source_filename": "beta.md",
                "rights_basis": "public_domain",
                "segment_target_characters": 100_000,
                "content": "乙" * 120_000,
            },
        )
        loaded = client.get(f"/api/projects/{project_id}")

    assert first.status_code == 201
    assert second.status_code == 201
    assert [len(item["segments"]) for item in loaded.json()["reference_works"]] == [3, 2]
    assert [item["title"] for item in loaded.json()["reference_works"]] == ["参考甲", "参考乙"]
    assert "content" not in first.json()
    assert all("content" not in segment for segment in first.json()["segments"])
    assert "甲" * 100 not in first.text
    assert "乙" * 100 not in loaded.text


def test_global_reference_work_is_imported_once_and_linked_to_two_projects(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        first_project = client.post(
            "/api/projects",
            json={
                "title": "南平商战",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()["project"]["id"]
        second_project = client.post(
            "/api/projects",
            json={
                "title": "闽北风云",
                "genre": "historical_rebirth",
                "rebirth_year": 1911,
                "rebirth_location": "福建南平",
            },
        ).json()["project"]["id"]

        imported = client.post(
            "/api/reference-library/works",
            json={
                "title": "公共参考样本",
                "source_filename": "sample.txt",
                "rights_basis": "authorized",
                "segment_target_characters": 100_000,
                "content": "第一章 起势\n" + "甲" * 120_000,
            },
        )
        work_id = imported.json()["id"]
        first_link = client.post(
            f"/api/projects/{first_project}/reference-works/{work_id}"
        )
        second_link = client.post(
            f"/api/projects/{second_project}/reference-works/{work_id}"
        )
        library = client.get("/api/reference-library/works")
        first_workspace = client.get(f"/api/projects/{first_project}")
        second_workspace = client.get(f"/api/projects/{second_project}")
        unlinked = client.delete(
            f"/api/projects/{first_project}/reference-works/{work_id}"
        )
        first_after_unlink = client.get(f"/api/projects/{first_project}")
        library_after_unlink = client.get("/api/reference-library/works")

    assert imported.status_code == 201
    assert first_link.status_code == 200
    assert second_link.status_code == 200
    assert library.status_code == 200
    assert library.json()[0]["project_ids"] == sorted([first_project, second_project])
    assert first_workspace.json()["reference_works"][0]["id"] == work_id
    assert second_workspace.json()["reference_works"][0]["id"] == work_id
    assert '"content":' not in library.text
    assert unlinked.status_code == 204
    assert first_after_unlink.json()["reference_works"] == []
    assert library_after_unlink.json()[0]["id"] == work_id


def test_reference_import_rejects_unsafe_input_without_echoing_original_text(
    tmp_path: Path,
) -> None:
    sensitive_marker = "不要在错误里回显这段参考原文"
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "安全导入实验",
                "genre": "historical_rebirth",
                "rebirth_year": 1911,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        unsafe = client.post(
            f"/api/projects/{project_id}/reference-works",
            json={
                "title": "不安全文本",
                "source_filename": "unsafe.txt",
                "rights_basis": "authorized",
                "content": sensitive_marker + "\u0000",
            },
        )
        unsupported = client.post(
            f"/api/projects/{project_id}/reference-works",
            json={
                "title": "错误格式",
                "source_filename": "book.epub",
                "rights_basis": "self_owned",
                "content": "合法内容",
            },
        )

    assert unsafe.status_code == 422
    assert unsafe.json() == {"detail": "请求内容格式无效"}
    assert sensitive_marker not in unsafe.text
    assert unsupported.status_code == 415
    assert unsupported.json() == {"detail": "当前只支持 UTF-8 TXT 或 Markdown 参考作品"}


def test_ai_synthesizes_six_dimensions_from_segments_across_multiple_books(
    tmp_path: Path,
) -> None:
    manager = AiGatewayManager(ReferenceAnalysisStubGateway())
    with TestClient(create_app(tmp_path / "mozhou.db", ai_manager=manager)) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "多书六维萃取",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        works = []
        for title, filename, content in [
            ("参考甲", "alpha.txt", "第一章 开局\n时代机会与家庭欲望。"),
            ("参考乙", "beta.md", "第一章 入局\n资源积累与竞争因果。"),
        ]:
            works.append(client.post(
                f"/api/projects/{project_id}/reference-works",
                json={
                    "title": title,
                    "source_filename": filename,
                    "rights_basis": "self_owned",
                    "content": content,
                },
            ).json())
        segment_ids = [work["segments"][0]["id"] for work in works]
        proposal = client.post(
            f"/api/projects/{project_id}/reference-synthesis-proposals",
            json={
                "selected_segment_ids": segment_ids,
                "author_focus": "重点比较重生后的资源增长",
                "confirm_external_processing": True,
            },
        )
        reloaded = client.get(f"/api/projects/{project_id}")

    assert proposal.status_code == 200
    assert proposal.json()["id"]
    assert proposal.json()["era"]["source_segment_ids"] == segment_ids
    assert proposal.json()["resource_system"]["summary"] == "资源从知识、人脉逐步转化为组织能力。"
    assert proposal.json()["key_scene_sequence"]["summary"].startswith("发现机会")
    assert "content" not in proposal.text
    assert [card["id"] for card in reloaded.json()["reference_pattern_cards"]] == [
        proposal.json()["id"]
    ]
    assert "时代机会与家庭欲望" not in reloaded.text
    assert "资源积累与竞争因果" not in reloaded.text


def test_reference_synthesis_requires_consent_and_multiple_works(tmp_path: Path) -> None:
    manager = AiGatewayManager(ReferenceAnalysisStubGateway())
    with TestClient(create_app(tmp_path / "mozhou.db", ai_manager=manager)) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "多书分析门禁",
                "genre": "historical_rebirth",
                "rebirth_year": 1984,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        work = client.post(
            f"/api/projects/{project_id}/reference-works",
            json={
                "title": "单书长篇",
                "source_filename": "single.txt",
                "rights_basis": "authorized",
                "segment_target_characters": 100_000,
                "content": "甲" * 150_000,
            },
        ).json()
        segment_ids = [segment["id"] for segment in work["segments"]]

        without_consent = client.post(
            f"/api/projects/{project_id}/reference-synthesis-proposals",
            json={
                "selected_segment_ids": segment_ids,
                "author_focus": "",
                "confirm_external_processing": False,
            },
        )
        one_work_only = client.post(
            f"/api/projects/{project_id}/reference-synthesis-proposals",
            json={
                "selected_segment_ids": segment_ids,
                "author_focus": "",
                "confirm_external_processing": True,
            },
        )

    assert without_consent.status_code == 400
    assert one_work_only.status_code == 400
    assert without_consent.json() == one_work_only.json()


def test_author_applies_selected_pattern_dimensions_to_current_project(tmp_path: Path) -> None:
    manager = AiGatewayManager(ReferenceAnalysisStubGateway())
    with TestClient(create_app(tmp_path / "mozhou.db", ai_manager=manager)) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "把结构带回新书",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        segment_ids = []
        for index in range(2):
            work = client.post(
                f"/api/projects/{project_id}/reference-works",
                json={
                    "title": f"合成参考{index + 1}",
                    "source_filename": f"fixture-{index + 1}.txt",
                    "rights_basis": "self_owned",
                    "content": f"第一章 开局\n合成内容{index + 1}",
                },
            ).json()
            segment_ids.append(work["segments"][0]["id"])
        card = client.post(
            f"/api/projects/{project_id}/reference-synthesis-proposals",
            json={
                "selected_segment_ids": segment_ids,
                "author_focus": "重点比较重生后的资源增长",
                "confirm_external_processing": True,
            },
        ).json()

        applied = client.post(
            f"/api/projects/{project_id}/reference-pattern-cards/{card['id']}/applications",
            json={
                "selected_dimensions": ["era", "resource_system"],
                "application_note": "改成南平本地产业与师徒竞争关系。",
                "confirm_original_adaptation": True,
            },
        )
        duplicate = client.post(
            f"/api/projects/{project_id}/reference-pattern-cards/{card['id']}/applications",
            json={
                "selected_dimensions": ["era"],
                "application_note": "重复应用不应覆盖原选择。",
                "confirm_original_adaptation": True,
            },
        )
        unconfirmed = client.post(
            f"/api/projects/{project_id}/reference-pattern-cards/{card['id']}/applications",
            json={
                "selected_dimensions": ["era"],
                "application_note": "",
                "confirm_original_adaptation": False,
            },
        )
        other_project = client.post(
            "/api/projects",
            json={
                "title": "另一本书",
                "genre": "historical_rebirth",
                "rebirth_year": 1911,
                "rebirth_location": "福建南平",
            },
        ).json()["project"]["id"]
        cross_project = client.post(
            f"/api/projects/{other_project}/reference-pattern-cards/{card['id']}/applications",
            json={
                "selected_dimensions": ["era"],
                "application_note": "",
                "confirm_original_adaptation": True,
            },
        )
        reloaded = client.get(f"/api/projects/{project_id}")

    reloaded_workspace = Workspace.model_validate(reloaded.json())
    context = json.loads(build_chapter_context(
        reloaded_workspace,
        reloaded_workspace.chapters[0],
        "",
    ))

    assert applied.status_code == 201
    assert duplicate.status_code == 409
    assert unconfirmed.status_code == 422
    assert cross_project.status_code == 404
    assert applied.json()["selected_dimensions"] == ["era", "resource_system"]
    assert set(applied.json()["dimensions"]) == {"era", "resource_system"}
    assert applied.json()["dimensions"]["resource_system"]["summary"].startswith("资源从知识")
    assert reloaded.json()["reference_pattern_applications"] == [applied.json()]
    assert "合成内容1" not in applied.text
    assert context["applied_reference_patterns"][0]["selected_dimensions"] == [
        "era",
        "resource_system",
    ]
    assert context["applied_reference_patterns"][0]["dimensions"]["era"]["summary"]
    assert "source_segment_ids" not in json.dumps(
        context["applied_reference_patterns"],
        ensure_ascii=False,
    )
