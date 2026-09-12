from collections.abc import Iterable, Sequence
from itertools import pairwise

from app.models import (
    Chapter,
    ChapterStatus,
    ChapterSummary,
    ContinuityIssue,
    ContinuityIssueKind,
    ContinuitySeverity,
    ResumeCard,
    ResumeCardItem,
    Workspace,
    WorkspaceSummary,
    is_rebirth_genre,
)

ChapterView = Chapter | ChapterSummary
WorkspaceView = Workspace | WorkspaceSummary

RHYTHM_FIELDS = (
    ("reader_promise", "读者承诺"),
    ("opening_hook", "开篇钩子"),
    ("emotional_payoff", "情绪回报"),
    ("ending_cliffhanger", "章尾悬念"),
)


def enrich_serial_control[WorkspaceType: (Workspace, WorkspaceSummary)](
    workspace: WorkspaceType,
) -> WorkspaceType:
    issues = build_continuity_issues(workspace)
    return workspace.model_copy(
        update={
            "continuity_issues": issues,
            "resume_card": build_resume_card(
                workspace,
                issues,
            ),
        }
    )


def build_continuity_issues(workspace: WorkspaceView) -> list[ContinuityIssue]:
    issues: list[ContinuityIssue] = []
    last_chapter_number = max(chapter.chapter_number for chapter in workspace.chapters)

    for knowledge in workspace.future_knowledge:
        if knowledge.status.value == "candidate_invalid":
            issues.append(
                _issue(
                    f"future:{knowledge.id}",
                    ContinuityIssueKind.FUTURE_KNOWLEDGE_REVIEW,
                    ContinuitySeverity.WARNING,
                    f"{knowledge.future_year} 年未来知识待复核",
                    knowledge.content,
                    [knowledge.source_note or "未记录记忆来源"],
                )
            )

    for thread in workspace.story_threads:
        if (
            thread.status.value == "open"
            and thread.planted_chapter_number is not None
            and last_chapter_number - thread.planted_chapter_number >= 3
        ):
            issues.append(
                _issue(
                    f"thread:{thread.id}",
                    ContinuityIssueKind.OVERDUE_THREAD,
                    ContinuitySeverity.WARNING,
                    f"伏笔已悬置 {last_chapter_number - thread.planted_chapter_number} 章",
                    thread.title,
                    [f"第 {thread.planted_chapter_number} 章埋设"],
                )
            )

    approved_chapters = [
        chapter for chapter in workspace.chapters if chapter.status == ChapterStatus.APPROVED
    ]
    for chapter in approved_chapters:
        missing = [
            label
            for field, label in (("reader_promise", "读者承诺"), ("emotional_payoff", "情绪回报"))
            if not getattr(chapter, field).strip()
        ]
        if missing:
            issues.append(
                _issue(
                    f"rhythm-gap:{chapter.id}",
                    ContinuityIssueKind.RHYTHM_GAP,
                    ContinuitySeverity.INFO,
                    f"第 {chapter.chapter_number} 章节奏记录不完整",
                    f"缺少{'、'.join(missing)}，后续复盘无法判断承诺是否兑现。",
                    [chapter.title],
                )
            )

    for previous, current in _adjacent_pairs(workspace.chapters):
        for field, label in RHYTHM_FIELDS:
            value = getattr(current, field).strip()
            if value and value == getattr(previous, field).strip():
                issues.append(
                    _issue(
                        f"repeat:{field}:{previous.id}:{current.id}",
                        ContinuityIssueKind.REPEATED_BEAT,
                        ContinuitySeverity.WARNING,
                        f"连续两章使用相同{label}",
                        value,
                        [previous.title, current.title],
                    )
                )

    for entity in workspace.story_entities:
        if not entity.current_state.strip():
            issues.append(
                _issue(
                    f"entity:{entity.id}",
                    ContinuityIssueKind.ENTITY_STATE_GAP,
                    ContinuitySeverity.INFO,
                    f"{entity.name} 缺少当前状态",
                    "补充当前状态后，生成上下文才能区分过去设定与眼下局面。",
                    ["人物与资源账本"],
                )
            )

    for card in workspace.source_cards:
        year = workspace.project.rebirth_year
        if card.confirmed and not card.applicable_year_start <= year <= card.applicable_year_end:
            issue_title = (
                "现实锚点不覆盖重生年份"
                if is_rebirth_genre(workspace.project.genre)
                else "资料年代不覆盖故事纪年"
            )
            issues.append(
                _issue(
                    f"source-year:{card.id}",
                    ContinuityIssueKind.SOURCE_YEAR_MISMATCH,
                    ContinuitySeverity.INFO,
                    issue_title,
                    f"{card.title} 适用于 {card.applicable_year_start}–{card.applicable_year_end} 年。",
                    [card.source_reference],
                )
            )
    return issues


def build_resume_card(
    workspace: WorkspaceView,
    issues: list[ContinuityIssue] | None = None,
) -> ResumeCard:
    active_chapter = _active_chapter(workspace.chapters)
    next_chapter = next(
        (
            chapter
            for chapter in workspace.chapters
            if chapter.chapter_number > active_chapter.chapter_number
        ),
        None,
    )
    content_progress = (
        active_chapter.content.strip()[:160]
        if isinstance(active_chapter, Chapter)
        else (
            f"本章已有 {active_chapter.content_characters} 字正文，打开后可继续。"
            if active_chapter.has_content
            else ""
        )
    )
    last_progress = (
        active_chapter.state_change.strip()
        or content_progress
        or "本章尚未写下正文或状态变化。"
    )
    next_entry = _next_entry(active_chapter, next_chapter)
    pending_reviews = sum(
        change_set.state.value == "candidate" for change_set in workspace.fact_change_sets
    ) + sum(
        knowledge.status.value == "candidate_invalid" for knowledge in workspace.future_knowledge
    ) + sum(not card.confirmed for card in workspace.source_cards)
    resolved_issues = issues if issues is not None else build_continuity_issues(workspace)
    return ResumeCard(
        chapter_id=active_chapter.id,
        chapter_number=active_chapter.chapter_number,
        chapter_title=active_chapter.title,
        chapter_status=active_chapter.status,
        last_progress=last_progress,
        next_entry=next_entry,
        open_threads=[
            ResumeCardItem(
                label=thread.title,
                detail=thread.summary or "尚未记录回收计划。",
                source=(
                    f"第 {thread.planted_chapter_number} 章埋设"
                    if thread.planted_chapter_number is not None
                    else "未记录埋设章节"
                ),
            )
            for thread in workspace.story_threads
            if thread.status.value == "open"
        ][:5],
        active_entities=[
            ResumeCardItem(
                label=entity.name,
                detail=entity.current_state or "尚未记录当前状态。",
                source="人物账本" if entity.kind.value == "character" else "资源账本",
            )
            for entity in workspace.story_entities
        ][:6],
        pending_reviews=pending_reviews,
        warning_count=sum(issue.severity == ContinuitySeverity.WARNING for issue in resolved_issues),
        next_action=workspace.author_next_action,
    )


def _active_chapter(chapters: Sequence[ChapterView]) -> ChapterView:
    progressed = [
        chapter
        for chapter in chapters
        if _has_content(chapter) or chapter.status != ChapterStatus.PLANNED
    ]
    return max(progressed or chapters, key=lambda chapter: chapter.chapter_number)


def _has_content(chapter: ChapterView) -> bool:
    if isinstance(chapter, Chapter):
        return bool(chapter.content.strip())
    return chapter.has_content


def _next_entry(current: ChapterView, next_chapter: ChapterView | None) -> str:
    if next_chapter is not None:
        return (
            next_chapter.opening_hook.strip()
            or next_chapter.state_change.strip()
            or f"继续规划第 {next_chapter.chapter_number} 章。"
        )
    if current.ending_cliffhanger.strip():
        return f"承接本章悬念：{current.ending_cliffhanger.strip()}"
    return "添加下一章，并先写清开篇钩子与状态变化。"


def _adjacent_pairs(chapters: Sequence[ChapterView]) -> Iterable[tuple[ChapterView, ChapterView]]:
    ordered = sorted(chapters, key=lambda chapter: chapter.chapter_number)
    return pairwise(ordered)


def _issue(
    issue_id: str,
    kind: ContinuityIssueKind,
    severity: ContinuitySeverity,
    title: str,
    detail: str,
    source_labels: list[str],
) -> ContinuityIssue:
    return ContinuityIssue(
        id=issue_id,
        kind=kind,
        severity=severity,
        title=title,
        detail=detail,
        source_labels=source_labels,
    )
