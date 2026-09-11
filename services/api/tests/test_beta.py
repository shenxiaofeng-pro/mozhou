import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from app.archive import ARCHIVE_TABLES
from app.main import create_app


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
    assert payload["metrics"]["chapter_count"] == 1
    assert payload["metrics"]["written_chapter_count"] == 1
    assert payload["feedback"][0]["rating"] == 4
    milestones = {item["key"]: item for item in payload["milestones"]}
    assert milestones["project"]["completed"] is True
    assert milestones["export"]["completed"] is True
    assert milestones["ten_chapters"]["completed"] is False
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "不能进入封测报告的作品名" not in serialized
    assert "这段正文绝不能进入报告" not in serialized
    assert str(database_path) not in serialized


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
