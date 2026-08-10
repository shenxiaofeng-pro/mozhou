from pathlib import Path
from time import perf_counter

from fastapi.testclient import TestClient

from app.main import create_app


def _project(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/projects",
        json={
            "title": "南平旧梦",
            "genre": "urban_rebirth",
            "rebirth_year": 1992,
            "rebirth_location": "南平",
            "chapter_target_words": 3200,
            "safety_buffer_chapters": 5,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_serial_goal_actual_words_and_optimistic_concurrency(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "serial.db")) as client:
        workspace = _project(client)
        project_id = workspace["project"]["id"]
        chapter = workspace["chapters"][0]
        content = "列车驶入南平站。厂门外挤满了人。"
        saved = client.patch(
            f"/api/chapters/{chapter['id']}",
            json={"content": content, "expected_revision": chapter["revision"]},
        )
        assert saved.status_code == 200

        dashboard = client.get(f"/api/projects/{project_id}/serial-dashboard").json()
        assert dashboard["goal"]["target_characters"] == 3200
        assert dashboard["goal"]["actual_characters"] == len(content)
        goal_date = dashboard["goal"]["goal_date"]

        updated = client.put(
            f"/api/projects/{project_id}/serial-goals/{goal_date}",
            json={"target_characters": 6000, "expected_revision": 0},
        )
        assert updated.status_code == 200
        assert updated.json()["goal"]["target_characters"] == 6000
        updated_again = client.put(
            f"/api/projects/{project_id}/serial-goals/{goal_date}",
            json={"target_characters": 8000, "expected_revision": 0},
        )
        assert updated_again.status_code == 200
        assert client.put(
            f"/api/projects/{project_id}/serial-goals/{goal_date}",
            json={"target_characters": 9000, "expected_revision": 0},
        ).status_code == 409


def test_search_scans_a_300k_manuscript_and_returns_bounded_snippets(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "search.db")) as client:
        workspace = _project(client)
        project_id = workspace["project"]["id"]
        chapter = workspace["chapters"][0]
        content = "甲" * 299_950 + "竹海订单终于落地" + "乙" * 30
        saved = client.patch(
            f"/api/chapters/{chapter['id']}",
            json={"content": content, "expected_revision": chapter["revision"]},
        )
        assert saved.status_code == 200
        character = client.post(
            f"/api/projects/{project_id}/story-entities",
            json={
                "kind": "character",
                "name": "陈砚",
                "role": "竹海订单经办人",
                "goal": "保住纸厂",
                "current_state": "等待签约",
                "relationship_notes": "与厂长存在分歧",
            },
        )
        assert character.status_code == 201

        started = perf_counter()
        response = client.get(
            f"/api/projects/{project_id}/search",
            params={"q": "竹海订单", "limit": 20},
        )
        elapsed = perf_counter() - started

        assert response.status_code == 200
        assert elapsed < 2
        results = response.json()
        assert {item["kind"] for item in results} == {"chapter", "character"}
        assert all(len(item["snippet"]) <= 162 for item in results)
        assert next(item for item in results if item["kind"] == "chapter")["chapter_id"] == chapter["id"]
