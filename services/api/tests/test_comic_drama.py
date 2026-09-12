import json
from pathlib import Path
from typing import cast
from uuid import uuid4

from fastapi.testclient import TestClient

from app.ai import AiGateway, AiGatewayManager
from app.database import Database
from app.main import create_app
from app.models import (
    AiProvider,
    AiStatus,
    ComicAssetRequirement,
    ComicDialogueDraft,
    ComicEpisodeOutlineDraft,
    ComicEpisodeScriptDraft,
    ComicSceneDraft,
    ComicSeasonDraft,
)
from app.repository import now_iso


class FakeComicGateway:
    def __init__(self, profile_id: str) -> None:
        self.profile_id = profile_id
        self.calls = 0
        self.forge_source = False

    def status(self) -> AiStatus:
        return AiStatus(
            configured=True,
            provider=AiProvider.OPENAI_COMPATIBLE,
            model="fake-comic-model",
            key_source="test",
            profile_id=self.profile_id,
            profile_name="测试漫剧线路",
        )

    def plan_comic_season(self, context_text: str) -> ComicSeasonDraft:
        self.calls += 1
        context = json.loads(context_text)
        source_id = (
            "00000000-0000-4000-8000-000000000099"
            if self.forge_source
            else context["allowed_source_chapter_ids"][0]
        )
        return ComicSeasonDraft(
            logline="重生青年抢在停产前救下父亲和老厂。",
            theme="普通人重新掌握命运",
            core_desire="保住家庭与工厂",
            main_conflict="主角与短视管理层争夺改制主动权",
            adaptation_strategy="压缩支线，以八次阶段胜负推进主线。",
            character_recomposition=["合并两名信息型配角"],
            episode_outlines=[
                ComicEpisodeOutlineDraft(
                    episode_number=index,
                    title=f"第 {index} 集",
                    source_chapter_ids=[source_id],
                    opening_hook="停产通知突然贴出",
                    episode_goal="抢到关键订单",
                    core_conflict="管理层拒绝冒险",
                    reversal="客户提前到厂",
                    emotional_payoff="父亲第一次相信主角",
                    ending_cliffhanger="竞争对手拿出另一份合同",
                    cast=["沈砚", "父亲"],
                    locations=["南平旧厂"],
                    key_props=["停产通知"],
                    next_episode_promise="查清合同来源",
                )
                for index in range(1, 9)
            ],
        )

    def write_comic_episode(self, context_text: str) -> ComicEpisodeScriptDraft:
        self.calls += 1
        context = json.loads(context_text)
        episode = context["episode"]
        source_id = context["allowed_source_chapter_ids"][0]
        return ComicEpisodeScriptDraft(
            episode_number=episode["episode_number"],
            title=episode["title"],
            estimated_seconds=90,
            scenes=[
                ComicSceneDraft(
                    scene_number=1,
                    interior_exterior="EXT",
                    location="南平旧厂门口",
                    time_of_day="清晨",
                    cast=["沈砚", "父亲"],
                    action="沈砚撕下停产通知，挡在父亲和厂门之间。",
                    dialogue=[
                        ComicDialogueDraft(
                            character="沈砚",
                            line="今天谁也别想关这扇门。",
                            emotion="克制而坚定",
                        )
                    ],
                    narration="",
                    visual_focus="通知纸在风里绷紧，父亲抬起头。",
                    ending_beat="一辆陌生轿车停在门外。",
                    source_chapter_ids=[source_id],
                    asset_requirements=[
                        ComicAssetRequirement(
                            kind="prop",
                            name="停产通知",
                            description="九十年代厂区红头通知",
                        )
                    ],
                )
            ],
        )


def _configure_comic_profile(database_path: Path, profile_id: str) -> None:
    timestamp = now_iso()
    with Database(database_path).connect() as connection:
        connection.execute(
            """INSERT INTO ai_provider_profiles (
                id, name, provider, base_url, model, capabilities_json,
                input_cost_microusd_per_million, output_cost_microusd_per_million,
                revision, created_at, updated_at
            ) VALUES (?, '测试漫剧线路', 'openai_compatible',
                'http://127.0.0.1:11434/v1', 'fake-comic-model', ?,
                1000000, 1000000, 0, ?, ?)""",
            (
                profile_id,
                json.dumps({"structured_output": True}),
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            "INSERT INTO ai_task_defaults (task_type, profile_id, revision, updated_at) "
            "VALUES ('comic_season_plan', ?, 0, ?)",
            (profile_id, timestamp),
        )
        connection.execute(
            "INSERT INTO ai_task_defaults (task_type, profile_id, revision, updated_at) "
            "VALUES ('comic_episode_script', ?, 0, ?)",
            (profile_id, timestamp),
        )


def _create_novel(client: TestClient, title: str = "南平重启") -> dict[str, object]:
    response = client.post(
        "/api/projects",
        json={
            "title": title,
            "genre": "urban_rebirth",
            "rebirth_year": 1998,
            "rebirth_location": "福建南平",
        },
    )
    assert response.status_code == 201
    return response.json()


def _add_chapter(client: TestClient, project_id: str, last_number: int) -> dict[str, object]:
    response = client.post(
        f"/api/projects/{project_id}/chapters",
        json={"expected_last_chapter_number": last_number},
    )
    assert response.status_code == 201
    return response.json()


def _create_comic(
    client: TestClient,
    project_id: str,
    chapter_ids: list[str],
) -> object:
    return client.post(
        f"/api/projects/{project_id}/comic-projects",
        json={
            "title": "旧厂新生·第一季",
            "source_chapter_ids": chapter_ids,
            "episode_target_count": 8,
            "episode_duration_seconds": 90,
            "aspect_ratio": "9:16",
            "art_style": "写实国漫，九十年代暖灰色调",
            "adaptation_mode": "balanced",
            "narration_preference": "只在转场使用少量旁白",
            "author_requirements": "保留父子和解线",
        },
    )


def test_creates_lists_and_loads_comic_project_with_frozen_source(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        novel = _create_novel(client)
        project_id = novel["project"]["id"]
        first = novel["chapters"][0]
        second = _add_chapter(client, project_id, 1)
        client.patch(
            f"/api/chapters/{first['id']}",
            json={"content": "厂门口贴出了停产通知。", "expected_revision": 0},
        )
        client.patch(
            f"/api/chapters/{second['id']}",
            json={"content": "沈砚决定提前救下老厂。", "expected_revision": 0},
        )

        created = _create_comic(client, project_id, [first["id"], second["id"]])
        comic_id = created.json()["project"]["id"]
        listed = client.get(f"/api/projects/{project_id}/comic-projects")
        loaded = client.get(f"/api/comic-projects/{comic_id}")
        impact = client.get(f"/api/comic-projects/{comic_id}/delete-impact")

    assert created.status_code == 201
    assert created.json()["project"]["source_chapter_ids"] == [first["id"], second["id"]]
    assert len(created.json()["project"]["source_snapshot_sha256"]) == 64
    assert created.json()["project"]["state"] == "draft"
    assert created.json()["episodes"] == []
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [comic_id]
    assert loaded.status_code == 200
    assert loaded.json() == created.json()
    assert impact.json() == {
        "comic_project_id": comic_id,
        "episode_count": 0,
        "version_count": 0,
        "scene_count": 0,
        "can_delete": True,
    }


def test_rejects_duplicate_non_contiguous_and_cross_project_sources(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        novel = _create_novel(client)
        project_id = novel["project"]["id"]
        first = novel["chapters"][0]
        _add_chapter(client, project_id, 1)
        third = _add_chapter(client, project_id, 2)
        other = _create_novel(client, "另一部书")

        duplicate = _create_comic(client, project_id, [first["id"], first["id"]])
        non_contiguous = _create_comic(client, project_id, [first["id"], third["id"]])
        cross_project = _create_comic(
            client,
            project_id,
            [first["id"], other["chapters"][0]["id"]],
        )

    assert duplicate.status_code == 422
    assert non_contiguous.status_code == 422
    assert cross_project.status_code == 422
    assert duplicate.json() == {"detail": "漫剧来源章节无效"}


def test_rejects_deleted_source_chapter(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        novel = _create_novel(client)
        project_id = novel["project"]["id"]
        first = novel["chapters"][0]
        second = _add_chapter(client, project_id, 1)
        deleted = client.request(
            "DELETE",
            f"/api/directory-nodes/chapter/{second['id']}",
            json={"expected_revision": 0, "confirm_impact": True},
        )
        assert deleted.status_code == 200

        response = _create_comic(client, project_id, [first["id"], second["id"]])

    assert response.status_code == 422
    assert response.json() == {"detail": "漫剧来源章节无效"}


def test_archive_round_trip_remaps_comic_source_ids_and_snapshot(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        novel = _create_novel(client)
        project_id = novel["project"]["id"]
        chapter_id = novel["chapters"][0]["id"]
        comic = _create_comic(client, project_id, [chapter_id]).json()
        archive = client.get(f"/api/projects/{project_id}/export").json()
        restored = client.post(
            "/api/project-imports",
            content=json.dumps(archive, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json"},
        )
        restored_project_id = restored.json()["project"]["id"]
        restored_comics = client.get(
            f"/api/projects/{restored_project_id}/comic-projects"
        ).json()

    assert restored.status_code == 201
    assert len(restored_comics) == 1
    assert restored_comics[0]["id"] != comic["project"]["id"]
    assert restored_comics[0]["source_chapter_ids"] == [restored.json()["chapters"][0]["id"]]
    assert len(restored_comics[0]["source_snapshot_sha256"]) == 64


def test_season_plan_requires_preview_confirmation_and_stays_candidate(tmp_path: Path) -> None:
    database_path = tmp_path / "mozhou.db"
    profile_id = str(uuid4())
    gateway = FakeComicGateway(profile_id)
    app = create_app(
        database_path,
        ai_manager=AiGatewayManager(cast(AiGateway, gateway)),
        defer_job_runtime=True,
    )
    with TestClient(app) as client:
        _configure_comic_profile(database_path, profile_id)
        novel = _create_novel(client)
        project_id = novel["project"]["id"]
        comic = _create_comic(client, project_id, [novel["chapters"][0]["id"]]).json()
        comic_id = comic["project"]["id"]

        preview = client.post(
            f"/api/comic-projects/{comic_id}/season-plan/preview",
            json={"author_direction": "父子关系优先"},
        )
        assert preview.status_code == 200
        assert gateway.calls == 0
        blocked = client.post(
            f"/api/comic-projects/{comic_id}/season-plan",
            json={
                "author_direction": "父子关系优先",
                "expected_source_snapshot_sha256": preview.json()[
                    "source_snapshot_sha256"
                ],
            },
        )
        assert blocked.status_code == 409
        assert gateway.calls == 0
        submitted = client.post(
            f"/api/comic-projects/{comic_id}/season-plan",
            json={
                "author_direction": "父子关系优先",
                "expected_source_snapshot_sha256": preview.json()[
                    "source_snapshot_sha256"
                ],
                "confirm_external_processing": True,
                "max_estimated_cost_microusd": preview.json()[
                    "estimated_cost_microusd"
                ],
            },
        )
        assert submitted.status_code == 202
        assert gateway.calls == 0
        assert app.state.job_runtime.run_once()
        workspace = client.get(f"/api/comic-projects/{comic_id}").json()

        season = next(
            item for item in workspace["versions"] if item["target_kind"] == "season"
        )
        assert season["state"] == "candidate"
        assert workspace["episodes"] == []
        assert gateway.calls == 1
        adopted = client.post(
            f"/api/comic-projects/{comic_id}/season-plan/adopt",
            json={"version_id": season["id"], "expected_revision": 0},
        )

    assert adopted.status_code == 200
    assert len(adopted.json()["episodes"]) == 8
    assert {item["outline_state"] for item in adopted.json()["episodes"]} == {"candidate"}
    assert {item["script_state"] for item in adopted.json()["episodes"]} == {"empty"}


def test_season_preview_detects_novel_changes_after_source_freeze(tmp_path: Path) -> None:
    database_path = tmp_path / "mozhou.db"
    profile_id = str(uuid4())
    gateway = FakeComicGateway(profile_id)
    app = create_app(
        database_path,
        ai_manager=AiGatewayManager(cast(AiGateway, gateway)),
        defer_job_runtime=True,
    )
    with TestClient(app) as client:
        _configure_comic_profile(database_path, profile_id)
        novel = _create_novel(client)
        chapter = novel["chapters"][0]
        comic = _create_comic(
            client,
            novel["project"]["id"],
            [chapter["id"]],
        ).json()
        client.patch(
            f"/api/chapters/{chapter['id']}",
            json={"content": "冻结后修改的正文", "expected_revision": 0},
        )

        response = client.post(
            f"/api/comic-projects/{comic['project']['id']}/season-plan/preview",
            json={},
        )

    assert response.status_code == 409
    assert gateway.calls == 0


def test_season_job_rejects_model_forged_source_ids(tmp_path: Path) -> None:
    database_path = tmp_path / "mozhou.db"
    profile_id = str(uuid4())
    gateway = FakeComicGateway(profile_id)
    gateway.forge_source = True
    app = create_app(
        database_path,
        ai_manager=AiGatewayManager(cast(AiGateway, gateway)),
        defer_job_runtime=True,
    )
    with TestClient(app) as client:
        _configure_comic_profile(database_path, profile_id)
        novel = _create_novel(client)
        comic = _create_comic(
            client,
            novel["project"]["id"],
            [novel["chapters"][0]["id"]],
        ).json()
        comic_id = comic["project"]["id"]
        preview = client.post(
            f"/api/comic-projects/{comic_id}/season-plan/preview", json={}
        ).json()
        submitted = client.post(
            f"/api/comic-projects/{comic_id}/season-plan",
            json={
                "expected_source_snapshot_sha256": preview[
                    "source_snapshot_sha256"
                ],
                "confirm_external_processing": True,
                "max_estimated_cost_microusd": preview[
                    "estimated_cost_microusd"
                ],
            },
        ).json()
        assert app.state.job_runtime.run_once()
        job = client.get(f"/api/jobs/{submitted['job']['id']}").json()
        workspace = client.get(f"/api/comic-projects/{comic_id}").json()

    assert job["state"] == "failed"
    assert workspace["versions"] == []


def test_episode_requires_outline_approval_and_materializes_scenes_only_after_review(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "mozhou.db"
    profile_id = str(uuid4())
    gateway = FakeComicGateway(profile_id)
    app = create_app(
        database_path,
        ai_manager=AiGatewayManager(cast(AiGateway, gateway)),
        defer_job_runtime=True,
    )
    with TestClient(app) as client:
        _configure_comic_profile(database_path, profile_id)
        novel = _create_novel(client)
        comic = _create_comic(
            client,
            novel["project"]["id"],
            [novel["chapters"][0]["id"]],
        ).json()
        comic_id = comic["project"]["id"]
        season_preview = client.post(
            f"/api/comic-projects/{comic_id}/season-plan/preview", json={}
        ).json()
        client.post(
            f"/api/comic-projects/{comic_id}/season-plan",
            json={
                "expected_source_snapshot_sha256": season_preview[
                    "source_snapshot_sha256"
                ],
                "confirm_external_processing": True,
                "max_estimated_cost_microusd": season_preview[
                    "estimated_cost_microusd"
                ],
            },
        )
        assert app.state.job_runtime.run_once()
        workspace = client.get(f"/api/comic-projects/{comic_id}").json()
        season = next(item for item in workspace["versions"] if item["target_kind"] == "season")
        adopted = client.post(
            f"/api/comic-projects/{comic_id}/season-plan/adopt",
            json={"version_id": season["id"], "expected_revision": 0},
        ).json()
        episode = adopted["episodes"][0]

        blocked = client.post(
            f"/api/comic-episodes/{episode['id']}/script/preview", json={}
        )
        assert blocked.status_code == 409
        approved_outline = client.post(
            f"/api/comic-episodes/{episode['id']}/outline/review",
            json={"action": "approve", "expected_revision": 0},
        )
        assert approved_outline.status_code == 200
        episode = approved_outline.json()["episodes"][0]
        preview = client.post(
            f"/api/comic-episodes/{episode['id']}/script/preview",
            json={"author_direction": "开场三秒见冲突"},
        ).json()
        submitted = client.post(
            f"/api/comic-episodes/{episode['id']}/script",
            json={
                "author_direction": "开场三秒见冲突",
                "expected_source_snapshot_sha256": preview["source_snapshot_sha256"],
                "expected_outline_revision": episode["outline_revision"],
                "confirm_external_processing": True,
                "max_estimated_cost_microusd": preview["estimated_cost_microusd"],
            },
        )
        assert submitted.status_code == 202
        assert app.state.job_runtime.run_once()
        candidate = client.get(f"/api/comic-projects/{comic_id}").json()
        episode = candidate["episodes"][0]
        script_version = next(
            item
            for item in candidate["versions"]
            if item["target_kind"] == "episode_script"
        )

        assert episode["script_state"] == "candidate"
        assert candidate["scenes"] == []
        approved_script = client.post(
            f"/api/comic-episodes/{episode['id']}/script/review",
            json={
                "action": "approve",
                "expected_revision": 0,
                "version_id": script_version["id"],
            },
        )
        audit = client.get(f"/api/comic-projects/{comic_id}/audit")
        assets = client.get(f"/api/comic-projects/{comic_id}/assets")
        package = client.get(f"/api/comic-projects/{comic_id}/production-package")
        exported_json = client.get(f"/api/comic-projects/{comic_id}/export?format=json")
        exported_json_again = client.get(
            f"/api/comic-projects/{comic_id}/export?format=json"
        )
        exported_markdown = client.get(
            f"/api/comic-projects/{comic_id}/export?format=markdown"
        )
        exported_docx = client.get(f"/api/comic-projects/{comic_id}/export?format=docx")
        archive = client.get(f"/api/projects/{novel['project']['id']}/export").json()
        restored_novel = client.post(
            "/api/project-imports",
            content=json.dumps(archive, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json"},
        ).json()
        restored_comic = client.get(
            f"/api/projects/{restored_novel['project']['id']}/comic-projects"
        ).json()[0]
        restored_workspace = client.get(
            f"/api/comic-projects/{restored_comic['id']}"
        ).json()

    assert approved_script.status_code == 200
    assert approved_script.json()["episodes"][0]["script_state"] == "approved"
    assert len(approved_script.json()["scenes"]) == 1
    assert approved_script.json()["scenes"][0]["content"]["dialogue"][0]["character"] == "沈砚"
    assert audit.status_code == 200
    assert assets.status_code == 200
    assert any(item["name"] == "停产通知" for item in assets.json())
    assert package.status_code == 200
    assert package.json()["ai_generated"] is True
    assert len(package.json()["episodes"]) == 1
    assert exported_json.content == exported_json_again.content
    assert len(json.loads(exported_json.content)["episodes"]) == 1
    assert "AI 漫剧制作包" in exported_markdown.text
    assert exported_docx.content.startswith(b"PK")
    assert len(restored_workspace["episodes"]) == 8
    assert len(restored_workspace["scenes"]) == 1
    assert restored_workspace["episodes"][0]["source_chapter_ids"] == [
        restored_novel["chapters"][0]["id"]
    ]
    assert restored_workspace["scenes"][0]["episode_id"] == restored_workspace["episodes"][0]["id"]
