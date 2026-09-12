import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai import AiGatewayManager
from app.context.plan_models import (
    AdoptPlanRebaseCandidateRequest,
    CreatePlanRebaseCandidateRequest,
    CreativePlanDependencyState,
    PlanRebaseCandidate,
    PlanRebaseRollingEdit,
    PlanRebaseVolumeEdit,
    UpdatePlanRebaseCandidateRequest,
)
from app.context.plan_repository import PlanRebaseConflictError, PlanRebaseRepository
from app.context.plan_routes import plan_rebase_router
from app.creative_safety import CreativeSafetyProvenance
from app.database import Database
from app.director.repository import DirectorRepository
from app.jobs.repository import JobRepository
from app.models import (
    BookBlueprintContent,
    BookBlueprintField,
    ConfirmTopicDecisionRequest,
    CreateProjectRequest,
    DirectorEntityProposal,
    DirectorExpansionDraft,
    DirectorSceneBeat,
    DirectorStartupCandidate,
    Genre,
    RollingChapterPlanContent,
    StoryEntityKind,
    TopicDecisionField,
    UpdateBookBlueprintRequest,
    UpdateRollingChapterPlanRequest,
    UpdateTopicDecisionRequest,
    UpdateVolumePlanRequest,
    VolumePlanContent,
)
from app.repository import ProjectRepository
from app.topic_decisions import TopicDecisionService


class _ToggleSafetyGate:
    def __init__(self) -> None:
        self.blocked = False

    def require_creative_safety(
        self,
        project_id: str,
        expected: CreativeSafetyProvenance | None = None,
    ) -> CreativeSafetyProvenance | None:
        del project_id, expected
        if self.blocked:
            raise ValueError("originality_check_required")
        return None


class _BlockingSafetyGate:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()

    def require_creative_safety(
        self,
        project_id: str,
        expected: CreativeSafetyProvenance | None = None,
    ) -> CreativeSafetyProvenance | None:
        del project_id, expected
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("test safety gate was not released")
        return None


def _blueprint() -> BookBlueprintContent:
    return BookBlueprintContent(
        title="回到九八年的南平",
        genre=Genre.URBAN_REBIRTH,
        rebirth_year=1998,
        rebirth_location="福建南平",
        target_audience="喜欢强因果、产业升级的网文读者",
        core_selling_points=["信息差救家", "小城产业升级"],
        core_desire="挽回家庭遗憾，建立能长期运转的事业",
        divergence_point="提前三天截住第一张违约订单",
        long_term_promise="每卷完成一次产业跃迁和关系兑现",
        ending_direction="完成代际和解并留下本地产业系统",
        protagonist_arc="从弥补家人走向承担公共责任",
        resource_growth="从未来信息到现金流、组织与信用网",
        relationship_design="家人是价值锚，伙伴执行，对手迫使升级",
    )


def _rolling(chapter_number: int) -> RollingChapterPlanContent:
    return RollingChapterPlanContent(
        chapter_number=chapter_number,
        title=f"第 {chapter_number} 章 抢时间",
        reader_promise="看主角解决一个可验证的现实阻碍",
        opening_hook="坏消息比记忆中更早到来",
        state_change="从被动得知转为主动介入",
        resource_change="新增一个可调动的资源节点",
        emotional_payoff="家人第一次给予有限信任",
        ending_cliffhanger="更大的违约代价提前浮现",
        verification="合同、关系或资源状态发生可观察变化",
        scene_beats=[
            DirectorSceneBeat(
                ordinal=1,
                summary="坏消息落地，迫使主角立即选择",
                state_change="主角开始介入",
                resource_change="暴露当前资源缺口",
                emotional_turn="焦虑转为决断",
                verification="明确下一步行动和失败代价",
            )
        ],
    )


def _planning(tmp_path: Path) -> tuple[Database, str, DirectorRepository]:
    database = Database(tmp_path / "plan-rebase.db")
    database.initialize()
    projects = ProjectRepository(database)
    workspace = projects.create_project(
        CreateProjectRequest(
            title="回到九八年的南平",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1998,
            rebirth_location="福建南平",
            template_id="urban-rebirth",
        )
    )
    project_id = workspace.project.id
    topics = TopicDecisionService(
        database,
        JobRepository(database),
        AiGatewayManager(),
    )
    assert workspace.topic_decision is not None
    topics.confirm_decision(
        project_id,
        ConfirmTopicDecisionRequest(expected_revision=workspace.topic_decision.revision),
    )
    director = DirectorRepository(database)
    blueprint = director.select_startup_candidate(
        project_id,
        "重生后抢救家庭和竹木厂",
        DirectorStartupCandidate(
            id=str(uuid4()),
            ordinal=1,
            label="订单线",
            blueprint=_blueprint(),
            why_distinct="以可验证订单而非空泛商战起步",
            risks=["年代资料仍需核验"],
        ),
        expected_blueprint_revision=None,
    )
    director.apply_expansion(
        project_id,
        DirectorExpansionDraft(
            entities=[
                DirectorEntityProposal(
                    kind=StoryEntityKind.CHARACTER,
                    name="林川",
                    role="主角",
                    goal="保住家庭",
                    initial_state="有信息、无资源",
                ),
                DirectorEntityProposal(
                    kind=StoryEntityKind.RESOURCE,
                    name="订单网",
                    role="首卷杠杆",
                    goal="建立现金流",
                    initial_state="分散且不稳定",
                ),
            ],
            volumes=[
                VolumePlanContent(
                    volume_number=1,
                    title="第一卷 抢回订单",
                    direction="用小订单撬动家庭与产业线",
                    central_conflict="没有信用，也没有现金",
                    state_goal="成为能调动三方资源的执行者",
                    resource_goal="形成第一笔稳定现金流",
                    emotional_payoff="父亲第一次承认主角能扛事",
                    climax="违约前夜完成替代交付",
                    verification="回款、关系与竞争格局同时变化",
                )
            ],
            chapters=[_rolling(number) for number in range(1, 4)],
            why_writeable="每章都有行动、阻力和可验证的状态变化",
        ),
        expected_blueprint_revision=blueprint.revision,
    )
    return database, project_id, director


def _install_profile_stub(database: Database, project_id: str) -> str:
    recipe_id = str(uuid4())
    recipe_version_id = str(uuid4())
    profile_id = str(uuid4())
    link_id = str(uuid4())
    timestamp = "2026-09-12T00:00:00+00:00"
    with database.connect() as connection:
        topic = connection.execute(
            """
            SELECT v.id, v.revision, v.content_sha256
            FROM topic_decisions d JOIN topic_decision_versions v
              ON v.topic_decision_id = d.id AND v.revision = d.confirmed_revision
            WHERE d.project_id = ?
            """,
            (project_id,),
        ).fetchone()
        assert topic is not None
        connection.execute(
            """
            INSERT INTO writing_pattern_recipes (
                id, created_from_project_id, lifecycle_state, lifecycle_revision,
                created_at, updated_at
            ) VALUES (?, ?, 'active', 0, ?, ?)
            """,
            (recipe_id, project_id, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO writing_pattern_recipe_versions (
                id, recipe_id, version, name, description,
                conflict_decisions_json, conflicts_json, source_asset_count,
                source_work_count, safety_basis, source_snapshot_sha256,
                content_sha256, created_at
            ) VALUES (?, ?, 1, '测试配方', '', '[]', '[]', 1, 1,
                      'abstract_only', ?, ?, ?)
            """,
            (recipe_version_id, recipe_id, "a" * 64, "b" * 64, timestamp),
        )
        connection.execute(
            """
            INSERT INTO writing_pattern_profile_versions (
                id, project_id, recipe_version_id, recipe_content_sha256,
                topic_decision_version_id, topic_revision, topic_content_sha256,
                compiler_version, safety_basis, source_snapshot_sha256,
                profile_json, conflicts_json, decisions_json,
                excluded_entry_keys_json, profile_fingerprint_sha256, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'test-v1', 'abstract_only', ?, '{}',
                      '[]', '[]', '[]', ?, ?)
            """,
            (
                profile_id,
                project_id,
                recipe_version_id,
                "b" * 64,
                topic["id"],
                topic["revision"],
                topic["content_sha256"],
                "a" * 64,
                "d" * 64,
                timestamp,
            ),
        )
        connection.execute(
            """
            INSERT INTO project_writing_pattern_profiles (
                id, project_id, profile_version_id, lifecycle_state,
                lifecycle_revision, created_at, updated_at
            ) VALUES (?, ?, ?, 'active', 0, ?, ?)
            """,
            (link_id, project_id, profile_id, timestamp, timestamp),
        )
    return link_id


def _volume_edits(
    candidate: PlanRebaseCandidate,
    replacements: dict[str, VolumePlanContent] | None = None,
) -> list[PlanRebaseVolumeEdit]:
    replacements = replacements or {}
    return [
        PlanRebaseVolumeEdit(
            id=item.id,
            content=replacements.get(item.id, item.content),
        )
        for item in candidate.volume_plans
    ]


def _rolling_edits(
    candidate: PlanRebaseCandidate,
    replacements: dict[str, RollingChapterPlanContent] | None = None,
) -> list[PlanRebaseRollingEdit]:
    replacements = replacements or {}
    return [
        PlanRebaseRollingEdit(
            id=item.id,
            content=replacements.get(item.id, item.content),
        )
        for item in candidate.rolling_chapter_plans
    ]


def test_legacy_plans_have_visible_impact_and_can_be_cloned_for_rebase(
    tmp_path: Path,
) -> None:
    database, project_id, _director = _planning(tmp_path)
    service = PlanRebaseRepository(database)

    impact = service.get_impact(project_id)

    assert impact.reasons == ["legacy_dependency_snapshot"]
    assert impact.can_rebase is True
    assert len(impact.targets) == 5
    assert {target.state for target in impact.targets} == {
        CreativePlanDependencyState.LEGACY
    }
    with database.connect() as connection:
        dependency_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM creative_plan_dependencies WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
        )
    assert dependency_count == 0

    candidate = service.create_candidate(
        project_id,
        CreatePlanRebaseCandidateRequest(
            expected_dependency_fingerprint_sha256=(
                impact.current_dependency_fingerprint_sha256
            )
        ),
    )

    assert candidate.target_dependency_fingerprint_sha256 == (
        impact.current_dependency_fingerprint_sha256
    )
    assert candidate.book_blueprint is not None
    assert len(candidate.volume_plans) == 1
    assert len(candidate.rolling_chapter_plans) == 3


def test_candidate_creation_holds_a_stable_write_window_before_safety_recheck(
    tmp_path: Path,
) -> None:
    database, project_id, director = _planning(tmp_path)
    service = PlanRebaseRepository(database)
    impact = service.get_impact(project_id)
    gate = _BlockingSafetyGate()
    service.set_creative_safety_gate(gate)
    blueprint = director.require_book_blueprint(project_id)
    changed = blueprint.content.model_copy(
        update={"ending_direction": "并发写入应等待候选冻结完成"}
    )
    writer_started = Event()
    writer_finished = Event()

    def create_candidate() -> PlanRebaseCandidate:
        return service.create_candidate(
            project_id,
            CreatePlanRebaseCandidateRequest(
                expected_dependency_fingerprint_sha256=(
                    impact.current_dependency_fingerprint_sha256
                )
            ),
        )

    def change_blueprint() -> None:
        writer_started.set()
        try:
            director.update_book_blueprint(
                project_id,
                UpdateBookBlueprintRequest(
                    content=changed,
                    changed_fields=[BookBlueprintField.ENDING_DIRECTION],
                    expected_revision=blueprint.revision,
                ),
            )
        finally:
            writer_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        creator = executor.submit(create_candidate)
        try:
            assert gate.entered.wait(timeout=2)
            writer = executor.submit(change_blueprint)
            assert writer_started.wait(timeout=2)
            writer_completed_before_gate_release = writer_finished.wait(timeout=0.2)
        finally:
            gate.release.set()
        created = creator.result(timeout=5)
        writer.result(timeout=5)

    assert writer_completed_before_gate_release is False
    assert created.target_dependency_fingerprint_sha256 == (
        impact.current_dependency_fingerprint_sha256
    )


@pytest.mark.parametrize("operation", ["update", "adopt"])
def test_candidate_write_holds_lock_while_rechecking_context_safety(
    tmp_path: Path,
    operation: str,
) -> None:
    database, project_id, director = _planning(tmp_path)
    service = PlanRebaseRepository(database)
    impact = service.get_impact(project_id)
    candidate = service.create_candidate(
        project_id,
        CreatePlanRebaseCandidateRequest(
            expected_dependency_fingerprint_sha256=(
                impact.current_dependency_fingerprint_sha256
            )
        ),
    )
    gate = _BlockingSafetyGate()
    service.set_creative_safety_gate(gate)
    blueprint = director.require_book_blueprint(project_id)
    changed = blueprint.content.model_copy(
        update={"ending_direction": f"{operation} 安全复核后的并发改动"}
    )
    writer_started = Event()
    writer_finished = Event()

    def write_candidate() -> None:
        if operation == "update":
            service.update_candidate(
                project_id,
                candidate.id,
                UpdatePlanRebaseCandidateRequest(
                    expected_revision=candidate.revision,
                    book_blueprint_content=(
                        candidate.book_blueprint.content
                        if candidate.book_blueprint is not None
                        else None
                    ),
                    volume_plans=_volume_edits(candidate),
                    rolling_chapter_plans=_rolling_edits(candidate),
                ),
            )
        else:
            service.adopt_candidate(
                project_id,
                candidate.id,
                AdoptPlanRebaseCandidateRequest(
                    expected_revision=candidate.revision,
                    expected_dependency_fingerprint_sha256=(
                        candidate.target_dependency_fingerprint_sha256
                    ),
                    idempotency_key="locked-safety-recheck",
                ),
            )

    def change_blueprint() -> None:
        writer_started.set()
        try:
            director.update_book_blueprint(
                project_id,
                UpdateBookBlueprintRequest(
                    content=changed,
                    changed_fields=[BookBlueprintField.ENDING_DIRECTION],
                    expected_revision=blueprint.revision,
                ),
            )
        finally:
            writer_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        candidate_writer = executor.submit(write_candidate)
        try:
            assert gate.entered.wait(timeout=2)
            plan_writer = executor.submit(change_blueprint)
            assert writer_started.wait(timeout=2)
            writer_completed_before_gate_release = writer_finished.wait(timeout=0.2)
        finally:
            gate.release.set()
        candidate_writer.result(timeout=5)
        plan_writer.result(timeout=5)

    assert writer_completed_before_gate_release is False


@pytest.mark.parametrize("operation", ["update", "adopt"])
def test_candidate_write_rejects_corrupt_frozen_provenance_without_writes(
    tmp_path: Path,
    operation: str,
) -> None:
    database, project_id, director = _planning(tmp_path)
    service = PlanRebaseRepository(database)
    impact = service.get_impact(project_id)
    candidate = service.create_candidate(
        project_id,
        CreatePlanRebaseCandidateRequest(
            expected_dependency_fingerprint_sha256=(
                impact.current_dependency_fingerprint_sha256
            )
        ),
    )
    corrupted_impact = candidate.impact.model_dump(mode="json")
    corrupted_impact["project_id"] = str(uuid4())
    with database.connect() as connection:
        connection.execute(
            "UPDATE plan_rebase_candidates SET impact_json = ? WHERE id = ?",
            (
                json.dumps(corrupted_impact),
                candidate.id,
            ),
        )
    before = director.get_snapshot(project_id)

    with pytest.raises(PlanRebaseConflictError, match="rebase_candidate_changed"):
        if operation == "update":
            service.update_candidate(
                project_id,
                candidate.id,
                UpdatePlanRebaseCandidateRequest(
                    expected_revision=candidate.revision,
                    book_blueprint_content=(
                        candidate.book_blueprint.content
                        if candidate.book_blueprint is not None
                        else None
                    ),
                    volume_plans=_volume_edits(candidate),
                    rolling_chapter_plans=_rolling_edits(candidate),
                ),
            )
        else:
            service.adopt_candidate(
                project_id,
                candidate.id,
                AdoptPlanRebaseCandidateRequest(
                    expected_revision=candidate.revision,
                    expected_dependency_fingerprint_sha256=(
                        candidate.target_dependency_fingerprint_sha256
                    ),
                    idempotency_key="reject-corrupt-provenance",
                ),
            )

    assert director.get_snapshot(project_id) == before
    with database.connect() as connection:
        stored = connection.execute(
            "SELECT state, revision FROM plan_rebase_candidates WHERE id = ?",
            (candidate.id,),
        ).fetchone()
    assert stored is not None
    assert tuple(stored) == ("candidate", candidate.revision)


def test_blueprint_change_marks_every_bound_plan_stale(tmp_path: Path) -> None:
    database, project_id, director = _planning(tmp_path)
    service = PlanRebaseRepository(database)
    baseline = service.bind_current_planning(project_id)
    assert baseline.reasons == []

    blueprint = director.require_book_blueprint(project_id)
    changed = blueprint.content.model_copy(
        update={"long_term_promise": "每卷都将家庭信任与产业跃迁同时兑现"}
    )
    director.update_book_blueprint(
        project_id,
        UpdateBookBlueprintRequest(
            content=changed,
            changed_fields=[BookBlueprintField.LONG_TERM_PROMISE],
            expected_revision=blueprint.revision,
        ),
    )

    impact = service.get_impact(project_id)

    assert impact.reasons == ["base_blueprint_dependency_changed"]
    assert all(
        target.state == CreativePlanDependencyState.STALE
        for target in impact.targets
    )
    assert impact.affected_blueprint_fields == list(BookBlueprintField)


def test_candidate_edit_cannot_change_a_locked_blueprint_field(tmp_path: Path) -> None:
    database, project_id, director = _planning(tmp_path)
    blueprint = director.require_book_blueprint(project_id)
    locked = director.update_book_blueprint(
        project_id,
        UpdateBookBlueprintRequest(
            content=blueprint.content,
            lock_updates={BookBlueprintField.CORE_DESIRE: True},
            expected_revision=blueprint.revision,
        ),
    )
    service = PlanRebaseRepository(database)
    impact = service.get_impact(project_id)
    candidate = service.create_candidate(
        project_id,
        CreatePlanRebaseCandidateRequest(
            expected_dependency_fingerprint_sha256=(
                impact.current_dependency_fingerprint_sha256
            )
        ),
    )
    assert candidate.book_blueprint is not None
    changed = candidate.book_blueprint.content.model_copy(
        update={"core_desire": "候选试图覆盖作者锁定的核心欲望"}
    )

    with pytest.raises(PlanRebaseConflictError, match="locked_blueprint_field"):
        service.update_candidate(
            project_id,
            candidate.id,
            UpdatePlanRebaseCandidateRequest(
                expected_revision=candidate.revision,
                book_blueprint_content=changed,
                volume_plans=_volume_edits(candidate),
                rolling_chapter_plans=_rolling_edits(candidate),
            ),
        )

    current = director.require_book_blueprint(project_id)
    assert current.revision == locked.revision
    assert current.content.core_desire == locked.content.core_desire


def test_adopt_rebase_is_atomic_and_never_changes_approved_chapter_body(
    tmp_path: Path,
) -> None:
    database, project_id, _director = _planning(tmp_path)
    service = PlanRebaseRepository(database)
    impact = service.get_impact(project_id)
    candidate = service.create_candidate(
        project_id,
        CreatePlanRebaseCandidateRequest(
            expected_dependency_fingerprint_sha256=(
                impact.current_dependency_fingerprint_sha256
            )
        ),
    )
    assert candidate.book_blueprint is not None
    blueprint_content = candidate.book_blueprint.content.model_copy(
        update={"long_term_promise": "新主线：从南平到全省的产业网络"}
    )
    first_volume = candidate.volume_plans[0]
    volume_content = first_volume.content.model_copy(
        update={"direction": "先建立交付信用，再用现金流扩大供应网"}
    )
    first_rolling = candidate.rolling_chapter_plans[0]
    rolling_content = first_rolling.content.model_copy(
        update={"reader_promise": "看主角在二十四小时内拿到第一份信任"}
    )
    edited = service.update_candidate(
        project_id,
        candidate.id,
        UpdatePlanRebaseCandidateRequest(
            expected_revision=candidate.revision,
            book_blueprint_content=blueprint_content,
            volume_plans=_volume_edits(
                candidate,
                {first_volume.id: volume_content},
            ),
            rolling_chapter_plans=_rolling_edits(
                candidate,
                {first_rolling.id: rolling_content},
            ),
        ),
    )
    approved_body = "这是作者已确认的第一章正文，重基不得修改。"
    with database.connect() as connection:
        approved = connection.execute(
            "SELECT id FROM chapters WHERE project_id = ? ORDER BY chapter_number LIMIT 1",
            (project_id,),
        ).fetchone()
        assert approved is not None
        approved_id = str(approved["id"])
        connection.execute(
            "UPDATE chapters SET content = ?, status = 'approved', revision = 7 WHERE id = ?",
            (approved_body, approved_id),
        )

    adopted = service.adopt_candidate(
        project_id,
        candidate.id,
        AdoptPlanRebaseCandidateRequest(
            expected_revision=edited.revision,
            expected_dependency_fingerprint_sha256=(
                edited.target_dependency_fingerprint_sha256
            ),
            idempotency_key="adopt-plan-once",
        ),
    )

    assert adopted.candidate.state.value == "adopted"
    assert adopted.planning.book_blueprint is not None
    assert (
        adopted.planning.book_blueprint.content.long_term_promise
        == blueprint_content.long_term_promise
    )
    assert adopted.planning.volume_plans[0].direction == volume_content.direction
    assert (
        adopted.planning.rolling_chapter_plans[0].reader_promise
        == rolling_content.reader_promise
    )
    with database.connect() as connection:
        chapter = connection.execute(
            "SELECT content, status, revision FROM chapters WHERE id = ?",
            (approved_id,),
        ).fetchone()
    assert chapter is not None
    assert tuple(chapter) == (approved_body, "approved", 7)
    assert service.get_impact(project_id).reasons == []
    retried = service.adopt_candidate(
        project_id,
        candidate.id,
        AdoptPlanRebaseCandidateRequest(
            expected_revision=edited.revision,
            expected_dependency_fingerprint_sha256=(
                edited.target_dependency_fingerprint_sha256
            ),
            idempotency_key="adopt-plan-once",
        ),
    )
    assert retried.candidate.revision == adopted.candidate.revision


def test_concurrent_plan_change_rejects_adoption_without_partial_updates(
    tmp_path: Path,
) -> None:
    database, project_id, director = _planning(tmp_path)
    service = PlanRebaseRepository(database)
    impact = service.get_impact(project_id)
    candidate = service.create_candidate(
        project_id,
        CreatePlanRebaseCandidateRequest(
            expected_dependency_fingerprint_sha256=(
                impact.current_dependency_fingerprint_sha256
            )
        ),
    )
    assert candidate.book_blueprint is not None
    desired_blueprint = candidate.book_blueprint.content.model_copy(
        update={"ending_direction": "候选的新结局方向"}
    )
    edited = service.update_candidate(
        project_id,
        candidate.id,
        UpdatePlanRebaseCandidateRequest(
            expected_revision=0,
            book_blueprint_content=desired_blueprint,
            volume_plans=_volume_edits(candidate),
            rolling_chapter_plans=_rolling_edits(candidate),
        ),
    )
    before = director.get_snapshot(project_id)
    rolling = before.rolling_chapter_plans[0]
    concurrent_content = RollingChapterPlanContent.model_validate(
        rolling.model_dump()
    ).model_copy(update={"opening_hook": "作者并发修改的开篇钩子"})
    director.update_rolling_plan(
        project_id,
        rolling.id,
        UpdateRollingChapterPlanRequest(
            content=concurrent_content,
            locked=rolling.locked,
            expected_revision=rolling.revision,
        ),
    )

    with pytest.raises(PlanRebaseConflictError, match="rebase_candidate_changed"):
        service.adopt_candidate(
            project_id,
            candidate.id,
            AdoptPlanRebaseCandidateRequest(
                expected_revision=edited.revision,
                expected_dependency_fingerprint_sha256=(
                    edited.target_dependency_fingerprint_sha256
                ),
                idempotency_key="concurrent-adoption",
            ),
        )

    after = director.get_snapshot(project_id)
    assert before.book_blueprint is not None and after.book_blueprint is not None
    assert after.book_blueprint.content == before.book_blueprint.content
    assert after.rolling_chapter_plans[0].opening_hook == concurrent_content.opening_hook
    assert service.get_candidate(project_id, candidate.id).state.value == "candidate"


def test_candidate_edit_preserves_locked_volume_and_rolling_plans(tmp_path: Path) -> None:
    database, project_id, director = _planning(tmp_path)
    snapshot = director.get_snapshot(project_id)
    assert snapshot.book_blueprint is not None
    director.update_book_blueprint(
        project_id,
        UpdateBookBlueprintRequest(
            content=snapshot.book_blueprint.content,
            lock_updates={BookBlueprintField.CORE_DESIRE: True},
            expected_revision=snapshot.book_blueprint.revision,
        ),
    )
    volume = snapshot.volume_plans[0]
    locked_volume = director.update_volume_plan(
        project_id,
        volume.id,
        UpdateVolumePlanRequest(
            content=VolumePlanContent.model_validate(volume.model_dump()),
            locked=True,
            expected_revision=volume.revision,
        ),
    )
    rolling = snapshot.rolling_chapter_plans[0]
    locked_rolling = director.update_rolling_plan(
        project_id,
        rolling.id,
        UpdateRollingChapterPlanRequest(
            content=RollingChapterPlanContent.model_validate(rolling.model_dump()),
            locked=True,
            expected_revision=rolling.revision,
        ),
    )
    service = PlanRebaseRepository(database)
    impact = service.get_impact(project_id)
    candidate = service.create_candidate(
        project_id,
        CreatePlanRebaseCandidateRequest(
            expected_dependency_fingerprint_sha256=(
                impact.current_dependency_fingerprint_sha256
            )
        ),
    )
    volume_edit = candidate.volume_plans[0].content.model_copy(
        update={"direction": "不得写入的锁定卷纲"}
    )
    common_rolling = _rolling_edits(candidate)
    with pytest.raises(PlanRebaseConflictError, match="locked_volume_plan"):
        service.update_candidate(
            project_id,
            candidate.id,
            UpdatePlanRebaseCandidateRequest(
                expected_revision=0,
                volume_plans=_volume_edits(
                    candidate,
                    {locked_volume.id: volume_edit},
                ),
                rolling_chapter_plans=common_rolling,
            ),
        )

    rolling_edit = next(
        item for item in candidate.rolling_chapter_plans if item.id == locked_rolling.id
    ).content.model_copy(update={"opening_hook": "不得写入的锁定章钩子"})
    with pytest.raises(PlanRebaseConflictError, match="locked_rolling_plan"):
        service.update_candidate(
            project_id,
            candidate.id,
            UpdatePlanRebaseCandidateRequest(
                expected_revision=0,
                volume_plans=_volume_edits(candidate),
                rolling_chapter_plans=_rolling_edits(
                    candidate,
                    {locked_rolling.id: rolling_edit},
                ),
            ),
        )

    assert candidate.book_blueprint is not None
    edited = service.update_candidate(
        project_id,
        candidate.id,
        UpdatePlanRebaseCandidateRequest(
            expected_revision=0,
            book_blueprint_content=candidate.book_blueprint.content.model_copy(
                update={"long_term_promise": "仅调整未锁定的长线承诺"}
            ),
            volume_plans=_volume_edits(candidate),
            rolling_chapter_plans=_rolling_edits(candidate),
        ),
    )
    adopted = service.adopt_candidate(
        project_id,
        candidate.id,
        AdoptPlanRebaseCandidateRequest(
            expected_revision=edited.revision,
            expected_dependency_fingerprint_sha256=(
                edited.target_dependency_fingerprint_sha256
            ),
            idempotency_key="preserve-all-locks",
        ),
    )
    assert adopted.planning.book_blueprint is not None
    assert adopted.planning.book_blueprint.locks[BookBlueprintField.CORE_DESIRE]
    assert adopted.planning.volume_plans[0].locked is True
    locked_after = next(
        item
        for item in adopted.planning.rolling_chapter_plans
        if item.id == locked_rolling.id
    )
    assert locked_after.locked is True
    assert locked_after.opening_hook == locked_rolling.opening_hook


def test_confirmed_topic_revision_change_marks_plans_stale(tmp_path: Path) -> None:
    database, project_id, _director = _planning(tmp_path)
    service = PlanRebaseRepository(database)
    service.bind_current_planning(project_id)
    topics = TopicDecisionService(
        database,
        JobRepository(database),
        AiGatewayManager(),
    )
    current = topics.get_decision(project_id)
    updated = topics.update_decision(
        project_id,
        UpdateTopicDecisionRequest(
            content=current.content.model_copy(
                update={"premise": "从竹木订单起步，重建小城产业信用"}
            ),
            changed_fields=[TopicDecisionField.PREMISE],
            expected_revision=current.revision,
        ),
    )
    blocked = service.get_impact(project_id)
    assert blocked.can_rebase is False
    assert "context_blocked" in blocked.reasons
    with pytest.raises(PlanRebaseConflictError, match="context_blocked"):
        service.create_candidate(
            project_id,
            CreatePlanRebaseCandidateRequest(
                expected_dependency_fingerprint_sha256=(
                    blocked.current_dependency_fingerprint_sha256
                )
            ),
        )
    topics.confirm_decision(
        project_id,
        ConfirmTopicDecisionRequest(expected_revision=updated.revision),
    )

    impact = service.get_impact(project_id)

    assert impact.reasons == ["topic_dependency_changed"]
    assert all(
        target.stale_reasons == ["topic_dependency_changed"]
        for target in impact.targets
    )


def test_active_writing_profile_revision_change_marks_plans_stale(tmp_path: Path) -> None:
    database, project_id, _director = _planning(tmp_path)
    link_id = _install_profile_stub(database, project_id)
    service = PlanRebaseRepository(database, _ToggleSafetyGate())
    service.bind_current_planning(project_id)

    with database.connect() as connection:
        connection.execute(
            """
            UPDATE project_writing_pattern_profiles
            SET lifecycle_revision = lifecycle_revision + 1,
                updated_at = '2026-09-12T00:01:00+00:00'
            WHERE id = ?
            """,
            (link_id,),
        )

    impact = service.get_impact(project_id)

    assert impact.reasons == ["writing_pattern_profile_dependency_changed"]
    assert all(
        target.state == CreativePlanDependencyState.STALE
        for target in impact.targets
    )

    with database.connect() as connection:
        connection.execute(
            "UPDATE writing_pattern_recipe_versions SET content_sha256 = ?",
            ("e" * 64,),
        )
    blocked = service.get_impact(project_id)
    assert blocked.can_rebase is False
    assert "context_blocked" in blocked.reasons


def test_failed_originality_gate_blocks_adoption_before_any_plan_write(
    tmp_path: Path,
) -> None:
    database, project_id, director = _planning(tmp_path)
    gate = _ToggleSafetyGate()
    service = PlanRebaseRepository(database, gate)
    impact = service.get_impact(project_id)
    candidate = service.create_candidate(
        project_id,
        CreatePlanRebaseCandidateRequest(
            expected_dependency_fingerprint_sha256=(
                impact.current_dependency_fingerprint_sha256
            )
        ),
    )
    before = director.get_snapshot(project_id)
    gate.blocked = True

    with pytest.raises(PlanRebaseConflictError, match="context_blocked"):
        service.adopt_candidate(
            project_id,
            candidate.id,
            AdoptPlanRebaseCandidateRequest(
                expected_revision=candidate.revision,
                expected_dependency_fingerprint_sha256=(
                    candidate.target_dependency_fingerprint_sha256
                ),
                idempotency_key="blocked-by-originality",
            ),
        )

    assert director.get_snapshot(project_id) == before


def test_open_rebase_candidate_becomes_stale_when_dependency_changes(
    tmp_path: Path,
) -> None:
    database, project_id, director = _planning(tmp_path)
    service = PlanRebaseRepository(database)
    impact = service.get_impact(project_id)
    candidate = service.create_candidate(
        project_id,
        CreatePlanRebaseCandidateRequest(
            expected_dependency_fingerprint_sha256=(
                impact.current_dependency_fingerprint_sha256
            )
        ),
    )
    blueprint = director.require_book_blueprint(project_id)
    director.update_book_blueprint(
        project_id,
        UpdateBookBlueprintRequest(
            content=blueprint.content.model_copy(
                update={"ending_direction": "作者在候选创建后更改了结局"}
            ),
            changed_fields=[BookBlueprintField.ENDING_DIRECTION],
            expected_revision=blueprint.revision,
        ),
    )
    with database.connect() as connection:
        before_get = connection.execute(
            "SELECT state, revision, updated_at FROM plan_rebase_candidates WHERE id = ?",
            (candidate.id,),
        ).fetchone()
    assert before_get is not None

    stale = service.get_candidate(project_id, candidate.id)

    assert stale.state.value == "stale"
    assert stale.revision == candidate.revision
    with database.connect() as connection:
        after_get = connection.execute(
            "SELECT state, revision, updated_at FROM plan_rebase_candidates WHERE id = ?",
            (candidate.id,),
        ).fetchone()
    assert after_get is not None
    assert tuple(after_get) == tuple(before_get) == (
        "candidate",
        candidate.revision,
        candidate.updated_at,
    )


def test_plan_rebase_routes_expose_impact_and_structured_conflicts(tmp_path: Path) -> None:
    database, project_id, _director = _planning(tmp_path)
    app = FastAPI()
    app.state.plan_rebase_service = PlanRebaseRepository(database)
    app.include_router(plan_rebase_router)

    with TestClient(app) as client:
        response = client.get(f"/api/projects/{project_id}/creative-context/impact")
        assert response.status_code == 200
        impact = response.json()
        assert impact["can_rebase"] is True
        created = client.post(
            f"/api/projects/{project_id}/plan-rebase-candidates",
            json={
                "expected_dependency_fingerprint_sha256": impact[
                    "current_dependency_fingerprint_sha256"
                ]
            },
        )
        assert created.status_code == 201
        candidate = created.json()
        fetched = client.get(
            f"/api/projects/{project_id}/plan-rebase-candidates/{candidate['id']}"
        )
        assert fetched.status_code == 200
        assert fetched.json()["id"] == candidate["id"]

        conflict = client.post(
            f"/api/projects/{project_id}/plan-rebase-candidates",
            json={"expected_dependency_fingerprint_sha256": "0" * 64},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == (
            "creative_context_dependency_changed"
        )
