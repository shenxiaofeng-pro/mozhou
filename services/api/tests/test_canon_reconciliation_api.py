from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.chapter_production.models import (
    AdoptCandidateRequest,
    AdoptionMode,
    ChapterOutline,
    ModelTrace,
)
from app.context import CreativeContextPurpose
from app.database import Database
from app.main import create_app


def _sha(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _trace(purpose: CreativeContextPurpose) -> ModelTrace:
    return ModelTrace(
        purpose=purpose,
        context_packet_id=f"preference-{purpose.value}",
        context_packet_sha256="a" * 64,
        context_dependency_fingerprint_sha256="b" * 64,
        context_compiler_version="test-v1",
        provider="test",
        model="fixture",
        prompt_version="test-v1",
    )


def _reviewing_chapter(client: TestClient) -> tuple[str, dict[str, object]]:
    workspace = client.post(
        "/api/projects",
        json={
            "title": "定稿回流黄金项目",
            "genre": "eastern_fantasy",
            "rebirth_year": 728,
            "rebirth_location": "九州·云泽",
        },
    ).json()
    project_id = str(workspace["project"]["id"])
    chapter = workspace["chapters"][0]
    body = (
        "沈砚重生回到728年，来到云泽。"
        "沈砚获得灵石，突破炼气境。"
        "沈砚与林瑶结盟，发现宗门藏着一个秘密。"
    )
    chapter = client.patch(
        f"/api/chapters/{chapter['id']}",
        json={"content": body, "expected_revision": chapter["revision"]},
    ).json()
    chapter = client.patch(
        f"/api/chapters/{chapter['id']}/brief",
        json={
            "opening_hook": "重生后第一眼看见旧敌",
            "state_change": "沈砚突破炼气境",
            "ending_cliffhanger": "宗门秘密浮出水面",
            "expected_revision": chapter["revision"],
        },
    ).json()
    for target in ("drafted", "reviewing"):
        response = client.post(
            f"/api/chapters/{chapter['id']}/transition",
            json={"target_status": target, "expected_revision": chapter["revision"]},
        )
        assert response.status_code == 200
        chapter = response.json()
    return project_id, chapter


def test_approval_commits_version_job_and_reconciliation_atomically(tmp_path: Path) -> None:
    database_path = tmp_path / "approval.db"
    app = create_app(database_path, defer_job_runtime=True)
    with TestClient(app) as client:
        project_id, chapter = _reviewing_chapter(client)
        response = client.post(
            f"/api/chapters/{chapter['id']}/transition",
            json={
                "target_status": "approved",
                "expected_revision": chapter["revision"],
                "expected_content_sha256": _sha(str(chapter["content"])),
            },
        )

        assert response.status_code == 200
        approved = response.json()
        assert approved["status"] == "approved"
        assert approved["revision"] == int(chapter["revision"]) + 1

        latest = client.get(
            f"/api/projects/{project_id}/chapters/{chapter['id']}/canon-reconciliation/latest"
        )
        assert latest.status_code == 200
        assert latest.json()["reconciliation"]["state"] == "pending"

        with Database(database_path).connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM chapter_approvals").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM canon_reconciliations").fetchone()[0] == 1
            assert connection.execute(
                "SELECT COUNT(*) FROM chapter_versions WHERE source = 'approval'"
            ).fetchone()[0] == 1
            job = connection.execute(
                "SELECT provider, estimated_calls, workflow FROM jobs WHERE id = ?",
                (latest.json()["reconciliation"]["job_id"],),
            ).fetchone()
            assert tuple(job) == ("local", 0, "canon_reconciliation_v1")


def test_wrong_approval_hash_rolls_back_every_side_effect(tmp_path: Path) -> None:
    database_path = tmp_path / "stale.db"
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        _project_id, chapter = _reviewing_chapter(client)
        response = client.post(
            f"/api/chapters/{chapter['id']}/transition",
            json={
                "target_status": "approved",
                "expected_revision": chapter["revision"],
                "expected_content_sha256": "0" * 64,
            },
        )
        current = client.get(f"/api/chapters/{chapter['id']}").json()

    assert response.status_code == 409
    assert current["status"] == "reviewing"
    assert current["revision"] == chapter["revision"]
    with Database(database_path).connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM chapter_approvals").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM canon_reconciliations").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE workflow = 'canon_reconciliation_v1'"
        ).fetchone()[0] == 0


def test_reopened_chapter_stales_ready_reconciliation_before_any_canon_write(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "reopened-ready-reconciliation.db"
    app = create_app(database_path, defer_job_runtime=True)
    with TestClient(app) as client:
        project_id, chapter = _reviewing_chapter(client)
        approved = client.post(
            f"/api/chapters/{chapter['id']}/transition",
            json={
                "target_status": "approved",
                "expected_revision": chapter["revision"],
                "expected_content_sha256": _sha(str(chapter["content"])),
            },
        ).json()
        assert app.state.job_runtime.run_once()
        latest_url = (
            f"/api/projects/{project_id}/chapters/{chapter['id']}"
            "/canon-reconciliation/latest"
        )
        snapshot = client.get(latest_url).json()
        assert snapshot["reconciliation"]["state"] == "ready"
        candidate = snapshot["canon_candidates"][0]
        reopened = client.post(
            f"/api/chapters/{chapter['id']}/transition",
            json={
                "target_status": "drafted",
                "expected_revision": approved["revision"],
            },
        )
        assert reopened.status_code == 200, reopened.text

        decision = client.post(
            f"/api/projects/{project_id}/canon-reconciliations/"
            f"{snapshot['reconciliation']['id']}/decisions",
            json={
                "reconciliation_id": snapshot["reconciliation"]["id"],
                "expected_reconciliation_revision": snapshot["reconciliation"][
                    "revision"
                ],
                "idempotency_key": "reopened-chapter-must-stale",
                "canon_decisions": [
                    {
                        "candidate_id": candidate["id"],
                        "expected_revision": candidate["revision"],
                        "action": "accept",
                    }
                ],
                "preference_decisions": [],
            },
        )

        assert decision.status_code == 409, decision.text
        assert decision.json()["detail"]["code"] == "stale_revision"
        stale = client.get(latest_url).json()
        assert stale["reconciliation"]["state"] == "stale"
        assert all(item["state"] == "stale" for item in stale["canon_candidates"])
        with Database(database_path).connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM canon_records").fetchone()[0] == 0


def test_local_worker_keeps_typed_candidates_isolated_until_author_decides(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "journey.db"
    app = create_app(database_path, defer_job_runtime=True)
    with TestClient(app) as client:
        project_id, chapter = _reviewing_chapter(client)
        approved = client.post(
            f"/api/chapters/{chapter['id']}/transition",
            json={
                "target_status": "approved",
                "expected_revision": chapter["revision"],
                "expected_content_sha256": _sha(str(chapter["content"])),
            },
        )
        assert approved.status_code == 200
        assert app.state.job_runtime.run_once()

        latest_url = (
            f"/api/projects/{project_id}/chapters/{chapter['id']}"
            "/canon-reconciliation/latest"
        )
        snapshot = client.get(latest_url).json()
        assert snapshot["reconciliation"]["state"] == "ready"
        assert snapshot["canon_candidates"]
        assert snapshot["preference_candidates"] == []
        assert snapshot["reconciliation"]["preference_skip_reason"] == (
            "no_adopted_writing_outcome"
        )

        body = str(chapter["content"])
        for candidate in snapshot["canon_candidates"]:
            evidence = candidate["evidence"]
            assert body[evidence["start_char"] : evidence["end_char"]] == evidence["excerpt"]
        with Database(database_path).connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM canon_records").fetchone()[0] == 0

        first, *rest = snapshot["canon_candidates"]
        assert rest
        first_request = {
            "reconciliation_id": snapshot["reconciliation"]["id"],
            "expected_reconciliation_revision": snapshot["reconciliation"]["revision"],
            "idempotency_key": "author-decision-part-0001",
            "canon_decisions": [
                {
                    "candidate_id": first["id"],
                    "expected_revision": first["revision"],
                    "action": "accept",
                }
            ],
            "preference_decisions": [],
        }
        partial = client.post(
            f"/api/projects/{project_id}/canon-reconciliations/"
            f"{snapshot['reconciliation']['id']}/decisions",
            json=first_request,
        )
        assert partial.status_code == 200, partial.text
        assert len(partial.json()["accepted_canon_record_ids"]) == 1
        assert partial.json()["rolling_plan_replenishment_id"] is None

        partial_snapshot = client.get(latest_url).json()
        final_request = {
            "reconciliation_id": partial_snapshot["reconciliation"]["id"],
            "expected_reconciliation_revision": partial_snapshot["reconciliation"][
                "revision"
            ],
            "idempotency_key": "author-decision-part-0002",
            "canon_decisions": [
                {
                    "candidate_id": item["id"],
                    "expected_revision": item["revision"],
                    "action": "reject",
                    "rejection_reason": "本章不作为长期设定",
                }
                for item in partial_snapshot["canon_candidates"]
                if item["state"] == "candidate"
            ],
            "preference_decisions": [],
        }
        decided = client.post(
            f"/api/projects/{project_id}/canon-reconciliations/"
            f"{snapshot['reconciliation']['id']}/decisions",
            json=final_request,
        )
        assert decided.status_code == 200, decided.text
        assert decided.json()["accepted_canon_record_ids"] == []
        assert decided.json()["rolling_plan_replenishment_id"] is not None
        replay = client.post(
            f"/api/projects/{project_id}/canon-reconciliations/"
            f"{snapshot['reconciliation']['id']}/decisions",
            json=final_request,
        )
        assert replay.status_code == 200
        assert replay.json()["replayed"] is True

        final = client.get(latest_url).json()
        assert final["reconciliation"]["state"] == "decided"
        assert final["rolling_plan_replenishment"]["state"] == "not_needed"
        assert final["rolling_plan_replenishment"]["blocked_reason"] == (
            "volume_plan_required"
        )
        with Database(database_path).connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM canon_records").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM story_facts").fetchone()[0] == 0


def test_stale_decision_snapshot_does_not_discard_another_authors_pending_work(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "concurrent-canon-decisions.db"
    app = create_app(database_path, defer_job_runtime=True)
    with TestClient(app) as client:
        project_id, chapter = _reviewing_chapter(client)
        approved = client.post(
            f"/api/chapters/{chapter['id']}/transition",
            json={
                "target_status": "approved",
                "expected_revision": chapter["revision"],
                "expected_content_sha256": _sha(str(chapter["content"])),
            },
        )
        assert approved.status_code == 200, approved.text
        assert app.state.job_runtime.run_once()
        latest_url = (
            f"/api/projects/{project_id}/chapters/{chapter['id']}"
            "/canon-reconciliation/latest"
        )
        original = client.get(latest_url).json()
        first, second, *_rest = original["canon_candidates"]

        accepted = client.post(
            f"/api/projects/{project_id}/canon-reconciliations/"
            f"{original['reconciliation']['id']}/decisions",
            json={
                "reconciliation_id": original["reconciliation"]["id"],
                "expected_reconciliation_revision": original["reconciliation"][
                    "revision"
                ],
                "idempotency_key": "concurrent-canon-first-window",
                "canon_decisions": [
                    {
                        "candidate_id": first["id"],
                        "expected_revision": first["revision"],
                        "action": "accept",
                    }
                ],
                "preference_decisions": [],
            },
        )
        assert accepted.status_code == 200, accepted.text

        stale = client.post(
            f"/api/projects/{project_id}/canon-reconciliations/"
            f"{original['reconciliation']['id']}/decisions",
            json={
                "reconciliation_id": original["reconciliation"]["id"],
                "expected_reconciliation_revision": original["reconciliation"][
                    "revision"
                ],
                "idempotency_key": "concurrent-canon-stale-window",
                "canon_decisions": [
                    {
                        "candidate_id": second["id"],
                        "expected_revision": second["revision"],
                        "action": "reject",
                        "rejection_reason": "旧窗口中的决定",
                    }
                ],
                "preference_decisions": [],
            },
        )

        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"]["code"] == "stale_revision"
        current = client.get(latest_url).json()
        assert current["reconciliation"]["state"] == "ready"
        states = {item["id"]: item["state"] for item in current["canon_candidates"]}
        assert states[first["id"]] == "accepted"
        assert states[second["id"]] == "candidate"


def test_older_ready_reconciliation_cannot_overwrite_newer_canon_record(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "out-of-order-canon-decisions.db"
    app = create_app(database_path, defer_job_runtime=True)
    with TestClient(app) as client:
        project_id, first_chapter = _reviewing_chapter(client)
        first_approval = client.post(
            f"/api/chapters/{first_chapter['id']}/transition",
            json={
                "target_status": "approved",
                "expected_revision": first_chapter["revision"],
                "expected_content_sha256": _sha(str(first_chapter["content"])),
            },
        )
        assert first_approval.status_code == 200, first_approval.text
        assert app.state.job_runtime.run_once()
        first_url = (
            f"/api/projects/{project_id}/chapters/{first_chapter['id']}"
            "/canon-reconciliation/latest"
        )
        first_snapshot = client.get(first_url).json()
        assert first_snapshot["reconciliation"]["state"] == "ready"

        second_chapter = client.post(
            f"/api/projects/{project_id}/chapters",
            json={"expected_last_chapter_number": 1},
        ).json()
        second_body = "沈砚获得灵石，突破筑基境。"
        second_chapter = client.patch(
            f"/api/chapters/{second_chapter['id']}",
            json={
                "content": second_body,
                "expected_revision": second_chapter["revision"],
            },
        ).json()
        second_chapter = client.patch(
            f"/api/chapters/{second_chapter['id']}/brief",
            json={
                "opening_hook": "灵石内的新力量苏醒",
                "state_change": "沈砚突破筑基境",
                "ending_cliffhanger": "白塔守门人发现了他",
                "expected_revision": second_chapter["revision"],
            },
        ).json()
        for target in ("drafted", "reviewing"):
            transitioned = client.post(
                f"/api/chapters/{second_chapter['id']}/transition",
                json={
                    "target_status": target,
                    "expected_revision": second_chapter["revision"],
                },
            )
            assert transitioned.status_code == 200, transitioned.text
            second_chapter = transitioned.json()
        second_approval = client.post(
            f"/api/chapters/{second_chapter['id']}/transition",
            json={
                "target_status": "approved",
                "expected_revision": second_chapter["revision"],
                "expected_content_sha256": _sha(second_body),
            },
        )
        assert second_approval.status_code == 200, second_approval.text
        assert app.state.job_runtime.run_once()
        second_url = (
            f"/api/projects/{project_id}/chapters/{second_chapter['id']}"
            "/canon-reconciliation/latest"
        )
        second_snapshot = client.get(second_url).json()
        assert second_snapshot["reconciliation"]["state"] == "ready"

        first_progression = next(
            item
            for item in first_snapshot["canon_candidates"]
            if item["kind"] == "progression"
        )
        first_unrelated = next(
            item
            for item in first_snapshot["canon_candidates"]
            if item["kind"] == "timeline_event"
        )
        second_progression = next(
            item
            for item in second_snapshot["canon_candidates"]
            if item["kind"] == "progression"
        )
        assert first_progression["subject_key"] == second_progression["subject_key"]
        assert first_progression["conflicts"] == []
        assert second_progression["conflicts"] == []

        newer_decision = client.post(
            f"/api/projects/{project_id}/canon-reconciliations/"
            f"{second_snapshot['reconciliation']['id']}/decisions",
            json={
                "reconciliation_id": second_snapshot["reconciliation"]["id"],
                "expected_reconciliation_revision": second_snapshot["reconciliation"][
                    "revision"
                ],
                "idempotency_key": "newer-canon-confirmation",
                "canon_decisions": [
                    {
                        "candidate_id": second_progression["id"],
                        "expected_revision": second_progression["revision"],
                        "action": "accept",
                    }
                ],
                "preference_decisions": [],
            },
        )
        assert newer_decision.status_code == 200, newer_decision.text

        stale_decision = client.post(
            f"/api/projects/{project_id}/canon-reconciliations/"
            f"{first_snapshot['reconciliation']['id']}/decisions",
            json={
                "reconciliation_id": first_snapshot["reconciliation"]["id"],
                "expected_reconciliation_revision": first_snapshot["reconciliation"][
                    "revision"
                ],
                "idempotency_key": "older-canon-must-not-regress",
                "canon_decisions": [
                    {
                        "candidate_id": first_unrelated["id"],
                        "expected_revision": first_unrelated["revision"],
                        "action": "accept",
                    },
                    {
                        "candidate_id": first_progression["id"],
                        "expected_revision": first_progression["revision"],
                        "action": "accept",
                    },
                ],
                "preference_decisions": [],
            },
        )

        assert stale_decision.status_code == 409, stale_decision.text
        assert stale_decision.json()["detail"]["code"] == "stale_revision"
        current_first = client.get(first_url).json()
        assert current_first["reconciliation"]["state"] == "ready"
        assert all(
            item["state"] == "candidate"
            for item in current_first["canon_candidates"]
        )
        with Database(database_path).connect() as connection:
            records = connection.execute(
                "SELECT kind, subject_key, source_candidate_id FROM canon_records"
            ).fetchall()
            assert [tuple(row) for row in records] == [
                (
                    "progression",
                    second_progression["subject_key"],
                    second_progression["id"],
                )
            ]
            assert connection.execute(
                "SELECT COUNT(*) FROM timeline_events WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0] == 0


def test_failed_canon_reconciliation_can_resume_after_transient_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "retry-canon-reconciliation.db"
    app = create_app(database_path, defer_job_runtime=True)
    with TestClient(app) as client:
        project_id, chapter = _reviewing_chapter(client)
        approved = client.post(
            f"/api/chapters/{chapter['id']}/transition",
            json={
                "target_status": "approved",
                "expected_revision": chapter["revision"],
                "expected_content_sha256": _sha(str(chapter["content"])),
            },
        )
        assert approved.status_code == 200, approved.text
        latest_url = (
            f"/api/projects/{project_id}/chapters/{chapter['id']}"
            "/canon-reconciliation/latest"
        )
        pending = client.get(latest_url).json()
        job_id = pending["reconciliation"]["job_id"]
        service = app.state.canon_reconciliation_service
        original = service._canon_candidates
        attempts = 0

        def fail_once(**kwargs: object):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ValueError("temporary extraction failure")
            return original(**kwargs)

        monkeypatch.setattr(service, "_canon_candidates", fail_once)
        assert app.state.job_runtime.run_once()
        assert client.get(f"/api/jobs/{job_id}").json()["state"] == "failed"
        assert client.get(latest_url).json()["reconciliation"]["state"] == "failed"

        retried = client.post(f"/api/jobs/{job_id}/retry")
        assert retried.status_code == 200, retried.text
        assert retried.json()["state"] == "queued"
        assert client.get(latest_url).json()["reconciliation"]["state"] == "pending"
        assert app.state.job_runtime.run_once()

        completed = client.get(latest_url).json()
        assert completed["reconciliation"]["state"] == "ready"
        assert client.get(f"/api/jobs/{job_id}").json()["state"] == "succeeded"


def test_whole_ai_candidate_can_yield_confirmed_compact_preference(tmp_path: Path) -> None:
    database_path = tmp_path / "preference.db"
    app = create_app(database_path, defer_job_runtime=True)
    with TestClient(app) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "作者偏好回流",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        chapter = workspace["chapters"][0]
        productions = app.state.chapter_production_repository
        production = productions.create_production(
            project_id=project_id,
            chapter_id=chapter["id"],
            expected_chapter_revision=chapter["revision"],
            expected_chapter_content_sha256=_sha(chapter["content"]),
        )
        outline = productions.add_outline_candidate(
            production_id=production.id,
            outline=ChapterOutline(
                title="第一章 返城",
                reader_promise="主角改变第一次选择",
                opening_hook="老车票上的日期提前了",
                state_change="主角决定提前回城",
                emotional_payoff="赶在事故前见到父亲",
                ending_cliffhanger="厂门口出现不该在的人",
                scene_beats=["发现日期", "改变行程", "抵达厂门"],
            ),
            label="作者确认章纲",
            trace=_trace(CreativeContextPurpose.BRIEF),
        )
        productions.record_preflight(
            production_id=production.id,
            outline_candidate_id=outline.id,
            expected_outline_revision=outline.current_version.revision,
            expected_outline_content_sha256=outline.current_version.content_sha256,
            checks={
                "reader_promise": True,
                "opening_hook": True,
                "state_change": True,
                "emotional_payoff": True,
                "ending_cliffhanger": True,
            },
            missing_fields=[],
        )
        ai_body = (
            "沈砚在车站反复回想过去的每一个细节，他慢慢地思考，"
            "又慢慢地走向出口。他解释了自己为什么必须回城，"
            "也解释了所有可能的风险和原因。"
        )
        candidate = productions.create_draft_candidate(
            production_id=production.id,
            outline_candidate_id=outline.id,
            expected_outline_revision=outline.current_version.revision,
            expected_outline_content_sha256=outline.current_version.content_sha256,
            content=ai_body,
            label="AI 正文候选",
            trace=_trace(CreativeContextPurpose.DRAFT),
        )
        outcome = productions.adopt_candidate(
            production_id=production.id,
            candidate_id=candidate.id,
            request=AdoptCandidateRequest(
                expected_candidate_revision=candidate.current_version.revision,
                expected_candidate_content_sha256=candidate.current_version.content_sha256,
                expected_chapter_revision=chapter["revision"],
                expected_chapter_content_sha256=_sha(chapter["content"]),
                mode=AdoptionMode.WHOLE,
                idempotency_key="adopt-whole-for-preference",
            ),
        )
        final_body = "沈砚收起车票，直奔南平老厂。"
        chapter = client.patch(
            f"/api/chapters/{chapter['id']}",
            json={
                "content": final_body,
                "expected_revision": outcome.final_chapter_revision,
            },
        ).json()
        chapter = client.patch(
            f"/api/chapters/{chapter['id']}/brief",
            json={
                "opening_hook": "收起车票直奔老厂",
                "state_change": "沈砚决定不再解释",
                "ending_cliffhanger": "老厂提前关门",
                "expected_revision": chapter["revision"],
            },
        ).json()
        chapter = client.post(
            f"/api/chapters/{chapter['id']}/transition",
            json={"target_status": "reviewing", "expected_revision": chapter["revision"]},
        ).json()
        approved = client.post(
            f"/api/chapters/{chapter['id']}/transition",
            json={
                "target_status": "approved",
                "expected_revision": chapter["revision"],
                "expected_content_sha256": _sha(final_body),
                "source_writing_outcome_id": outcome.id,
            },
        )
        assert approved.status_code == 200, approved.text
        assert app.state.job_runtime.run_once()

        latest_url = (
            f"/api/projects/{project_id}/chapters/{chapter['id']}"
            "/canon-reconciliation/latest"
        )
        snapshot = client.get(latest_url).json()
        assert snapshot["preference_candidates"]
        preference = snapshot["preference_candidates"][0]
        assert preference["dimension"] == "pacing"
        assert ai_body not in preference["compact_rule"]

        response = client.post(
            f"/api/projects/{project_id}/canon-reconciliations/"
            f"{snapshot['reconciliation']['id']}/decisions",
            json={
                "reconciliation_id": snapshot["reconciliation"]["id"],
                "expected_reconciliation_revision": snapshot["reconciliation"]["revision"],
                "idempotency_key": "confirm-one-author-preference",
                "canon_decisions": [
                    {
                        "candidate_id": item["id"],
                        "expected_revision": item["revision"],
                        "action": "reject",
                        "rejection_reason": "不需要长期记忆",
                    }
                    for item in snapshot["canon_candidates"]
                ],
                "preference_decisions": [
                    {
                        "candidate_id": preference["id"],
                        "expected_revision": preference["revision"],
                        "action": "accept",
                    },
                    *[
                        {
                            "candidate_id": item["id"],
                            "expected_revision": item["revision"],
                            "action": "reject",
                            "rejection_reason": "暂不作为长期偏好",
                        }
                        for item in snapshot["preference_candidates"][1:]
                    ],
                ],
            },
        )
        assert response.status_code == 200, response.text
        preferences = client.get(f"/api/projects/{project_id}/author-preferences").json()
        assert len(preferences) == 1
        assert preferences[0]["compact_rule"] == preference["compact_rule"]
        assert ai_body not in preferences[0]["compact_rule"]

        deleted = client.request(
            "DELETE",
            f"/api/projects/{project_id}/author-preferences/{preferences[0]['id']}",
            json={"expected_revision": preferences[0]["revision"]},
        )
        assert deleted.status_code == 200
        assert deleted.json()["state"] == "deleted"
        assert client.get(f"/api/projects/{project_id}/author-preferences").json() == []
