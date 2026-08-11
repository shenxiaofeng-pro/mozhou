from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

SESSION_TOKEN = "a" * 64


def test_health(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_session_token_rejects_missing_and_wrong_values_but_accepts_the_current_token(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db", session_token=SESSION_TOKEN)) as client:
        health = client.get("/health")
        missing = client.get("/api/projects")
        wrong = client.get(
            "/api/projects",
            headers={"X-Mozhou-Session-Token": "b" * 64},
        )
        correct = client.get(
            "/api/projects",
            headers={"X-Mozhou-Session-Token": SESSION_TOKEN},
        )

    assert health.status_code == 200
    assert missing.status_code == 401
    assert missing.json() == {"detail": "本地会话无效，请重启墨舟"}
    assert wrong.status_code == 401
    assert wrong.json() == missing.json()
    assert correct.status_code == 200
    assert correct.json() == []


@pytest.mark.parametrize("session_token", ["", "short", "G" * 64])
def test_rejects_invalid_configured_session_tokens(
    tmp_path: Path,
    session_token: str,
) -> None:
    with pytest.raises(ValueError, match="session token"):
        create_app(tmp_path / "mozhou.db", session_token=session_token)


@pytest.mark.parametrize(
    "origin",
    ["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"],
)
def test_allows_only_known_tauri_origins(tmp_path: Path, origin: str) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db", session_token=SESSION_TOKEN)) as client:
        response = client.options(
            "/api/projects",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-mozhou-session-token",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "x-mozhou-session-token" in response.headers["access-control-allow-headers"].lower()


def test_create_load_and_update_project(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        created = client.post(
            "/api/projects",
            json={
                "title": "回到九八年的南平",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
                "chapter_target_words": 3000,
                "safety_buffer_chapters": 3,
            },
        )
        workspace = created.json()
        loaded = client.get(f"/api/projects/{workspace['project']['id']}")
        saved = client.patch(
            f"/api/chapters/{workspace['chapters'][0]['id']}",
            json={"content": "列车驶入南平站。", "expected_revision": 0},
        )
        stale = client.patch(
            f"/api/chapters/{workspace['chapters'][0]['id']}",
            json={"content": "过期草稿", "expected_revision": 0},
        )

    assert created.status_code == 201
    assert loaded.status_code == 200
    assert saved.status_code == 200
    assert saved.json()["revision"] == 1
    assert stale.status_code == 409
    assert stale.json() == {"detail": "章节已在其他位置更新，请重新载入"}


@pytest.mark.parametrize(
    ("genre", "title", "story_year", "story_location"),
    [
        ("eastern_fantasy", "万山问道", 728, "九州·云泽"),
        ("western_fantasy", "灰塔之誓", 1243, "阿尔登大陆·北境"),
    ],
)
def test_creates_and_reopens_fantasy_genre_projects(
    tmp_path: Path,
    genre: str,
    title: str,
    story_year: int,
    story_location: str,
) -> None:
    with TestClient(create_app(tmp_path / f"{genre}.db")) as client:
        created = client.post(
            "/api/projects",
            json={
                "title": title,
                "genre": genre,
                "rebirth_year": story_year,
                "rebirth_location": story_location,
            },
        )
        assert created.status_code == 201
        project_id = created.json()["project"]["id"]
        reopened = client.get(f"/api/projects/{project_id}/summary")

    assert reopened.status_code == 200
    assert reopened.json()["project"]["genre"] == genre
    assert reopened.json()["project"]["rebirth_year"] == story_year
    assert reopened.json()["project"]["rebirth_location"] == story_location


def test_loads_workspace_summary_without_manuscript_and_fetches_chapter_on_demand(
    tmp_path: Path,
) -> None:
    manuscript = "这段正文只能由单章接口按需返回。" * 200
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "长篇按需加载",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        chapter_id = workspace["chapters"][0]["id"]
        saved = client.patch(
            f"/api/chapters/{chapter_id}",
            json={"content": manuscript, "expected_revision": 0},
        )

        summary = client.get(f"/api/projects/{project_id}/summary")
        chapter = client.get(f"/api/chapters/{chapter_id}")
        legacy_workspace = client.get(f"/api/projects/{project_id}")

    assert saved.status_code == 200
    assert summary.status_code == 200
    assert "content" not in summary.json()["chapters"][0]
    assert manuscript not in summary.text
    assert chapter.status_code == 200
    assert chapter.json()["content"] == manuscript
    assert legacy_workspace.status_code == 200
    assert legacy_workspace.json()["chapters"][0]["content"] == manuscript


def test_summary_and_chapter_reads_return_not_found(tmp_path: Path) -> None:
    missing_id = "00000000-0000-4000-8000-000000000001"
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        summary = client.get(f"/api/projects/{missing_id}/summary")
        chapter = client.get(f"/api/chapters/{missing_id}")

    assert summary.status_code == 404
    assert summary.json() == {"detail": "项目不存在"}
    assert chapter.status_code == 404
    assert chapter.json() == {"detail": "章节不存在"}


def test_lists_projects_without_loading_manuscript_content(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        first = client.post(
            "/api/projects",
            json={
                "title": "南平旧厂",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        second = client.post(
            "/api/projects",
            json={
                "title": "绍兴新局",
                "genre": "historical_rebirth",
                "rebirth_year": 1127,
                "rebirth_location": "绍兴",
            },
        ).json()
        client.patch(
            f"/api/chapters/{first['chapters'][0]['id']}",
            json={"content": "把这一部重新写到最前面。", "expected_revision": 0},
        )

        response = client.get("/api/projects")

    assert response.status_code == 200
    assert [project["id"] for project in response.json()] == [
        first["project"]["id"],
        second["project"]["id"],
    ]
    assert set(response.json()[0]) == {
        "id",
        "title",
        "genre",
        "rebirth_year",
        "rebirth_location",
        "chapter_target_words",
        "safety_buffer_chapters",
        "created_at",
        "updated_at",
    }


def test_update_chapter_brief(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        created = client.post(
            "/api/projects",
            json={
                "title": "回到九八年的南平",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        chapter = created["chapters"][0]
        saved = client.patch(
            f"/api/chapters/{chapter['id']}/brief",
            json={
                "opening_hook": "停产通知提前一天贴出",
                "state_change": "保住父亲的工作",
                "ending_cliffhanger": "厂长认出了主角",
                "expected_revision": 0,
            },
        )
        stale = client.patch(
            f"/api/chapters/{chapter['id']}/brief",
            json={
                "opening_hook": "过期章纲",
                "state_change": "过期章纲",
                "ending_cliffhanger": "过期章纲",
                "expected_revision": 0,
            },
        )

    assert saved.status_code == 200
    assert saved.json()["revision"] == 1
    assert saved.json()["opening_hook"] == "停产通知提前一天贴出"
    assert stale.status_code == 409
    assert stale.json() == {"detail": "章节已有新版本，请重新载入章纲"}


def test_create_next_chapter_and_transition_state(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        created = client.post(
            "/api/projects",
            json={
                "title": "回到九八年的南平",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        first = created["chapters"][0]
        next_chapter = client.post(
            f"/api/projects/{created['project']['id']}/chapters",
            json={"expected_last_chapter_number": 1},
        )
        stale_create = client.post(
            f"/api/projects/{created['project']['id']}/chapters",
            json={"expected_last_chapter_number": 1},
        )
        invalid_title = client.post(
            f"/api/projects/{created['project']['id']}/chapters",
            json={"expected_last_chapter_number": 2, "title": "坏标题\u0000隐藏"},
        )
        saved = client.patch(
            f"/api/chapters/{first['id']}",
            json={"content": "列车驶入南平站。", "expected_revision": 0},
        ).json()
        drafted = client.post(
            f"/api/chapters/{first['id']}/transition",
            json={"target_status": "drafted", "expected_revision": saved["revision"]},
        )

    assert next_chapter.status_code == 201
    assert next_chapter.json()["chapter_number"] == 2
    assert stale_create.status_code == 409
    assert stale_create.json() == {"detail": "章节目录已有更新，请重新载入"}
    assert invalid_title.status_code == 422
    assert drafted.status_code == 200
    assert drafted.json()["status"] == "drafted"


def test_rejects_invalid_project_input(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        response = client.post(
            "/api/projects",
            json={
                "title": "   ",
                "genre": "urban_rebirth",
                "rebirth_year": 2099,
                "rebirth_location": "南平",
            },
        )

    assert response.status_code == 422


def test_generation_candidate_requires_explicit_apply(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        created = client.post(
            "/api/projects",
            json={
                "title": "回到九八年的南平",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        chapter = created["chapters"][0]
        generated = client.post(
            f"/api/chapters/{chapter['id']}/generation-runs",
            json={"expected_revision": 0},
        )
        unchanged = client.get(f"/api/projects/{created['project']['id']}").json()
        applied = client.post(
            f"/api/generation-runs/{generated.json()['id']}/apply",
            json={"expected_revision": 0},
        )

    assert generated.status_code == 201
    assert generated.json()["state"] == "drafted"
    assert unchanged["chapters"][0]["content"] == ""
    assert applied.status_code == 200
    assert applied.json()["content"] == generated.json()["candidate_content"]


def test_fact_backfill_requires_author_confirmation(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        created = client.post(
            "/api/projects",
            json={
                "title": "回到九八年的南平",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = created["project"]["id"]
        chapter = created["chapters"][0]
        original = client.post(
            f"/api/projects/{project_id}/timeline-events",
            json={
                "event_year": 1998,
                "title": "南平铝厂推进改制",
                "summary": "现实资料锚点",
            },
        )
        chapter = client.patch(
            f"/api/chapters/{chapter['id']}",
            json={"content": "列车驶入南平站。", "expected_revision": 0},
        ).json()
        chapter = client.patch(
            f"/api/chapters/{chapter['id']}/brief",
            json={
                "title": "第一章 旧站",
                "opening_hook": "停产通知提前贴出",
                "state_change": "保住父亲的工作",
                "ending_cliffhanger": "厂长认出了主角",
                "expected_revision": chapter["revision"],
            },
        ).json()
        for target in ("drafted", "reviewing", "approved"):
            chapter = client.post(
                f"/api/chapters/{chapter['id']}/transition",
                json={"target_status": target, "expected_revision": chapter["revision"]},
            ).json()
        candidate = client.post(f"/api/chapters/{chapter['id']}/fact-change-sets")
        before_apply = client.get(f"/api/projects/{project_id}").json()
        applied = client.post(
            f"/api/fact-change-sets/{candidate.json()['id']}/apply",
            json={
                "selected_change_ids": [item["id"] for item in candidate.json()["changes"]],
                "expected_revision": 0,
            },
        )
        after_apply = client.get(f"/api/projects/{project_id}").json()

    assert original.status_code == 201
    assert original.json()["layer"] == "original"
    assert candidate.status_code == 201
    assert before_apply["story_facts"] == []
    assert [event["layer"] for event in before_apply["timeline_events"]] == ["original"]
    assert applied.status_code == 200
    assert applied.json()["state"] == "applied"
    assert len(after_apply["story_facts"]) == 2
    assert {event["layer"] for event in after_apply["timeline_events"]} == {"original", "novel"}


def test_future_knowledge_validates_year_and_review_state(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        created = client.post(
            "/api/projects",
            json={
                "title": "回到九八年的南平",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = created["project"]["id"]
        too_early = client.post(
            f"/api/projects/{project_id}/future-knowledge",
            json={"future_year": 1997, "content": "早于重生点"},
        )
        knowledge = client.post(
            f"/api/projects/{project_id}/future-knowledge",
            json={
                "future_year": 2003,
                "content": "建阳会开出大型连锁超市",
                "source_note": "上一世亲历",
                "confidence": "certain",
            },
        )
        premature_review = client.post(
            f"/api/future-knowledge/{knowledge.json()['id']}/review",
            json={"action": "confirm_invalid", "expected_revision": 0},
        )

    assert too_early.status_code == 400
    assert knowledge.status_code == 201
    assert knowledge.json()["status"] == "valid"
    assert premature_review.status_code == 409


def test_story_ledgers_and_source_cards_validate_and_persist(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        created = client.post(
            "/api/projects",
            json={
                "title": "回到九八年的南平",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = created["project"]["id"]
        entity = client.post(
            f"/api/projects/{project_id}/story-entities",
            json={
                "kind": "character",
                "name": "沈砚'); DROP TABLE projects; --",
                "role": "重生者",
                "goal": "保住父亲的工作",
                "current_state": "刚回南平",
                "relationship_notes": "与父亲有隔阂",
            },
        )
        updated = client.patch(
            f"/api/story-entities/{entity.json()['id']}",
            json={
                **{key: entity.json()[key] for key in (
                    "name", "role", "goal", "current_state", "relationship_notes"
                )},
                "current_state": "已进入厂长办公室",
                "expected_revision": 0,
            },
        )
        invalid_card = client.post(
            f"/api/projects/{project_id}/source-cards",
            json={
                "source_kind": "industry",
                "title": "错误年代范围",
                "source_reference": "本地笔记",
                "applicable_year_start": 2000,
                "applicable_year_end": 1998,
            },
        )
        card = client.post(
            f"/api/projects/{project_id}/source-cards",
            json={
                "source_kind": "industry",
                "title": "南平铝厂改制资料",
                "source_reference": "作者本地档案 1998-04",
                "applicable_year_start": 1998,
                "applicable_year_end": 1999,
                "confidence": "high",
                "excerpt": "先岗位摸底，再公布分流方案。",
            },
        )
        confirmed = client.post(
            f"/api/source-cards/{card.json()['id']}/confirmation",
            json={"confirmed": True, "expected_revision": 0},
        )
        loaded = client.get(f"/api/projects/{project_id}")

    assert entity.status_code == 201
    assert updated.status_code == 200
    assert updated.json()["current_state"] == "已进入厂长办公室"
    assert invalid_card.status_code == 422
    assert card.status_code == 201
    assert card.json()["confirmed"] is False
    assert confirmed.json()["confirmed"] is True
    assert len(loaded.json()["story_entities"]) == 1
    assert len(loaded.json()["source_cards"]) == 1
