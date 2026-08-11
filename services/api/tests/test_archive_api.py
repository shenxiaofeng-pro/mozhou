import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.jobs import JobKind, JobRepository
from app.main import create_app
from app.models import (
    ReviewDimension,
    ReviewEvidence,
    ReviewEvidenceKind,
    ReviewSeverity,
)
from app.review.rules import make_finding

ARCHIVE_TABLES = {
    "projects",
    "book_blueprints",
    "volume_plans",
    "rolling_chapter_plans",
    "manuscript_volumes",
    "chapters",
    "manuscript_scenes",
    "directory_events",
    "serial_daily_goals",
    "chapter_versions",
    "context_directives",
    "generation_runs",
    "chapter_events",
    "run_events",
    "jobs",
    "job_chunks",
    "job_attempts",
    "job_artifacts",
    "job_events",
    "timeline_events",
    "story_facts",
    "fact_change_sets",
    "fact_changes",
    "future_knowledge",
    "story_entities",
    "story_threads",
    "source_documents",
    "source_cards",
    "reference_works",
    "reference_segments",
    "reference_pattern_cards",
    "reference_pattern_applications",
    "reference_blueprint_versions",
    "originality_reports",
    "scene_originality_checks",
    "scene_originality_findings",
    "review_findings",
    "text_change_sets",
    "text_changes",
}


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def test_exports_complete_project_archive_with_checksum(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "回到九八年的南平",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        chapter_id = workspace["chapters"][0]["id"]
        client.patch(
            f"/api/chapters/{chapter_id}",
            json={"content": "列车驶入南平站。", "expected_revision": 0},
        )
        reference = client.post(
            f"/api/projects/{project_id}/reference-works",
            json={
                "title": "自有旧稿",
                "source_filename": "old.md",
                "rights_basis": "self_owned",
                "content": "# 第一章\n潮水从闽江上来。",
                "segment_target_characters": 500_000,
            },
        ).json()

        default_response = client.get(f"/api/projects/{project_id}/export")
        response = client.get(
            f"/api/projects/{project_id}/export?include_reference_assets=true"
        )

    assert response.status_code == 200
    archive = response.json()
    default_archive = default_response.json()
    assert default_archive["tables"]["reference_works"] == []
    assert default_archive["tables"]["reference_segments"] == []
    assert archive["format"] == "mozhou-project"
    assert archive["format_version"] == 7
    assert archive["source_project_id"] == project_id
    assert archive["source_project_title"] == "回到九八年的南平"
    assert set(archive["tables"]) == ARCHIVE_TABLES
    assert archive["tables"]["chapters"][0]["content"] == "列车驶入南平站。"
    assert archive["tables"]["reference_segments"][0]["content"] == "# 第一章\n潮水从闽江上来。"
    assert archive["tables"]["reference_segments"][0]["id"] == reference["segments"][0]["id"]
    checksum = archive.pop("checksum_sha256")
    assert checksum == hashlib.sha256(canonical_json(archive)).hexdigest()


def test_archive_round_trip_preserves_book_director_plans(tmp_path: Path) -> None:
    database_path = tmp_path / "mozhou.db"
    timestamp = "2026-08-11T00:00:00+00:00"
    fields = (
        "title", "genre", "rebirth_year", "rebirth_location", "target_audience",
        "core_selling_points", "core_desire", "divergence_point", "long_term_promise",
        "ending_direction", "protagonist_arc", "resource_growth", "relationship_design",
    )
    blueprint_content = {
        "title": "闽北春潮",
        "genre": "urban_rebirth",
        "rebirth_year": 1998,
        "rebirth_location": "福建南平",
        "target_audience": "年代创业读者",
        "core_selling_points": ["木竹产业", "家庭改命"],
        "core_desire": "改变家庭命运",
        "divergence_point": "提前拿到停产名单",
        "long_term_promise": "从工厂自救到产业升级",
        "ending_direction": "建立可持续的产业联盟",
        "protagonist_arc": "从救家人到承担公共责任",
        "resource_growth": "信息差到组织信用",
        "relationship_design": "父子、师徒和竞争者重新组合",
    }
    volume_content = {
        "volume_number": 1,
        "title": "停产名单",
        "direction": "完成工厂自救",
        "central_conflict": "旧管理层阻止改制",
        "state_goal": "父亲保住岗位",
        "resource_goal": "获得第一笔订单",
        "emotional_payoff": "父子恢复信任",
        "climax": "公开竞标逆转",
        "verification": "核对 1998 年当地改制流程",
    }
    rolling_content = {
        "chapter_number": 1,
        "title": "名单之前",
        "reader_promise": "第一次改命",
        "opening_hook": "停产名单提前贴出",
        "state_change": "父亲暂时留岗",
        "resource_change": "获得厂长注意",
        "emotional_payoff": "父子关系松动",
        "ending_cliffhanger": "厂长叫出主角小名",
        "verification": "核对厂办张榜流程",
        "scene_beats": [{
            "ordinal": 1,
            "summary": "主角发现名单",
            "state_change": "确认时间线变化",
            "resource_change": "得到行动窗口",
            "emotional_turn": "恐慌转为决断",
            "verification": "核对公告地点",
        }],
    }
    with TestClient(create_app(database_path)) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "闽北春潮",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        blueprint_id = "0a9cc817-ac3f-40c5-a749-f77dbcd85546"
        volume_id = "b5f28e1e-73f6-4379-b542-e751493952ae"
        rolling_id = "0a1465f4-3005-40cf-a93b-f63e6bbd4038"
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                """
                INSERT INTO book_blueprints (
                    id, project_id, idea, content_json, locks_json, field_versions_json,
                    stale_fields_json, plan_stale, source_candidate_id, revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, '[]', 0, ?, 2, ?, ?)
                """,
                (
                    blueprint_id,
                    project_id,
                    "回到一九九八年救下家乡木竹厂",
                    json.dumps(blueprint_content, ensure_ascii=False),
                    json.dumps({field: field == "ending_direction" for field in fields}),
                    json.dumps({field: 1 for field in fields}),
                    "f6f7db1e-96a7-4656-a540-96d81d9fa046",
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO volume_plans (
                    id, project_id, volume_number, content_json, locked, revision, created_at, updated_at
                ) VALUES (?, ?, 1, ?, 1, 1, ?, ?)
                """,
                (volume_id, project_id, json.dumps(volume_content, ensure_ascii=False), timestamp, timestamp),
            )
            connection.execute(
                """
                INSERT INTO rolling_chapter_plans (
                    id, project_id, volume_plan_id, chapter_number, content_json,
                    locked, revision, created_at, updated_at
                ) VALUES (?, ?, ?, 1, ?, 0, 3, ?, ?)
                """,
                (
                    rolling_id,
                    project_id,
                    volume_id,
                    json.dumps(rolling_content, ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
        archive = client.get(f"/api/projects/{project_id}/export").json()
        restored_response = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )

    assert archive["format_version"] == 7
    assert archive["tables"]["book_blueprints"][0]["revision"] == 2
    assert restored_response.status_code == 201
    restored = restored_response.json()
    assert restored["book_blueprint"]["content"]["ending_direction"] == blueprint_content[
        "ending_direction"
    ]
    assert restored["book_blueprint"]["locks"]["ending_direction"] is True
    assert restored["volume_plans"][0]["title"] == "停产名单"
    assert restored["volume_plans"][0]["locked"] is True
    assert restored["rolling_chapter_plans"][0]["opening_hook"] == "停产名单提前贴出"
    assert restored["rolling_chapter_plans"][0]["revision"] == 3


def test_archive_round_trip_preserves_review_versions_and_partial_changes(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "review-archive.db"
    manuscript = "一九九八年，他掏出智能手机。院外一片寂静。"
    with TestClient(create_app(database_path)) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "审校归档",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        chapter_id = workspace["chapters"][0]["id"]
        chapter = client.patch(
            f"/api/chapters/{chapter_id}",
            json={"content": manuscript, "expected_revision": 0},
        ).json()
        reviews = client.app.state.review_repository
        excerpts = [
            ("智能手机", "传呼机", ReviewDimension.REALISM, "年代物件错置"),
            ("一片寂静", "只剩虫鸣", ReviewDimension.STYLE, "场景感官单薄"),
        ]
        findings = []
        for ordinal, (excerpt, replacement, dimension, title) in enumerate(excerpts):
            start = manuscript.index(excerpt)
            finding = make_finding(
                job_id=f"archive-review-{ordinal}",
                project_id=project_id,
                chapter_id=chapter_id,
                chapter_revision=chapter["revision"],
                dimension=dimension,
                severity=ReviewSeverity.WARNING,
                code=f"archive_{ordinal}",
                title=title,
                evidence=[
                    ReviewEvidence(
                        kind=ReviewEvidenceKind.BODY,
                        chapter_id=chapter_id,
                        start_char=start,
                        end_char=start + len(excerpt),
                        excerpt=excerpt,
                        label="正文原句",
                    )
                ],
                explanation="该处需要作者确认后局部修改。",
                suggestion="仅替换有证据的正文范围。",
                suggested_replacement=replacement,
                confidence=0.95,
            ).model_copy(update={"review_job_id": None})
            findings.append(finding)
        reviews.save_findings(findings)

        change_set = client.post(
            f"/api/chapters/{chapter_id}/text-change-sets",
            json={"finding_ids": [item.id for item in findings]},
        ).json()
        selected = change_set["changes"][0]
        applied = client.post(
            f"/api/text-change-sets/{change_set['id']}/apply",
            json={
                "selected_change_ids": [selected["id"]],
                "edited_replacements": {selected["id"]: "传呼机和公用电话"},
                "expected_set_revision": change_set["revision"],
                "expected_chapter_revision": chapter["revision"],
            },
        ).json()
        archive = client.get(f"/api/projects/{project_id}/export").json()
        restored_response = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )
        restored = restored_response.json()
        restored_chapter_id = restored["chapters"][0]["id"]
        restored_versions = client.get(
            f"/api/chapters/{restored_chapter_id}/versions"
        ).json()
        restored_findings = client.get(
            f"/api/chapters/{restored_chapter_id}/review-findings"
        ).json()
        restored_sets = client.get(
            f"/api/chapters/{restored_chapter_id}/text-change-sets"
        ).json()

    assert restored_response.status_code == 201
    assert restored["chapters"][0]["content"] == applied["content"]
    assert [item["source"] for item in restored_versions][:2] == [
        "change_set_apply",
        "manual_save",
    ]
    assert {item["state"] for item in restored_findings} == {"accepted", "open"}
    assert restored_sets[0]["state"] == "applied"
    assert [item["selected"] for item in restored_sets[0]["changes"]] == [True, False]
    assert restored_sets[0]["changes"][0]["applied_replacement"] == "传呼机和公用电话"


def test_reality_source_archive_defaults_to_card_snapshot_and_can_include_raw_asset(
    tmp_path: Path,
) -> None:
    raw_source = "一九九八年春，南平城区早市猪肉每斤六元。".encode()
    source_sha256 = hashlib.sha256(raw_source).hexdigest()
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "现实资料归档",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        imported_card = client.post(
            "/api/source-library/file-imports",
            params={
                "project_id": project_id,
                "source_filename": "南平早市.txt",
                "title": "南平早市物价",
                "source_kind": "historical_record",
                "source_reference": "作者自有走访记录",
                "applicable_year_start": 1998,
                "applicable_year_end": 1998,
                "confidence": "medium",
                "source_date": "1998-03",
                "expected_source_sha256": source_sha256,
                "confirm_preview": "true",
            },
            content=raw_source,
            headers={"Content-Type": "text/plain"},
        ).json()

        default_archive = client.get(f"/api/projects/{project_id}/export").json()
        full_archive = client.get(
            f"/api/projects/{project_id}/export?include_reference_assets=true"
        ).json()
        restored = client.post(
            "/api/project-imports",
            content=canonical_json(full_archive),
            headers={"Content-Type": "application/json"},
        ).json()
        global_documents = client.get("/api/source-library/documents").json()

    assert default_archive["tables"]["source_documents"] == []
    assert default_archive["tables"]["source_cards"][0]["source_document_id"] is None
    assert default_archive["tables"]["source_cards"][0]["excerpt"] == raw_source.decode()
    assert full_archive["tables"]["source_documents"][0]["content"] == raw_source.decode()
    assert full_archive["tables"]["source_cards"][0]["source_document_id"] == imported_card[
        "source_document_id"
    ]
    assert restored["source_cards"][0]["source_document_id"] != imported_card[
        "source_document_id"
    ]
    assert restored["source_cards"][0]["source_date"] == "1998-03"
    assert len(global_documents) == 2


def test_export_returns_not_found_without_leaking_details(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        response = client.get(
            "/api/projects/05f14cb8-d0ed-4489-bc20-31c44c1efbba/export"
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "项目不存在"}


def test_import_upgrades_v1_project_owned_reference_archive(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "旧归档迁移",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        client.post(
            f"/api/projects/{project_id}/reference-works",
            json={
                "title": "旧版参考",
                "source_filename": "legacy.txt",
                "rights_basis": "self_owned",
                "content": "旧版原文",
                "segment_target_characters": 500_000,
            },
        )
        archive = client.get(
            f"/api/projects/{project_id}/export?include_reference_assets=true"
        ).json()
        archive["format_version"] = 1
        archive["tables"]["reference_works"] = [
            {
                key: value
                for key, value in work.items()
                if key not in {
                    "content_sha256", "source_sha256", "source_encoding",
                    "encoding_confidence", "import_state", "source_spans_json",
                    "duplicate_of_id", "updated_at",
                }
            } | {"project_id": project_id}
            for work in archive["tables"]["reference_works"]
        ]
        unsigned = dict(archive)
        unsigned.pop("checksum_sha256")
        archive["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()

        restored = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )

    assert restored.status_code == 201
    assert restored.json()["reference_works"][0]["title"] == "旧版参考"
    assert restored.json()["reference_works"][0]["segments"][0]["character_count"] == 4


def test_import_restores_complete_project_as_new_copy(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        original = client.post(
            "/api/projects",
            json={
                "title": "回到九八年的南平",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = original["project"]["id"]
        chapter_id = original["chapters"][0]["id"]
        client.patch(
            f"/api/chapters/{chapter_id}",
            json={"content": "原稿不可被覆盖。", "expected_revision": 0},
        )
        source_entity = client.post(
            f"/api/projects/{project_id}/story-entities",
            json={
                "kind": "character",
                "name": "林川",
                "role": "主角",
                "goal": "改变家庭命运",
                "current_state": "刚回到一九九八年",
                "relationship_notes": "",
            },
        ).json()
        client.put(
            f"/api/chapters/{chapter_id}/context-directives",
            json={
                "source_kind": "entity",
                "source_id": source_entity["id"],
                "action": "pin",
                "expected_revision": None,
            },
        )
        imported_reference = client.post(
            f"/api/projects/{project_id}/reference-works",
            json={
                "title": "第一份自有素材",
                "source_filename": "owned.txt",
                "rights_basis": "self_owned",
                "content": "第一章\n来自旧时代的潮声。",
                "segment_target_characters": 500_000,
            },
        ).json()
        source_segment_id = imported_reference["segments"][0]["id"]
        jobs: JobRepository = client.app.state.job_repository
        source_job, _ = jobs.create_job(
            project_id=project_id,
            kind=JobKind.REVIEW,
            idempotency_key="pattern-source-job",
            input_payload={"selected_segment_ids": [source_segment_id]},
            provider="openai",
            model="gpt-5.6",
        )
        archive = client.get(
            f"/api/projects/{project_id}/export?include_reference_assets=true"
        ).json()
        pattern_card_id = str(uuid4())
        dimension = {
            "summary": "现实秩序发生松动",
            "source_segment_ids": [source_segment_id],
            "transferable_logic": "先给主角一个可验证的小窗口",
            "adaptation_risk": "必须重组人物和场景",
        }
        archive["tables"]["reference_pattern_cards"].append({
            "id": pattern_card_id,
            "project_id": project_id,
            "selected_segment_ids_json": json.dumps([source_segment_id]),
            "author_focus": "验证模式卡引用重映射",
            "proposal_json": json.dumps({
                "era": dimension,
                "core_desire": dimension,
                "conflict_causality": dimension,
                "resource_system": dimension,
                "key_scene_sequence": dimension,
                "ending": dimension,
                "shared_patterns": ["先验证信息差"],
                "differences": ["人物关系不同"],
                "relationship_recomposition": "将原关系重组为师徒竞争",
                "originality_risks": [],
            }, ensure_ascii=False),
            "provider": "openai",
            "model": "gpt-5.6",
            "source_job_id": source_job.id,
            "created_at": archive["exported_at"],
        })
        application_id = str(uuid4())
        blueprint = {
            "dimensions": {
                "era": {
                    "source": dimension,
                    "mode": "preserve",
                    "author_edits": "只保留抽象因果",
                    "generated_variant": {
                        "summary": "现实秩序发生松动",
                        "transferable_logic": "先给主角一个可验证的小窗口",
                    },
                    "version": 1,
                    "locked": False,
                    "named_entities": [],
                    "source_beats": [],
                    "key_beats": [],
                }
            },
            "relationship": {
                "source": "将原关系重组为师徒竞争",
                "mode": "preserve",
                "author_edits": "只保留抽象因果",
                "generated_variant": "将原关系重组为师徒竞争",
                "version": 1,
                "locked": False,
                "relationships": [],
            },
        }
        blueprint_json = json.dumps(blueprint, ensure_ascii=False)
        archive["tables"]["reference_pattern_applications"].append({
            "id": application_id,
            "project_id": project_id,
            "pattern_card_id": pattern_card_id,
            "selected_dimensions_json": json.dumps(["era"]),
            "dimensions_json": json.dumps({
                "era": {
                    "summary": "现实秩序发生松动",
                    "transferable_logic": "先给主角一个可验证的小窗口",
                }
            }, ensure_ascii=False),
            "relationship_recomposition": "将原关系重组为师徒竞争",
            "application_note": "只保留抽象因果",
            "blueprint_json": blueprint_json,
            "originality_status": "needs_check",
            "risk_level": None,
            "latest_report_id": None,
            "threshold_version": None,
            "revision": 0,
            "created_at": archive["exported_at"],
            "updated_at": archive["exported_at"],
        })
        archive["tables"]["reference_blueprint_versions"].append({
            "id": str(uuid4()),
            "application_id": application_id,
            "blueprint_revision": 0,
            "blueprint_json": blueprint_json,
            "changed_dimensions_json": json.dumps(["era"]),
            "relationship_changed": 1,
            "created_at": archive["exported_at"],
        })
        unsigned = dict(archive)
        unsigned.pop("checksum_sha256")
        archive["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()

        restored_response = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )

        original_after = client.get(f"/api/projects/{project_id}").json()
        projects = client.get("/api/projects").json()
        restored_jobs = client.get(
            f"/api/projects/{restored_response.json()['project']['id']}/jobs"
        ).json()
        restored_directives = client.get(
            f"/api/chapters/{restored_response.json()['chapters'][0]['id']}/context-directives"
        ).json()

    assert restored_response.status_code == 201
    restored = restored_response.json()
    assert restored["project"]["id"] != project_id
    assert restored["project"]["title"] == "回到九八年的南平（恢复副本）"
    assert restored["chapters"][0]["id"] != chapter_id
    assert restored["chapters"][0]["project_id"] == restored["project"]["id"]
    assert restored["chapters"][0]["content"] == "原稿不可被覆盖。"
    assert restored["reference_works"][0]["id"] != imported_reference["id"]
    assert restored["reference_works"][0]["segments"][0]["id"] != imported_reference["segments"][0]["id"]
    restored_segment_id = restored["reference_works"][0]["segments"][0]["id"]
    restored_card = restored["reference_pattern_cards"][0]
    assert restored_card["id"] != pattern_card_id
    assert restored_card["selected_segment_ids"] == [restored_segment_id]
    assert restored_card["era"]["source_segment_ids"] == [restored_segment_id]
    assert restored_card["source_job_id"] == restored_jobs[0]["id"]
    assert restored_card["source_job_id"] != source_job.id
    assert restored["reference_pattern_applications"][0]["pattern_card_id"] == restored_card["id"]
    assert restored_directives[0]["source_id"] == restored["story_entities"][0]["id"]
    assert restored_directives[0]["source_id"] != source_entity["id"]
    assert original_after["project"]["title"] == "回到九八年的南平"
    assert original_after["chapters"][0]["id"] == chapter_id
    assert len(projects) == 2


def test_archive_round_trip_preserves_job_history_and_immutable_artifacts(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "可恢复任务归档",
                "genre": "historical_rebirth",
                "rebirth_year": 1984,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        jobs: JobRepository = client.app.state.job_repository
        job, _ = jobs.create_job(
            project_id=project_id,
            kind=JobKind.REFERENCE_FUSION,
            idempotency_key="archive-fusion",
            input_payload={"selected_segment_ids": ["a", "b"]},
            provider="openai",
            model="test-model",
        )
        artifact, _ = jobs.put_artifact(
            job.id,
            kind="reference_map",
            artifact_key="map-a-0",
            payload='{"era":"旧城改造"}',
            content_type="application/json",
            provider="openai",
            model="test-model",
        )
        archive = client.get(f"/api/projects/{project_id}/export").json()

        legacy_v3 = json.loads(json.dumps(archive))
        legacy_v3["format_version"] = 3
        for table_name in ("book_blueprints", "volume_plans", "rolling_chapter_plans"):
            legacy_v3["tables"].pop(table_name)
        for legacy_job in legacy_v3["tables"]["jobs"]:
            legacy_job.pop("workflow")
        legacy_unsigned = dict(legacy_v3)
        legacy_unsigned.pop("checksum_sha256")
        legacy_v3["checksum_sha256"] = hashlib.sha256(
            canonical_json(legacy_unsigned)
        ).hexdigest()
        legacy_restored = client.post(
            "/api/project-imports",
            content=canonical_json(legacy_v3),
            headers={"Content-Type": "application/json"},
        )

        restored = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        ).json()
        restored_project_id = restored["project"]["id"]
        restored_jobs = client.get(
            f"/api/projects/{restored_project_id}/jobs"
        ).json()
        restored_detail = client.get(f"/api/jobs/{restored_jobs[0]['id']}").json()
        restored_artifact = client.get(
            f"/api/job-artifacts/{restored_detail['artifacts'][0]['id']}"
        ).json()

    assert legacy_restored.status_code == 201
    assert restored_jobs[0]["id"] != job.id
    assert restored_jobs[0]["project_id"] == restored_project_id
    assert restored_jobs[0]["workflow"] == ""
    assert restored_detail["artifacts"][0]["id"] != artifact.id
    assert restored_artifact["payload"] == '{"era":"旧城改造"}'


def test_import_rejects_tampered_or_unknown_archive_without_writing(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        original = client.post(
            "/api/projects",
            json={
                "title": "南平旧厂",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "南平",
            },
        ).json()
        archive = client.get(
            f"/api/projects/{original['project']['id']}/export"
        ).json()
        archive["tables"]["projects"][0]["title"] = "被篡改的标题"

        tampered = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )

        archive = client.get(
            f"/api/projects/{original['project']['id']}/export"
        ).json()
        archive["tables"]["unknown_table"] = []
        archive_without_checksum = dict(archive)
        archive_without_checksum.pop("checksum_sha256")
        archive["checksum_sha256"] = hashlib.sha256(
            canonical_json(archive_without_checksum)
        ).hexdigest()
        unknown = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )
        projects = client.get("/api/projects").json()

    assert tampered.status_code == 400
    assert tampered.json() == {"detail": "项目归档无效或已损坏"}
    assert unknown.status_code == 400
    assert unknown.json() == {"detail": "项目归档无效或已损坏"}
    assert len(projects) == 1


def test_import_rejects_semantically_invalid_archive_without_orphan_copy(
    tmp_path: Path,
) -> None:
    application = create_app(tmp_path / "mozhou.db")
    with TestClient(application, raise_server_exceptions=False) as client:
        original = client.post(
            "/api/projects",
            json={
                "title": "语义校验底稿",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "南平",
            },
        ).json()
        archive = client.get(
            f"/api/projects/{original['project']['id']}/export"
        ).json()
        archive["tables"]["projects"][0]["genre"] = "unknown_genre"
        unsigned = dict(archive)
        unsigned.pop("checksum_sha256")
        archive["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()

        response = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )
        projects = client.get("/api/projects").json()

    assert response.status_code == 400
    assert response.json() == {"detail": "项目归档无效或已损坏"}
    assert [project["id"] for project in projects] == [original["project"]["id"]]


def test_import_requires_json_content_type(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        response = client.post(
            "/api/project-imports",
            content=b"not an archive",
            headers={"Content-Type": "text/plain"},
        )

    assert response.status_code == 415
    assert response.json() == {"detail": "请选择墨舟项目归档文件"}


def test_creates_lists_and_restores_compressed_recovery_point(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        original = client.post(
            "/api/projects",
            json={
                "title": "闽江潮生",
                "genre": "historical_rebirth",
                "rebirth_year": 1127,
                "rebirth_location": "福建路",
            },
        ).json()
        project_id = original["project"]["id"]
        chapter_id = original["chapters"][0]["id"]
        client.patch(
            f"/api/chapters/{chapter_id}",
            json={"content": "这是大改前必须保留的正文。" * 50, "expected_revision": 0},
        )

        created = client.post(
            f"/api/projects/{project_id}/recovery-points",
            json={"label": "第二卷大改前"},
        )
        listed = client.get(f"/api/projects/{project_id}/recovery-points")
        recovery_id = created.json()["id"]
        restored = client.post(f"/api/recovery-points/{recovery_id}/restore")

    assert created.status_code == 201
    assert created.json()["project_id"] == project_id
    assert created.json()["label"] == "第二卷大改前"
    assert created.json()["kind"] == "manual"
    assert created.json()["uncompressed_bytes"] > created.json()["compressed_bytes"]
    assert len(created.json()["archive_sha256"]) == 64
    assert listed.status_code == 200
    assert listed.json() == [created.json()]
    assert "payload_zlib" not in listed.json()[0]
    assert restored.status_code == 201
    assert restored.json()["project"]["id"] != project_id
    assert restored.json()["project"]["title"] == "闽江潮生（恢复副本）"
    assert restored.json()["chapters"][0]["content"] == "这是大改前必须保留的正文。" * 50


def test_recovery_point_project_and_id_return_sanitized_not_found(tmp_path: Path) -> None:
    missing_id = "05f14cb8-d0ed-4489-bc20-31c44c1efbba"
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        create_response = client.post(
            f"/api/projects/{missing_id}/recovery-points",
            json={"label": "不存在"},
        )
        restore_response = client.post(f"/api/recovery-points/{missing_id}/restore")

    assert create_response.status_code == 404
    assert create_response.json() == {"detail": "项目不存在"}
    assert restore_response.status_code == 404
    assert restore_response.json() == {"detail": "恢复点不存在"}
