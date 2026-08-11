from pathlib import Path

from fastapi.testclient import TestClient

from app.database import Database
from app.main import create_app
from app.models import ChapterVersionSource
from app.review.repository import ReviewRepository


def _project(client: TestClient) -> tuple[str, str]:
    workspace = client.post(
        "/api/projects",
        json={
            "title": "南平连载",
            "genre": "urban_rebirth",
            "rebirth_year": 1992,
            "rebirth_location": "南平",
            "chapter_target_words": 500,
        },
    ).json()
    return workspace["project"]["id"], workspace["chapters"][0]["id"]


def test_calendar_annotation_anchor_and_stale_detection(tmp_path: Path) -> None:
    database_path = tmp_path / "mozhou.db"
    with TestClient(create_app(database_path)) as client:
        project_id, chapter_id = _project(client)
        content = "列车驶入南平站，他把车票折起来。"
        saved = client.patch(
            f"/api/chapters/{chapter_id}", json={"content": content, "expected_revision": 0}
        ).json()
        start = content.index("南平站")
        created = client.post(
            f"/api/chapters/{chapter_id}/annotations",
            json={
                "comment": "补一笔当年站房细节",
                "start_char": start,
                "end_char": start + len("南平站"),
                "expected_chapter_revision": saved["revision"],
            },
        )
        assert created.status_code == 201
        annotation = created.json()
        assert annotation["selected_text"] == "南平站"
        moved_content = "当天清晨，" + content
        client.patch(
            f"/api/chapters/{chapter_id}",
            json={"content": moved_content, "expected_revision": saved["revision"]},
        )
        relocated = client.get(f"/api/chapters/{chapter_id}/annotations").json()[0]
        assert relocated["status"] == "open"
        assert relocated["start_char"] == start + 5
        with Database(database_path).connect() as connection:
            ReviewRepository.append_chapter_version(
                connection,
                chapter_id=chapter_id,
                chapter_revision=saved["revision"] + 1,
                content="这是一份没有被作者采用的超长候选稿。" * 20,
                source=ChapterVersionSource.GENERATION_CANDIDATE,
                source_id="calendar-candidate",
                is_candidate=True,
            )
        client.patch(
            f"/api/chapters/{chapter_id}",
            json={"content": "文字已完全重写。", "expected_revision": saved["revision"] + 1},
        )
        stale = client.get(f"/api/chapters/{chapter_id}/annotations").json()[0]
        assert stale["status"] == "stale"
        calendar = client.get(f"/api/projects/{project_id}/writing-calendar").json()
        assert len(calendar["days"]) == 42
        assert calendar["total_net_characters"] == len("文字已完全重写。")


def test_idea_candidate_isolation_and_formal_graph_sources(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        project_id, chapter_id = _project(client)
        idea = client.post(
            "/api/author-ideas",
            json={
                "project_id": project_id,
                "title": "纸厂首单",
                "content": "主角用小额现金试单。",
                "tags": ["首单", "资源"],
            },
        ).json()
        prepared = client.post(
            f"/api/author-ideas/{idea['id']}/prepare",
            json={
                "target_kind": "chapter_brief",
                "expected_revision": 0,
            },
        ).json()
        assert prepared["status"] == "planned" and prepared["target_id"] is None
        workspace = client.get(f"/api/projects/{project_id}").json()
        assert workspace["story_entities"] == []

        first = client.post(
            f"/api/projects/{project_id}/story-entities",
            json={
                "kind": "character",
                "name": "陈潮",
                "role": "重生创业者",
                "goal": "拿下首单",
                "current_state": "资金紧张",
                "relationship_notes": "",
            },
        ).json()
        second = client.post(
            f"/api/projects/{project_id}/story-entities",
            json={
                "kind": "character",
                "name": "林会计",
                "role": "合作伙伴",
                "goal": "控制风险",
                "current_state": "谨慎",
                "relationship_notes": "",
            },
        ).json()
        relation = client.post(
            f"/api/projects/{project_id}/story-relationships",
            json={
                "source_entity_id": first["id"],
                "target_entity_id": second["id"],
                "relation_type": "合伙人",
                "summary": "信任仍在建立",
                "source_chapter_id": chapter_id,
            },
        )
        assert relation.status_code == 201
        graphs = client.get(f"/api/projects/{project_id}/story-graphs").json()
        assert len(graphs["relationship_nodes"]) == 2
        assert graphs["relationship_edges"][0]["chapter_id"] == chapter_id
