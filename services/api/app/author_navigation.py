from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.models import (
    AuthorNextAction,
    AuthorNextActionKind,
    AuthorWorkflowStage,
    AuthorWorkspaceView,
    Chapter,
    ChapterStatus,
    ChapterSummary,
    ProjectNextAction,
    RollingChapterPlan,
)

ChapterView = Chapter | ChapterSummary


@dataclass(frozen=True)
class ReconciliationCheckpoint:
    id: str
    chapter_id: str
    state: Literal["pending", "ready", "failed"]


@dataclass(frozen=True)
class RollingPlanCheckpoint:
    id: str
    source_chapter_id: str


def build_author_next_action(
    *,
    legacy_action: ProjectNextAction,
    chapters: Sequence[ChapterView],
    rolling_plans: Sequence[RollingChapterPlan],
    reconciliation: ReconciliationCheckpoint | None = None,
    rolling_replenishment: RollingPlanCheckpoint | None = None,
) -> AuthorNextAction:
    """Choose one deterministic, author-owned next step from persisted state.

    The legacy topic/book action remains authoritative until writing can start.
    Once writing is available, approval feedback is settled before the next
    unfinished chapter. AI output is only ever surfaced as a candidate stage.
    """

    ordered_chapters = sorted(chapters, key=lambda item: item.chapter_number)
    approved = [item for item in ordered_chapters if item.status == ChapterStatus.APPROVED]
    last_approved = approved[-1] if approved else None
    legacy = _legacy_action(legacy_action, last_approved)
    if legacy is not None:
        return legacy

    if reconciliation is not None:
        chapter = _chapter_by_id(ordered_chapters, reconciliation.chapter_id)
        return AuthorNextAction(
            kind=AuthorNextActionKind.REVIEW_CANON_RECONCILIATION,
            target_view=AuthorWorkspaceView.WRITING,
            target_stage=AuthorWorkflowStage.FEEDBACK,
            chapter_id=reconciliation.chapter_id,
            chapter_number=chapter.chapter_number if chapter is not None else None,
            last_approved_chapter_id=(last_approved.id if last_approved is not None else None),
            reconciliation_id=reconciliation.id,
            blocked=reconciliation.state == "pending",
        )

    if rolling_replenishment is not None:
        chapter = _chapter_by_id(ordered_chapters, rolling_replenishment.source_chapter_id)
        return AuthorNextAction(
            kind=AuthorNextActionKind.REVIEW_ROLLING_PLAN,
            target_view=AuthorWorkspaceView.WRITING,
            target_stage=AuthorWorkflowStage.FEEDBACK,
            chapter_id=rolling_replenishment.source_chapter_id,
            chapter_number=chapter.chapter_number if chapter is not None else None,
            last_approved_chapter_id=(last_approved.id if last_approved is not None else None),
            rolling_plan_replenishment_id=rolling_replenishment.id,
        )

    unfinished = next(
        (item for item in ordered_chapters if item.status != ChapterStatus.APPROVED),
        None,
    )
    if unfinished is not None:
        return _chapter_action(unfinished, last_approved)

    max_chapter_number = ordered_chapters[-1].chapter_number if ordered_chapters else 0
    future_plan = next(
        (
            item
            for item in sorted(rolling_plans, key=lambda plan: plan.chapter_number)
            if item.chapter_number > max_chapter_number
        ),
        None,
    )
    if future_plan is not None:
        return AuthorNextAction(
            kind=AuthorNextActionKind.CREATE_NEXT_CHAPTER,
            target_view=AuthorWorkspaceView.WRITING,
            target_stage=AuthorWorkflowStage.PLAN,
            chapter_number=future_plan.chapter_number,
            last_approved_chapter_id=(last_approved.id if last_approved is not None else None),
            rolling_plan_id=future_plan.id,
        )

    if ordered_chapters:
        return AuthorNextAction(
            kind=AuthorNextActionKind.PROJECT_COMPLETE,
            target_view=AuthorWorkspaceView.WRITING,
            target_stage=AuthorWorkflowStage.COMPLETE,
            chapter_id=last_approved.id if last_approved is not None else None,
            chapter_number=(last_approved.chapter_number if last_approved is not None else None),
            last_approved_chapter_id=(last_approved.id if last_approved is not None else None),
        )

    return AuthorNextAction(
        kind=AuthorNextActionKind.PLAN_CHAPTER,
        target_view=AuthorWorkspaceView.WRITING,
        target_stage=AuthorWorkflowStage.PLAN,
    )


def _legacy_action(
    action: ProjectNextAction,
    last_approved: ChapterView | None,
) -> AuthorNextAction | None:
    values: dict[
        ProjectNextAction,
        tuple[AuthorNextActionKind, AuthorWorkspaceView, AuthorWorkflowStage],
    ] = {
        ProjectNextAction.CONFIRM_TOPIC: (
            AuthorNextActionKind.CONFIRM_TOPIC,
            AuthorWorkspaceView.TOPIC_DECISION,
            AuthorWorkflowStage.TOPIC,
        ),
        ProjectNextAction.REVIEW_TOPIC_CHANGES: (
            AuthorNextActionKind.REVIEW_TOPIC_CHANGES,
            AuthorWorkspaceView.TOPIC_DECISION,
            AuthorWorkflowStage.TOPIC,
        ),
        ProjectNextAction.PLAN_BOOK: (
            AuthorNextActionKind.PLAN_BOOK,
            AuthorWorkspaceView.WRITING,
            AuthorWorkflowStage.BOOK,
        ),
        ProjectNextAction.REVIEW_DOWNSTREAM_PLANS: (
            AuthorNextActionKind.REVIEW_DOWNSTREAM_PLANS,
            AuthorWorkspaceView.WRITING,
            AuthorWorkflowStage.BOOK,
        ),
    }
    selected = values.get(action)
    if selected is None:
        return None
    kind, view, stage = selected
    return AuthorNextAction(
        kind=kind,
        target_view=view,
        target_stage=stage,
        last_approved_chapter_id=(last_approved.id if last_approved is not None else None),
    )


def _chapter_action(
    chapter: ChapterView,
    last_approved: ChapterView | None,
) -> AuthorNextAction:
    if chapter.status == ChapterStatus.REVIEWING:
        kind = AuthorNextActionKind.REVIEW_CHAPTER
        stage = AuthorWorkflowStage.REVIEW
    elif chapter.status == ChapterStatus.DRAFTED or _has_content(chapter):
        kind = AuthorNextActionKind.CONTINUE_CHAPTER_DRAFT
        stage = AuthorWorkflowStage.REVIEW
    elif _brief_is_ready(chapter):
        kind = AuthorNextActionKind.GENERATE_CHAPTER_CANDIDATE
        stage = AuthorWorkflowStage.CANDIDATE
    else:
        kind = AuthorNextActionKind.PLAN_CHAPTER
        stage = AuthorWorkflowStage.PLAN
    return AuthorNextAction(
        kind=kind,
        target_view=AuthorWorkspaceView.WRITING,
        target_stage=stage,
        chapter_id=chapter.id,
        chapter_number=chapter.chapter_number,
        last_approved_chapter_id=(last_approved.id if last_approved is not None else None),
    )


def _has_content(chapter: ChapterView) -> bool:
    if isinstance(chapter, Chapter):
        return bool(chapter.content.strip())
    return chapter.has_content


def _brief_is_ready(chapter: ChapterView) -> bool:
    return all(
        getattr(chapter, field).strip()
        for field in (
            "reader_promise",
            "opening_hook",
            "state_change",
            "emotional_payoff",
            "ending_cliffhanger",
        )
    )


def _chapter_by_id(
    chapters: Sequence[ChapterView],
    chapter_id: str,
) -> ChapterView | None:
    return next((item for item in chapters if item.id == chapter_id), None)
