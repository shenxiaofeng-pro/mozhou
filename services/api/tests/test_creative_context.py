import json
from pathlib import Path

import pytest

from app.context import (
    ContextRepository,
    CreativeContextBlockedError,
    CreativeContextChangedError,
    CreativeContextCompileRequest,
    CreativeContextPurpose,
    CreativeContextService,
    CreativeContextSubject,
    CreativeContextSubjectKind,
)
from app.database import Database
from app.director.repository import DirectorRepository
from app.models import (
    BookBlueprintContent,
    CreateChapterRequest,
    CreateProjectRequest,
    DirectorStartupCandidate,
    Genre,
    UpdateChapterRequest,
)
from app.repository import ProjectRepository
from app.writing_patterns.models import (
    ModelSafeWritingPatternProfile,
    ModelSafeWritingPatternRule,
    WritingPatternLifecycleState,
    WritingPatternProfileVersion,
    WritingPatternSafetyBasis,
)


class _FixedProfileRepository:
    def __init__(self, profile: WritingPatternProfileVersion) -> None:
        self.profile = profile

    def get_active_profile(self, _project_id: str) -> WritingPatternProfileVersion:
        return self.profile


def _profile(project_id: str, *, rule_count: int = 10) -> WritingPatternProfileVersion:
    digest = "a" * 64
    model_profile = ModelSafeWritingPatternProfile(
        compiler_version="recipe-v1",
        topic_revision=1,
        topic_content_sha256="b" * 64,
        recipe_content_sha256="c" * 64,
        safety_basis=WritingPatternSafetyBasis.SOURCE_VERIFIED,
        rules=[
            ModelSafeWritingPatternRule(
                source_content_sha256=f"{index:064x}",
                dimension="hook_mechanics",
                name=f"来源技法 {index}",
                transferable_rule=f"主角加入赤月剑宗后，用三步压力递增形成章末钩子 {index}。",
                adaptation_risk="不得复制《星海旧事》中的人物与证据。",
                purpose="learn",
                strategy="transform",
                weight_basis_points=1_000,
                applicable_stages=[
                    "chapter_brief",
                    "chapter_draft",
                    "review",
                ],
                chapter_start=1,
                chapter_end=30,
            )
            for index in range(rule_count)
        ],
    )
    return WritingPatternProfileVersion(
        id="profile-version",
        project_id=project_id,
        recipe_version_id="recipe-version",
        recipe_content_sha256="c" * 64,
        topic_revision=1,
        topic_content_sha256="b" * 64,
        safety_basis=WritingPatternSafetyBasis.SOURCE_VERIFIED,
        profile_fingerprint_sha256=digest,
        lifecycle_state=WritingPatternLifecycleState.ACTIVE,
        lifecycle_revision=0,
        is_current=True,
        created_at="2026-09-12T00:00:00+00:00",
        updated_at="2026-09-12T00:00:00+00:00",
        topic_decision_version_id="topic-version",
        compiler_version="recipe-v1",
        source_snapshot_sha256="d" * 64,
        model_safe_profile=model_profile,
        conflicts=[],
        decisions=[],
        excluded_entry_keys=[],
    )


def _project(database: Database) -> tuple[ProjectRepository, str, str]:
    projects = ProjectRepository(database)
    workspace = projects.create_project(
        CreateProjectRequest(
            title="南平回潮",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1998,
            rebirth_location="福建南平",
        )
    )
    return projects, workspace.project.id, workspace.chapters[0].id


def _add_blueprint(database: Database, project_id: str) -> None:
    DirectorRepository(database).select_startup_candidate(
        project_id,
        "一九九八年回到南平改写家庭和产业命运",
        DirectorStartupCandidate(
            id="candidate",
            ordinal=1,
            label="现实产业线",
            blueprint=BookBlueprintContent(
                title="南平回潮",
                genre=Genre.URBAN_REBIRTH,
                rebirth_year=1998,
                rebirth_location="福建南平",
                target_audience="偏好现实成长的网文读者",
                core_selling_points=["真实产业变迁"],
                core_desire="保住家人并弥补遗憾",
                divergence_point="抢下一张即将违约的订单",
                long_term_promise="建立可复制的竹木产业网",
                ending_direction="让家人和工人共享成果",
                protagonist_arc="从独断走向信任与责任",
                resource_growth="订单、现金流和渠道逐步扩张",
                relationship_design="父子冲突后形成并肩合作",
            ),
            why_distinct="以小城产业为资源飞轮",
            risks=[],
        ),
        None,
    )


def test_creative_context_compiles_brief_through_one_persisted_interface(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "creative-context.db")
    database.initialize()
    projects, project_id, chapter_id = _project(database)
    workspace = projects.get_workspace(project_id)
    service = CreativeContextService(
        projects,
        ContextRepository(database),
    )

    packet = service.compile(
        workspace,
        CreativeContextCompileRequest(
            purpose=CreativeContextPurpose.BRIEF,
            subject=CreativeContextSubject(
                kind=CreativeContextSubjectKind.CHAPTER,
                id=chapter_id,
                revision=0,
            ),
            token_budget=8_000,
            author_intent="先让主角解决家庭危机",
        ),
    )

    assert packet.purpose == CreativeContextPurpose.BRIEF
    assert packet.subject.kind == CreativeContextSubjectKind.CHAPTER
    assert packet.subject.id == chapter_id
    assert packet.blocking_reasons == []
    assert packet.task_type is not None
    assert service.require_usable(packet) == packet
    assert ContextRepository(database).get_packet(packet.id) == packet
    rendered = json.loads(packet.rendered_context)
    assert rendered["creative_context"]["purpose"] == "brief"
    assert "source_refs" not in packet.rendered_context
    assert chapter_id not in packet.rendered_context


def test_creative_context_rejects_mismatched_subject_before_persisting(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "creative-context-subject.db")
    database.initialize()
    projects, project_id, _chapter_id = _project(database)
    service = CreativeContextService(projects, ContextRepository(database))

    with pytest.raises(ValueError, match="purpose_subject_mismatch"):
        service.compile(
            projects.get_workspace(project_id),
            CreativeContextCompileRequest(
                purpose=CreativeContextPurpose.BRIEF,
                subject=CreativeContextSubject(
                    kind=CreativeContextSubjectKind.PROJECT,
                    id=project_id,
                    revision=0,
                ),
                token_budget=8_000,
            ),
        )


@pytest.mark.parametrize("budget", [8_000, 16_000, 24_000])
@pytest.mark.parametrize("rule_count", [2, 5, 10])
def test_current_pattern_profile_is_required_compact_and_safe_at_every_budget(
    tmp_path: Path,
    budget: int,
    rule_count: int,
) -> None:
    database = Database(
        tmp_path / f"creative-context-profile-{budget}-{rule_count}.db"
    )
    database.initialize()
    projects, project_id, chapter_id = _project(database)
    profile = _profile(project_id, rule_count=rule_count)
    service = CreativeContextService(
        projects,
        ContextRepository(database),
        patterns=_FixedProfileRepository(profile),  # type: ignore[arg-type]
    )

    packet = service.compile(
        projects.get_workspace(project_id),
        CreativeContextCompileRequest(
            purpose=CreativeContextPurpose.DRAFT,
            subject=CreativeContextSubject(
                kind=CreativeContextSubjectKind.CHAPTER,
                id=chapter_id,
                revision=0,
            ),
            token_budget=budget,
        ),
    )

    profile_items = [
        item for item in packet.items if item.kind.value == "writing_pattern_profile"
    ]
    assert len(profile_items) == 1
    assert profile_items[0].required and profile_items[0].included
    assert packet.profile_fingerprint_sha256 == profile.profile_fingerprint_sha256
    assert "source_content_sha256" not in packet.rendered_context
    assert '"name"' not in profile_items[0].content
    assert "赤月剑宗" not in packet.rendered_context
    assert "星海旧事" not in packet.rendered_context
    assert "[来源专名]" in packet.rendered_context


@pytest.mark.parametrize(
    ("purpose", "subject_kind"),
    [
        (CreativeContextPurpose.STARTUP, CreativeContextSubjectKind.PROJECT),
        (CreativeContextPurpose.EXPANSION, CreativeContextSubjectKind.BOOK_BLUEPRINT),
        (CreativeContextPurpose.FIELD, CreativeContextSubjectKind.BOOK_BLUEPRINT),
        (CreativeContextPurpose.BRIEF, CreativeContextSubjectKind.CHAPTER),
        (CreativeContextPurpose.DRAFT, CreativeContextSubjectKind.CHAPTER),
        (CreativeContextPurpose.CANDIDATE_REVIEW, CreativeContextSubjectKind.CHAPTER),
        (CreativeContextPurpose.CANON_RECONCILIATION, CreativeContextSubjectKind.CHAPTER),
    ],
)
def test_every_purpose_uses_same_safe_profile_and_persisted_interface(
    tmp_path: Path,
    purpose: CreativeContextPurpose,
    subject_kind: CreativeContextSubjectKind,
) -> None:
    database = Database(tmp_path / f"creative-context-{purpose.value}.db")
    database.initialize()
    projects, project_id, chapter_id = _project(database)
    _add_blueprint(database, project_id)
    workspace = projects.get_workspace(project_id)
    assert workspace.book_blueprint is not None
    profile = _profile(project_id)
    service = CreativeContextService(
        projects,
        ContextRepository(database),
        patterns=_FixedProfileRepository(profile),
    )
    subject = {
        CreativeContextSubjectKind.PROJECT: CreativeContextSubject(
            kind=subject_kind,
            id=project_id,
        ),
        CreativeContextSubjectKind.BOOK_BLUEPRINT: CreativeContextSubject(
            kind=subject_kind,
            id=workspace.book_blueprint.id,
            revision=workspace.book_blueprint.revision,
        ),
        CreativeContextSubjectKind.CHAPTER: CreativeContextSubject(
            kind=subject_kind,
            id=chapter_id,
            revision=workspace.chapters[0].revision,
        ),
    }[subject_kind]

    packet = service.compile(
        workspace,
        CreativeContextCompileRequest(
            purpose=purpose,
            subject=subject,
            token_budget=24_000,
            author_intent="只增强主角的主动选择",
            target_field=(
                "core_desire" if purpose == CreativeContextPurpose.FIELD else None
            ),
        ),
    )

    assert service.require_usable(packet) == packet
    assert packet.profile_fingerprint_sha256 == profile.profile_fingerprint_sha256
    assert packet.purpose == purpose
    assert packet.subject.kind == subject_kind
    assert ContextRepository(database).get_packet(packet.id) == packet
    assert any(item.kind.value == "writing_pattern_profile" for item in packet.items)
    for forbidden in (
        "source_content_sha256",
        "赤月剑宗",
        "星海旧事",
        project_id,
        chapter_id,
    ):
        assert forbidden not in packet.rendered_context


def test_required_profile_over_budget_blocks_explicitly(tmp_path: Path) -> None:
    database = Database(tmp_path / "creative-context-overflow.db")
    database.initialize()
    projects, project_id, chapter_id = _project(database)
    profile = _profile(project_id, rule_count=500)
    profile = profile.model_copy(
        update={
            "model_safe_profile": profile.model_safe_profile.model_copy(
                update={
                    "rules": [
                        rule.model_copy(
                            update={
                                "transferable_rule": rule.transferable_rule
                                + "每个场景的压力、代价和反转必须逐步改变人物决策。" * 20
                            }
                        )
                        for rule in profile.model_safe_profile.rules
                    ]
                }
            )
        }
    )
    service = CreativeContextService(
        projects,
        ContextRepository(database),
        patterns=_FixedProfileRepository(profile),
    )

    packet = service.compile(
        projects.get_workspace(project_id),
        CreativeContextCompileRequest(
            purpose=CreativeContextPurpose.DRAFT,
            subject=CreativeContextSubject(
                kind=CreativeContextSubjectKind.CHAPTER,
                id=chapter_id,
                revision=0,
            ),
            token_budget=8_000,
        ),
    )

    assert packet.overflow_tokens > 0
    assert packet.blocking_reasons == [
        "writing_pattern_profile_over_limit",
        "required_context_over_budget",
    ]
    with pytest.raises(CreativeContextBlockedError, match="required_context_over_budget"):
        service.require_usable(packet)


@pytest.mark.parametrize(
    "purpose",
    [
        CreativeContextPurpose.CANDIDATE_REVIEW,
        CreativeContextPurpose.CANON_RECONCILIATION,
    ],
)
def test_review_window_dependency_invalidates_packet_when_prior_chapter_changes(
    tmp_path: Path,
    purpose: CreativeContextPurpose,
) -> None:
    database = Database(tmp_path / f"review-window-{purpose.value}.db")
    database.initialize()
    projects, project_id, first_id = _project(database)
    first = projects.update_chapter(
        first_id,
        UpdateChapterRequest(content="第一章原始正文", expected_revision=0),
    )
    second = projects.create_chapter(
        project_id,
        CreateChapterRequest(expected_last_chapter_number=1, title="第二章"),
    )
    projects.update_chapter(
        second.id,
        UpdateChapterRequest(content="第二章原始正文", expected_revision=second.revision),
    )
    third = projects.create_chapter(
        project_id,
        CreateChapterRequest(expected_last_chapter_number=2, title="第三章"),
    )
    third = projects.update_chapter(
        third.id,
        UpdateChapterRequest(content="第三章原始正文", expected_revision=third.revision),
    )
    service = CreativeContextService(projects, ContextRepository(database))
    packet = service.compile(
        projects.get_workspace(project_id),
        CreativeContextCompileRequest(
            purpose=purpose,
            subject=CreativeContextSubject(
                kind=CreativeContextSubjectKind.CHAPTER,
                id=third.id,
                revision=third.revision,
            ),
            token_budget=24_000,
            window_size=3,
        ),
    )

    assert service.require_current(packet) == packet
    projects.update_chapter(
        first.id,
        UpdateChapterRequest(
            content="第一章已被作者改写",
            expected_revision=first.revision,
        ),
    )

    with pytest.raises(
        CreativeContextChangedError,
        match="creative_context_dependency_changed",
    ):
        service.require_current(packet)
