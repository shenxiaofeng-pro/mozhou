from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from app.author_navigation import (
    ReconciliationCheckpoint,
    RollingPlanCheckpoint,
    build_author_next_action,
)
from app.canon_reconciliation.repository import CanonReconciliationRepository
from app.database import Database
from app.models import (
    AuthorNextActionKind,
    AuthorWorkflowStage,
    Chapter,
    ChapterStatus,
    CreateChapterRequest,
    CreateProjectRequest,
    DirectorSceneBeat,
    Genre,
    ProjectNextAction,
    RollingChapterPlan,
)
from app.repository import ProjectRepository


def _chapter(
    number: int,
    status: ChapterStatus = ChapterStatus.PLANNED,
    *,
    content: str = "",
    complete_brief: bool = False,
) -> Chapter:
    brief = "已确认" if complete_brief else ""
    return Chapter(
        id=f"chapter-{number}",
        project_id="project-1",
        volume_id="volume-1",
        volume_number=1,
        chapter_number=number,
        sort_key=number * 1024,
        title=f"第 {number} 章",
        content=content,
        reader_promise=brief,
        opening_hook=brief,
        state_change=brief,
        emotional_payoff=brief,
        ending_cliffhanger=brief,
        status=status,
        revision=number,
        updated_at="2026-09-12T00:00:00+00:00",
    )


def _rolling_plan(number: int) -> RollingChapterPlan:
    return RollingChapterPlan(
        id=f"rolling-{number}",
        project_id="project-1",
        volume_plan_id="volume-plan-1",
        chapter_number=number,
        title=f"第 {number} 章计划",
        reader_promise="兑现承诺",
        opening_hook="冲突入场",
        state_change="局面改变",
        resource_change="资源变化",
        emotional_payoff="情绪兑现",
        ending_cliffhanger="留下悬念",
        verification="状态发生可验证变化",
        scene_beats=[
            DirectorSceneBeat(
                ordinal=1,
                summary="冲突推进",
                state_change="主角作出选择",
                resource_change="资源承担代价",
                emotional_turn="压力转为行动",
                verification="选择改变下一步",
            )
        ],
        revision=0,
        locked=False,
        created_at="2026-09-12T00:00:00+00:00",
        updated_at="2026-09-12T00:00:00+00:00",
    )


@pytest.mark.parametrize(
    ("legacy", "kind", "stage"),
    [
        (
            ProjectNextAction.CONFIRM_TOPIC,
            AuthorNextActionKind.CONFIRM_TOPIC,
            AuthorWorkflowStage.TOPIC,
        ),
        (
            ProjectNextAction.REVIEW_TOPIC_CHANGES,
            AuthorNextActionKind.REVIEW_TOPIC_CHANGES,
            AuthorWorkflowStage.TOPIC,
        ),
        (
            ProjectNextAction.PLAN_BOOK,
            AuthorNextActionKind.PLAN_BOOK,
            AuthorWorkflowStage.BOOK,
        ),
        (
            ProjectNextAction.REVIEW_DOWNSTREAM_PLANS,
            AuthorNextActionKind.REVIEW_DOWNSTREAM_PLANS,
            AuthorWorkflowStage.BOOK,
        ),
    ],
)
def test_prewrite_next_actions_remain_author_decisions(
    legacy: ProjectNextAction,
    kind: AuthorNextActionKind,
    stage: AuthorWorkflowStage,
) -> None:
    result = build_author_next_action(
        legacy_action=legacy,
        chapters=[_chapter(1)],
        rolling_plans=[],
    )

    assert result.kind == kind
    assert result.target_stage == stage
    assert result.chapter_id is None


@pytest.mark.parametrize(
    ("chapter", "kind", "stage"),
    [
        (
            _chapter(1),
            AuthorNextActionKind.PLAN_CHAPTER,
            AuthorWorkflowStage.PLAN,
        ),
        (
            _chapter(1, complete_brief=True),
            AuthorNextActionKind.GENERATE_CHAPTER_CANDIDATE,
            AuthorWorkflowStage.CANDIDATE,
        ),
        (
            _chapter(1, ChapterStatus.DRAFTED, content="作者采用并调整的草稿"),
            AuthorNextActionKind.CONTINUE_CHAPTER_DRAFT,
            AuthorWorkflowStage.REVIEW,
        ),
        (
            _chapter(1, ChapterStatus.REVIEWING, content="等待作者最终审校"),
            AuthorNextActionKind.REVIEW_CHAPTER,
            AuthorWorkflowStage.REVIEW,
        ),
    ],
)
def test_chapter_state_selects_a_single_visible_stage(
    chapter: Chapter,
    kind: AuthorNextActionKind,
    stage: AuthorWorkflowStage,
) -> None:
    result = build_author_next_action(
        legacy_action=ProjectNextAction.CONTINUE_WRITING,
        chapters=[chapter],
        rolling_plans=[],
    )

    assert result.kind == kind
    assert result.target_stage == stage
    assert result.chapter_id == chapter.id


def test_approval_feedback_precedes_the_next_unfinished_chapter() -> None:
    chapters = [
        _chapter(1, ChapterStatus.APPROVED, content="第一章定稿"),
        _chapter(2),
    ]
    pending = build_author_next_action(
        legacy_action=ProjectNextAction.CONTINUE_WRITING,
        chapters=chapters,
        rolling_plans=[],
        reconciliation=ReconciliationCheckpoint(
            id="reconciliation-1",
            chapter_id="chapter-1",
            state="pending",
        ),
    )
    ready = build_author_next_action(
        legacy_action=ProjectNextAction.CONTINUE_WRITING,
        chapters=chapters,
        rolling_plans=[],
        reconciliation=ReconciliationCheckpoint(
            id="reconciliation-1",
            chapter_id="chapter-1",
            state="ready",
        ),
    )

    assert pending.kind == AuthorNextActionKind.REVIEW_CANON_RECONCILIATION
    assert pending.target_stage == AuthorWorkflowStage.FEEDBACK
    assert pending.blocked is True
    assert ready.blocked is False
    assert pending.chapter_id == "chapter-1"
    assert pending.last_approved_chapter_id == "chapter-1"


def test_canon_decision_surfaces_rolling_candidate_then_next_chapter() -> None:
    chapters = [
        _chapter(1, ChapterStatus.APPROVED, content="第一章定稿"),
        _chapter(2),
    ]
    rolling_review = build_author_next_action(
        legacy_action=ProjectNextAction.CONTINUE_WRITING,
        chapters=chapters,
        rolling_plans=[],
        rolling_replenishment=RollingPlanCheckpoint(
            id="replenishment-1",
            source_chapter_id="chapter-1",
        ),
    )
    next_chapter = build_author_next_action(
        legacy_action=ProjectNextAction.CONTINUE_WRITING,
        chapters=chapters,
        rolling_plans=[],
    )

    assert rolling_review.kind == AuthorNextActionKind.REVIEW_ROLLING_PLAN
    assert rolling_review.rolling_plan_replenishment_id == "replenishment-1"
    assert next_chapter.kind == AuthorNextActionKind.PLAN_CHAPTER
    assert next_chapter.chapter_id == "chapter-2"
    assert next_chapter.last_approved_chapter_id == "chapter-1"


def test_all_written_chapters_use_a_future_plan_or_finish_the_project() -> None:
    chapters = [_chapter(1, ChapterStatus.APPROVED, content="全书定稿")]
    continue_book = build_author_next_action(
        legacy_action=ProjectNextAction.CONTINUE_WRITING,
        chapters=chapters,
        rolling_plans=[_rolling_plan(2)],
    )
    completed = build_author_next_action(
        legacy_action=ProjectNextAction.CONTINUE_WRITING,
        chapters=chapters,
        rolling_plans=[],
    )

    assert continue_book.kind == AuthorNextActionKind.CREATE_NEXT_CHAPTER
    assert continue_book.chapter_id is None
    assert continue_book.chapter_number == 2
    assert continue_book.rolling_plan_id == "rolling-2"
    assert completed.kind == AuthorNextActionKind.PROJECT_COMPLETE
    assert completed.target_stage == AuthorWorkflowStage.COMPLETE


def test_workspace_refresh_reflects_atomic_approval_and_reconciliation_decision(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "author-navigation.db")
    database.initialize()
    projects = ProjectRepository(database)
    workspace = projects.create_project(
        CreateProjectRequest(
            title="连续创作测试",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1998,
            rebirth_location="福建南平",
            chapter_target_words=3_000,
            safety_buffer_chapters=3,
        )
    )
    chapter = workspace.chapters[0]
    with database.connect() as connection:
        connection.execute(
            "DELETE FROM topic_decisions WHERE project_id = ?",
            (workspace.project.id,),
        )
        connection.execute(
            """
            UPDATE chapters
            SET content = ?, reader_promise = ?, opening_hook = ?, state_change = ?,
                emotional_payoff = ?, ending_cliffhanger = ?, status = 'reviewing', revision = 1
            WHERE id = ?
            """,
            ("主角作出选择。", "兑现", "冲突", "选择", "回报", "新问题", chapter.id),
        )

    approval = CanonReconciliationRepository(database).approve_chapter_and_enqueue(
        project_id=workspace.project.id,
        chapter_id=chapter.id,
        expected_revision=1,
        expected_content_sha256=sha256("主角作出选择。".encode()).hexdigest(),
    )
    awaiting_feedback = projects.get_workspace_summary(workspace.project.id)

    assert awaiting_feedback.author_next_action is not None
    assert (
        awaiting_feedback.author_next_action.kind
        == AuthorNextActionKind.REVIEW_CANON_RECONCILIATION
    )
    assert awaiting_feedback.author_next_action.reconciliation_id == approval.reconciliation.id
    assert awaiting_feedback.resume_card is not None
    assert awaiting_feedback.resume_card.next_action == awaiting_feedback.author_next_action

    with database.connect() as connection:
        connection.execute(
            "UPDATE canon_reconciliations SET state = 'failed' WHERE id = ?",
            (approval.reconciliation.id,),
        )
    failed_feedback = projects.get_workspace_summary(workspace.project.id)
    assert failed_feedback.author_next_action is not None
    assert (
        failed_feedback.author_next_action.kind
        == AuthorNextActionKind.REVIEW_CANON_RECONCILIATION
    )
    assert failed_feedback.author_next_action.reconciliation_id == approval.reconciliation.id
    assert failed_feedback.author_next_action.blocked is False

    with database.connect() as connection:
        connection.execute(
            "UPDATE canon_reconciliations SET state = 'decided' WHERE id = ?",
            (approval.reconciliation.id,),
        )
    completed = projects.get_workspace_summary(workspace.project.id)
    assert completed.author_next_action is not None
    assert completed.author_next_action.kind == AuthorNextActionKind.PROJECT_COMPLETE

    projects.create_chapter(
        workspace.project.id,
        CreateChapterRequest(expected_last_chapter_number=1),
    )
    continued = projects.get_workspace_summary(workspace.project.id)
    assert continued.author_next_action is not None
    assert continued.author_next_action.kind == AuthorNextActionKind.PLAN_CHAPTER
    assert continued.author_next_action.chapter_number == 2
