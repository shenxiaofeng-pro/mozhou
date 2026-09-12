import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.ai import AiGatewayManager
from app.database import Database
from app.main import create_app
from app.models import (
    AiProvider,
    AiStatus,
    TopicDecisionCandidateDraft,
    TopicDecisionCandidateDraftSet,
    TopicDecisionContent,
)


class TopicGateway:
    def __init__(self) -> None:
        self.calls = 0
        self.contexts: list[dict[str, object]] = []

    def status(self) -> AiStatus:
        return AiStatus(
            configured=True,
            provider=AiProvider.OPENAI,
            model="topic-test-v1",
            key_source="test",
        )

    def propose_topic_decisions(self, context_text: str) -> TopicDecisionCandidateDraftSet:
        self.calls += 1
        context = json.loads(context_text)
        self.contexts.append(context)
        current = TopicDecisionContent.model_validate(context["current_topic"])
        target_field = context.get("target_field")
        candidates: list[TopicDecisionCandidateDraft] = []
        for ordinal in range(1, 4):
            content = current.model_copy(deep=True)
            if target_field == "core_desire":
                content.core_desire = f"第 {ordinal} 套：先保住家庭现金流，再重建地方产业信用"
            else:
                content.premise = f"第 {ordinal} 套命题：从一张即将违约的订单改变家庭命运"
                content.core_desire = f"第 {ordinal} 套欲望：救下家庭并建立可持续的产业网络"
            candidates.append(
                TopicDecisionCandidateDraft(
                    label=f"方向 {ordinal}",
                    content=content,
                    why_distinct=f"第 {ordinal} 种冲突发动机。",
                    risks=["需要继续核对年代资料"],
                )
            )
        return TopicDecisionCandidateDraftSet(candidates=candidates)


def _project_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": "回到九八年的南平",
        "genre": "urban_rebirth",
        "rebirth_year": 1998,
        "rebirth_location": "福建南平",
        "chapter_target_words": 3000,
        "safety_buffer_chapters": 3,
        "template_id": "urban-rebirth",
        "topic_seed": "一个失败商人重生后，先救下父亲的竹木厂",
    }
    payload.update(overrides)
    return payload


def _create(client: TestClient, **overrides: object) -> dict[str, object]:
    response = client.post("/api/projects", json=_project_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def test_template_project_creates_editable_topic_in_same_transaction_and_confirms_version(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "topic-manual.db"
    app = create_app(database_path, defer_job_runtime=True)
    with TestClient(app) as client:
        workspace = _create(client)
        project_id = workspace["project"]["id"]
        topic = workspace["topic_decision"]
        assert workspace["next_action"] == "confirm_topic"
        assert topic["status"] == "draft"
        assert topic["revision"] == 0
        assert topic["confirmed_revision"] is None
        assert topic["source_template_id"] == "urban-rebirth"
        assert topic["content"]["premise"] == _project_payload()["topic_seed"]
        assert topic["content"]["subgenre"] == "都市重生"
        assert "1998" in topic["content"]["reality_anchor"]
        assert topic["content"]["first_ten_chapter_goal"]

        confirmed_response = client.post(
            f"/api/projects/{project_id}/topic-decision/confirm",
            json={"expected_revision": 0},
        )
        assert confirmed_response.status_code == 200, confirmed_response.text
        confirmed = confirmed_response.json()
        assert confirmed["status"] == "confirmed"
        assert confirmed["revision"] == 1
        assert confirmed["confirmed_revision"] == 1

        repeated = client.post(
            f"/api/projects/{project_id}/topic-decision/confirm",
            json={"expected_revision": 1},
        )
        assert repeated.status_code == 409

        locked = client.patch(
            f"/api/projects/{project_id}/topic-decision",
            json={
                "content": confirmed["content"],
                "changed_fields": [],
                "lock_updates": {"core_desire": True},
                "rejection_reason_updates": {},
                "expected_revision": 1,
            },
        )
        assert locked.status_code == 200, locked.text
        locked_topic = locked.json()
        pending_workspace = client.get(f"/api/projects/{project_id}").json()
        assert locked_topic["status"] == "pending_reconfirmation"
        assert pending_workspace["next_action"] == "review_topic_changes"
        changed_content = {**locked_topic["content"], "core_desire": "不允许覆盖的新欲望"}
        blocked = client.patch(
            f"/api/projects/{project_id}/topic-decision",
            json={
                "content": changed_content,
                "changed_fields": ["core_desire"],
                "lock_updates": {},
                "rejection_reason_updates": {},
                "expected_revision": locked_topic["revision"],
            },
        )
        assert blocked.status_code == 409
        assert client.get(f"/api/projects/{project_id}/topic-decision").json() == locked_topic

    database = Database(database_path)
    with database.connect() as connection:
        versions = connection.execute(
            "SELECT revision, content_sha256 FROM topic_decision_versions"
        ).fetchall()
    assert [(row["revision"], len(row["content_sha256"])) for row in versions] == [(1, 64)]


def test_invalid_or_mismatched_template_never_leaves_partial_project(tmp_path: Path) -> None:
    database_path = tmp_path / "topic-template.db"
    app = create_app(database_path, defer_job_runtime=True)
    with TestClient(app) as client:
        missing = client.post(
            "/api/projects",
            json=_project_payload(template_id="missing-template"),
        )
        mismatch = client.post(
            "/api/projects",
            json=_project_payload(genre="western_fantasy"),
        )
        assert missing.status_code == 422
        assert mismatch.status_code == 422
        assert client.get("/api/projects").json() == []

    with Database(database_path).connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM topic_decisions").fetchone()[0] == 0


def test_incomplete_manual_topic_requires_valid_cas_and_declared_changes(
    tmp_path: Path,
) -> None:
    app = create_app(tmp_path / "topic-incomplete.db", defer_job_runtime=True)
    with TestClient(app) as client:
        workspace = _create(client, template_id=None, topic_seed="")
        project_id = workspace["project"]["id"]
        topic = workspace["topic_decision"]

        incomplete = client.post(
            f"/api/projects/{project_id}/topic-decision/confirm",
            json={"expected_revision": topic["revision"]},
        )
        assert incomplete.status_code == 409

        mismatched_content = {**topic["content"], "premise": "作者手工改写的命题"}
        undeclared = client.patch(
            f"/api/projects/{project_id}/topic-decision",
            json={
                "content": mismatched_content,
                "changed_fields": ["core_desire"],
                "lock_updates": {},
                "rejection_reason_updates": {},
                "expected_revision": topic["revision"],
            },
        )
        assert undeclared.status_code == 409
        stale = client.patch(
            f"/api/projects/{project_id}/topic-decision",
            json={
                "content": mismatched_content,
                "changed_fields": ["premise"],
                "lock_updates": {},
                "rejection_reason_updates": {},
                "expected_revision": topic["revision"] + 1,
            },
        )
        assert stale.status_code == 409


def test_ai_topic_candidates_are_persisted_and_selection_only_updates_draft(
    tmp_path: Path,
) -> None:
    gateway = TopicGateway()
    app = create_app(
        tmp_path / "topic-ai.db",
        AiGatewayManager(gateway),
        defer_job_runtime=True,
    )
    with TestClient(app) as client:
        workspace = _create(client)
        project_id = workspace["project"]["id"]
        initial = workspace["topic_decision"]
        preview = client.post(
            f"/api/projects/{project_id}/topic-decision/candidates-preview",
            json={"expected_revision": 0, "author_intent": "更强家庭与产业双线"},
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["mode"] == "full"
        submitted = client.post(
            f"/api/projects/{project_id}/topic-decision/candidate-jobs",
            json={
                "expected_revision": 0,
                "author_intent": "更强家庭与产业双线",
                "confirm_external_processing": True,
            },
        )
        assert submitted.status_code == 202, submitted.text
        job = submitted.json()
        assert job["kind"] == "topic_decision"
        assert job["workflow"] == "topic_candidates"
        assert client.app.state.job_runtime.run_once() is True
        result_response = client.get(
            f"/api/jobs/{job['id']}/topic-decision-candidates"
        )
        assert result_response.status_code == 200, result_response.text
        result = result_response.json()
        assert result["based_on_revision"] == 0
        assert result["target_field"] is None
        assert len(result["candidates"]) == 3
        assert gateway.calls == 1
        assert gateway.contexts[0]["current_topic"] == initial["content"]

        candidate = result["candidates"][1]
        selected = client.post(
            f"/api/projects/{project_id}/topic-decision/candidate-selection",
            json={
                "job_id": job["id"],
                "candidate_id": candidate["id"],
                "selected_fields": ["core_desire"],
                "expected_revision": 0,
            },
        )
        assert selected.status_code == 200, selected.text
        topic = selected.json()
        assert topic["status"] == "draft"
        assert topic["confirmed_revision"] is None
        assert topic["revision"] == 1
        assert topic["content"]["core_desire"] == candidate["content"]["core_desire"]
        assert topic["content"]["premise"] == initial["content"]["premise"]
        assert topic["source_job_id"] == job["id"]
        assert topic["source_candidate_ids"] == [candidate["id"]]

        second_candidate = result["candidates"][2]
        merged = client.post(
            f"/api/projects/{project_id}/topic-decision/candidate-selection",
            json={
                "job_id": job["id"],
                "candidate_id": second_candidate["id"],
                "selected_fields": ["premise"],
                "expected_revision": topic["revision"],
            },
        )
        assert merged.status_code == 200, merged.text
        merged_topic = merged.json()
        assert merged_topic["revision"] == 2
        assert merged_topic["content"]["core_desire"] == candidate["content"]["core_desire"]
        assert merged_topic["content"]["premise"] == second_candidate["content"]["premise"]
        assert merged_topic["source_candidate_ids"] == [candidate["id"], second_candidate["id"]]

        manually_changed_content = {
            **merged_topic["content"],
            "reference_purpose": "作者手工改为只参考长线兑现节奏",
        }
        manual = client.patch(
            f"/api/projects/{project_id}/topic-decision",
            json={
                "content": manually_changed_content,
                "changed_fields": ["reference_purpose"],
                "lock_updates": {},
                "rejection_reason_updates": {},
                "expected_revision": merged_topic["revision"],
            },
        )
        assert manual.status_code == 200, manual.text
        stale_after_manual_edit = client.post(
            f"/api/projects/{project_id}/topic-decision/candidate-selection",
            json={
                "job_id": job["id"],
                "candidate_id": result["candidates"][0]["id"],
                "selected_fields": ["premise"],
                "expected_revision": manual.json()["revision"],
            },
        )
        assert stale_after_manual_edit.status_code == 409

        stale_repeat = client.post(
            f"/api/projects/{project_id}/topic-decision/candidate-selection",
            json={
                "job_id": job["id"],
                "candidate_id": candidate["id"],
                "selected_fields": ["premise"],
                "expected_revision": 0,
            },
        )
        assert stale_repeat.status_code == 409


def test_field_regeneration_respects_lock_and_rejected_or_cross_project_candidates(
    tmp_path: Path,
) -> None:
    gateway = TopicGateway()
    app = create_app(
        tmp_path / "topic-field.db",
        AiGatewayManager(gateway),
        defer_job_runtime=True,
    )
    with TestClient(app) as client:
        first = _create(client)
        second = _create(client, title="另一本书")
        first_id = first["project"]["id"]
        second_id = second["project"]["id"]

        locked = client.patch(
            f"/api/projects/{first_id}/topic-decision",
            json={
                "content": first["topic_decision"]["content"],
                "changed_fields": [],
                "lock_updates": {"core_desire": True},
                "rejection_reason_updates": {},
                "expected_revision": 0,
            },
        ).json()
        blocked = client.post(
            f"/api/projects/{first_id}/topic-decision/regeneration-preview",
            json={
                "target_field": "core_desire",
                "expected_revision": locked["revision"],
                "author_intent": "更具体",
            },
        )
        assert blocked.status_code == 409
        assert gateway.calls == 0

        unlocked = client.patch(
            f"/api/projects/{first_id}/topic-decision",
            json={
                "content": locked["content"],
                "changed_fields": [],
                "lock_updates": {"core_desire": False},
                "rejection_reason_updates": {"core_desire": "不要只写抽象的逆袭"},
                "expected_revision": locked["revision"],
            },
        ).json()
        submitted = client.post(
            f"/api/projects/{first_id}/topic-decision/regeneration-jobs",
            json={
                "target_field": "core_desire",
                "expected_revision": unlocked["revision"],
                "author_intent": "欲望必须能按章兑现",
                "confirm_external_processing": True,
            },
        )
        assert submitted.status_code == 202, submitted.text
        job = submitted.json()
        assert job["workflow"] == "topic_field_regeneration"
        assert client.app.state.job_runtime.run_once() is True
        result = client.get(
            f"/api/jobs/{job['id']}/topic-decision-candidates"
        ).json()
        assert result["target_field"] == "core_desire"
        assert all(item["changed_fields"] == ["core_desire"] for item in result["candidates"])

        candidate = result["candidates"][0]
        cross_project = client.post(
            f"/api/projects/{second_id}/topic-decision/candidate-selection",
            json={
                "job_id": job["id"],
                "candidate_id": candidate["id"],
                "selected_fields": ["core_desire"],
                "expected_revision": 0,
            },
        )
        assert cross_project.status_code == 404

        rejected = client.post(
            f"/api/projects/{first_id}/topic-decision/candidate-rejection",
            json={
                "job_id": job["id"],
                "candidate_id": candidate["id"],
                "reason": "仍然太抽象，没有首三章兑现点",
                "expected_revision": unlocked["revision"],
            },
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["state"] == "rejected"
        assert rejected.json()["rejection_reason"].startswith("仍然太抽象")
        repeated_rejection = client.post(
            f"/api/projects/{first_id}/topic-decision/candidate-rejection",
            json={
                "job_id": job["id"],
                "candidate_id": candidate["id"],
                "reason": "重复拒绝",
                "expected_revision": unlocked["revision"],
            },
        )
        assert repeated_rejection.status_code == 409
        rejected_selection = client.post(
            f"/api/projects/{first_id}/topic-decision/candidate-selection",
            json={
                "job_id": job["id"],
                "candidate_id": candidate["id"],
                "selected_fields": ["core_desire"],
                "expected_revision": unlocked["revision"],
            },
        )
        assert rejected_selection.status_code == 409

        regenerated = client.post(
            f"/api/projects/{first_id}/topic-decision/regeneration-jobs",
            json={
                "target_field": "core_desire",
                "expected_revision": unlocked["revision"],
                "author_intent": "欲望必须能按章兑现",
                "confirm_external_processing": True,
            },
        )
        assert regenerated.status_code == 202, regenerated.text
        assert regenerated.json()["id"] != job["id"]
        assert client.app.state.job_runtime.run_once() is True
        assert gateway.contexts[-1]["rejected_candidate_reasons"] == [
            "仍然太抽象，没有首三章兑现点"
        ]
