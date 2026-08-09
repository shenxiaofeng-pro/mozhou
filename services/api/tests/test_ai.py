from pathlib import Path

from fastapi.testclient import TestClient

from app.ai import AiGatewayManager, AiProviderError
from app.main import create_app
from app.models import (
    AiChapterBriefProposal,
    AiProvider,
    AiStatus,
    Chapter,
    Workspace,
)


class StubAiGateway:
    def __init__(self, *, fail_draft: bool = False) -> None:
        self.fail_draft = fail_draft

    def status(self) -> AiStatus:
        return AiStatus(
            configured=True,
            provider=AiProvider.OPENAI,
            model="test-writing-model",
            key_source="test",
        )

    def propose_brief(
        self,
        workspace: Workspace,
        chapter: Chapter,
        author_intent: str,
    ) -> AiChapterBriefProposal:
        assert workspace.project.rebirth_location == "福建南平"
        assert author_intent == "让主角先用信息差救下父亲"
        return AiChapterBriefProposal(
            title="第一章 名单之前",
            reader_promise="主角第一次改变家庭命运",
            opening_hook="停产名单比记忆中提前贴出",
            state_change="主角让父亲避开首轮裁员",
            emotional_payoff="父亲保住岗位却开始怀疑儿子",
            ending_cliffhanger="厂长拿出一张不该存在的旧照片",
            why_this_works="信息差立即转化为行动和家庭回报。",
            risk_notes=["厂办流程需要现实资料校验"],
        )

    def draft_chapter(
        self,
        workspace: Workspace,
        chapter: Chapter,
        author_intent: str,
    ) -> str:
        if self.fail_draft:
            raise AiProviderError("provider failed")
        assert chapter.opening_hook == "停产名单比记忆中提前贴出"
        return "一九九八年的梅山坡还没有后来那排高楼。" * 30


def create_project(client: TestClient) -> dict[str, object]:
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


def test_ai_requires_configuration_and_never_echoes_session_key(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        created = create_project(client)
        chapter = created["chapters"][0]  # type: ignore[index]
        unavailable = client.post(
            f"/api/chapters/{chapter['id']}/ai-brief-proposals",  # type: ignore[index]
            json={"expected_revision": 0, "author_intent": ""},
        )
        invalid_secret = "too-short-secret"
        invalid = client.post(
            "/api/ai/configure",
            json={"api_key": invalid_secret, "model": "gpt-5.6"},
        )
        configured = client.post(
            "/api/ai/configure",
            json={"api_key": "sk-test-abcdefghijklmnopqrstuvwxyz", "model": "gpt-5.6"},
        )

    assert unavailable.status_code == 409
    assert unavailable.json() == {"detail": "请先配置 AI 模型"}
    assert invalid.status_code == 422
    assert invalid_secret not in invalid.text
    assert configured.status_code == 200
    assert configured.json() == {
        "configured": True,
        "provider": "openai",
        "model": "gpt-5.6",
        "key_source": "session",
    }
    assert "api_key" not in configured.text
    assert "sk-test" not in configured.text


def test_ai_brief_and_draft_remain_candidates_until_author_applies(tmp_path: Path) -> None:
    manager = AiGatewayManager(StubAiGateway())
    with TestClient(create_app(tmp_path / "mozhou.db", ai_manager=manager)) as client:
        created = create_project(client)
        chapter = created["chapters"][0]  # type: ignore[index]
        proposal = client.post(
            f"/api/chapters/{chapter['id']}/ai-brief-proposals",  # type: ignore[index]
            json={
                "expected_revision": 0,
                "author_intent": "让主角先用信息差救下父亲",
            },
        )
        unchanged = client.get(f"/api/projects/{created['project']['id']}").json()  # type: ignore[index]
        saved = client.patch(
            f"/api/chapters/{chapter['id']}/brief",  # type: ignore[index]
            json={**proposal.json(), "expected_revision": 0},
        ).json()
        draft = client.post(
            f"/api/chapters/{chapter['id']}/ai-draft-runs",  # type: ignore[index]
            json={"expected_revision": saved["revision"], "author_intent": ""},
        )
        before_apply = client.get(f"/api/projects/{created['project']['id']}").json()  # type: ignore[index]
        applied = client.post(
            f"/api/generation-runs/{draft.json()['id']}/apply",
            json={"expected_revision": saved["revision"]},
        )

    assert proposal.status_code == 200
    assert proposal.json()["title"] == "第一章 名单之前"
    assert unchanged["chapters"][0]["opening_hook"] == ""
    assert draft.status_code == 201
    assert draft.json()["provider"] == "openai"
    assert draft.json()["model"] == "test-writing-model"
    assert before_apply["chapters"][0]["content"] == ""
    assert applied.status_code == 200
    assert applied.json()["content"] == draft.json()["candidate_content"]


def test_ai_provider_failure_is_generic_and_leaves_interrupted_run(tmp_path: Path) -> None:
    manager = AiGatewayManager(StubAiGateway(fail_draft=True))
    application = create_app(tmp_path / "mozhou.db", ai_manager=manager)
    with TestClient(application) as client:
        created = create_project(client)
        chapter = created["chapters"][0]  # type: ignore[index]
        saved = client.patch(
            f"/api/chapters/{chapter['id']}/brief",  # type: ignore[index]
            json={
                "opening_hook": "停产名单比记忆中提前贴出",
                "state_change": "主角让父亲避开首轮裁员",
                "ending_cliffhanger": "厂长拿出一张旧照片",
                "expected_revision": 0,
            },
        ).json()
        failed = client.post(
            f"/api/chapters/{chapter['id']}/ai-draft-runs",  # type: ignore[index]
            json={"expected_revision": saved["revision"], "author_intent": ""},
        )
        with application.state.repository.database.connect() as connection:
            run = connection.execute(
                "SELECT state, error_message FROM generation_runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()

    assert failed.status_code == 502
    assert failed.json() == {"detail": "AI 暂时未能生成可用正文"}
    assert run is not None
    assert dict(run) == {
        "state": "interrupted",
        "error_message": "模型服务未完成本次生成",
    }
