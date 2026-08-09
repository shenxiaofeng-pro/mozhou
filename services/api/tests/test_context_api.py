from pathlib import Path

from fastapi.testclient import TestClient

from app.ai import AiGatewayManager, OpenAiGateway
from app.main import create_app


def _create_project(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/projects",
        json={
            "title": "南平回潮",
            "genre": "urban_rebirth",
            "rebirth_year": 1998,
            "rebirth_location": "福建南平",
        },
    )
    assert response.status_code == 201
    return response.json()


def _manager() -> AiGatewayManager:
    return AiGatewayManager(OpenAiGateway(
        "unused-context-preview-key",
        "context-preview-model",
        "test",
    ))


def test_preview_persists_context_packet_and_confirm_binds_job_artifact(tmp_path: Path) -> None:
    with TestClient(create_app(
        tmp_path / "context-preview.db",
        ai_manager=_manager(),
        defer_job_runtime=True,
    )) as client:
        workspace = _create_project(client)
        chapter = workspace["chapters"][0]
        preview = client.post(
            f"/api/chapters/{chapter['id']}/ai-brief-preview",
            json={
                "expected_revision": 0,
                "author_intent": "先救下父亲",
                "context_token_budget": 8000,
            },
        )
        assert preview.status_code == 200
        packet = preview.json()["context_packet"]

        packets = client.get(f"/api/chapters/{chapter['id']}/context-packets")
        submitted = client.post(
            f"/api/chapters/{chapter['id']}/ai-brief-jobs",
            json={
                "expected_revision": 0,
                "author_intent": "先救下父亲",
                "context_token_budget": 8000,
                "context_packet_id": packet["id"],
            },
        )
        detail = client.get(f"/api/jobs/{submitted.json()['id']}")

    assert packets.status_code == 200
    assert [item["id"] for item in packets.json()] == [packet["id"]]
    assert submitted.status_code == 202
    context_artifact = next(
        item for item in detail.json()["artifacts"]
        if item["kind"] == "context_packet"
    )
    assert context_artifact["metadata"]["context_packet_id"] == packet["id"]
    assert context_artifact["metadata"]["packet_sha256"] == packet["packet_sha256"]


def test_confirm_rejects_stale_preview_before_creating_job(tmp_path: Path) -> None:
    with TestClient(create_app(
        tmp_path / "context-stale.db",
        ai_manager=_manager(),
        defer_job_runtime=True,
    )) as client:
        workspace = _create_project(client)
        project = workspace["project"]
        chapter = workspace["chapters"][0]
        preview = client.post(
            f"/api/chapters/{chapter['id']}/ai-brief-preview",
            json={"expected_revision": 0, "author_intent": "先救下父亲"},
        ).json()
        created_entity = client.post(
            f"/api/projects/{project['id']}/story-entities",
            json={
                "kind": "character",
                "name": "新竞争者",
                "role": "厂长外甥",
                "goal": "抢下订单",
                "current_state": "尚未登场",
                "relationship_notes": "",
            },
        )
        submitted = client.post(
            f"/api/chapters/{chapter['id']}/ai-brief-jobs",
            json={
                "expected_revision": 0,
                "author_intent": "先救下父亲",
                "context_packet_id": preview["context_packet"]["id"],
            },
        )
        jobs = client.get(f"/api/projects/{project['id']}/jobs")

    assert created_entity.status_code == 201
    assert submitted.status_code == 409
    assert submitted.json()["detail"] == "上下文已变化，请重新预览后确认"
    assert jobs.json() == []


def test_context_directive_api_is_revisioned_and_chapter_scoped(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "context-directive.db", defer_job_runtime=True)) as client:
        workspace = _create_project(client)
        project = workspace["project"]
        chapter = workspace["chapters"][0]
        entity = client.post(
            f"/api/projects/{project['id']}/story-entities",
            json={
                "kind": "character",
                "name": "林川",
                "role": "主角",
                "goal": "改变家庭命运",
                "current_state": "刚回到一九九八年",
                "relationship_notes": "",
            },
        ).json()
        pinned = client.put(
            f"/api/chapters/{chapter['id']}/context-directives",
            json={
                "source_kind": "entity",
                "source_id": entity["id"],
                "action": "pin",
                "expected_revision": None,
            },
        )
        stale = client.put(
            f"/api/chapters/{chapter['id']}/context-directives",
            json={
                "source_kind": "entity",
                "source_id": entity["id"],
                "action": "exclude",
                "expected_revision": 9,
            },
        )
        removed = client.delete(
            f"/api/context-directives/{pinned.json()['id']}?expected_revision=0"
        )
        directives = client.get(f"/api/chapters/{chapter['id']}/context-directives")

    assert pinned.status_code == 200
    assert stale.status_code == 409
    assert removed.status_code == 204
    assert directives.json() == []
