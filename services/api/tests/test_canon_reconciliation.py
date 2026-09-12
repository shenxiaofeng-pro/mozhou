from hashlib import sha256
from pathlib import Path
from sqlite3 import IntegrityError

import pytest

from app.canon_reconciliation.models import (
    AdoptRollingPlanReplenishmentRequest,
    CandidateDecisionAction,
    CanonCandidateDecision,
    CanonConflict,
    CanonConflictKind,
    CanonDecisionBatchRequest,
    CanonDeltaCandidateDraft,
    CanonEvidence,
    CanonKind,
    CanonReconciliationState,
    CharacterStatePayload,
    ReconciliationAnalysis,
    RollingPlanReplenishmentDraft,
    RollingPlanReplenishmentState,
)
from app.canon_reconciliation.repository import (
    CanonDecisionIdempotencyError,
    CanonReconciliationNotFoundError,
    CanonReconciliationRepository,
    CanonReconciliationStaleError,
    canonical_json,
    canonical_sha256,
    text_sha256,
)
from app.database import Database
from app.models import (
    ChapterStatus,
    CreateChapterRequest,
    CreateProjectRequest,
    DirectorSceneBeat,
    Genre,
    RollingChapterPlanContent,
    TransitionChapterRequest,
    UpdateChapterBriefRequest,
    UpdateChapterRequest,
    VolumePlanContent,
)
from app.repository import ProjectRepository


def _reviewing_chapter(
    path: Path,
    *,
    body: str = "沈砚🀄在雨夜突破筑基，终于改变了自己的命运。",
) -> tuple[Database, ProjectRepository, str, str, int]:
    database = Database(path)
    database.initialize()
    projects = ProjectRepository(database)
    workspace = projects.create_project(
        CreateProjectRequest(
            title="归来仍是剑修",
            genre=Genre.EASTERN_FANTASY,
            rebirth_year=2026,
            rebirth_location="南平",
        )
    )
    chapter = workspace.chapters[0]
    chapter = projects.update_chapter(
        chapter.id,
        UpdateChapterRequest(content=body, expected_revision=chapter.revision),
    )
    chapter = projects.update_chapter_brief(
        chapter.id,
        UpdateChapterBriefRequest(
            title="雨夜筑基",
            reader_promise="突破后的第一次选择",
            opening_hook="沉寂多年的剑突然鸣响",
            state_change="沈砚突破筑基",
            emotional_payoff="他终于能保护家人",
            ending_cliffhanger="白塔主人在门外等他",
            expected_revision=chapter.revision,
        ),
    )
    chapter = projects.transition_chapter(
        chapter.id,
        TransitionChapterRequest(
            target_status=ChapterStatus.DRAFTED,
            expected_revision=chapter.revision,
        ),
    )
    chapter = projects.transition_chapter(
        chapter.id,
        TransitionChapterRequest(
            target_status=ChapterStatus.REVIEWING,
            expected_revision=chapter.revision,
        ),
    )
    return database, projects, workspace.project.id, chapter.id, chapter.revision


def _candidate(
    *,
    version_id: str,
    chapter_id: str,
    chapter_revision: int,
    body: str,
    excerpt: str,
    subject_key: str = "沈砚",
) -> CanonDeltaCandidateDraft:
    start = body.index(excerpt)
    return CanonDeltaCandidateDraft(
        kind=CanonKind.CHARACTER_STATE,
        subject_key=subject_key,
        summary="沈砚的境界在本章发生变化",
        payload=CharacterStatePayload(
            character_name="沈砚",
            state="筑基初期",
            change="雨夜突破",
        ),
        evidence=CanonEvidence(
            approval_version_id=version_id,
            chapter_id=chapter_id,
            chapter_revision=chapter_revision,
            chapter_content_sha256=text_sha256(body),
            start_char=start,
            end_char=start + len(excerpt),
            excerpt=excerpt,
            excerpt_sha256=text_sha256(excerpt),
        ),
    )


def test_legacy_canon_conflict_serialization_does_not_change_archive_hash_shape() -> None:
    legacy = {
        "kind": "supersedes",
        "summary": "旧归档只记录了冲突对象",
        "existing_record_id": "legacy-record-id",
    }

    conflict = CanonConflict.model_validate(legacy)

    assert conflict.existing_record_revision is None
    assert conflict.existing_record_payload_sha256 is None
    assert conflict.model_dump(mode="json") == legacy


def test_approval_and_local_job_are_one_transaction(tmp_path: Path) -> None:
    body = "沈砚🀄在雨夜突破筑基。"
    database, projects, project_id, chapter_id, revision = _reviewing_chapter(
        tmp_path / "atomic-approval.db",
        body=body,
    )
    reconciliations = CanonReconciliationRepository(database)
    with database.connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER abort_canon_reconciliation
            BEFORE INSERT ON canon_reconciliations
            BEGIN SELECT RAISE(ABORT, 'injected failure'); END
            """
        )

    with pytest.raises(IntegrityError, match="injected failure"):
        reconciliations.approve_chapter_and_enqueue(
            project_id=project_id,
            chapter_id=chapter_id,
            expected_revision=revision,
            expected_content_sha256=text_sha256(body),
        )

    assert projects.get_chapter(chapter_id).status == ChapterStatus.REVIEWING
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM chapter_approvals").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM chapter_versions WHERE source = 'approval'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE workflow = 'canon_reconciliation_v1'"
            ).fetchone()[0]
            == 0
        )
        connection.execute("DROP TRIGGER abort_canon_reconciliation")

    result = reconciliations.approve_chapter_and_enqueue(
        project_id=project_id,
        chapter_id=chapter_id,
        expected_revision=revision,
        expected_content_sha256=text_sha256(body),
    )

    assert result.chapter_status == "approved"
    assert result.chapter_revision == revision + 1
    assert result.reconciliation.state == CanonReconciliationState.PENDING
    assert projects.get_chapter(chapter_id).status == ChapterStatus.APPROVED
    with database.connect() as connection:
        job = connection.execute(
            "SELECT * FROM jobs WHERE id = ?", (result.job_id,)
        ).fetchone()
        assert job is not None
        assert (job["workflow"], job["provider"], job["model"], job["estimated_calls"]) == (
            "canon_reconciliation_v1",
            "local",
            "typed-reconciliation-v1",
            0,
        )


def test_exact_evidence_and_edit_accept_materialize_canon_and_legacy_ledger(
    tmp_path: Path,
) -> None:
    body = "沈砚🀄在雨夜突破筑基，终于改变了命运。"
    database, _, project_id, chapter_id, revision = _reviewing_chapter(
        tmp_path / "decision.db",
        body=body,
    )
    repository = CanonReconciliationRepository(database)
    approval = repository.approve_chapter_and_enqueue(
        project_id=project_id,
        chapter_id=chapter_id,
        expected_revision=revision,
        expected_content_sha256=text_sha256(body),
    )
    candidate = _candidate(
        version_id=approval.approval.chapter_version_id,
        chapter_id=chapter_id,
        chapter_revision=approval.chapter_revision,
        body=body,
        excerpt="沈砚🀄在雨夜突破筑基",
    )
    snapshot = repository.persist_analysis(
        approval.reconciliation.id,
        ReconciliationAnalysis(
            context_packet_id="packet-1",
            context_packet_sha256="a" * 64,
            context_dependency_fingerprint_sha256="b" * 64,
            canon_candidates=[candidate],
            preference_skip_reason="no_adopted_writing_outcome",
        ),
    )
    persisted = snapshot.canon_candidates[0]
    request = CanonDecisionBatchRequest(
        reconciliation_id=snapshot.reconciliation.id,
        expected_reconciliation_revision=snapshot.reconciliation.revision,
        idempotency_key="edit-accept-character-state",
        canon_decisions=[
            CanonCandidateDecision(
                candidate_id=persisted.id,
                expected_revision=persisted.revision,
                action=CandidateDecisionAction.EDIT,
                edited_subject_key="沈砚",
                edited_summary="作者确认沈砚进入筑基初期",
                edited_payload=CharacterStatePayload(
                    character_name="沈砚",
                    state="筑基初期（稳固）",
                    change="雨夜完成突破",
                ),
            )
        ],
    )

    decision = repository.decide_batch(project_id=project_id, request=request)

    assert len(decision.accepted_canon_record_ids) == 1
    assert repository.get_reconciliation(snapshot.reconciliation.id).state == (
        CanonReconciliationState.DECIDED
    )
    record = repository.list_canon_records(project_id)[0]
    assert isinstance(record.payload, CharacterStatePayload)
    assert record.payload.state == "筑基初期（稳固）"
    with database.connect() as connection:
        entity = connection.execute(
            """
            SELECT * FROM story_entities
            WHERE project_id = ? AND kind = 'character' AND name = '沈砚'
            """,
            (project_id,),
        ).fetchone()
        assert entity is not None
        assert entity["current_state"] == "筑基初期（稳固）"
    replay = repository.decide_batch(project_id=project_id, request=request)
    assert replay.batch_id == decision.batch_id
    assert replay.replayed is True
    changed_request = request.model_copy(
        update={"expected_reconciliation_revision": decision.reconciliation_revision}
    )
    with pytest.raises(CanonDecisionIdempotencyError):
        repository.decide_batch(project_id=project_id, request=changed_request)


def test_casefold_equivalent_candidate_updates_existing_canon_record(
    tmp_path: Path,
) -> None:
    body = "hero突破至白银阶。"
    database, _, project_id, chapter_id, revision = _reviewing_chapter(
        tmp_path / "casefold-canon-identity.db",
        body=body,
    )
    repository = CanonReconciliationRepository(database)
    approval = repository.approve_chapter_and_enqueue(
        project_id=project_id,
        chapter_id=chapter_id,
        expected_revision=revision,
        expected_content_sha256=text_sha256(body),
    )
    previous_payload = CharacterStatePayload(
        character_name="Hero",
        state="青铜阶",
        change="完成初次晋升",
    )
    previous_payload_value = previous_payload.model_dump(mode="json")
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO canon_records (
                id, project_id, kind, subject_key, payload_json,
                payload_sha256, revision, state, source_candidate_id,
                created_at, updated_at
            ) VALUES (
                'canon-hero', ?, 'character_state', 'Hero', ?, ?, 3,
                'active', NULL, 'now', 'now'
            )
            """,
            (
                project_id,
                canonical_json(previous_payload_value),
                canonical_sha256(previous_payload_value),
            ),
        )
        connection.execute(
            """
            INSERT INTO story_entities (
                id, project_id, kind, name, role, goal, current_state,
                relationship_notes, revision, created_at, updated_at
            ) VALUES (
                'entity-hero', ?, 'character', 'Hero', '', '', '青铜阶',
                '完成初次晋升', 2, 'now', 'now'
            )
            """,
            (project_id,),
        )
    existing = repository.list_canon_records(project_id)[0]
    candidate = CanonDeltaCandidateDraft(
        **{
            **_candidate(
                version_id=approval.approval.chapter_version_id,
                chapter_id=chapter_id,
                chapter_revision=approval.chapter_revision,
                body=body,
                excerpt=body[:-1],
                subject_key="hero",
            ).model_dump(mode="python"),
            "payload": CharacterStatePayload(
                character_name="hero",
                state="白银阶",
                change="再次晋升",
            ),
            "conflicts": [
                CanonConflict(
                    kind=CanonConflictKind.SUPERSEDES,
                    summary="替换同一角色的旧境界",
                    existing_record_id=existing.id,
                    existing_record_revision=existing.revision,
                    existing_record_payload_sha256=existing.payload_sha256,
                )
            ],
        }
    )
    snapshot = repository.persist_analysis(
        approval.reconciliation.id,
        ReconciliationAnalysis(
            context_packet_id="packet-casefold-canon",
            context_packet_sha256="5" * 64,
            context_dependency_fingerprint_sha256="6" * 64,
            canon_candidates=[candidate],
            preference_skip_reason="no_adopted_writing_outcome",
        ),
    )
    persisted = snapshot.canon_candidates[0]

    decision = repository.decide_batch(
        project_id=project_id,
        request=CanonDecisionBatchRequest(
            reconciliation_id=snapshot.reconciliation.id,
            expected_reconciliation_revision=snapshot.reconciliation.revision,
            idempotency_key="casefold-canon-update",
            canon_decisions=[
                CanonCandidateDecision(
                    candidate_id=persisted.id,
                    expected_revision=persisted.revision,
                    action=CandidateDecisionAction.ACCEPT,
                )
            ],
        ),
    )

    assert decision.accepted_canon_record_ids == [existing.id]
    records = repository.list_canon_records(project_id)
    assert len(records) == 1
    assert records[0].id == existing.id
    assert records[0].subject_key == "Hero"
    assert records[0].revision == existing.revision + 1
    assert isinstance(records[0].payload, CharacterStatePayload)
    assert records[0].payload.state == "白银阶"
    with database.connect() as connection:
        entities = connection.execute(
            """
            SELECT id, name, current_state, revision FROM story_entities
            WHERE project_id = ? AND kind = 'character'
            """,
            (project_id,),
        ).fetchall()
    logical_heroes = [
        row for row in entities if str(row["name"]).casefold() == "hero"
    ]
    assert [tuple(row) for row in logical_heroes] == [
        ("entity-hero", "Hero", "白银阶", 3)
    ]


def test_invalid_second_decision_rolls_back_first_ledger_write(tmp_path: Path) -> None:
    body = "沈砚改变状态。林青也改变状态。"
    database, _, project_id, chapter_id, revision = _reviewing_chapter(
        tmp_path / "batch-rollback.db",
        body=body,
    )
    repository = CanonReconciliationRepository(database)
    approval = repository.approve_chapter_and_enqueue(
        project_id=project_id,
        chapter_id=chapter_id,
        expected_revision=revision,
        expected_content_sha256=text_sha256(body),
    )
    candidates = [
        _candidate(
            version_id=approval.approval.chapter_version_id,
            chapter_id=chapter_id,
            chapter_revision=approval.chapter_revision,
            body=body,
            excerpt="沈砚改变状态",
        ),
        CanonDeltaCandidateDraft(
            **{
                **_candidate(
                    version_id=approval.approval.chapter_version_id,
                    chapter_id=chapter_id,
                    chapter_revision=approval.chapter_revision,
                    body=body,
                    excerpt="林青也改变状态",
                    subject_key="林青",
                ).model_dump(mode="python"),
                "payload": CharacterStatePayload(
                    character_name="林青",
                    state="已动摇",
                    change="立场改变",
                ),
            }
        ),
    ]
    snapshot = repository.persist_analysis(
        approval.reconciliation.id,
        ReconciliationAnalysis(
            context_packet_id="packet-2",
            context_packet_sha256="c" * 64,
            context_dependency_fingerprint_sha256="d" * 64,
            canon_candidates=candidates,
            preference_skip_reason="no_adopted_writing_outcome",
        ),
    )
    first = snapshot.canon_candidates[0]
    with pytest.raises(CanonReconciliationNotFoundError):
        repository.decide_batch(
            project_id=project_id,
            request=CanonDecisionBatchRequest(
                reconciliation_id=snapshot.reconciliation.id,
                expected_reconciliation_revision=snapshot.reconciliation.revision,
                idempotency_key="rollback-invalid-second-candidate",
                canon_decisions=[
                    CanonCandidateDecision(
                        candidate_id=first.id,
                        expected_revision=first.revision,
                        action=CandidateDecisionAction.ACCEPT,
                    ),
                    CanonCandidateDecision(
                        candidate_id="missing-candidate",
                        expected_revision=0,
                        action=CandidateDecisionAction.ACCEPT,
                    ),
                ],
            ),
        )

    assert repository.list_canon_records(project_id) == []
    after = repository.get_latest_snapshot(project_id=project_id, chapter_id=chapter_id)
    assert all(item.state.value == "candidate" for item in after.canon_candidates)
    assert after.reconciliation.revision == snapshot.reconciliation.revision


def test_rolling_plan_candidate_never_overwrites_and_adopts_new_chapters(
    tmp_path: Path,
) -> None:
    body = "沈砚突破筑基。"
    database, _, project_id, chapter_id, revision = _reviewing_chapter(
        tmp_path / "rolling-plan.db",
        body=body,
    )
    repository = CanonReconciliationRepository(database)
    approval = repository.approve_chapter_and_enqueue(
        project_id=project_id,
        chapter_id=chapter_id,
        expected_revision=revision,
        expected_content_sha256=text_sha256(body),
    )
    snapshot = repository.persist_analysis(
        approval.reconciliation.id,
        ReconciliationAnalysis(
            context_packet_id="packet-rolling",
            context_packet_sha256="e" * 64,
            context_dependency_fingerprint_sha256="f" * 64,
            canon_candidates=[
                _candidate(
                    version_id=approval.approval.chapter_version_id,
                    chapter_id=chapter_id,
                    chapter_revision=approval.chapter_revision,
                    body=body,
                    excerpt=body[:-1],
                )
            ],
            preference_skip_reason="no_adopted_writing_outcome",
        ),
    )
    decision = repository.decide_batch(
        project_id=project_id,
        request=CanonDecisionBatchRequest(
            reconciliation_id=snapshot.reconciliation.id,
            expected_reconciliation_revision=snapshot.reconciliation.revision,
            idempotency_key="accept-before-rolling-plan",
            canon_decisions=[
                CanonCandidateDecision(
                    candidate_id=snapshot.canon_candidates[0].id,
                    expected_revision=0,
                    action=CandidateDecisionAction.ACCEPT,
                )
            ],
        ),
    )
    volume_plan_id = "volume-plan-1"
    volume = VolumePlanContent(
        volume_number=1,
        title="筑基新局",
        direction="进入白塔争夺传承",
        central_conflict="白塔封锁了主角所需的功法",
        state_goal="站稳筑基初期",
        resource_goal="获得白塔令牌",
        emotional_payoff="证明自己能保护家人",
        climax="在白塔顶层击败守门人",
        verification="传承、代价与家人三条线同时推进",
    )
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO volume_plans (
                id, project_id, volume_number, content_json, locked,
                revision, created_at, updated_at
            ) VALUES (?, ?, 1, ?, 0, 0, 'now', 'now')
            """,
            (volume_plan_id, project_id, volume.model_dump_json()),
        )
    beat = DirectorSceneBeat(
        ordinal=1,
        summary="上章后果落地",
        state_change="主角做出新选择",
        resource_change="明确代价",
        emotional_turn="小胜后紧张",
        verification="能找到上章事实的具体后果",
    )
    plans = [
        RollingChapterPlanContent(
            chapter_number=number,
            title=f"第{number}章 新局",
            reader_promise="上章事实开始改变主角的选择",
            opening_hook="白塔令牌突然出现",
            state_change="主角做出不可逆选择",
            resource_change="获得线索并付出代价",
            emotional_payoff="先赢一局再暴露危机",
            ending_cliffhanger="白塔的真正主人现身",
            verification="结果、代价、钩子三者相连",
            scene_beats=[beat],
        )
        for number in (2, 3, 4)
    ]
    replenishment = repository.create_rolling_plan_replenishment(
        project_id=project_id,
        reconciliation_id=snapshot.reconciliation.id,
        draft=RollingPlanReplenishmentDraft(
            source_decision_batch_id=decision.batch_id,
            source_chapter_id=chapter_id,
            source_canon_record_ids=decision.accepted_canon_record_ids,
            volume_plan_id=volume_plan_id,
            protected_chapter_numbers=[],
            plans=plans,
        ),
    )
    request = AdoptRollingPlanReplenishmentRequest(
        expected_revision=replenishment.revision,
        expected_plans_sha256=replenishment.plans_sha256,
        idempotency_key="adopt-three-rolling-chapters",
    )

    adopted = repository.adopt_rolling_plan_replenishment(
        project_id=project_id,
        replenishment_id=replenishment.id,
        request=request,
    )

    assert adopted.state.value == "adopted"
    assert repository.adopt_rolling_plan_replenishment(
        project_id=project_id,
        replenishment_id=replenishment.id,
        request=request,
    ).id == adopted.id
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM rolling_chapter_plans WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
            == 3
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM chapters WHERE project_id = ? AND chapter_number > 1",
                (project_id,),
            ).fetchone()[0]
            == 3
        )


def test_rolling_plan_candidate_becomes_stale_when_source_canon_changes(
    tmp_path: Path,
) -> None:
    body = "沈砚突破筑基。"
    database, projects, project_id, chapter_id, revision = _reviewing_chapter(
        tmp_path / "rolling-plan-stale-canon.db",
        body=body,
    )
    repository = CanonReconciliationRepository(database)
    approval = repository.approve_chapter_and_enqueue(
        project_id=project_id,
        chapter_id=chapter_id,
        expected_revision=revision,
        expected_content_sha256=text_sha256(body),
    )
    snapshot = repository.persist_analysis(
        approval.reconciliation.id,
        ReconciliationAnalysis(
            context_packet_id="packet-stale-rolling",
            context_packet_sha256="1" * 64,
            context_dependency_fingerprint_sha256="2" * 64,
            canon_candidates=[
                _candidate(
                    version_id=approval.approval.chapter_version_id,
                    chapter_id=chapter_id,
                    chapter_revision=approval.chapter_revision,
                    body=body,
                    excerpt=body[:-1],
                )
            ],
            preference_skip_reason="no_adopted_writing_outcome",
        ),
    )
    decision = repository.decide_batch(
        project_id=project_id,
        request=CanonDecisionBatchRequest(
            reconciliation_id=snapshot.reconciliation.id,
            expected_reconciliation_revision=snapshot.reconciliation.revision,
            idempotency_key="accept-before-stale-rolling",
            canon_decisions=[
                CanonCandidateDecision(
                    candidate_id=snapshot.canon_candidates[0].id,
                    expected_revision=snapshot.canon_candidates[0].revision,
                    action=CandidateDecisionAction.ACCEPT,
                )
            ],
        ),
    )
    volume_plan_id = "volume-plan-stale-canon"
    volume = VolumePlanContent(
        volume_number=1,
        title="筑基新局",
        direction="进入白塔争夺传承",
        central_conflict="白塔封锁了主角所需的功法",
        state_goal="站稳筑基初期",
        resource_goal="获得白塔令牌",
        emotional_payoff="证明自己能保护家人",
        climax="在白塔顶层击败守门人",
        verification="传承、代价与家人三条线同时推进",
    )
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO volume_plans (
                id, project_id, volume_number, content_json, locked,
                revision, created_at, updated_at
            ) VALUES (?, ?, 1, ?, 0, 0, 'now', 'now')
            """,
            (volume_plan_id, project_id, volume.model_dump_json()),
        )
    plan = RollingChapterPlanContent(
        chapter_number=2,
        title="第2章 新局",
        reader_promise="上章事实开始改变主角的选择",
        opening_hook="白塔令牌突然出现",
        state_change="主角做出不可逆选择",
        resource_change="获得线索并付出代价",
        emotional_payoff="先赢一局再暴露危机",
        ending_cliffhanger="白塔的真正主人现身",
        verification="结果、代价、钩子三者相连",
        scene_beats=[
            DirectorSceneBeat(
                ordinal=1,
                summary="上章后果落地",
                state_change="主角做出新选择",
                resource_change="明确代价",
                emotional_turn="小胜后紧张",
                verification="能找到上章事实的具体后果",
            )
        ],
    )
    replenishment = repository.create_rolling_plan_replenishment(
        project_id=project_id,
        reconciliation_id=snapshot.reconciliation.id,
        draft=RollingPlanReplenishmentDraft(
            source_decision_batch_id=decision.batch_id,
            source_chapter_id=chapter_id,
            source_canon_record_ids=decision.accepted_canon_record_ids,
            volume_plan_id=volume_plan_id,
            protected_chapter_numbers=[],
            plans=[
                plan.model_copy(
                    update={"chapter_number": number, "title": f"第{number}章 新局"}
                )
                for number in (3, 4, 5)
            ],
        ),
    )
    next_body = "沈砚再次突破，进入筑基中期。"
    next_chapter = projects.create_chapter(
        project_id,
        CreateChapterRequest(expected_last_chapter_number=1),
    )
    next_chapter = projects.update_chapter(
        next_chapter.id,
        UpdateChapterRequest(
            content=next_body,
            expected_revision=next_chapter.revision,
        ),
    )
    next_chapter = projects.update_chapter_brief(
        next_chapter.id,
        UpdateChapterBriefRequest(
            title="再破一境",
            reader_promise="旧境界设定将被更新",
            opening_hook="灵气再次涌入丹田",
            state_change="沈砚进入筑基中期",
            emotional_payoff="实力跨越新台阶",
            ending_cliffhanger="白塔主人察觉变化",
            expected_revision=next_chapter.revision,
        ),
    )
    for target in (ChapterStatus.DRAFTED, ChapterStatus.REVIEWING):
        next_chapter = projects.transition_chapter(
            next_chapter.id,
            TransitionChapterRequest(
                target_status=target,
                expected_revision=next_chapter.revision,
            ),
        )
    next_approval = repository.approve_chapter_and_enqueue(
        project_id=project_id,
        chapter_id=next_chapter.id,
        expected_revision=next_chapter.revision,
        expected_content_sha256=text_sha256(next_body),
    )
    next_candidate = CanonDeltaCandidateDraft(
        **{
            **_candidate(
                version_id=next_approval.approval.chapter_version_id,
                chapter_id=next_chapter.id,
                chapter_revision=next_approval.chapter_revision,
                body=next_body,
                excerpt=next_body[:-1],
            ).model_dump(mode="python"),
            "payload": CharacterStatePayload(
                character_name="沈砚",
                state="筑基中期",
                change="后续章节再次突破",
            ),
            "conflicts": [
                CanonConflict(
                    kind=CanonConflictKind.SUPERSEDES,
                    summary="替换上一章已确认的人物状态",
                    existing_record_id=record.id,
                    existing_record_revision=record.revision,
                    existing_record_payload_sha256=record.payload_sha256,
                )
                for record in repository.list_canon_records(project_id)
                if record.kind == CanonKind.CHARACTER_STATE
                and record.subject_key == "沈砚"
            ],
        }
    )
    next_snapshot = repository.persist_analysis(
        next_approval.reconciliation.id,
        ReconciliationAnalysis(
            context_packet_id="packet-new-canon",
            context_packet_sha256="3" * 64,
            context_dependency_fingerprint_sha256="4" * 64,
            canon_candidates=[next_candidate],
            preference_skip_reason="no_adopted_writing_outcome",
        ),
    )
    next_decision = repository.decide_batch(
        project_id=project_id,
        request=CanonDecisionBatchRequest(
            reconciliation_id=next_snapshot.reconciliation.id,
            expected_reconciliation_revision=next_snapshot.reconciliation.revision,
            idempotency_key="update-canon-after-rolling",
            canon_decisions=[
                CanonCandidateDecision(
                    candidate_id=next_snapshot.canon_candidates[0].id,
                    expected_revision=next_snapshot.canon_candidates[0].revision,
                    action=CandidateDecisionAction.ACCEPT,
                )
            ],
        ),
    )
    assert next_decision.accepted_canon_record_ids == decision.accepted_canon_record_ids

    with pytest.raises(CanonReconciliationStaleError, match="rolling_canon_changed"):
        repository.adopt_rolling_plan_replenishment(
            project_id=project_id,
            replenishment_id=replenishment.id,
            request=AdoptRollingPlanReplenishmentRequest(
                expected_revision=replenishment.revision,
                expected_plans_sha256=replenishment.plans_sha256,
                idempotency_key="reject-stale-canon-rolling",
            ),
        )

    current = repository.get_latest_snapshot(
        project_id=project_id,
        chapter_id=chapter_id,
    ).rolling_plan_replenishment
    assert current is not None
    assert current.state == RollingPlanReplenishmentState.STALE
    assert current.blocked_reason == "rolling_canon_changed"
    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM rolling_chapter_plans WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0] == 0


def test_v31_accepts_approval_versions_and_preference_context_purpose(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "schema-v31.db")
    database.initialize()
    with database.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 31
        chapter_sql = str(
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='chapter_versions'"
            ).fetchone()[0]
        )
        context_sql = str(
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='context_packets'"
            ).fetchone()[0]
        )
        assert "'approval'" in chapter_sql
        assert "'preference'" in context_sql
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert len(sha256(chapter_sql.encode()).hexdigest()) == 64
