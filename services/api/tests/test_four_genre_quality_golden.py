from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any
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
    ContextItemKind,
    ContextPacket,
    ContextRepository,
    CreativeContextCompileRequest,
    CreativeContextPurpose,
    CreativeContextService,
    CreativeContextSubject,
    CreativeContextSubjectKind,
)
from app.database import Database
from app.director.repository import DirectorRepository
from app.main import create_app
from app.models import (
    AppliedReferenceDimension,
    BlueprintDimensionState,
    BlueprintMode,
    BlueprintRelationshipState,
    BookBlueprintContent,
    CraftPatternDimension,
    DirectorStartupCandidate,
    Genre,
    OriginalityRiskLevel,
    ReferenceBlueprintState,
    ReferenceDimensionSynthesis,
    ReferencePatternDimension,
    SceneOriginalityAssessment,
)
from app.reference_lab import ReferenceAnalysisInput
from app.scene_originality import assess_scene_plot_graph
from app.writing_patterns.models import (
    ModelSafeWritingPatternProfile,
    ModelSafeWritingPatternRule,
    WritingPatternLifecycleState,
    WritingPatternProfileVersion,
    WritingPatternPurpose,
    WritingPatternSafetyBasis,
    WritingPatternStage,
    WritingPatternStrategy,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "four_genre_quality.json"
FIXTURE: dict[str, Any] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
CASES: list[dict[str, Any]] = FIXTURE["cases"]
NOW = "2026-09-12T00:00:00+00:00"


class _FixedPatternReader:
    def __init__(self, profile: WritingPatternProfileVersion) -> None:
        self.profile = profile

    def get_active_profile(self, project_id: str) -> WritingPatternProfileVersion:
        assert project_id == self.profile.project_id
        return self.profile


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _book_blueprint(case: dict[str, Any]) -> BookBlueprintContent:
    return BookBlueprintContent(
        title=case["title"],
        genre=Genre(case["genre"]),
        rebirth_year=case["story_year"],
        rebirth_location=case["story_location"],
        **case["blueprint"],
    )


def _scene_assessment(case: dict[str, Any]) -> SceneOriginalityAssessment:
    segment_ids = [f"segment-{case['id']}-a", f"segment-{case['id']}-b"]
    source_beats = list(FIXTURE["source_beats"])
    candidate_beats = list(case["outline"]["scene_beats"])
    blueprint = ReferenceBlueprintState(
        dimensions={
            ReferencePatternDimension.KEY_SCENE_SEQUENCE: BlueprintDimensionState(
                source=ReferenceDimensionSynthesis(
                    summary="两本作品的抽象连载节奏",
                    source_segment_ids=segment_ids,
                    transferable_logic="期限、验证、兑现、新代价",
                    adaptation_risk="不保留人物、场景和独特顺序",
                ),
                mode=BlueprintMode.RECONSTRUCT,
                author_edits="按当前题材重组具体冲突",
                generated_variant=AppliedReferenceDimension(
                    summary="用新世界规则承载连载节奏",
                    transferable_logic=case["abstract_rule"],
                ),
                source_beats=source_beats,
                key_beats=candidate_beats,
            )
        },
        relationship=BlueprintRelationshipState(
            source="来源人物功能组合必须重构",
            mode=BlueprintMode.RECONSTRUCT,
            author_edits="改变权力方向与利益依赖",
            generated_variant=case["blueprint"]["relationship_design"],
        ),
    )
    marker = str(FIXTURE["raw_reference_marker"])
    sources = [
        ReferenceAnalysisInput(
            work_id=f"work-{case['id']}-{suffix}",
            work_title=f"参考作品-{suffix}",
            segment_id=segment_id,
            ordinal=ordinal,
            start_char=ordinal * 1_000,
            end_char=ordinal * 1_000 + len(marker) + 2,
            chapter_start="第一章",
            chapter_end="第十章",
            content=f"{marker}-{suffix}",
        )
        for ordinal, (suffix, segment_id) in enumerate(zip(("A", "B"), segment_ids, strict=True))
    ]
    return assess_scene_plot_graph(blueprint, sources)


def _trace(packet: ContextPacket, purpose: CreativeContextPurpose) -> ModelTrace:
    return ModelTrace(
        purpose=purpose,
        context_packet_id=packet.id,
        context_packet_sha256=packet.packet_sha256,
        context_dependency_fingerprint_sha256=packet.dependency_fingerprint_sha256,
        context_compiler_version=packet.compiler_version,
        profile_fingerprint_sha256=packet.profile_fingerprint_sha256,
        provider="local",
        model="four-genre-golden",
        prompt_version="four-genre-golden-v1",
    )


def _profile(
    database: Database,
    project_id: str,
    case: dict[str, Any],
) -> WritingPatternProfileVersion:
    with database.connect() as connection:
        topic = connection.execute(
            """
            SELECT v.id, v.revision, v.content_sha256
            FROM topic_decisions d
            JOIN topic_decision_versions v
              ON v.topic_decision_id = d.id AND v.revision = d.confirmed_revision
            WHERE d.project_id = ?
            """,
            (project_id,),
        ).fetchone()
    assert topic is not None
    recipe_sha = _digest(f"recipe:{case['id']}")
    rules = [
        ModelSafeWritingPatternRule(
            source_content_sha256=_digest(f"work:{case['id']}:{ordinal}"),
            dimension=dimension,
            name=name,
            transferable_rule=rule,
            adaptation_risk=case["adaptation_risk"],
            purpose=WritingPatternPurpose.LEARN,
            strategy=WritingPatternStrategy.TRANSFORM,
            weight_basis_points=5_000,
            applicable_stages=[
                WritingPatternStage.CHAPTER_BRIEF,
                WritingPatternStage.CHAPTER_DRAFT,
                WritingPatternStage.REVIEW,
            ],
        )
        for ordinal, (dimension, name, rule) in enumerate(
            (
                (
                    CraftPatternDimension.HOOK_MECHANICS,
                    "期限与验证",
                    case["abstract_rule"],
                ),
                (
                    CraftPatternDimension.PROMISE_PAYOFF_CADENCE,
                    "状态兑现",
                    "每章至少完成一次可核验的资源、关系或能力变化。",
                ),
            ),
            start=1,
        )
    ]
    safe_profile = ModelSafeWritingPatternProfile(
        compiler_version="four-genre-golden-v1",
        topic_revision=int(topic["revision"]),
        topic_content_sha256=str(topic["content_sha256"]),
        recipe_content_sha256=recipe_sha,
        safety_basis=WritingPatternSafetyBasis.SOURCE_VERIFIED,
        rules=rules,
    )
    return WritingPatternProfileVersion(
        id=str(uuid4()),
        project_id=project_id,
        recipe_version_id=str(uuid4()),
        recipe_content_sha256=recipe_sha,
        topic_decision_version_id=str(topic["id"]),
        topic_revision=int(topic["revision"]),
        topic_content_sha256=str(topic["content_sha256"]),
        compiler_version=safe_profile.compiler_version,
        safety_basis=WritingPatternSafetyBasis.SOURCE_VERIFIED,
        source_snapshot_sha256=_digest(f"sources:{case['id']}"),
        model_safe_profile=safe_profile,
        conflicts=[],
        decisions=[],
        excluded_entry_keys=[],
        profile_fingerprint_sha256=_digest(f"profile:{case['id']}"),
        lifecycle_state=WritingPatternLifecycleState.ACTIVE,
        lifecycle_revision=0,
        is_current=True,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: str(case["id"]))
def test_four_genre_author_led_ai_writing_golden_journey(
    tmp_path: Path,
    case: dict[str, Any],
) -> None:
    """No-fee golden: topic -> safe pattern -> AI candidate -> author Canon -> next."""

    database_path = tmp_path / f"{case['id']}.db"
    database = Database(database_path)
    app = create_app(database_path, defer_job_runtime=True)
    with TestClient(app) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": case["title"],
                "genre": case["genre"],
                "rebirth_year": case["story_year"],
                "rebirth_location": case["story_location"],
                "template_id": case["template_id"],
                "topic_seed": case["topic_seed"],
            },
        ).json()
        project_id = str(workspace["project"]["id"])
        chapter = workspace["chapters"][0]
        topic = workspace["topic_decision"]
        confirmed = client.post(
            f"/api/projects/{project_id}/topic-decision/confirm",
            json={"expected_revision": topic["revision"]},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "confirmed"

        scene_assessment = _scene_assessment(case)
        assert scene_assessment.risk_level == OriginalityRiskLevel.LOW
        assert scene_assessment.source_work_count == 2
        assert scene_assessment.source_segment_ids == [
            f"segment-{case['id']}-a",
            f"segment-{case['id']}-b",
        ]
        assert FIXTURE["raw_reference_marker"] not in scene_assessment.model_dump_json()

        DirectorRepository(database).select_startup_candidate(
            project_id,
            case["topic_seed"],
            DirectorStartupCandidate(
                id=str(uuid4()),
                ordinal=1,
                label="作者选中的原创迁移方案",
                blueprint=_book_blueprint(case),
                why_distinct="只借鉴抽象功能，具体世界、人物和因果已重组。",
                risks=[case["adaptation_risk"]],
            ),
            expected_blueprint_revision=None,
        )
        profile = _profile(database, project_id, case)
        context_service = CreativeContextService(
            app.state.repository,
            ContextRepository(database),
            patterns=_FixedPatternReader(profile),
        )
        current_workspace = app.state.repository.get_workspace(project_id)
        subject = CreativeContextSubject(
            kind=CreativeContextSubjectKind.CHAPTER,
            id=str(chapter["id"]),
            revision=int(chapter["revision"]),
        )
        brief_packet = context_service.compile(
            current_workspace,
            CreativeContextCompileRequest(
                purpose=CreativeContextPurpose.BRIEF,
                subject=subject,
                author_intent=str(case["outline"]["reader_promise"]),
            ),
        )
        draft_packet = context_service.compile(
            current_workspace,
            CreativeContextCompileRequest(
                purpose=CreativeContextPurpose.DRAFT,
                subject=subject,
                author_intent=str(case["outline"]["reader_promise"]),
            ),
        )
        for packet in (brief_packet, draft_packet):
            assert packet.profile_fingerprint_sha256 == profile.profile_fingerprint_sha256
            assert case["abstract_rule"] in packet.rendered_context
            assert FIXTURE["raw_reference_marker"] not in packet.rendered_context
            assert all(FIXTURE["raw_reference_marker"] not in item.content for item in packet.items)

        productions = app.state.chapter_production_repository
        production = productions.create_production(
            project_id=project_id,
            chapter_id=str(chapter["id"]),
            expected_chapter_revision=int(chapter["revision"]),
            expected_chapter_content_sha256=_digest(str(chapter["content"])),
        )
        outline_value = ChapterOutline.model_validate(case["outline"])
        outline = productions.add_outline_candidate(
            production_id=production.id,
            outline=outline_value,
            label="AI 章纲候选",
            trace=_trace(brief_packet, CreativeContextPurpose.BRIEF),
        )
        productions.record_preflight(
            production_id=production.id,
            outline_candidate_id=outline.id,
            expected_outline_revision=outline.current_version.revision,
            expected_outline_content_sha256=outline.current_version.content_sha256,
            checks={
                field: True
                for field in (
                    "reader_promise",
                    "opening_hook",
                    "state_change",
                    "emotional_payoff",
                    "ending_cliffhanger",
                )
            },
            missing_fields=[],
        )
        candidate = productions.create_draft_candidate(
            production_id=production.id,
            outline_candidate_id=outline.id,
            expected_outline_revision=outline.current_version.revision,
            expected_outline_content_sha256=outline.current_version.content_sha256,
            content=str(case["ai_body"]),
            label="AI 正文候选",
            trace=_trace(draft_packet, CreativeContextPurpose.DRAFT),
        )
        assert client.get(f"/api/chapters/{chapter['id']}").json()["content"] == ""

        outcome = productions.adopt_candidate(
            production_id=production.id,
            candidate_id=candidate.id,
            request=AdoptCandidateRequest(
                expected_candidate_revision=candidate.current_version.revision,
                expected_candidate_content_sha256=candidate.current_version.content_sha256,
                expected_chapter_revision=int(chapter["revision"]),
                expected_chapter_content_sha256=_digest(str(chapter["content"])),
                mode=AdoptionMode.WHOLE,
                idempotency_key=f"golden-adopt-{case['id']}",
            ),
        )
        adopted = client.get(f"/api/chapters/{chapter['id']}").json()
        assert adopted["content"] == case["ai_body"]
        adjusted = client.patch(
            f"/api/chapters/{chapter['id']}",
            json={
                "content": case["final_body"],
                "expected_revision": outcome.final_chapter_revision,
            },
        ).json()
        adjusted = client.patch(
            f"/api/chapters/{chapter['id']}/brief",
            json={**case["outline"], "expected_revision": adjusted["revision"]},
        ).json()
        reviewing = client.post(
            f"/api/chapters/{chapter['id']}/transition",
            json={"target_status": "reviewing", "expected_revision": adjusted["revision"]},
        ).json()
        approved = client.post(
            f"/api/chapters/{chapter['id']}/transition",
            json={
                "target_status": "approved",
                "expected_revision": reviewing["revision"],
                "expected_content_sha256": _digest(str(case["final_body"])),
                "source_writing_outcome_id": outcome.id,
            },
        )
        assert approved.status_code == 200, approved.text

        pending_summary = client.get(f"/api/projects/{project_id}/summary").json()
        assert pending_summary["author_next_action"]["kind"] == ("review_canon_reconciliation")
        assert pending_summary["author_next_action"]["blocked"] is True
        assert app.state.job_runtime.run_once() is True

        snapshot_url = (
            f"/api/projects/{project_id}/chapters/{chapter['id']}/canon-reconciliation/latest"
        )
        snapshot = client.get(snapshot_url).json()
        assert snapshot["reconciliation"]["state"] == "ready"
        assert set(case["expected_canon_kinds"]) <= {
            item["kind"] for item in snapshot["canon_candidates"]
        }
        assert snapshot["preference_candidates"]
        for item in snapshot["canon_candidates"]:
            evidence = item["evidence"]
            assert (
                case["final_body"][evidence["start_char"] : evidence["end_char"]]
                == (evidence["excerpt"])
            )
        with database.connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM canon_records").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM author_preferences").fetchone()[0] == 0

        decided = client.post(
            f"/api/projects/{project_id}/canon-reconciliations/"
            f"{snapshot['reconciliation']['id']}/decisions",
            json={
                "reconciliation_id": snapshot["reconciliation"]["id"],
                "expected_reconciliation_revision": snapshot["reconciliation"]["revision"],
                "idempotency_key": f"golden-canon-{case['id']}",
                "canon_decisions": [
                    {
                        "candidate_id": item["id"],
                        "expected_revision": item["revision"],
                        "action": "accept",
                    }
                    for item in snapshot["canon_candidates"]
                ],
                "preference_decisions": [
                    {
                        "candidate_id": item["id"],
                        "expected_revision": item["revision"],
                        "action": "accept",
                    }
                    for item in snapshot["preference_candidates"]
                ],
            },
        )
        assert decided.status_code == 200, decided.text

        next_chapter = client.post(
            f"/api/projects/{project_id}/chapters",
            json={"expected_last_chapter_number": 1, "title": "第二章 代价发酵"},
        )
        assert next_chapter.status_code == 201, next_chapter.text
        next_value = next_chapter.json()
        resumed = client.get(f"/api/projects/{project_id}/summary").json()
        assert resumed["author_next_action"]["kind"] == "plan_chapter"
        assert resumed["author_next_action"]["chapter_id"] == next_value["id"]

        next_packet = context_service.compile(
            app.state.repository.get_workspace(project_id),
            CreativeContextCompileRequest(
                purpose=CreativeContextPurpose.DRAFT,
                subject=CreativeContextSubject(
                    kind=CreativeContextSubjectKind.CHAPTER,
                    id=next_value["id"],
                    revision=next_value["revision"],
                ),
                author_intent="按作者已确认的事实与调整偏好规划下一章",
            ),
        )
        included_kinds = {item.kind for item in next_packet.items if item.included}
        assert ContextItemKind.CANON_RECORD in included_kinds
        assert ContextItemKind.AUTHOR_PREFERENCE in included_kinds
        assert case["ai_body"] not in next_packet.rendered_context
        assert FIXTURE["raw_reference_marker"] not in next_packet.rendered_context
