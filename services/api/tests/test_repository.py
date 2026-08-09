from pathlib import Path

import pytest

from app.database import Database
from app.models import (
    ApplyFactChangeSetRequest,
    ChapterStatus,
    CreateChapterRequest,
    CreateFutureKnowledgeRequest,
    CreateProjectRequest,
    CreateSourceCardRequest,
    CreateStoryEntityRequest,
    CreateTimelineEventRequest,
    Genre,
    KnowledgeConfidence,
    KnowledgeReviewAction,
    RejectFactChangeSetRequest,
    ReviewFutureKnowledgeRequest,
    SetSourceCardConfirmationRequest,
    SourceConfidence,
    SourceKind,
    StoryEntityKind,
    StoryThreadStatus,
    TransitionChapterRequest,
    TransitionStoryThreadRequest,
    UpdateChapterBriefRequest,
    UpdateChapterRequest,
    UpdateStoryEntityRequest,
)
from app.repository import (
    InvalidChapterStateError,
    ProjectRepository,
    StaleChapterSequenceError,
    StaleRevisionError,
)


@pytest.fixture
def repository(tmp_path: Path) -> ProjectRepository:
    database = Database(tmp_path / "mozhou.db")
    database.initialize()
    return ProjectRepository(database)


def test_create_project_also_creates_first_chapter(repository: ProjectRepository) -> None:
    workspace = repository.create_project(
        CreateProjectRequest(
            title="南平旧事",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=2001,
            rebirth_location="福建南平",
        )
    )

    assert workspace.project.title == "南平旧事"
    assert workspace.chapters[0].title == "第一章 未命名"
    assert workspace.chapters[0].revision == 0


def test_project_title_is_stored_as_data(repository: ProjectRepository) -> None:
    suspicious_title = "旧梦'); DROP TABLE projects; --"
    workspace = repository.create_project(
        CreateProjectRequest(
            title=suspicious_title,
            genre=Genre.HISTORICAL_REBIRTH,
            rebirth_year=1127,
            rebirth_location="建州",
        )
    )

    loaded = repository.get_workspace(workspace.project.id)

    assert loaded.project.title == suspicious_title


def test_chapter_update_uses_optimistic_revision(repository: ProjectRepository) -> None:
    workspace = repository.create_project(
        CreateProjectRequest(
            title="闽北来信",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1998,
            rebirth_location="南平",
        )
    )
    chapter = workspace.chapters[0]

    updated = repository.update_chapter(
        chapter.id,
        UpdateChapterRequest(content="雨落在站前路。", expected_revision=0),
    )

    assert updated.revision == 1
    assert updated.content == "雨落在站前路。"
    with pytest.raises(StaleRevisionError):
        repository.update_chapter(
            chapter.id,
            UpdateChapterRequest(content="过期内容", expected_revision=0),
        )


def test_chapter_brief_uses_the_same_optimistic_revision(repository: ProjectRepository) -> None:
    workspace = repository.create_project(
        CreateProjectRequest(
            title="九八年的第一桶金",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1998,
            rebirth_location="福建南平",
        )
    )
    chapter = workspace.chapters[0]

    updated = repository.update_chapter_brief(
        chapter.id,
        UpdateChapterBriefRequest(
            opening_hook="主角在拆迁通知贴出前醒来",
            state_change="拿到第一笔启动资金",
            ending_cliffhanger="上一世的对手提前出现",
            expected_revision=0,
        ),
    )

    assert updated.revision == 1
    assert updated.opening_hook == "主角在拆迁通知贴出前醒来"
    assert updated.state_change == "拿到第一笔启动资金"
    assert updated.ending_cliffhanger == "上一世的对手提前出现"
    with pytest.raises(StaleRevisionError):
        repository.update_chapter(
            chapter.id,
            UpdateChapterRequest(content="基于旧 revision 的正文", expected_revision=0),
        )


def test_create_chapter_requires_current_sequence(repository: ProjectRepository) -> None:
    workspace = repository.create_project(
        CreateProjectRequest(
            title="南平潮生",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1998,
            rebirth_location="福建南平",
        )
    )

    chapter = repository.create_chapter(
        workspace.project.id,
        CreateChapterRequest(
            expected_last_chapter_number=1,
            opening_hook="县里突然收紧贷款",
        ),
    )

    assert chapter.chapter_number == 2
    assert chapter.title == "第2章 未命名"
    assert chapter.opening_hook == "县里突然收紧贷款"
    with pytest.raises(StaleChapterSequenceError):
        repository.create_chapter(
            workspace.project.id,
            CreateChapterRequest(expected_last_chapter_number=1),
        )


def test_chapter_state_machine_records_events_and_locks_approved_text(
    repository: ProjectRepository,
) -> None:
    workspace = repository.create_project(
        CreateProjectRequest(
            title="南平旧事",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1998,
            rebirth_location="福建南平",
        )
    )
    chapter = workspace.chapters[0]
    with pytest.raises(InvalidChapterStateError):
        repository.transition_chapter(
            chapter.id,
            TransitionChapterRequest(target_status=ChapterStatus.REVIEWING, expected_revision=0),
        )
    chapter = repository.update_chapter(
        chapter.id,
        UpdateChapterRequest(content="雨落在站前路。", expected_revision=0),
    )
    chapter = repository.update_chapter_brief(
        chapter.id,
        UpdateChapterBriefRequest(
            title="第一章 旧站",
            opening_hook="停产通知提前贴出",
            state_change="保住父亲的工作",
            ending_cliffhanger="厂长认出了主角",
            expected_revision=chapter.revision,
        ),
    )

    for target in (
        ChapterStatus.DRAFTED,
        ChapterStatus.REVIEWING,
        ChapterStatus.APPROVED,
    ):
        chapter = repository.transition_chapter(
            chapter.id,
            TransitionChapterRequest(target_status=target, expected_revision=chapter.revision),
        )

    assert chapter.status == ChapterStatus.APPROVED
    assert chapter.title == "第一章 旧站"
    with pytest.raises(InvalidChapterStateError):
        repository.update_chapter(
            chapter.id,
            UpdateChapterRequest(content="不应覆盖定稿", expected_revision=chapter.revision),
        )
    with repository.database.connect() as connection:
        events = connection.execute(
            """
            SELECT from_status, to_status, revision
            FROM chapter_events WHERE chapter_id = ? ORDER BY revision
            """,
            (chapter.id,),
        ).fetchall()
    assert [tuple(event) for event in events] == [
        ("planned", "drafted", 3),
        ("drafted", "reviewing", 4),
        ("reviewing", "approved", 5),
    ]


def approve_first_chapter(repository: ProjectRepository):
    workspace = repository.create_project(
        CreateProjectRequest(
            title="回到九八年的南平",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1998,
            rebirth_location="福建南平",
        )
    )
    chapter = repository.update_chapter(
        workspace.chapters[0].id,
        UpdateChapterRequest(content="列车驶入南平站。", expected_revision=0),
    )
    chapter = repository.update_chapter_brief(
        chapter.id,
        UpdateChapterBriefRequest(
            title="第一章 旧站",
            opening_hook="停产通知提前贴出",
            state_change="保住父亲的工作",
            ending_cliffhanger="厂长认出了主角",
            expected_revision=chapter.revision,
        ),
    )
    for target in (
        ChapterStatus.DRAFTED,
        ChapterStatus.REVIEWING,
        ChapterStatus.APPROVED,
    ):
        chapter = repository.transition_chapter(
            chapter.id,
            TransitionChapterRequest(target_status=target, expected_revision=chapter.revision),
        )
    return workspace.project, chapter


def test_original_timeline_and_confirmed_facts_stay_in_separate_layers(
    repository: ProjectRepository,
) -> None:
    project, chapter = approve_first_chapter(repository)
    original = repository.create_original_timeline_event(
        project.id,
        CreateTimelineEventRequest(
            event_year=1998,
            title="南平铝厂推进改制",
            summary="现实世界资料锚点",
        ),
    )

    candidate = repository.create_fact_change_set(chapter.id)
    same_candidate = repository.create_fact_change_set(chapter.id)
    before_apply = repository.get_workspace(project.id)
    applied = repository.apply_fact_change_set(
        candidate.id,
        ApplyFactChangeSetRequest(
            selected_change_ids=[change.id for change in candidate.changes],
            expected_revision=0,
        ),
    )
    after_apply = repository.get_workspace(project.id)

    assert original.layer.value == "original"
    assert candidate.id == same_candidate.id
    assert {change.kind.value for change in candidate.changes} == {"state_change", "open_thread"}
    assert before_apply.story_facts == []
    assert [event.layer.value for event in before_apply.timeline_events] == ["original"]
    assert applied.state.value == "applied"
    assert len(after_apply.story_facts) == 2
    assert {event.layer.value for event in after_apply.timeline_events} == {"original", "novel"}
    novel = next(event for event in after_apply.timeline_events if event.layer.value == "novel")
    assert novel.summary == "保住父亲的工作"
    assert novel.source_chapter_id == chapter.id


def test_rejected_fact_changes_do_not_enter_canon(repository: ProjectRepository) -> None:
    project, chapter = approve_first_chapter(repository)
    candidate = repository.create_fact_change_set(chapter.id)

    rejected = repository.reject_fact_change_set(
        candidate.id,
        RejectFactChangeSetRequest(expected_revision=0),
    )
    workspace = repository.get_workspace(project.id)

    assert rejected.state.value == "rejected"
    assert workspace.story_facts == []
    assert workspace.timeline_events == []


def test_fact_change_set_requires_an_approved_chapter(repository: ProjectRepository) -> None:
    workspace = repository.create_project(
        CreateProjectRequest(
            title="南平旧事",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1998,
            rebirth_location="福建南平",
        )
    )

    with pytest.raises(InvalidChapterStateError):
        repository.create_fact_change_set(workspace.chapters[0].id)


def test_divergence_only_marks_future_knowledge_as_candidate_invalid(
    repository: ProjectRepository,
) -> None:
    project, chapter = approve_first_chapter(repository)
    knowledge = repository.create_future_knowledge(
        project.id,
        CreateFutureKnowledgeRequest(
            future_year=2003,
            content="建阳会在这一年开出第一家大型连锁超市",
            source_note="主角上一世亲历",
            confidence=KnowledgeConfidence.CERTAIN,
        ),
    )
    candidate = repository.create_fact_change_set(chapter.id)
    state_change = next(change for change in candidate.changes if change.kind.value == "state_change")

    repository.apply_fact_change_set(
        candidate.id,
        ApplyFactChangeSetRequest(
            selected_change_ids=[state_change.id],
            expected_revision=0,
        ),
    )
    pending = repository.get_workspace(project.id).future_knowledge[0]
    kept = repository.review_future_knowledge(
        knowledge.id,
        ReviewFutureKnowledgeRequest(
            action=KnowledgeReviewAction.KEEP_VALID,
            expected_revision=pending.revision,
        ),
    )

    assert knowledge.status.value == "valid"
    assert pending.status.value == "candidate_invalid"
    assert pending.divergence_event_id is not None
    assert kept.status.value == "valid"
    assert kept.revision == 2


def test_future_knowledge_cannot_predate_rebirth(repository: ProjectRepository) -> None:
    workspace = repository.create_project(
        CreateProjectRequest(
            title="南平旧事",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1998,
            rebirth_location="福建南平",
        )
    )

    with pytest.raises(ValueError):
        repository.create_future_knowledge(
            workspace.project.id,
            CreateFutureKnowledgeRequest(
                future_year=1997,
                content="不应允许",
            ),
        )


def test_character_and_resource_ledger_use_optimistic_revisions(
    repository: ProjectRepository,
) -> None:
    workspace = repository.create_project(
        CreateProjectRequest(
            title="南平旧事",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1998,
            rebirth_location="福建南平",
        )
    )
    character = repository.create_story_entity(
        workspace.project.id,
        CreateStoryEntityRequest(
            kind=StoryEntityKind.CHARACTER,
            name="沈砚",
            role="重生者",
            goal="保住父亲的工作",
            current_state="刚回到南平",
            relationship_notes="与父亲存在上一世未解的隔阂",
        ),
    )
    resource = repository.create_story_entity(
        workspace.project.id,
        CreateStoryEntityRequest(
            kind=StoryEntityKind.RESOURCE,
            name="改制名单",
            role="信息资源",
            goal="用于提前组织工人",
            current_state="由沈砚持有复印件",
        ),
    )
    updated = repository.update_story_entity(
        character.id,
        UpdateStoryEntityRequest(
            name=character.name,
            role=character.role,
            goal=character.goal,
            current_state="已进入厂长办公室",
            relationship_notes=character.relationship_notes,
            expected_revision=0,
        ),
    )

    assert resource.kind == StoryEntityKind.RESOURCE
    assert updated.current_state == "已进入厂长办公室"
    assert updated.revision == 1
    with pytest.raises(StaleRevisionError):
        repository.update_story_entity(
            character.id,
            UpdateStoryEntityRequest(
                name=character.name,
                role=character.role,
                goal=character.goal,
                current_state="过期状态",
                relationship_notes=character.relationship_notes,
                expected_revision=0,
            ),
        )


def test_confirmed_open_thread_enters_the_thread_ledger(repository: ProjectRepository) -> None:
    project, chapter = approve_first_chapter(repository)
    candidate = repository.create_fact_change_set(chapter.id)
    open_thread = next(change for change in candidate.changes if change.kind.value == "open_thread")

    repository.apply_fact_change_set(
        candidate.id,
        ApplyFactChangeSetRequest(
            selected_change_ids=[open_thread.id],
            expected_revision=0,
        ),
    )
    thread = repository.get_workspace(project.id).story_threads[0]
    resolved = repository.transition_story_thread(
        thread.id,
        TransitionStoryThreadRequest(
            target_status=StoryThreadStatus.RESOLVED,
            resolved_chapter_id=chapter.id,
            expected_revision=0,
        ),
    )

    assert thread.title == "厂长认出了主角"
    assert thread.status == StoryThreadStatus.OPEN
    assert thread.planted_chapter_number == 1
    assert resolved.status == StoryThreadStatus.RESOLVED
    assert resolved.resolved_chapter_id == chapter.id


def test_source_cards_require_explicit_confirmation(repository: ProjectRepository) -> None:
    workspace = repository.create_project(
        CreateProjectRequest(
            title="回到九八年的南平",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1998,
            rebirth_location="福建南平",
        )
    )
    card = repository.create_source_card(
        workspace.project.id,
        CreateSourceCardRequest(
            source_kind=SourceKind.INDUSTRY,
            title="南平铝厂改制资料",
            source_reference="作者本地档案 1998-04",
            applicable_year_start=1998,
            applicable_year_end=1999,
            confidence=SourceConfidence.HIGH,
            excerpt="先进行岗位摸底，再公布分流方案。",
        ),
    )
    confirmed = repository.set_source_card_confirmation(
        card.id,
        SetSourceCardConfirmationRequest(confirmed=True, expected_revision=0),
    )

    assert card.confirmed is False
    assert confirmed.confirmed is True
    assert confirmed.revision == 1
