import json
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from app.archive import ARCHIVE_TABLES
from app.chapter_production.demo import DeterministicDemoChapterAdapter
from app.main import create_app
from app.models import ChapterVersionSource
from app.review.repository import ReviewRepository


def _create_project(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/projects",
        json={
            "title": "不能进入封测报告的作品名",
            "genre": "urban_rebirth",
            "rebirth_year": 1998,
            "rebirth_location": "福建南平",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_closed_beta_templates_cover_five_guided_scenarios(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        response = client.get("/api/beta/templates")

    assert response.status_code == 200
    templates = response.json()
    assert [template["id"] for template in templates] == [
        "historical-rebirth",
        "urban-rebirth",
        "reality-anchor",
        "eastern-fantasy",
        "western-fantasy",
    ]
    assert {template["genre"] for template in templates} == {
        "historical_rebirth",
        "urban_rebirth",
        "eastern_fantasy",
        "western_fantasy",
    }
    assert all(template["idea_prompt"] for template in templates)
    assert all(template["reality_anchor"] for template in templates)


def test_closed_beta_report_tracks_local_milestones_without_manuscript(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "mozhou.db"
    with TestClient(create_app(database_path)) as client:
        workspace = _create_project(client)
        project = workspace["project"]
        chapter = workspace["chapters"][0]
        assert isinstance(project, dict)
        assert isinstance(chapter, dict)
        project_id = str(project["id"])
        chapter_id = str(chapter["id"])

        saved = client.patch(
            f"/api/chapters/{chapter_id}",
            json={"content": "这段正文绝不能进入报告。", "expected_revision": 0},
        )
        assert saved.status_code == 200
        feedback = client.post(
            f"/api/projects/{project_id}/beta-feedback",
            json={
                "category": "usability",
                "context": "writing",
                "rating": 4,
                "note": "切章很顺手，但还想要更醒目的状态。",
            },
        )
        event = client.post(
            f"/api/projects/{project_id}/beta-events/manuscript_export"
        )
        report = client.get(f"/api/projects/{project_id}/beta-report")

    assert feedback.status_code == 201
    assert event.status_code == 204
    assert report.status_code == 200
    payload = report.json()
    assert payload["format"] == "mozhou-closed-beta-report"
    assert payload["format_version"] == 2
    assert payload["metrics"]["chapter_count"] == 1
    assert payload["metrics"]["written_chapter_count"] == 1
    assert payload["metrics"]["longest_consecutive_written_chapters"] == 1
    assert payload["metrics"]["ten_chapter_sequence_completed"] is False
    assert payload["feedback"][0]["rating"] == 4
    assert payload["subjective_ratings"] == [
        {
            "category": "usability",
            "context": "writing",
            "response_count": 1,
            "mean_rating": 4.0,
        }
    ]
    milestones = {item["key"]: item for item in payload["milestones"]}
    assert milestones["project"]["completed"] is True
    assert milestones["export"]["completed"] is True
    assert milestones["ten_chapters"]["completed"] is False
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "不能进入封测报告的作品名" not in serialized
    assert "这段正文绝不能进入报告" not in serialized
    assert str(database_path) not in serialized


def test_closed_beta_report_separates_retention_adjustments_sequence_and_ratings(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "beta-metric-boundaries.db"
    with TestClient(create_app(database_path)) as client:
        workspace = _create_project(client)
        project_id = str(workspace["project"]["id"])
        chapters = [workspace["chapters"][0]]
        for number in range(2, 11):
            response = client.post(
                f"/api/projects/{project_id}/chapters",
                json={"expected_last_chapter_number": number - 1},
            )
            assert response.status_code == 201, response.text
            chapters.append(response.json())

        applied_and_current = (
            ("abcdefghij", "abcdefghij"),
            ("abcdefghij", "abcdefghiX"),
            ("abcdefghij", "abcdXXXXXX"),
            ("abcdefghij", "XXXXXXXXXX"),
        )
        database = client.app.state.repository.database
        for index, chapter in enumerate(chapters):
            applied_content = (
                applied_and_current[index][0]
                if index < len(applied_and_current)
                else f"第 {index + 1} 章已完成正文"
            )
            saved = client.patch(
                f"/api/chapters/{chapter['id']}",
                json={"content": applied_content, "expected_revision": 0},
            )
            assert saved.status_code == 200, saved.text
            if index < len(applied_and_current):
                with database.connect() as connection:
                    ReviewRepository.append_chapter_version(
                        connection,
                        chapter_id=str(chapter["id"]),
                        chapter_revision=1,
                        content=applied_content,
                        source=ChapterVersionSource.GENERATION_CANDIDATE,
                        source_id=str(uuid4()),
                        is_candidate=True,
                    )
                    ReviewRepository.append_chapter_version(
                        connection,
                        chapter_id=str(chapter["id"]),
                        chapter_revision=1,
                        content=applied_content,
                        source=ChapterVersionSource.GENERATION_APPLY,
                        source_id=str(uuid4()),
                    )
                current_content = applied_and_current[index][1]
                if current_content != applied_content:
                    changed = client.patch(
                        f"/api/chapters/{chapter['id']}",
                        json={"content": current_content, "expected_revision": 1},
                    )
                    assert changed.status_code == 200, changed.text

        for rating in (3, 5):
            feedback = client.post(
                f"/api/projects/{project_id}/beta-feedback",
                json={
                    "category": "ai_quality",
                    "context": "writing",
                    "rating": rating,
                    "note": "只记录主观感受，不混入系统指标。",
                },
            )
            assert feedback.status_code == 201
        report = client.get(f"/api/projects/{project_id}/beta-report")

    assert report.status_code == 200
    payload = report.json()
    metrics = payload["metrics"]
    assert metrics["longest_consecutive_written_chapters"] == 10
    assert metrics["ten_chapter_sequence_completed"] is True
    assert metrics["ai_candidate_count"] == 4
    assert metrics["ai_applied_count"] == 4
    assert metrics["ai_adoption_rate"] == 1.0
    assert metrics["mean_ai_text_retention_rate"] == 0.575
    assert metrics["mean_manual_modification_ratio"] == 0.425
    assert metrics["manual_adjustment_type_counts"] == {
        "accepted_as_is": 1,
        "light_edit": 1,
        "substantial_edit": 1,
        "rewrite": 1,
        "partial_adoption": 0,
    }
    milestones = {item["key"]: item for item in payload["milestones"]}
    assert milestones["ten_chapters"] == {
        "key": "ten_chapters",
        "label": "连续完成至少十章正文",
        "completed": True,
        "evidence_count": 10,
    }
    assert payload["subjective_ratings"] == [
        {
            "category": "ai_quality",
            "context": "writing",
            "response_count": 2,
            "mean_rating": 4.0,
        }
    ]


def test_closed_beta_report_tracks_m33_adoption_and_m34_canon_acceptance(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "beta-m33-m34.db"
    app = create_app(database_path, defer_job_runtime=True)
    with TestClient(app) as client:
        app.state.chapter_production_service.adapter = (
            DeterministicDemoChapterAdapter()
        )
        workspace = _create_project(client)
        project_id = str(workspace["project"]["id"])
        chapter = workspace["chapters"][0]
        chapter_id = str(chapter["id"])

        production = client.post(
            f"/api/projects/{project_id}/chapters/{chapter_id}/productions",
            json={
                "expected_chapter_revision": chapter["revision"],
                "expected_chapter_content_sha256": sha256(
                    str(chapter["content"]).encode("utf-8")
                ).hexdigest(),
            },
        )
        assert production.status_code == 201, production.text
        production_id = production.json()["production"]["id"]

        outline_request = {"author_intent": "先用一场危机建立主角的行动力"}
        outline_preview = client.post(
            f"/api/chapter-productions/{production_id}/outline/preview",
            json=outline_request,
        )
        assert outline_preview.status_code == 200, outline_preview.text
        outline_job = client.post(
            f"/api/chapter-productions/{production_id}/outline/jobs",
            json={
                **outline_request,
                "context_packet_id": outline_preview.json()["context_packet_id"],
                "context_packet_sha256": outline_preview.json()[
                    "context_packet_sha256"
                ],
            },
        )
        assert outline_job.status_code == 202, outline_job.text
        assert app.state.job_runtime.run_once()
        outline = client.get(
            f"/api/chapter-productions/{production_id}/outline/jobs/"
            f"{outline_job.json()['id']}/result"
        )
        assert outline.status_code == 200, outline.text
        outline_candidate = outline.json()
        outline_guard = {
            "outline_candidate_id": outline_candidate["id"],
            "expected_outline_revision": outline_candidate["current_version"]["revision"],
            "expected_outline_content_sha256": outline_candidate["current_version"][
                "content_sha256"
            ],
        }

        draft_request = {
            **outline_guard,
            "author_intent": "保留现实代价，并在章末留下新压力",
        }
        draft_preview = client.post(
            f"/api/chapter-productions/{production_id}/draft/preview",
            json=draft_request,
        )
        assert draft_preview.status_code == 200, draft_preview.text
        draft_job = client.post(
            f"/api/chapter-productions/{production_id}/draft/jobs",
            json={
                **draft_request,
                "context_packet_id": draft_preview.json()["context_packet_id"],
                "context_packet_sha256": draft_preview.json()["context_packet_sha256"],
            },
        )
        assert draft_job.status_code == 202, draft_job.text
        assert app.state.job_runtime.run_once()
        draft = client.get(
            f"/api/chapter-productions/{production_id}/draft/jobs/"
            f"{draft_job.json()['id']}/result"
        )
        assert draft.status_code == 200, draft.text
        candidate = draft.json()
        candidate_version = candidate["current_version"]

        adopted = client.post(
            f"/api/chapter-productions/{production_id}/candidates/"
            f"{candidate['id']}/adopt",
            json={
                "expected_candidate_revision": candidate_version["revision"],
                "expected_candidate_content_sha256": candidate_version["content_sha256"],
                "expected_chapter_revision": chapter["revision"],
                "expected_chapter_content_sha256": sha256(
                    str(chapter["content"]).encode("utf-8")
                ).hexdigest(),
                "mode": "whole",
                "idempotency_key": "beta-m33-adopt-0001",
            },
        )
        assert adopted.status_code == 200, adopted.text

        final_body = f"{candidate_version['content']}\n\n沈砚得到一枚灵石。"
        chapter = client.patch(
            f"/api/chapters/{chapter_id}",
            json={
                "content": final_body,
                "expected_revision": adopted.json()["final_chapter_revision"],
            },
        ).json()
        chapter = client.patch(
            f"/api/chapters/{chapter_id}/brief",
            json={
                "opening_hook": "坏消息提前抵达",
                "state_change": "沈砚主动承担风险",
                "ending_cliffhanger": "更大的代价已经找上门",
                "expected_revision": chapter["revision"],
            },
        ).json()
        chapter = client.post(
            f"/api/chapters/{chapter_id}/transition",
            json={"target_status": "reviewing", "expected_revision": chapter["revision"]},
        ).json()
        approved = client.post(
            f"/api/chapters/{chapter_id}/transition",
            json={
                "target_status": "approved",
                "expected_revision": chapter["revision"],
                "expected_content_sha256": sha256(final_body.encode("utf-8")).hexdigest(),
                "source_writing_outcome_id": adopted.json()["id"],
            },
        )
        assert approved.status_code == 200, approved.text
        assert app.state.job_runtime.run_once()

        latest_url = (
            f"/api/projects/{project_id}/chapters/{chapter_id}"
            "/canon-reconciliation/latest"
        )
        reconciliation = client.get(latest_url)
        assert reconciliation.status_code == 200, reconciliation.text
        snapshot = reconciliation.json()
        first, *remaining = snapshot["canon_candidates"]
        decision = client.post(
            f"/api/projects/{project_id}/canon-reconciliations/"
            f"{snapshot['reconciliation']['id']}/decisions",
            json={
                "reconciliation_id": snapshot["reconciliation"]["id"],
                "expected_reconciliation_revision": snapshot["reconciliation"][
                    "revision"
                ],
                "idempotency_key": "beta-m34-canon-0001",
                "canon_decisions": [
                    {
                        "candidate_id": first["id"],
                        "expected_revision": first["revision"],
                        "action": "accept",
                    },
                    *[
                        {
                            "candidate_id": item["id"],
                            "expected_revision": item["revision"],
                            "action": "reject",
                            "rejection_reason": "本轮仅确认一条正式设定",
                        }
                        for item in remaining
                    ],
                ],
                "preference_decisions": [
                    {
                        "candidate_id": item["id"],
                        "expected_revision": item["revision"],
                        "action": "reject",
                        "rejection_reason": "本轮不累积写作偏好",
                    }
                    for item in snapshot["preference_candidates"]
                ],
            },
        )
        assert decision.status_code == 200, decision.text
        report = client.get(f"/api/projects/{project_id}/beta-report")

    assert report.status_code == 200, report.text
    payload = report.json()
    metrics = payload["metrics"]
    assert metrics["ai_candidate_count"] == 1
    assert metrics["ai_applied_count"] == 1
    assert metrics["ai_adoption_rate"] == 1.0
    assert 0.8 <= metrics["mean_ai_text_retention_rate"] < 0.98
    assert metrics["manual_adjustment_type_counts"] == {
        "accepted_as_is": 0,
        "light_edit": 1,
        "substantial_edit": 0,
        "rewrite": 0,
        "partial_adoption": 0,
    }
    milestones = {item["key"]: item for item in payload["milestones"]}
    assert milestones["fact"] == {
        "key": "fact",
        "label": "确认候选事实回灌",
        "completed": True,
        "evidence_count": 1,
    }


def test_ten_written_chapters_with_a_gap_do_not_complete_the_sequence(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(tmp_path / "beta-sequence-gap.db")) as client:
        workspace = _create_project(client)
        project_id = str(workspace["project"]["id"])
        chapters = [workspace["chapters"][0]]
        for number in range(2, 12):
            created = client.post(
                f"/api/projects/{project_id}/chapters",
                json={"expected_last_chapter_number": number - 1},
            )
            assert created.status_code == 201
            chapters.append(created.json())
        for number, chapter in enumerate(chapters, start=1):
            if number == 6:
                continue
            saved = client.patch(
                f"/api/chapters/{chapter['id']}",
                json={"content": f"第 {number} 章正文", "expected_revision": 0},
            )
            assert saved.status_code == 200
        report = client.get(f"/api/projects/{project_id}/beta-report")

    assert report.status_code == 200
    metrics = report.json()["metrics"]
    assert metrics["written_chapter_count"] == 10
    assert metrics["longest_consecutive_written_chapters"] == 5
    assert metrics["ten_chapter_sequence_completed"] is False
    milestone = next(
        item for item in report.json()["milestones"] if item["key"] == "ten_chapters"
    )
    assert milestone["completed"] is False
    assert milestone["evidence_count"] == 5


def test_unicode_whitespace_only_chapters_do_not_complete_the_sequence(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(tmp_path / "beta-unicode-whitespace.db")) as client:
        workspace = _create_project(client)
        project_id = str(workspace["project"]["id"])
        chapters = [workspace["chapters"][0]]
        for number in range(2, 11):
            created = client.post(
                f"/api/projects/{project_id}/chapters",
                json={"expected_last_chapter_number": number - 1},
            )
            assert created.status_code == 201
            chapters.append(created.json())
        for chapter in chapters:
            saved = client.patch(
                f"/api/chapters/{chapter['id']}",
                json={"content": "\n\t　", "expected_revision": 0},
            )
            assert saved.status_code == 200
        report = client.get(f"/api/projects/{project_id}/beta-report")

    assert report.status_code == 200
    metrics = report.json()["metrics"]
    assert metrics["written_chapter_count"] == 0
    assert metrics["longest_consecutive_written_chapters"] == 0
    assert metrics["ten_chapter_sequence_completed"] is False
    milestone = next(
        item for item in report.json()["milestones"] if item["key"] == "ten_chapters"
    )
    assert milestone["completed"] is False
    assert milestone["evidence_count"] == 0


def test_closed_beta_originality_metrics_only_count_active_reference_applications(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(tmp_path / "active-reference-metrics.db")) as client:
        workspace = _create_project(client)
        project_id = str(workspace["project"]["id"])
        timestamp = "2026-09-11T00:00:00+00:00"
        database = client.app.state.repository.database
        with database.connect() as connection:
            for lifecycle_state, originality_status in (
                ("active", "blocked"),
                ("archived", "blocked"),
                ("active", "passed"),
                ("archived", "passed"),
            ):
                card_id = str(uuid4())
                application_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO reference_pattern_cards (
                        id, project_id, selected_segment_ids_json, author_focus,
                        proposal_json, provider, model, created_at
                    ) VALUES (?, ?, '[]', '', '{}', 'test', 'test', ?)
                    """,
                    (card_id, project_id, timestamp),
                )
                connection.execute(
                    """
                    INSERT INTO reference_pattern_applications (
                        id, project_id, pattern_card_id, lifecycle_state,
                        selected_dimensions_json, dimensions_json,
                        relationship_recomposition, application_note,
                        blueprint_json, originality_status, risk_level,
                        latest_report_id, threshold_version, revision,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, '[]', '{}', '重组关系', '', '{}', ?,
                              NULL, NULL, NULL, 0, ?, ?)
                    """,
                    (
                        application_id,
                        project_id,
                        card_id,
                        lifecycle_state,
                        originality_status,
                        timestamp,
                        timestamp,
                    ),
                )
        report = client.get(f"/api/projects/{project_id}/beta-report")

    assert report.status_code == 200
    payload = report.json()
    assert payload["metrics"]["originality_blocked_count"] == 1
    reference_milestone = next(
        item for item in payload["milestones"] if item["key"] == "reference"
    )
    assert reference_milestone["evidence_count"] == 1


def test_feedback_validation_and_missing_project_are_sanitized(tmp_path: Path) -> None:
    missing_id = "00000000-0000-4000-8000-000000000001"
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        workspace = _create_project(client)
        project = workspace["project"]
        assert isinstance(project, dict)
        project_id = str(project["id"])
        invalid = client.post(
            f"/api/projects/{project_id}/beta-feedback",
            json={
                "category": "usability",
                "context": "writing",
                "rating": 6,
                "note": "越界评分",
            },
        )
        missing = client.get(f"/api/projects/{missing_id}/beta-report")

    assert invalid.status_code == 422
    assert missing.status_code == 404
    assert missing.json() == {"detail": "作品不存在"}


def test_beta_research_data_stays_out_of_project_archives(tmp_path: Path) -> None:
    assert "beta_feedback" not in ARCHIVE_TABLES
    assert "beta_events" not in ARCHIVE_TABLES
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        workspace = _create_project(client)
        project = workspace["project"]
        assert isinstance(project, dict)
        project_id = str(project["id"])
        created = client.post(
            f"/api/projects/{project_id}/beta-feedback",
            json={
                "category": "workflow",
                "context": "release",
                "rating": 3,
                "note": "这条研究反馈不应跟随作品归档。",
            },
        )
        archive = client.get(f"/api/projects/{project_id}/export")

    assert created.status_code == 201
    assert archive.status_code == 200
    tables = archive.json()["tables"]
    assert "beta_feedback" not in tables
    assert "beta_events" not in tables
    assert "研究反馈" not in archive.text
