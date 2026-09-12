import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.chapter_production.models import (
    AdoptCandidateRequest,
    AdoptionMode,
    ChapterOutline,
    ModelTrace,
)
from app.context import (
    ContextPacket,
    CreativeContextBlockedError,
    CreativeContextCompileRequest,
    CreativeContextPurpose,
    CreativeContextService,
    CreativeContextSubject,
    CreativeContextSubjectKind,
)
from app.database import Database
from app.jobs import JobKind, JobRepository
from app.main import create_app
from app.models import (
    ReviewDimension,
    ReviewEvidence,
    ReviewEvidenceKind,
    ReviewSeverity,
)
from app.repository import ProjectRepository
from app.review.rules import make_finding

ARCHIVE_TABLES = {
    "projects",
    "author_ideas",
    "book_blueprints",
    "volume_plans",
    "rolling_chapter_plans",
    "manuscript_volumes",
    "chapters",
    "manuscript_scenes",
    "directory_events",
    "serial_daily_goals",
    "chapter_versions",
    "chapter_annotations",
    "context_directives",
    "context_packets",
    "creative_plan_dependencies",
    "generation_runs",
    "chapter_events",
    "run_events",
    "jobs",
    "job_chunks",
    "job_attempts",
    "job_artifacts",
    "job_events",
    "chapter_productions",
    "chapter_production_events",
    "chapter_outline_candidates",
    "chapter_outline_candidate_versions",
    "chapter_preflight_checks",
    "chapter_draft_candidates",
    "chapter_draft_candidate_versions",
    "chapter_draft_candidate_locks",
    "chapter_candidate_reviews",
    "chapter_candidate_merge_sources",
    "chapter_writing_outcomes",
    "chapter_approvals",
    "canon_reconciliations",
    "canon_delta_candidates",
    "canon_records",
    "author_preference_candidates",
    "author_preferences",
    "author_preference_sources",
    "canon_decision_batches",
    "rolling_plan_replenishments",
    "craft_pattern_assets",
    "project_craft_pattern_assets",
    "craft_pattern_job_outputs",
    "topic_decisions",
    "topic_decision_versions",
    "topic_decision_candidate_sets",
    "topic_decision_candidates",
    "writing_pattern_recipes",
    "writing_pattern_recipe_versions",
    "writing_pattern_recipe_sources",
    "writing_pattern_profile_versions",
    "project_writing_pattern_profiles",
    "writing_pattern_adaptation_proposals",
    "writing_pattern_adaptation_candidates",
    "writing_pattern_adaptation_candidate_versions",
    "writing_pattern_adoptions",
    "writing_pattern_originality_reports",
    "writing_pattern_originality_findings",
    "comic_projects",
    "comic_episodes",
    "comic_versions",
    "comic_scenes",
    "timeline_events",
    "story_facts",
    "fact_change_sets",
    "fact_changes",
    "future_knowledge",
    "story_entities",
    "story_threads",
    "story_relationships",
    "source_documents",
    "source_cards",
    "research_sessions",
    "research_sources",
    "research_findings",
    "reference_works",
    "reference_segments",
    "reference_pattern_cards",
    "reference_pattern_applications",
    "reference_blueprint_versions",
    "originality_reports",
    "plan_rebase_candidates",
    "scene_originality_checks",
    "scene_originality_findings",
    "review_findings",
    "text_change_sets",
    "text_changes",
}


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _m34_decided_archive(
    client: TestClient,
    *,
    edit_first_candidate: bool = False,
    simulate_legacy_analysis_hash: bool = False,
) -> tuple[dict[str, object], dict[str, str]]:
    workspace = client.post(
        "/api/projects",
        json={
            "title": "定稿 Canon 归档",
            "genre": "eastern_fantasy",
            "rebirth_year": 728,
            "rebirth_location": "九州云泽",
        },
    ).json()
    project_id = str(workspace["project"]["id"])
    chapter = workspace["chapters"][0]
    body = "沈砚重生回到728年。沈砚获得灵石，突破炼气境。"
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
        chapter = client.post(
            f"/api/chapters/{chapter['id']}/transition",
            json={"target_status": target, "expected_revision": chapter["revision"]},
        ).json()
    approved = client.post(
        f"/api/chapters/{chapter['id']}/transition",
        json={
            "target_status": "approved",
            "expected_revision": chapter["revision"],
            "expected_content_sha256": hashlib.sha256(body.encode()).hexdigest(),
        },
    )
    assert approved.status_code == 200, approved.text
    assert client.app.state.job_runtime.run_once()
    latest_url = (
        f"/api/projects/{project_id}/chapters/{chapter['id']}"
        "/canon-reconciliation/latest"
    )
    snapshot = client.get(latest_url).json()
    first, *rest = snapshot["canon_candidates"]
    first_decision = {
        "candidate_id": first["id"],
        "expected_revision": first["revision"],
        "action": "edit" if edit_first_candidate else "accept",
    }
    if edit_first_candidate:
        first_decision.update(
            {
                "edited_subject_key": f"{first['subject_key']}·作者校准",
                "edited_summary": f"{first['summary']}（作者校准）",
                "edited_payload": first["payload"],
            }
        )
    decision = client.post(
        f"/api/projects/{project_id}/canon-reconciliations/"
        f"{snapshot['reconciliation']['id']}/decisions",
        json={
            "reconciliation_id": snapshot["reconciliation"]["id"],
            "expected_reconciliation_revision": snapshot["reconciliation"]["revision"],
            "idempotency_key": "archive-canon-decision-0001",
            "canon_decisions": [
                first_decision,
                *[
                    {
                        "candidate_id": candidate["id"],
                        "expected_revision": candidate["revision"],
                        "action": "reject",
                        "rejection_reason": "不进入长期设定",
                    }
                    for candidate in rest
                ],
            ],
            "preference_decisions": [],
        },
    )
    assert decision.status_code == 200, decision.text
    if simulate_legacy_analysis_hash:
        with client.app.state.repository.database.connect() as connection:
            connection.execute(
                """
                UPDATE canon_reconciliations SET analysis_sha256 = ?
                WHERE id = ?
                """,
                ("0" * 64, snapshot["reconciliation"]["id"]),
            )
    archive = client.get(f"/api/projects/{project_id}/export").json()
    ids = {
        "project": project_id,
        "chapter": str(chapter["id"]),
        "approval": str(archive["tables"]["chapter_approvals"][0]["id"]),
        "version": str(archive["tables"]["chapter_approvals"][0]["chapter_version_id"]),
        "reconciliation": str(archive["tables"]["canon_reconciliations"][0]["id"]),
        "candidate": str(archive["tables"]["canon_delta_candidates"][0]["id"]),
        "record": str(archive["tables"]["canon_records"][0]["id"]),
        "batch": str(archive["tables"]["canon_decision_batches"][0]["id"]),
        "replenishment": str(archive["tables"]["rolling_plan_replenishments"][0]["id"]),
    }
    return archive, ids


def _m34_pending_archive(client: TestClient) -> tuple[dict[str, object], dict[str, int]]:
    workspace = client.post(
        "/api/projects",
        json={
            "title": "待执行 Canon 归档",
            "genre": "eastern_fantasy",
            "rebirth_year": 728,
            "rebirth_location": "九州云泽",
        },
    ).json()
    project_id = str(workspace["project"]["id"])
    chapter = workspace["chapters"][0]
    body = "沈砚重生回到728年。沈砚获得灵石，突破炼气境。"
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
        chapter = client.post(
            f"/api/chapters/{chapter['id']}/transition",
            json={"target_status": target, "expected_revision": chapter["revision"]},
        ).json()
    approved = client.post(
        f"/api/chapters/{chapter['id']}/transition",
        json={
            "target_status": "approved",
            "expected_revision": chapter["revision"],
            "expected_content_sha256": hashlib.sha256(body.encode()).hexdigest(),
        },
    )
    assert approved.status_code == 200, approved.text
    archive = client.get(f"/api/projects/{project_id}/export").json()
    reconciliation = archive["tables"]["canon_reconciliations"][0]
    return archive, {"revision": int(reconciliation["revision"])}


def _m34_trace(
    client: TestClient,
    *,
    project_id: str,
    chapter_id: str,
    purpose: CreativeContextPurpose,
) -> ModelTrace:
    workspace = client.app.state.repository.get_workspace(project_id)
    chapter = next(item for item in workspace.chapters if item.id == chapter_id)
    packet = client.app.state.creative_context_service.compile(
        workspace,
        CreativeContextCompileRequest(
            purpose=purpose,
            subject=CreativeContextSubject(
                kind=CreativeContextSubjectKind.CHAPTER,
                id=chapter_id,
                revision=chapter.revision,
            ),
        ),
    )
    return ModelTrace(
        purpose=purpose,
        context_packet_id=packet.id,
        context_packet_sha256=packet.packet_sha256,
        context_dependency_fingerprint_sha256=(
            packet.dependency_fingerprint_sha256
        ),
        context_compiler_version=packet.compiler_version,
        profile_fingerprint_sha256=packet.profile_fingerprint_sha256,
        provider="test",
        model="fixture",
        prompt_version="archive-preference-v1",
    )


def _m34_preference_archive(
    client: TestClient,
) -> tuple[dict[str, object], dict[str, str]]:
    workspace = client.post(
        "/api/projects",
        json={
            "title": "作者偏好归档",
            "genre": "urban_rebirth",
            "rebirth_year": 1998,
            "rebirth_location": "福建南平",
        },
    ).json()
    project_id = str(workspace["project"]["id"])
    chapter = workspace["chapters"][0]
    chapter_id = str(chapter["id"])
    productions = client.app.state.chapter_production_repository
    production = productions.create_production(
        project_id=project_id,
        chapter_id=chapter_id,
        expected_chapter_revision=chapter["revision"],
        expected_chapter_content_sha256=hashlib.sha256(
            str(chapter["content"]).encode()
        ).hexdigest(),
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
        trace=_m34_trace(
            client,
            project_id=project_id,
            chapter_id=chapter_id,
            purpose=CreativeContextPurpose.BRIEF,
        ),
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
        trace=_m34_trace(
            client,
            project_id=project_id,
            chapter_id=chapter_id,
            purpose=CreativeContextPurpose.DRAFT,
        ),
    )
    outcome = productions.adopt_candidate(
        production_id=production.id,
        candidate_id=candidate.id,
        request=AdoptCandidateRequest(
            expected_candidate_revision=candidate.current_version.revision,
            expected_candidate_content_sha256=candidate.current_version.content_sha256,
            expected_chapter_revision=chapter["revision"],
            expected_chapter_content_sha256=hashlib.sha256(
                str(chapter["content"]).encode()
            ).hexdigest(),
            mode=AdoptionMode.WHOLE,
            idempotency_key="archive-whole-preference",
        ),
    )
    final_body = "沈砚收起车票，直奔南平老厂。"
    chapter = client.patch(
        f"/api/chapters/{chapter_id}",
        json={
            "content": final_body,
            "expected_revision": outcome.final_chapter_revision,
        },
    ).json()
    chapter = client.patch(
        f"/api/chapters/{chapter_id}/brief",
        json={
            "opening_hook": "收起车票直奔老厂",
            "state_change": "沈砚决定不再解释",
            "ending_cliffhanger": "老厂提前关门",
            "expected_revision": chapter["revision"],
        },
    ).json()
    chapter = client.post(
        f"/api/chapters/{chapter_id}/transition",
        json={"target_status": "reviewing", "expected_revision": chapter["revision"]},
    ).json()
    approved = client.post(
        f"/api/chapters/{chapter_id}/transition",
        json={
            "target_status": "approved",
            "expected_revision": chapter["revision"],
            "expected_content_sha256": hashlib.sha256(final_body.encode()).hexdigest(),
            "source_writing_outcome_id": outcome.id,
        },
    )
    assert approved.status_code == 200, approved.text
    assert client.app.state.job_runtime.run_once()
    snapshot = client.get(
        f"/api/projects/{project_id}/chapters/{chapter_id}"
        "/canon-reconciliation/latest"
    ).json()
    first_preference, *remaining_preferences = snapshot["preference_candidates"]
    decision = client.post(
        f"/api/projects/{project_id}/canon-reconciliations/"
        f"{snapshot['reconciliation']['id']}/decisions",
        json={
            "reconciliation_id": snapshot["reconciliation"]["id"],
            "expected_reconciliation_revision": snapshot["reconciliation"]["revision"],
            "idempotency_key": "archive-confirm-preference",
            "canon_decisions": [
                {
                    "candidate_id": item["id"],
                    "expected_revision": item["revision"],
                    "action": "reject",
                    "rejection_reason": "不进入长期设定",
                }
                for item in snapshot["canon_candidates"]
            ],
            "preference_decisions": [
                {
                    "candidate_id": first_preference["id"],
                    "expected_revision": first_preference["revision"],
                    "action": "edit",
                    "edited_scope_kind": first_preference["scope_kind"],
                    "edited_scope_value": first_preference["scope_value"],
                    "edited_dimension": first_preference["dimension"],
                    "edited_compact_rule": (
                        f"{first_preference['compact_rule']}（作者校准）"
                    ),
                    "edited_confidence": first_preference["confidence"],
                },
                *[
                    {
                        "candidate_id": item["id"],
                        "expected_revision": item["revision"],
                        "action": "reject",
                        "rejection_reason": "不作为长期偏好",
                    }
                    for item in remaining_preferences
                ],
            ],
        },
    )
    assert decision.status_code == 200, decision.text
    archive = client.get(f"/api/projects/{project_id}/export").json()
    return archive, {
        "project": project_id,
        "chapter": chapter_id,
        "outcome": outcome.id,
        "candidate_version": candidate.current_version.id,
        "preference_candidate": archive["tables"]["author_preference_candidates"][0][
            "id"
        ],
        "preference": archive["tables"]["author_preferences"][0]["id"],
    }


def test_exports_complete_project_archive_with_checksum(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "回到九八年的南平",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
                "template_id": "urban-rebirth",
            },
        ).json()
        project_id = workspace["project"]["id"]
        chapter_id = workspace["chapters"][0]["id"]
        client.patch(
            f"/api/chapters/{chapter_id}",
            json={"content": "列车驶入南平站。", "expected_revision": 0},
        )
        reference = client.post(
            f"/api/projects/{project_id}/reference-works",
            json={
                "title": "自有旧稿",
                "source_filename": "old.md",
                "rights_basis": "self_owned",
                "content": "# 第一章\n潮水从闽江上来。",
                "segment_target_characters": 500_000,
            },
        ).json()

        default_response = client.get(f"/api/projects/{project_id}/export")
        response = client.get(f"/api/projects/{project_id}/export?include_reference_assets=true")

    assert response.status_code == 200
    archive = response.json()
    default_archive = default_response.json()
    assert default_archive["tables"]["reference_works"] == []
    assert default_archive["tables"]["reference_segments"] == []
    assert archive["format"] == "mozhou-project"
    assert archive["format_version"] == 18
    assert archive["source_project_id"] == project_id
    assert archive["source_project_title"] == "回到九八年的南平"
    assert set(archive["tables"]) == ARCHIVE_TABLES
    assert archive["tables"]["chapters"][0]["content"] == "列车驶入南平站。"
    assert archive["tables"]["reference_segments"][0]["content"] == "# 第一章\n潮水从闽江上来。"
    assert archive["tables"]["reference_segments"][0]["id"] == reference["segments"][0]["id"]
    checksum = archive.pop("checksum_sha256")
    assert checksum == hashlib.sha256(canonical_json(archive)).hexdigest()


def test_round_trip_preserves_confirmed_topic_versions_and_rejected_candidates(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "topic-archive.db"
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "回到九八年的南平",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
                "template_id": "urban-rebirth",
                "topic_seed": "失败商人回到竹木厂违约前夜，先救下父亲。",
            },
        ).json()
        project_id = workspace["project"]["id"]
        confirmed = client.post(
            f"/api/projects/{project_id}/topic-decision/confirm",
            json={"expected_revision": 0},
        ).json()
        jobs: JobRepository = client.app.state.job_repository
        source_job, _created = jobs.create_job(
            project_id=project_id,
            kind=JobKind.TOPIC_DECISION,
            workflow="topic_candidates",
            idempotency_key="archive-topic-candidates",
            input_payload={"based_on_revision": confirmed["revision"]},
            provider="openai",
            model="topic-test-v1",
        )
        candidate_set_id = str(uuid4())
        candidate_ids = [str(uuid4()) for _ in range(3)]
        timestamp = confirmed["updated_at"]
        with sqlite3.connect(database_path) as connection:
            topic_id = connection.execute(
                "SELECT id FROM topic_decisions WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO topic_decision_candidate_sets (
                    id, topic_decision_id, project_id, source_job_id,
                    based_on_revision, target_field, created_at
                ) VALUES (?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    candidate_set_id,
                    topic_id,
                    project_id,
                    source_job.id,
                    confirmed["revision"],
                    timestamp,
                ),
            )
            for ordinal, candidate_id in enumerate(candidate_ids, start=1):
                content = {
                    **confirmed["content"],
                    "premise": f"候选 {ordinal}：以不同的原创冲突发动机开局。",
                }
                state = "rejected" if ordinal == 1 else "candidate"
                rejection_reason = "与作者期望的家庭主线不符" if ordinal == 1 else None
                decided_at = timestamp if ordinal == 1 else None
                connection.execute(
                    """
                    INSERT INTO topic_decision_candidates (
                        id, candidate_set_id, project_id, ordinal, label,
                        content_json, changed_fields_json, rationale, risks_json,
                        state, rejection_reason, created_at, updated_at, decided_at
                    ) VALUES (?, ?, ?, ?, ?, ?, '["premise"]', ?, '[]', ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate_id,
                        candidate_set_id,
                        project_id,
                        ordinal,
                        f"方向 {ordinal}",
                        json.dumps(
                            content,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        f"第 {ordinal} 种原创因果路径",
                        state,
                        rejection_reason,
                        timestamp,
                        timestamp,
                        decided_at,
                    ),
                )
        archive = client.get(f"/api/projects/{project_id}/export").json()
        restored_response = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )
        restored_project_id = restored_response.json()["project"]["id"]
        with sqlite3.connect(database_path) as connection:
            connection.row_factory = sqlite3.Row
            restored_versions = connection.execute(
                """
                SELECT v.revision, v.content_sha256
                FROM topic_decision_versions v
                WHERE v.project_id = ?
                """,
                (restored_project_id,),
            ).fetchall()
            restored_candidates = connection.execute(
                """
                SELECT ordinal, state, rejection_reason
                FROM topic_decision_candidates
                WHERE project_id = ?
                ORDER BY ordinal
                """,
                (restored_project_id,),
            ).fetchall()

    assert archive["format_version"] == 18
    assert len(archive["tables"]["topic_decisions"]) == 1
    assert len(archive["tables"]["topic_decision_versions"]) == 1
    assert len(archive["tables"]["topic_decision_candidate_sets"]) == 1
    assert len(archive["tables"]["topic_decision_candidates"]) == 3
    assert restored_response.status_code == 201, restored_response.text
    assert restored_response.json()["topic_decision"]["status"] == "confirmed"
    assert [(row["revision"], len(row["content_sha256"])) for row in restored_versions] == [
        (1, 64)
    ]
    assert [tuple(row) for row in restored_candidates] == [
        (1, "rejected", "与作者期望的家庭主线不符"),
        (2, "candidate", None),
        (3, "candidate", None),
    ]


def test_import_v11_creates_legacy_unconfirmed_topic_without_forcing_onboarding(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(tmp_path / "v11-topic-archive.db")) as client:
        original = client.post(
            "/api/projects",
            json={
                "title": "旧版本地作品",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        archive = client.get(f"/api/projects/{original['project']['id']}/export").json()
        archive["format_version"] = 11
        for table in (
            "topic_decisions",
            "topic_decision_versions",
            "topic_decision_candidate_sets",
            "topic_decision_candidates",
        ):
            archive["tables"].pop(table)
        unsigned = dict(archive)
        unsigned.pop("checksum_sha256")
        archive["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()

        restored = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )

    assert restored.status_code == 201, restored.text
    restored_workspace = restored.json()
    assert restored_workspace["topic_decision"]["status"] == "draft"
    assert restored_workspace["topic_decision"]["confirmed_revision"] is None
    assert restored_workspace["topic_decision"]["content"]["subgenre"] == "都市重生"
    assert restored_workspace["next_action"] == "plan_book"


def test_import_rejects_tampered_confirmed_topic_snapshot(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "tampered-topic-archive.db")) as client:
        original = client.post(
            "/api/projects",
            json={
                "title": "选题快照完整性",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
                "template_id": "urban-rebirth",
            },
        ).json()
        project_id = original["project"]["id"]
        client.post(
            f"/api/projects/{project_id}/topic-decision/confirm",
            json={"expected_revision": 0},
        )
        archive = client.get(f"/api/projects/{project_id}/export").json()
        version = archive["tables"]["topic_decision_versions"][0]
        content = json.loads(version["content_json"])
        content["premise"] = "篡改后企图绕过确认快照的选题"
        version["content_json"] = json.dumps(
            content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        unsigned = dict(archive)
        unsigned.pop("checksum_sha256")
        archive["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()

        response = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "项目归档无效或已损坏"}


def test_import_v10_defaults_reference_application_lifecycle_to_active(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(tmp_path / "v10-reference-application.db")) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "旧参考应用归档",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        reference = client.post(
            f"/api/projects/{project_id}/reference-works",
            json={
                "title": "自有测试稿",
                "source_filename": "legacy-reference.txt",
                "rights_basis": "self_owned",
                "content": "第一章\n时代潮水推动人物作出选择。",
                "segment_target_characters": 500_000,
            },
        ).json()
        segment_id = reference["segments"][0]["id"]
        archive = client.get(
            f"/api/projects/{project_id}/export?include_reference_assets=true"
        ).json()
        card_id = str(uuid4())
        application_id = str(uuid4())
        dimension = {
            "summary": "时代秩序出现新窗口",
            "source_segment_ids": [segment_id],
            "transferable_logic": "先用小行动验证机会",
            "adaptation_risk": "必须重写人物与场景",
        }
        proposal = {
            key: dimension
            for key in (
                "era",
                "core_desire",
                "conflict_causality",
                "resource_system",
                "key_scene_sequence",
                "ending",
            )
        } | {
            "shared_patterns": ["先验证机会"],
            "differences": ["资源条件不同"],
            "relationship_recomposition": "重组为师徒竞争",
            "originality_risks": [],
        }
        blueprint = {
            "dimensions": {
                "era": {
                    "source": dimension,
                    "mode": "preserve",
                    "author_edits": "仅保留抽象机会窗口",
                    "generated_variant": {
                        "summary": "南平地方产业出现服务缺口",
                        "transferable_logic": "先用小行动验证机会",
                    },
                    "version": 1,
                    "locked": False,
                    "named_entities": [],
                    "source_beats": [],
                    "key_beats": [],
                }
            },
            "relationship": {
                "source": "重组为师徒竞争",
                "mode": "reconstruct",
                "author_edits": "更换人物职能",
                "generated_variant": "地方创业者与家庭伙伴相互制衡",
                "version": 1,
                "locked": False,
                "relationships": [],
            },
        }
        archive["tables"]["reference_pattern_cards"].append(
            {
                "id": card_id,
                "project_id": project_id,
                "selected_segment_ids_json": json.dumps([segment_id]),
                "author_focus": "测试旧归档",
                "proposal_json": json.dumps(proposal, ensure_ascii=False),
                "provider": "openai",
                "model": "archive-fixture",
                "source_job_id": None,
                "created_at": archive["exported_at"],
            }
        )
        archive["tables"]["reference_pattern_applications"].append(
            {
                "id": application_id,
                "project_id": project_id,
                "pattern_card_id": card_id,
                "selected_dimensions_json": '["era"]',
                "dimensions_json": json.dumps(
                    {
                        "era": {
                            "summary": "南平地方产业出现服务缺口",
                            "transferable_logic": "先用小行动验证机会",
                        }
                    },
                    ensure_ascii=False,
                ),
                "relationship_recomposition": "地方创业者与家庭伙伴相互制衡",
                "application_note": "仅保留抽象机会窗口",
                "blueprint_json": json.dumps(blueprint, ensure_ascii=False),
                "originality_status": "needs_check",
                "risk_level": None,
                "latest_report_id": None,
                "threshold_version": None,
                "revision": 0,
                "created_at": archive["exported_at"],
                "updated_at": archive["exported_at"],
            }
        )
        archive["format_version"] = 10
        unsigned = dict(archive)
        unsigned.pop("checksum_sha256")
        archive["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()

        restored_response = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )

    assert restored_response.status_code == 201, restored_response.text
    restored = restored_response.json()["reference_pattern_applications"][0]
    assert restored["lifecycle_state"] == "active"
    assert restored["lifecycle_revision"] == 0
    assert restored["revision"] == 0


def test_archive_round_trip_preserves_fantasy_genre_story_anchors(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        created = client.post(
            "/api/projects",
            json={
                "title": "群星下的灰塔",
                "genre": "western_fantasy",
                "rebirth_year": 1243,
                "rebirth_location": "阿尔登大陆·北境",
            },
        ).json()
        archive = client.get(
            f"/api/projects/{created['project']['id']}/export"
        ).json()
        restored_response = client.post(
            "/api/project-imports",
            content=json.dumps(archive, ensure_ascii=False),
            headers={"Content-Type": "application/json"},
        )

    assert restored_response.status_code == 201
    restored = restored_response.json()["project"]
    assert restored["genre"] == "western_fantasy"
    assert restored["rebirth_year"] == 1243
    assert restored["rebirth_location"] == "阿尔登大陆·北境"


def test_archive_round_trip_preserves_book_director_plans(tmp_path: Path) -> None:
    database_path = tmp_path / "mozhou.db"
    timestamp = "2026-08-11T00:00:00+00:00"
    fields = (
        "title",
        "genre",
        "rebirth_year",
        "rebirth_location",
        "target_audience",
        "core_selling_points",
        "core_desire",
        "divergence_point",
        "long_term_promise",
        "ending_direction",
        "protagonist_arc",
        "resource_growth",
        "relationship_design",
    )
    blueprint_content = {
        "title": "闽北春潮",
        "genre": "urban_rebirth",
        "rebirth_year": 1998,
        "rebirth_location": "福建南平",
        "target_audience": "年代创业读者",
        "core_selling_points": ["木竹产业", "家庭改命"],
        "core_desire": "改变家庭命运",
        "divergence_point": "提前拿到停产名单",
        "long_term_promise": "从工厂自救到产业升级",
        "ending_direction": "建立可持续的产业联盟",
        "protagonist_arc": "从救家人到承担公共责任",
        "resource_growth": "信息差到组织信用",
        "relationship_design": "父子、师徒和竞争者重新组合",
    }
    volume_content = {
        "volume_number": 1,
        "title": "停产名单",
        "direction": "完成工厂自救",
        "central_conflict": "旧管理层阻止改制",
        "state_goal": "父亲保住岗位",
        "resource_goal": "获得第一笔订单",
        "emotional_payoff": "父子恢复信任",
        "climax": "公开竞标逆转",
        "verification": "核对 1998 年当地改制流程",
    }
    rolling_content = {
        "chapter_number": 1,
        "title": "名单之前",
        "reader_promise": "第一次改命",
        "opening_hook": "停产名单提前贴出",
        "state_change": "父亲暂时留岗",
        "resource_change": "获得厂长注意",
        "emotional_payoff": "父子关系松动",
        "ending_cliffhanger": "厂长叫出主角小名",
        "verification": "核对厂办张榜流程",
        "scene_beats": [
            {
                "ordinal": 1,
                "summary": "主角发现名单",
                "state_change": "确认时间线变化",
                "resource_change": "得到行动窗口",
                "emotional_turn": "恐慌转为决断",
                "verification": "核对公告地点",
            }
        ],
    }
    with TestClient(create_app(database_path)) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "闽北春潮",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        blueprint_id = "0a9cc817-ac3f-40c5-a749-f77dbcd85546"
        volume_id = "b5f28e1e-73f6-4379-b542-e751493952ae"
        rolling_id = "0a1465f4-3005-40cf-a93b-f63e6bbd4038"
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                """
                INSERT INTO book_blueprints (
                    id, project_id, idea, content_json, locks_json, field_versions_json,
                    stale_fields_json, plan_stale, source_candidate_id, revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, '[]', 0, ?, 2, ?, ?)
                """,
                (
                    blueprint_id,
                    project_id,
                    "回到一九九八年救下家乡木竹厂",
                    json.dumps(blueprint_content, ensure_ascii=False),
                    json.dumps({field: field == "ending_direction" for field in fields}),
                    json.dumps({field: 1 for field in fields}),
                    "f6f7db1e-96a7-4656-a540-96d81d9fa046",
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO volume_plans (
                    id, project_id, volume_number, content_json, locked, revision, created_at, updated_at
                ) VALUES (?, ?, 1, ?, 1, 1, ?, ?)
                """,
                (
                    volume_id,
                    project_id,
                    json.dumps(volume_content, ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO rolling_chapter_plans (
                    id, project_id, volume_plan_id, chapter_number, content_json,
                    locked, revision, created_at, updated_at
                ) VALUES (?, ?, ?, 1, ?, 0, 3, ?, ?)
                """,
                (
                    rolling_id,
                    project_id,
                    volume_id,
                    json.dumps(rolling_content, ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
        archive = client.get(f"/api/projects/{project_id}/export").json()
        restored_response = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )

    assert archive["format_version"] == 18
    assert archive["tables"]["book_blueprints"][0]["revision"] == 2
    assert restored_response.status_code == 201
    restored = restored_response.json()
    assert (
        restored["book_blueprint"]["content"]["ending_direction"]
        == blueprint_content["ending_direction"]
    )
    assert restored["book_blueprint"]["locks"]["ending_direction"] is True
    assert restored["volume_plans"][0]["title"] == "停产名单"
    assert restored["volume_plans"][0]["locked"] is True
    assert restored["rolling_chapter_plans"][0]["opening_hook"] == "停产名单提前贴出"
    assert restored["rolling_chapter_plans"][0]["revision"] == 3


def test_m32_archive_rebinds_context_and_plan_lineage_and_stales_open_candidate(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "m32-archive.db"
    timestamp = "2026-09-12T00:00:00+00:00"
    blueprint_id = str(uuid4())
    volume_id = str(uuid4())
    rolling_id = str(uuid4())
    blueprint_content = {
        "title": "南平春潮",
        "genre": "urban_rebirth",
        "rebirth_year": 1998,
        "rebirth_location": "福建南平",
        "target_audience": "喜欢产业升级与家庭关系的读者",
        "core_selling_points": ["订单破局", "家庭改命"],
        "core_desire": "保住家庭并建立长期事业",
        "divergence_point": "提前截住第一张违约订单",
        "long_term_promise": "每卷完成一次产业和关系跃迁",
        "ending_direction": "形成可持续的本地产业网络",
        "protagonist_arc": "从补偿家人走向承担公共责任",
        "resource_growth": "从信息差成长为组织与信用网络",
        "relationship_design": "家人锚定价值，伙伴执行，对手迫使升级",
    }
    volume_content = {
        "volume_number": 1,
        "title": "第一卷 抢回订单",
        "direction": "用第一笔订单重建家庭与行业信用",
        "central_conflict": "没有现金、资质和稳定交付能力",
        "state_goal": "成为能调动三方资源的执行者",
        "resource_goal": "建立第一笔可持续现金流",
        "emotional_payoff": "父亲第一次承认主角能扛事",
        "climax": "在违约前夜完成替代交付",
        "verification": "回款、关系和竞争格局同时变化",
    }
    rolling_content = {
        "chapter_number": 1,
        "title": "第一章 抢时间",
        "reader_promise": "看主角解决第一个现实阻碍",
        "opening_hook": "坏消息比记忆中更早到来",
        "state_change": "从被动得知转为主动介入",
        "resource_change": "新增一个可调动的资源节点",
        "emotional_payoff": "家人第一次给予有限信任",
        "ending_cliffhanger": "更大的违约代价提前浮现",
        "verification": "合同和关系状态发生可观察变化",
        "scene_beats": [
            {
                "ordinal": 1,
                "summary": "坏消息落地，主角立即选择",
                "state_change": "主角开始介入",
                "resource_change": "暴露当前资源缺口",
                "emotional_turn": "焦虑转为决断",
                "verification": "明确下一步行动和失败代价",
            }
        ],
    }
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "南平春潮",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
                "template_id": "urban-rebirth",
            },
        ).json()
        project_id = workspace["project"]["id"]
        chapter_id = workspace["chapters"][0]["id"]
        chapter_revision = workspace["chapters"][0]["revision"]
        confirmed = client.post(
            f"/api/projects/{project_id}/topic-decision/confirm",
            json={"expected_revision": workspace["topic_decision"]["revision"]},
        )
        assert confirmed.status_code == 200
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                """
                INSERT INTO book_blueprints (
                    id, project_id, idea, content_json, locks_json,
                    field_versions_json, stale_fields_json, plan_stale,
                    source_candidate_id, revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, '[]', 0, NULL, 0, ?, ?)
                """,
                (
                    blueprint_id,
                    project_id,
                    "用订单救下家庭和工厂",
                    json.dumps(blueprint_content, ensure_ascii=False),
                    json.dumps({key: False for key in blueprint_content}),
                    json.dumps({key: 1 for key in blueprint_content}),
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO volume_plans (
                    id, project_id, volume_number, content_json, locked,
                    revision, created_at, updated_at
                ) VALUES (?, ?, 1, ?, 0, 0, ?, ?)
                """,
                (volume_id, project_id, json.dumps(volume_content), timestamp, timestamp),
            )
            connection.execute(
                """
                INSERT INTO rolling_chapter_plans (
                    id, project_id, volume_plan_id, chapter_number, content_json,
                    locked, revision, created_at, updated_at
                ) VALUES (?, ?, ?, 1, ?, 0, 0, ?, ?)
                """,
                (
                    rolling_id,
                    project_id,
                    volume_id,
                    json.dumps(rolling_content),
                    timestamp,
                    timestamp,
                ),
            )

        impact = client.get(
            f"/api/projects/{project_id}/creative-context/impact"
        ).json()
        candidate_body = {
            "expected_dependency_fingerprint_sha256": impact[
                "current_dependency_fingerprint_sha256"
            ]
        }
        open_candidate = client.post(
            f"/api/projects/{project_id}/plan-rebase-candidates",
            json=candidate_body,
        ).json()
        adopted_candidate = client.post(
            f"/api/projects/{project_id}/plan-rebase-candidates",
            json=candidate_body,
        ).json()
        adopted = client.post(
            f"/api/projects/{project_id}/plan-rebase-candidates/"
            f"{adopted_candidate['id']}/adopt",
            json={
                "expected_revision": adopted_candidate["revision"],
                "expected_dependency_fingerprint_sha256": adopted_candidate[
                    "target_dependency_fingerprint_sha256"
                ],
                "idempotency_key": "archive-adopted-candidate",
            },
        )
        assert adopted.status_code == 200
        packet_response = client.post(
            f"/api/projects/{project_id}/creative-context/packets",
            json={
                "purpose": "draft",
                "subject": {
                    "kind": "chapter",
                    "id": chapter_id,
                    "revision": chapter_revision,
                },
                "token_budget": 8_000,
            },
        )
        assert packet_response.status_code == 201
        original_packet = packet_response.json()
        archive = client.get(f"/api/projects/{project_id}/export").json()
        original_topic_version_id = archive["tables"]["topic_decision_versions"][0][
            "id"
        ]
        restored_response = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )
        assert restored_response.status_code == 201, restored_response.text
        restored_workspace = restored_response.json()

    restored_project_id = restored_workspace["project"]["id"]
    restored_chapter_id = restored_workspace["chapters"][0]["id"]
    restored_blueprint_id = restored_workspace["book_blueprint"]["id"]
    restored_volume_id = restored_workspace["volume_plans"][0]["id"]
    restored_rolling_id = restored_workspace["rolling_chapter_plans"][0]["id"]
    with Database(database_path).connect() as connection:
        packet_row = connection.execute(
            "SELECT * FROM context_packets WHERE project_id = ?",
            (restored_project_id,),
        ).fetchone()
        dependency_rows = connection.execute(
            """
            SELECT * FROM creative_plan_dependencies
            WHERE project_id = ? ORDER BY subject_kind
            """,
            (restored_project_id,),
        ).fetchall()
        candidate_rows = connection.execute(
            """
            SELECT state, revision, adopted_at FROM plan_rebase_candidates
            WHERE project_id = ? ORDER BY id
            """,
            (restored_project_id,),
        ).fetchall()
    assert packet_row is not None
    packet = ContextPacket.model_validate_json(packet_row["packet_json"])
    assert packet.id != original_packet["id"]
    assert packet.project_id == restored_project_id
    assert packet.chapter_id == restored_chapter_id
    assert packet.subject.id == restored_chapter_id
    assert packet.dependency_snapshot.topic is not None
    assert packet.dependency_snapshot.topic.id != original_topic_version_id
    assert packet.dependency_snapshot.base_blueprint is not None
    assert packet.dependency_snapshot.base_blueprint.id == restored_blueprint_id
    assert packet.dependency_snapshot.schema_version == 2
    assert packet.dependency_snapshot.canon_state is not None
    assert packet.dependency_snapshot.canon_state.id == (
        f"canon-state:{restored_project_id}"
    )
    assert packet.dependency_snapshot.canon_state.id != (
        original_packet["dependency_snapshot"]["canon_state"]["id"]
    )
    assert packet.dependency_snapshot.author_preference_state is not None
    assert packet.dependency_snapshot.author_preference_state.id == (
        f"author-preference-state:{restored_project_id}"
    )
    assert packet.dependency_snapshot.author_preference_state.id != (
        original_packet["dependency_snapshot"]["author_preference_state"]["id"]
    )
    assert packet.dependency_fingerprint_sha256 == hashlib.sha256(
        canonical_json(packet.dependency_snapshot.canonical_payload())
    ).hexdigest()
    assert "restored_dependency_snapshot" in packet.blocking_reasons
    with pytest.raises(CreativeContextBlockedError, match="restored_dependency_snapshot"):
        CreativeContextService(
            ProjectRepository(Database(database_path))
        ).require_current(packet)

    expected_targets = {
        "book_blueprint": restored_blueprint_id,
        "volume_plan": restored_volume_id,
        "rolling_plan": restored_rolling_id,
    }
    assert {
        row["subject_kind"]: row["subject_id"] for row in dependency_rows
    } == expected_targets
    assert sorted(row["state"] for row in candidate_rows) == ["adopted", "stale"]
    stale_row = next(row for row in candidate_rows if row["state"] == "stale")
    assert stale_row["revision"] == open_candidate["revision"] + 1
    adopted_row = next(row for row in candidate_rows if row["state"] == "adopted")
    assert adopted_row["adopted_at"] is not None


def test_import_upgrades_v15_archive_with_empty_m32_tables(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "v15-m32-archive.db")) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "旧归档",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        archive = client.get(
            f"/api/projects/{workspace['project']['id']}/export"
        ).json()
        for table_name in (
            "context_packets",
            "creative_plan_dependencies",
            "plan_rebase_candidates",
        ):
            archive["tables"].pop(table_name)
        archive["format_version"] = 15
        unsigned = dict(archive)
        unsigned.pop("checksum_sha256")
        archive["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        restored = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )
        assert restored.status_code == 201, restored.text
        restored_project_id = restored.json()["project"]["id"]
        with sqlite3.connect(tmp_path / "v15-m32-archive.db") as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM context_packets WHERE project_id = ?",
                (restored_project_id,),
            ).fetchone()[0] == 0
            assert connection.execute(
                "SELECT COUNT(*) FROM creative_plan_dependencies WHERE project_id = ?",
                (restored_project_id,),
            ).fetchone()[0] == 0
            assert connection.execute(
                "SELECT COUNT(*) FROM plan_rebase_candidates WHERE project_id = ?",
                (restored_project_id,),
            ).fetchone()[0] == 0


def test_import_upgrades_v17_archive_with_m32_dependency_and_empty_m34_tables(
    tmp_path: Path,
) -> None:
    m34_tables = {
        "chapter_approvals",
        "canon_reconciliations",
        "canon_delta_candidates",
        "canon_records",
        "author_preference_candidates",
        "author_preferences",
        "author_preference_sources",
        "canon_decision_batches",
        "rolling_plan_replenishments",
    }
    database_path = tmp_path / "v17-m34-archive.db"
    with TestClient(create_app(database_path)) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "旧归档 Canon 兼容",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
                "template_id": "urban-rebirth",
            },
        ).json()
        project_id = str(workspace["project"]["id"])
        topic_decision = workspace["topic_decision"]
        confirmed = client.post(
            f"/api/projects/{project_id}/topic-decision/confirm",
            json={"expected_revision": topic_decision["revision"]},
        )
        assert confirmed.status_code == 200
        blueprint_id = str(uuid4())
        blueprint_content = {
            "title": "旧版创作蓝图",
            "genre": "urban_rebirth",
            "rebirth_year": 1998,
            "rebirth_location": "福建南平",
            "target_audience": "喜欢产业升级的读者",
            "core_selling_points": ["订单破局"],
            "core_desire": "保住家庭与工厂",
            "divergence_point": "提前截住违约订单",
            "long_term_promise": "持续完成产业和关系跃迁",
            "ending_direction": "建立本地产业网络",
            "protagonist_arc": "从补偿家人走向公共责任",
            "resource_growth": "从信息差成长为信用网络",
            "relationship_design": "家人锚定价值，伙伴负责执行",
        }
        timestamp = "2026-09-12T00:00:00+00:00"
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                """
                INSERT INTO book_blueprints (
                    id, project_id, idea, content_json, locks_json,
                    field_versions_json, stale_fields_json, plan_stale,
                    source_candidate_id, revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, '[]', 0, NULL, 0, ?, ?)
                """,
                (
                    blueprint_id,
                    project_id,
                    "用订单救下家庭和工厂",
                    json.dumps(blueprint_content, ensure_ascii=False),
                    json.dumps({key: False for key in blueprint_content}),
                    json.dumps({key: 1 for key in blueprint_content}),
                    timestamp,
                    timestamp,
                ),
            )
        client.app.state.plan_rebase_service.bind_current_planning(project_id)
        archive = client.get(
            f"/api/projects/{project_id}/export"
        ).json()
        dependency_rows = archive["tables"]["creative_plan_dependencies"]
        assert len(dependency_rows) == 1
        dependency_snapshot = json.loads(
            dependency_rows[0]["dependency_snapshot_json"]
        )
        assert dependency_snapshot.pop("canon_state") is None
        assert dependency_snapshot.pop("author_preference_state") is None
        dependency_rows[0]["dependency_snapshot_json"] = canonical_json(
            dependency_snapshot
        ).decode()
        dependency_rows[0]["dependency_fingerprint_sha256"] = hashlib.sha256(
            canonical_json(dependency_snapshot)
        ).hexdigest()
        for table_name in m34_tables:
            archive["tables"].pop(table_name)
        archive["format_version"] = 17
        unsigned = dict(archive)
        unsigned.pop("checksum_sha256")
        archive["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()

        restored = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )

    assert restored.status_code == 201, restored.text
    restored_project_id = restored.json()["project"]["id"]
    with sqlite3.connect(database_path) as connection:
        restored_dependency = connection.execute(
            """
            SELECT dependency_snapshot_json, dependency_fingerprint_sha256
            FROM creative_plan_dependencies WHERE project_id = ?
            """,
            (restored_project_id,),
        ).fetchone()
        assert restored_dependency is not None
        restored_snapshot = json.loads(restored_dependency[0])
        assert restored_dependency[1] == hashlib.sha256(
            canonical_json(restored_snapshot)
        ).hexdigest()
        for table_name in m34_tables:
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table_name} WHERE "
                + (
                    "preference_id IN (SELECT id FROM author_preferences WHERE project_id = ?)"
                    if table_name == "author_preference_sources"
                    else "project_id = ?"
                ),
                (restored_project_id,),
            ).fetchone()[0] == 0


def test_m34_archive_round_trip_rebinds_canon_graph_and_embedded_ids(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "m34-round-trip.db"
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        archive, old_ids = _m34_decided_archive(client)
        restored = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )

    assert restored.status_code == 201, restored.text
    restored_project_id = restored.json()["project"]["id"]
    with Database(database_path).connect() as connection:
        approval = dict(
            connection.execute(
                "SELECT * FROM chapter_approvals WHERE project_id = ?",
                (restored_project_id,),
            ).fetchone()
        )
        reconciliation = dict(
            connection.execute(
                "SELECT * FROM canon_reconciliations WHERE project_id = ?",
                (restored_project_id,),
            ).fetchone()
        )
        candidate = dict(
            connection.execute(
                """
                SELECT * FROM canon_delta_candidates
                WHERE project_id = ? AND state = 'accepted'
                """,
                (restored_project_id,),
            ).fetchone()
        )
        record = dict(
            connection.execute(
                "SELECT * FROM canon_records WHERE project_id = ?",
                (restored_project_id,),
            ).fetchone()
        )
        batch = dict(
            connection.execute(
                "SELECT * FROM canon_decision_batches WHERE project_id = ?",
                (restored_project_id,),
            ).fetchone()
        )
        replenishment = dict(
            connection.execute(
                "SELECT * FROM rolling_plan_replenishments WHERE project_id = ?",
                (restored_project_id,),
            ).fetchone()
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    assert restored_project_id != old_ids["project"]
    for table_id, row in (
        ("approval", approval),
        ("reconciliation", reconciliation),
        ("candidate", candidate),
        ("record", record),
        ("batch", batch),
        ("replenishment", replenishment),
    ):
        assert row["id"] != old_ids[table_id]
    assert approval["chapter_id"] != old_ids["chapter"]
    assert approval["chapter_version_id"] != old_ids["version"]
    assert reconciliation["approval_id"] == approval["id"]
    assert candidate["reconciliation_id"] == reconciliation["id"]
    assert candidate["accepted_record_id"] == record["id"]
    assert record["source_candidate_id"] == candidate["id"]
    evidence = json.loads(candidate["evidence_json"])
    payload = json.loads(candidate["payload_json"])
    assert evidence["approval_version_id"] == approval["chapter_version_id"]
    assert evidence["chapter_id"] == approval["chapter_id"]
    assert candidate["payload_sha256"] == hashlib.sha256(
        canonical_json(payload)
    ).hexdigest()
    assert candidate["evidence_sha256"] == hashlib.sha256(
        canonical_json(evidence)
    ).hexdigest()
    response = json.loads(batch["response_json"])
    assert response["batch_id"] == batch["id"]
    assert response["reconciliation_id"] == reconciliation["id"]
    assert response["accepted_canon_record_ids"] == [record["id"]]
    assert response["rolling_plan_replenishment_id"] is None
    assert replenishment["source_decision_batch_id"] == batch["id"]
    assert replenishment["source_chapter_id"] == approval["chapter_id"]


def test_m34_archive_round_trip_accepts_author_edited_canon_candidate(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "m34-edited-canon-round-trip.db"
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        archive, _old_ids = _m34_decided_archive(
            client,
            edit_first_candidate=True,
            simulate_legacy_analysis_hash=True,
        )
        restored = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )

    assert restored.status_code == 201, restored.text


def test_m34_archive_round_trip_rebinds_confirmed_preference_sources(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "m34-preference-round-trip.db"
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        archive, old_ids = _m34_preference_archive(client)
        restored = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )

    assert restored.status_code == 201, restored.text
    restored_project_id = restored.json()["project"]["id"]
    with Database(database_path).connect() as connection:
        preference_candidate = dict(
            connection.execute(
                """
                SELECT * FROM author_preference_candidates
                WHERE project_id = ? AND state = 'confirmed'
                """,
                (restored_project_id,),
            ).fetchone()
        )
        preference = dict(
            connection.execute(
                "SELECT * FROM author_preferences WHERE project_id = ?",
                (restored_project_id,),
            ).fetchone()
        )
        source = dict(
            connection.execute(
                """
                SELECT s.*
                FROM author_preference_sources s
                JOIN author_preferences p ON p.id = s.preference_id
                WHERE p.project_id = ?
                """,
                (restored_project_id,),
            ).fetchone()
        )
        approval = dict(
            connection.execute(
                "SELECT * FROM chapter_approvals WHERE project_id = ?",
                (restored_project_id,),
            ).fetchone()
        )
        decision = dict(
            connection.execute(
                "SELECT * FROM canon_decision_batches WHERE project_id = ?",
                (restored_project_id,),
            ).fetchone()
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    assert preference_candidate["id"] != old_ids["preference_candidate"]
    assert preference["id"] != old_ids["preference"]
    assert preference_candidate["confirmed_preference_id"] == preference["id"]
    assert preference_candidate["scope_kind"] == "project"
    assert preference_candidate["scope_value"] == restored_project_id
    assert preference["scope_value"] == restored_project_id
    assert source["preference_id"] == preference["id"]
    assert source["candidate_id"] == preference_candidate["id"]
    assert source["approval_id"] == approval["id"]
    assert source["source_writing_outcome_id"] != old_ids["outcome"]
    assert source["source_candidate_version_id"] != old_ids["candidate_version"]
    expected_fingerprint = {
        "schema_version": 1,
        "scope_kind": preference["scope_kind"],
        "scope_value": preference["scope_value"],
        "dimension": preference["dimension"],
        "compact_rule": preference["compact_rule"],
    }
    assert preference["fingerprint_sha256"] == hashlib.sha256(
        canonical_json(expected_fingerprint)
    ).hexdigest()
    response = json.loads(decision["response_json"])
    assert response["confirmed_preference_ids"] == [preference["id"]]


def test_m34_archive_restore_interrupts_pending_canon_work(tmp_path: Path) -> None:
    database_path = tmp_path / "m34-pending-restore.db"
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        archive, source = _m34_pending_archive(client)
        assert archive["tables"]["jobs"][-1]["state"] == "queued"
        assert archive["tables"]["canon_reconciliations"][0]["state"] == "pending"

        restored = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )

    assert restored.status_code == 201, restored.text
    restored_project_id = restored.json()["project"]["id"]
    with Database(database_path).connect() as connection:
        job = dict(
            connection.execute(
                """
                SELECT * FROM jobs
                WHERE project_id = ? AND workflow = 'canon_reconciliation_v1'
                """,
                (restored_project_id,),
            ).fetchone()
        )
        reconciliation = dict(
            connection.execute(
                "SELECT * FROM canon_reconciliations WHERE project_id = ?",
                (restored_project_id,),
            ).fetchone()
        )
        candidate_count = connection.execute(
            "SELECT COUNT(*) FROM canon_delta_candidates WHERE project_id = ?",
            (restored_project_id,),
        ).fetchone()[0]

    assert job["state"] == "interrupted"
    assert job["error_code"] == "restored_requires_resubmission"
    assert reconciliation["state"] == "stale"
    assert reconciliation["revision"] == source["revision"] + 1
    assert reconciliation["error_message"] == "restored_requires_resubmission"
    assert reconciliation["completed_at"] is not None
    assert candidate_count == 0


def test_m34_archive_rejects_tampered_hashes_and_project_links(tmp_path: Path) -> None:
    database_path = tmp_path / "m34-tamper.db"
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        archive, _old_ids = _m34_decided_archive(client)

        tampered_archives: list[dict[str, object]] = []
        for hash_column in ("payload_sha256", "evidence_sha256"):
            tampered = json.loads(json.dumps(archive))
            tampered["tables"]["canon_delta_candidates"][0][hash_column] = "0" * 64
            unsigned = dict(tampered)
            unsigned.pop("checksum_sha256")
            tampered["checksum_sha256"] = hashlib.sha256(
                canonical_json(unsigned)
            ).hexdigest()
            tampered_archives.append(tampered)

        wrong_project = json.loads(json.dumps(archive))
        wrong_project["tables"]["canon_delta_candidates"][0]["project_id"] = str(
            uuid4()
        )
        unsigned = dict(wrong_project)
        unsigned.pop("checksum_sha256")
        wrong_project["checksum_sha256"] = hashlib.sha256(
            canonical_json(unsigned)
        ).hexdigest()
        tampered_archives.append(wrong_project)

        responses = [
            client.post(
                "/api/project-imports",
                content=canonical_json(tampered),
                headers={"Content-Type": "application/json"},
            )
            for tampered in tampered_archives
        ]

    assert [response.status_code for response in responses] == [400, 400, 400]


def test_archive_round_trip_preserves_review_versions_and_partial_changes(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "review-archive.db"
    manuscript = "一九九八年，他掏出智能手机。院外一片寂静。"
    with TestClient(create_app(database_path)) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "审校归档",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        chapter_id = workspace["chapters"][0]["id"]
        chapter = client.patch(
            f"/api/chapters/{chapter_id}",
            json={"content": manuscript, "expected_revision": 0},
        ).json()
        reviews = client.app.state.review_repository
        excerpts = [
            ("智能手机", "传呼机", ReviewDimension.REALISM, "年代物件错置"),
            ("一片寂静", "只剩虫鸣", ReviewDimension.STYLE, "场景感官单薄"),
        ]
        findings = []
        for ordinal, (excerpt, replacement, dimension, title) in enumerate(excerpts):
            start = manuscript.index(excerpt)
            finding = make_finding(
                job_id=f"archive-review-{ordinal}",
                project_id=project_id,
                chapter_id=chapter_id,
                chapter_revision=chapter["revision"],
                dimension=dimension,
                severity=ReviewSeverity.WARNING,
                code=f"archive_{ordinal}",
                title=title,
                evidence=[
                    ReviewEvidence(
                        kind=ReviewEvidenceKind.BODY,
                        chapter_id=chapter_id,
                        start_char=start,
                        end_char=start + len(excerpt),
                        excerpt=excerpt,
                        label="正文原句",
                    )
                ],
                explanation="该处需要作者确认后局部修改。",
                suggestion="仅替换有证据的正文范围。",
                suggested_replacement=replacement,
                confidence=0.95,
            ).model_copy(update={"review_job_id": None})
            findings.append(finding)
        reviews.save_findings(findings)

        change_set = client.post(
            f"/api/chapters/{chapter_id}/text-change-sets",
            json={"finding_ids": [item.id for item in findings]},
        ).json()
        selected = change_set["changes"][0]
        applied = client.post(
            f"/api/text-change-sets/{change_set['id']}/apply",
            json={
                "selected_change_ids": [selected["id"]],
                "edited_replacements": {selected["id"]: "传呼机和公用电话"},
                "expected_set_revision": change_set["revision"],
                "expected_chapter_revision": chapter["revision"],
            },
        ).json()
        archive = client.get(f"/api/projects/{project_id}/export").json()
        restored_response = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )
        restored = restored_response.json()
        restored_chapter_id = restored["chapters"][0]["id"]
        restored_versions = client.get(f"/api/chapters/{restored_chapter_id}/versions").json()
        restored_findings = client.get(
            f"/api/chapters/{restored_chapter_id}/review-findings"
        ).json()
        restored_sets = client.get(f"/api/chapters/{restored_chapter_id}/text-change-sets").json()

    assert restored_response.status_code == 201
    assert restored["chapters"][0]["content"] == applied["content"]
    assert [item["source"] for item in restored_versions][:2] == [
        "change_set_apply",
        "manual_save",
    ]
    assert {item["state"] for item in restored_findings} == {"accepted", "open"}
    assert restored_sets[0]["state"] == "applied"
    assert [item["selected"] for item in restored_sets[0]["changes"]] == [True, False]
    assert restored_sets[0]["changes"][0]["applied_replacement"] == "传呼机和公用电话"


def test_reality_source_archive_defaults_to_card_snapshot_and_can_include_raw_asset(
    tmp_path: Path,
) -> None:
    raw_source = "一九九八年春，南平城区早市猪肉每斤六元。".encode()
    source_sha256 = hashlib.sha256(raw_source).hexdigest()
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "现实资料归档",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        imported_card = client.post(
            "/api/source-library/file-imports",
            params={
                "project_id": project_id,
                "source_filename": "南平早市.txt",
                "title": "南平早市物价",
                "source_kind": "historical_record",
                "source_reference": "作者自有走访记录",
                "applicable_year_start": 1998,
                "applicable_year_end": 1998,
                "confidence": "medium",
                "source_date": "1998-03",
                "expected_source_sha256": source_sha256,
                "confirm_preview": "true",
            },
            content=raw_source,
            headers={"Content-Type": "text/plain"},
        ).json()

        default_archive = client.get(f"/api/projects/{project_id}/export").json()
        full_archive = client.get(
            f"/api/projects/{project_id}/export?include_reference_assets=true"
        ).json()
        restored = client.post(
            "/api/project-imports",
            content=canonical_json(full_archive),
            headers={"Content-Type": "application/json"},
        ).json()
        global_documents = client.get("/api/source-library/documents").json()

    assert default_archive["tables"]["source_documents"] == []
    assert default_archive["tables"]["source_cards"][0]["source_document_id"] is None
    assert default_archive["tables"]["source_cards"][0]["excerpt"] == raw_source.decode()
    assert full_archive["tables"]["source_documents"][0]["content"] == raw_source.decode()
    assert (
        full_archive["tables"]["source_cards"][0]["source_document_id"]
        == imported_card["source_document_id"]
    )
    assert restored["source_cards"][0]["source_document_id"] != imported_card["source_document_id"]
    assert restored["source_cards"][0]["source_date"] == "1998-03"
    assert len(global_documents) == 2


def test_export_returns_not_found_without_leaking_details(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        response = client.get("/api/projects/05f14cb8-d0ed-4489-bc20-31c44c1efbba/export")

    assert response.status_code == 404
    assert response.json() == {"detail": "项目不存在"}


def test_import_upgrades_v1_project_owned_reference_archive(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "旧归档迁移",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        client.post(
            f"/api/projects/{project_id}/reference-works",
            json={
                "title": "旧版参考",
                "source_filename": "legacy.txt",
                "rights_basis": "self_owned",
                "content": "旧版原文",
                "segment_target_characters": 500_000,
            },
        )
        archive = client.get(
            f"/api/projects/{project_id}/export?include_reference_assets=true"
        ).json()
        archive["format_version"] = 1
        archive["tables"]["reference_works"] = [
            {
                key: value
                for key, value in work.items()
                if key
                not in {
                    "content_sha256",
                    "source_sha256",
                    "source_encoding",
                    "encoding_confidence",
                    "import_state",
                    "source_spans_json",
                    "duplicate_of_id",
                    "updated_at",
                }
            }
            | {"project_id": project_id}
            for work in archive["tables"]["reference_works"]
        ]
        unsigned = dict(archive)
        unsigned.pop("checksum_sha256")
        archive["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()

        restored = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )

    assert restored.status_code == 201
    assert restored.json()["reference_works"][0]["title"] == "旧版参考"
    assert restored.json()["reference_works"][0]["segments"][0]["character_count"] == 4


def test_import_restores_complete_project_as_new_copy(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        original = client.post(
            "/api/projects",
            json={
                "title": "回到九八年的南平",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = original["project"]["id"]
        chapter_id = original["chapters"][0]["id"]
        client.patch(
            f"/api/chapters/{chapter_id}",
            json={"content": "原稿不可被覆盖。", "expected_revision": 0},
        )
        source_entity = client.post(
            f"/api/projects/{project_id}/story-entities",
            json={
                "kind": "character",
                "name": "林川",
                "role": "主角",
                "goal": "改变家庭命运",
                "current_state": "刚回到一九九八年",
                "relationship_notes": "",
            },
        ).json()
        client.put(
            f"/api/chapters/{chapter_id}/context-directives",
            json={
                "source_kind": "entity",
                "source_id": source_entity["id"],
                "action": "pin",
                "expected_revision": None,
            },
        )
        imported_reference = client.post(
            f"/api/projects/{project_id}/reference-works",
            json={
                "title": "第一份自有素材",
                "source_filename": "owned.txt",
                "rights_basis": "self_owned",
                "content": "第一章\n来自旧时代的潮声。",
                "segment_target_characters": 500_000,
            },
        ).json()
        source_segment_id = imported_reference["segments"][0]["id"]
        jobs: JobRepository = client.app.state.job_repository
        source_job, _ = jobs.create_job(
            project_id=project_id,
            kind=JobKind.REVIEW,
            idempotency_key="pattern-source-job",
            input_payload={"selected_segment_ids": [source_segment_id]},
            provider="openai",
            model="gpt-5.6",
        )
        archive = client.get(
            f"/api/projects/{project_id}/export?include_reference_assets=true"
        ).json()
        pattern_card_id = str(uuid4())
        dimension = {
            "summary": "现实秩序发生松动",
            "source_segment_ids": [source_segment_id],
            "transferable_logic": "先给主角一个可验证的小窗口",
            "adaptation_risk": "必须重组人物和场景",
        }
        archive["tables"]["reference_pattern_cards"].append(
            {
                "id": pattern_card_id,
                "project_id": project_id,
                "selected_segment_ids_json": json.dumps([source_segment_id]),
                "author_focus": "验证模式卡引用重映射",
                "proposal_json": json.dumps(
                    {
                        "era": dimension,
                        "core_desire": dimension,
                        "conflict_causality": dimension,
                        "resource_system": dimension,
                        "key_scene_sequence": dimension,
                        "ending": dimension,
                        "shared_patterns": ["先验证信息差"],
                        "differences": ["人物关系不同"],
                        "relationship_recomposition": "将原关系重组为师徒竞争",
                        "originality_risks": [],
                    },
                    ensure_ascii=False,
                ),
                "provider": "openai",
                "model": "gpt-5.6",
                "source_job_id": source_job.id,
                "created_at": archive["exported_at"],
            }
        )
        application_id = str(uuid4())
        blueprint = {
            "dimensions": {
                "era": {
                    "source": dimension,
                    "mode": "preserve",
                    "author_edits": "只保留抽象因果",
                    "generated_variant": {
                        "summary": "现实秩序发生松动",
                        "transferable_logic": "先给主角一个可验证的小窗口",
                    },
                    "version": 1,
                    "locked": False,
                    "named_entities": [],
                    "source_beats": [],
                    "key_beats": [],
                }
            },
            "relationship": {
                "source": "将原关系重组为师徒竞争",
                "mode": "preserve",
                "author_edits": "只保留抽象因果",
                "generated_variant": "将原关系重组为师徒竞争",
                "version": 1,
                "locked": False,
                "relationships": [],
            },
        }
        blueprint_json = json.dumps(blueprint, ensure_ascii=False)
        archive["tables"]["reference_pattern_applications"].append(
            {
                "id": application_id,
                "project_id": project_id,
                "pattern_card_id": pattern_card_id,
                "lifecycle_state": "active",
                "lifecycle_revision": 0,
                "selected_dimensions_json": json.dumps(["era"]),
                "dimensions_json": json.dumps(
                    {
                        "era": {
                            "summary": "现实秩序发生松动",
                            "transferable_logic": "先给主角一个可验证的小窗口",
                        }
                    },
                    ensure_ascii=False,
                ),
                "relationship_recomposition": "将原关系重组为师徒竞争",
                "application_note": "只保留抽象因果",
                "blueprint_json": blueprint_json,
                "originality_status": "needs_check",
                "risk_level": None,
                "latest_report_id": None,
                "threshold_version": None,
                "revision": 0,
                "created_at": archive["exported_at"],
                "updated_at": archive["exported_at"],
            }
        )
        archive["tables"]["reference_blueprint_versions"].append(
            {
                "id": str(uuid4()),
                "application_id": application_id,
                "blueprint_revision": 0,
                "blueprint_json": blueprint_json,
                "changed_dimensions_json": json.dumps(["era"]),
                "relationship_changed": 1,
                "created_at": archive["exported_at"],
            }
        )
        unsigned = dict(archive)
        unsigned.pop("checksum_sha256")
        archive["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()

        restored_response = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )

        original_after = client.get(f"/api/projects/{project_id}").json()
        projects = client.get("/api/projects").json()
        restored_jobs = client.get(
            f"/api/projects/{restored_response.json()['project']['id']}/jobs"
        ).json()
        restored_directives = client.get(
            f"/api/chapters/{restored_response.json()['chapters'][0]['id']}/context-directives"
        ).json()

    assert restored_response.status_code == 201
    restored = restored_response.json()
    assert restored["project"]["id"] != project_id
    assert restored["project"]["title"] == "回到九八年的南平（恢复副本）"
    assert restored["chapters"][0]["id"] != chapter_id
    assert restored["chapters"][0]["project_id"] == restored["project"]["id"]
    assert restored["chapters"][0]["content"] == "原稿不可被覆盖。"
    assert restored["reference_works"][0]["id"] != imported_reference["id"]
    assert (
        restored["reference_works"][0]["segments"][0]["id"]
        != imported_reference["segments"][0]["id"]
    )
    restored_segment_id = restored["reference_works"][0]["segments"][0]["id"]
    restored_card = restored["reference_pattern_cards"][0]
    assert restored_card["id"] != pattern_card_id
    assert restored_card["selected_segment_ids"] == [restored_segment_id]
    assert restored_card["era"]["source_segment_ids"] == [restored_segment_id]
    assert restored_card["source_job_id"] == restored_jobs[0]["id"]
    assert restored_card["source_job_id"] != source_job.id
    assert restored["reference_pattern_applications"][0]["pattern_card_id"] == restored_card["id"]
    assert restored_directives[0]["source_id"] == restored["story_entities"][0]["id"]
    assert restored_directives[0]["source_id"] != source_entity["id"]
    assert original_after["project"]["title"] == "回到九八年的南平"
    assert original_after["chapters"][0]["id"] == chapter_id
    assert len(projects) == 2


def test_archive_round_trip_preserves_job_history_and_immutable_artifacts(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "可恢复任务归档",
                "genre": "historical_rebirth",
                "rebirth_year": 1984,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        jobs: JobRepository = client.app.state.job_repository
        job, _ = jobs.create_job(
            project_id=project_id,
            kind=JobKind.REFERENCE_FUSION,
            idempotency_key="archive-fusion",
            input_payload={"selected_segment_ids": ["a", "b"]},
            provider="openai",
            model="test-model",
        )
        artifact, _ = jobs.put_artifact(
            job.id,
            kind="reference_map",
            artifact_key="map-a-0",
            payload='{"era":"旧城改造"}',
            content_type="application/json",
            provider="openai",
            model="test-model",
        )
        archive = client.get(f"/api/projects/{project_id}/export").json()

        legacy_v3 = json.loads(json.dumps(archive))
        legacy_v3["format_version"] = 3
        for table_name in ("book_blueprints", "volume_plans", "rolling_chapter_plans"):
            legacy_v3["tables"].pop(table_name)
        for legacy_job in legacy_v3["tables"]["jobs"]:
            legacy_job.pop("workflow")
        legacy_unsigned = dict(legacy_v3)
        legacy_unsigned.pop("checksum_sha256")
        legacy_v3["checksum_sha256"] = hashlib.sha256(canonical_json(legacy_unsigned)).hexdigest()
        legacy_restored = client.post(
            "/api/project-imports",
            content=canonical_json(legacy_v3),
            headers={"Content-Type": "application/json"},
        )

        restored = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        ).json()
        restored_project_id = restored["project"]["id"]
        restored_jobs = client.get(f"/api/projects/{restored_project_id}/jobs").json()
        restored_detail = client.get(f"/api/jobs/{restored_jobs[0]['id']}").json()
        restored_artifact = client.get(
            f"/api/job-artifacts/{restored_detail['artifacts'][0]['id']}"
        ).json()

    assert legacy_restored.status_code == 201
    assert restored_jobs[0]["id"] != job.id
    assert restored_jobs[0]["project_id"] == restored_project_id
    assert restored_jobs[0]["workflow"] == ""
    assert restored_detail["artifacts"][0]["id"] != artifact.id
    assert restored_artifact["payload"] == '{"era":"旧城改造"}'


def test_import_rejects_tampered_or_unknown_archive_without_writing(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        original = client.post(
            "/api/projects",
            json={
                "title": "南平旧厂",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "南平",
            },
        ).json()
        archive = client.get(f"/api/projects/{original['project']['id']}/export").json()
        archive["tables"]["projects"][0]["title"] = "被篡改的标题"

        tampered = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )

        archive = client.get(f"/api/projects/{original['project']['id']}/export").json()
        archive["tables"]["unknown_table"] = []
        archive_without_checksum = dict(archive)
        archive_without_checksum.pop("checksum_sha256")
        archive["checksum_sha256"] = hashlib.sha256(
            canonical_json(archive_without_checksum)
        ).hexdigest()
        unknown = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )
        projects = client.get("/api/projects").json()

    assert tampered.status_code == 400
    assert tampered.json() == {"detail": "项目归档无效或已损坏"}
    assert unknown.status_code == 400
    assert unknown.json() == {"detail": "项目归档无效或已损坏"}
    assert len(projects) == 1


def test_import_rejects_semantically_invalid_archive_without_orphan_copy(
    tmp_path: Path,
) -> None:
    application = create_app(tmp_path / "mozhou.db")
    with TestClient(application, raise_server_exceptions=False) as client:
        original = client.post(
            "/api/projects",
            json={
                "title": "语义校验底稿",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "南平",
            },
        ).json()
        archive = client.get(f"/api/projects/{original['project']['id']}/export").json()
        archive["tables"]["projects"][0]["genre"] = "unknown_genre"
        unsigned = dict(archive)
        unsigned.pop("checksum_sha256")
        archive["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()

        response = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )
        projects = client.get("/api/projects").json()

    assert response.status_code == 400
    assert response.json() == {"detail": "项目归档无效或已损坏"}
    assert [project["id"] for project in projects] == [original["project"]["id"]]


def test_import_requires_json_content_type(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        response = client.post(
            "/api/project-imports",
            content=b"not an archive",
            headers={"Content-Type": "text/plain"},
        )

    assert response.status_code == 415
    assert response.json() == {"detail": "请选择墨舟项目归档文件"}


def test_import_upgrades_v13_archive_with_empty_writing_pattern_tables(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(tmp_path / "v13-archive.db")) as client:
        original = client.post(
            "/api/projects",
            json={
                "title": "旧归档写作模式兼容",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "南平",
            },
        ).json()
        archive = client.get(
            f"/api/projects/{original['project']['id']}/export"
        ).json()
        for table in (
            "writing_pattern_recipes",
            "writing_pattern_recipe_versions",
            "writing_pattern_recipe_sources",
            "writing_pattern_profile_versions",
            "project_writing_pattern_profiles",
        ):
            archive["tables"].pop(table)
        archive["format_version"] = 13
        unsigned = dict(archive)
        unsigned.pop("checksum_sha256")
        archive["checksum_sha256"] = hashlib.sha256(
            canonical_json(unsigned)
        ).hexdigest()

        restored = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )

    assert restored.status_code == 201, restored.text


def test_creates_lists_and_restores_compressed_recovery_point(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        original = client.post(
            "/api/projects",
            json={
                "title": "闽江潮生",
                "genre": "historical_rebirth",
                "rebirth_year": 1127,
                "rebirth_location": "福建路",
            },
        ).json()
        project_id = original["project"]["id"]
        chapter_id = original["chapters"][0]["id"]
        client.patch(
            f"/api/chapters/{chapter_id}",
            json={"content": "这是大改前必须保留的正文。" * 50, "expected_revision": 0},
        )

        created = client.post(
            f"/api/projects/{project_id}/recovery-points",
            json={"label": "第二卷大改前"},
        )
        listed = client.get(f"/api/projects/{project_id}/recovery-points")
        recovery_id = created.json()["id"]
        restored = client.post(f"/api/recovery-points/{recovery_id}/restore")

    assert created.status_code == 201
    assert created.json()["project_id"] == project_id
    assert created.json()["label"] == "第二卷大改前"
    assert created.json()["kind"] == "manual"
    assert created.json()["uncompressed_bytes"] > created.json()["compressed_bytes"]
    assert len(created.json()["archive_sha256"]) == 64
    assert listed.status_code == 200
    assert listed.json() == [created.json()]
    assert "payload_zlib" not in listed.json()[0]
    assert restored.status_code == 201
    assert restored.json()["project"]["id"] != project_id
    assert restored.json()["project"]["title"] == "闽江潮生（恢复副本）"
    assert restored.json()["chapters"][0]["content"] == "这是大改前必须保留的正文。" * 50


def test_recovery_point_project_and_id_return_sanitized_not_found(tmp_path: Path) -> None:
    missing_id = "05f14cb8-d0ed-4489-bc20-31c44c1efbba"
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        create_response = client.post(
            f"/api/projects/{missing_id}/recovery-points",
            json={"label": "不存在"},
        )
        restore_response = client.post(f"/api/recovery-points/{missing_id}/restore")

    assert create_response.status_code == 404
    assert create_response.json() == {"detail": "项目不存在"}
    assert restore_response.status_code == 404
    assert restore_response.json() == {"detail": "恢复点不存在"}
