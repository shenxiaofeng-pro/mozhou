import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def _create_project(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/projects",
        json={
            "title": "闽北商潮",
            "genre": "urban_rebirth",
            "rebirth_year": 1992,
            "rebirth_location": "福建南平",
            "chapter_target_words": 3000,
            "safety_buffer_chapters": 5,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_directory_create_rename_move_safe_delete_and_undo(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "directory.db")) as client:
        workspace = _create_project(client)
        project_id = workspace["project"]["id"]
        first_volume = workspace["manuscript_volumes"][0]

        created_volume = client.post(
            f"/api/projects/{project_id}/directory-nodes",
            json={"kind": "volume", "title": "第二卷 竹海"},
        )
        assert created_volume.status_code == 201
        second_volume = created_volume.json()["manuscript_volumes"][1]

        created_chapter = client.post(
            f"/api/projects/{project_id}/directory-nodes",
            json={"kind": "chapter", "parent_id": first_volume["id"], "title": "第二章 厂门"},
        )
        chapter = created_chapter.json()["chapters"][1]
        created_scene = client.post(
            f"/api/projects/{project_id}/directory-nodes",
            json={
                "kind": "scene",
                "parent_id": chapter["id"],
                "title": "门卫室交锋",
                "summary": "拿回工牌",
            },
        )
        scene = created_scene.json()["manuscript_scenes"][0]

        renamed = client.patch(
            f"/api/directory-nodes/scene/{scene['id']}",
            json={
                "title": "门卫室破局",
                "summary": "当众拿回工牌",
                "expected_revision": scene["revision"],
            },
        )
        assert renamed.status_code == 200
        renamed_scene = renamed.json()["manuscript_scenes"][0]
        assert renamed_scene["summary"] == "当众拿回工牌"
        assert client.patch(
            f"/api/directory-nodes/scene/{scene['id']}",
            json={"title": "过期修改", "expected_revision": 0},
        ).status_code == 409

        moved = client.post(
            f"/api/directory-nodes/chapter/{chapter['id']}/move",
            json={
                "parent_id": second_volume["id"],
                "before_id": None,
                "expected_revision": chapter["revision"],
            },
        )
        assert moved.status_code == 200
        moved_chapter = next(item for item in moved.json()["chapters"] if item["id"] == chapter["id"])
        assert moved_chapter["volume_id"] == second_volume["id"]

        impact = client.get(
            f"/api/directory-nodes/chapter/{chapter['id']}/delete-impact"
        ).json()
        assert impact["descendant_scenes"] == 1
        assert impact["references"]["章节版本"] == 1
        assert client.request(
            "DELETE",
            f"/api/directory-nodes/chapter/{chapter['id']}",
            json={"expected_revision": moved_chapter["revision"], "confirm_impact": False},
        ).status_code == 409

        deleted = client.request(
            "DELETE",
            f"/api/directory-nodes/chapter/{chapter['id']}",
            json={"expected_revision": moved_chapter["revision"], "confirm_impact": True},
        )
        assert deleted.status_code == 200
        assert all(item["id"] != chapter["id"] for item in deleted.json()["chapters"])
        assert all(item["id"] != scene["id"] for item in deleted.json()["manuscript_scenes"])
        assert client.get(f"/api/chapters/{chapter['id']}").status_code == 404

        undone = client.post(f"/api/projects/{project_id}/directory-events/undo")
        assert undone.status_code == 200
        assert any(item["id"] == chapter["id"] for item in undone.json()["chapters"])
        assert any(item["id"] == scene["id"] for item in undone.json()["manuscript_scenes"])
        events = client.get(f"/api/projects/{project_id}/directory-events").json()
        assert events[0]["action"] == "delete"
        assert events[0]["undone_at"] is not None


def test_directory_protects_the_last_volume_and_chapter(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "last-node.db")) as client:
        workspace = _create_project(client)
        volume = workspace["manuscript_volumes"][0]
        chapter = workspace["chapters"][0]

        volume_impact = client.get(
            f"/api/directory-nodes/volume/{volume['id']}/delete-impact"
        ).json()
        chapter_impact = client.get(
            f"/api/directory-nodes/chapter/{chapter['id']}/delete-impact"
        ).json()

        assert volume_impact["can_delete"] is False
        assert chapter_impact["can_delete"] is False


def test_archive_round_trip_preserves_hierarchy_events_and_daily_goal(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "roundtrip.db")) as client:
        workspace = _create_project(client)
        project_id = workspace["project"]["id"]
        first_chapter = workspace["chapters"][0]
        created = client.post(
            f"/api/projects/{project_id}/directory-nodes",
            json={
                "kind": "scene",
                "parent_id": first_chapter["id"],
                "title": "站台重逢",
                "summary": "父子第一次对视",
            },
        ).json()
        scene = created["manuscript_scenes"][0]
        dashboard = client.get(f"/api/projects/{project_id}/serial-dashboard").json()
        client.put(
            f"/api/projects/{project_id}/serial-goals/{dashboard['goal']['goal_date']}",
            json={"target_characters": 5200, "expected_revision": 0},
        )
        archive = client.get(f"/api/projects/{project_id}/export").json()
        restored_response = client.post(
            "/api/project-imports",
            content=json.dumps(archive, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json"},
        )

        assert archive["format_version"] == 9
        assert restored_response.status_code == 201
        restored = restored_response.json()
        assert restored["manuscript_scenes"][0]["title"] == scene["title"]
        assert restored["manuscript_scenes"][0]["id"] != scene["id"]
        restored_dashboard = client.get(
            f"/api/projects/{restored['project']['id']}/serial-dashboard",
            params={"goal_date": dashboard["goal"]["goal_date"]},
        ).json()
        restored_events = client.get(
            f"/api/projects/{restored['project']['id']}/directory-events"
        ).json()
        assert restored_dashboard["goal"]["target_characters"] == 5200
        assert restored_events[0]["node_id"] == restored["manuscript_scenes"][0]["id"]
