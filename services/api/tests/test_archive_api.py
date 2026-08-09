import hashlib
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.jobs import JobKind, JobRepository
from app.main import create_app

ARCHIVE_TABLES = {
    "projects",
    "chapters",
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
    "source_cards",
    "reference_works",
    "reference_segments",
    "reference_pattern_cards",
    "reference_pattern_applications",
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

        response = client.get(f"/api/projects/{project_id}/export")

    assert response.status_code == 200
    archive = response.json()
    assert archive["format"] == "mozhou-project"
    assert archive["format_version"] == 1
    assert archive["source_project_id"] == project_id
    assert archive["source_project_title"] == "回到九八年的南平"
    assert set(archive["tables"]) == ARCHIVE_TABLES
    assert archive["tables"]["chapters"][0]["content"] == "列车驶入南平站。"
    assert archive["tables"]["reference_segments"][0]["content"] == "# 第一章\n潮水从闽江上来。"
    assert archive["tables"]["reference_segments"][0]["id"] == reference["segments"][0]["id"]
    checksum = archive.pop("checksum_sha256")
    assert checksum == hashlib.sha256(canonical_json(archive)).hexdigest()


def test_export_returns_not_found_without_leaking_details(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        response = client.get(
            "/api/projects/05f14cb8-d0ed-4489-bc20-31c44c1efbba/export"
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "项目不存在"}


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
        archive = client.get(f"/api/projects/{project_id}/export").json()
        source_segment_id = imported_reference["segments"][0]["id"]
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
            "created_at": archive["exported_at"],
        })
        archive["tables"]["reference_pattern_applications"].append({
            "id": str(uuid4()),
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
    assert restored["reference_pattern_applications"][0]["pattern_card_id"] == restored_card["id"]
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

    assert restored_jobs[0]["id"] != job.id
    assert restored_jobs[0]["project_id"] == restored_project_id
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
