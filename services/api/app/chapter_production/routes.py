from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status

from app.ai import AiNotConfiguredError
from app.context import CreativeContextBlockedError, CreativeContextChangedError
from app.jobs.models import Job
from app.jobs.repository import JobNotFoundError
from app.repository import OriginalityGateBlockedError

from .models import (
    AdoptCandidateRequest,
    CandidateGuard,
    CandidateLock,
    CandidateReview,
    ChapterProductionOutboundPreview,
    CreateProductionRequest,
    DraftCandidate,
    DraftCandidateVersion,
    EditCandidateRequest,
    EditOutlineRequest,
    GenerateDraftRequest,
    GenerateOutlineRequest,
    LockSelectionRequest,
    MergeCandidatesRequest,
    MergeSource,
    OutlineCandidate,
    OutlineGuard,
    PreflightCheck,
    ProductionEvent,
    ProductionSnapshot,
    RegenerateSelectionRequest,
    RejectCandidateRequest,
    ReviewCandidateRequest,
    SubmitDraftJobRequest,
    SubmitOutlineJobRequest,
    SubmitReviewJobRequest,
    SubmitRewriteJobRequest,
    UndoCandidateRequest,
    WritingOutcome,
)
from .repository import (
    ChapterProductionConflictError,
    ChapterProductionNotFoundError,
    LockedSelectionError,
)
from .service import (
    DRAFT_WORKFLOW,
    REWRITE_WORKFLOW,
    ChapterProductionService,
)

chapter_production_router = APIRouter()


def _service(request: Request) -> ChapterProductionService:
    service: ChapterProductionService = request.app.state.chapter_production_service
    return service


def _not_found(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "not_found", "message": "单章生产记录不存在"},
    )


def _conflict(error: Exception) -> HTTPException:
    code = str(error)
    messages = {
        "chapter_changed": "章节已有新版本，请重新开始本章生产",
        "production_changed": "本章生产状态已变化，请刷新",
        "production_closed": "本次单章生产已结束",
        "approved_chapter_immutable": "已批准章节不能由候选稿覆盖",
        "outline_candidate_changed": "章纲候选已更新，请刷新后继续",
        "candidate_changed": "正文候选已更新，请刷新后继续",
        "preflight_not_passed": "请先补齐读者承诺、开篇钩子、状态变化、情绪兑现和章末悬念",
        "selection_changed": "选区文本已变化，请重新选择",
        "selection_out_of_bounds": "选区范围无效",
        "selection_locked": "选区与作者锁定内容重叠",
        "locked_text_cannot_be_relocated": "撤销后无法唯一定位锁定内容",
        "preview_changed": "预览后上下文已变化，请重新确认",
        "external_processing_not_confirmed": "请先确认将已净化的创作上下文发送给外部模型",
        "unknown_cost_not_confirmed": "当前无法预估费用，请明确确认后继续",
        "cost_limit_required": "请设置本次任务费用上限",
        "estimated_cost_exceeds_limit": "预计费用超过本次上限",
        "idempotency_key_reused": "同一幂等键对应了不同决定",
        "writing_pattern_profile_required": "请先启用一份写作配方",
        "writing_pattern_profile_stale": "写作配方已更新，请先重新检查创作上下文",
        "writing_pattern_profile_over_limit": "当前写作配方超出上下文上限，请先精简配方",
        "required_context_over_budget": "必需的创作上下文超出本次预算",
        "creative_context_changed": "创作上下文已变化，请重新预览后提交",
    }
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": messages.get(code, "当前单章生产状态不允许该操作")},
    )


def _run[T](call: Callable[[], T]) -> T:
    try:
        return call()
    except (ChapterProductionNotFoundError, JobNotFoundError) as error:
        raise _not_found(error) from error
    except AiNotConfiguredError as error:
        raise HTTPException(status_code=503, detail="AI 模型尚未配置") from error
    except (
        ChapterProductionConflictError,
        CreativeContextBlockedError,
        CreativeContextChangedError,
        LockedSelectionError,
        OriginalityGateBlockedError,
    ) as error:
        raise _conflict(error) from error


@chapter_production_router.post(
    "/api/projects/{project_id}/chapters/{chapter_id}/productions",
    response_model=ProductionSnapshot,
    status_code=status.HTTP_201_CREATED,
)
def create_production(
    project_id: UUID,
    chapter_id: UUID,
    body: CreateProductionRequest,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> ProductionSnapshot:
    def execute() -> ProductionSnapshot:
        production = service.productions.create_production(
            project_id=str(project_id),
            chapter_id=str(chapter_id),
            expected_chapter_revision=body.expected_chapter_revision,
            expected_chapter_content_sha256=body.expected_chapter_content_sha256,
        )
        return service.productions.get_snapshot(production.id)

    return _run(execute)


@chapter_production_router.get(
    "/api/projects/{project_id}/chapters/{chapter_id}/production",
    response_model=ProductionSnapshot,
)
def get_current_production(
    project_id: UUID,
    chapter_id: UUID,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> ProductionSnapshot:
    return _run(
        lambda: service.productions.get_snapshot(
            service.productions.get_current_production(
                str(project_id), str(chapter_id)
            ).id
        )
    )


@chapter_production_router.get(
    "/api/chapter-productions/{production_id}", response_model=ProductionSnapshot
)
def get_production(
    production_id: UUID,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> ProductionSnapshot:
    return _run(lambda: service.productions.get_snapshot(str(production_id)))


@chapter_production_router.get(
    "/api/chapter-productions/{production_id}/events",
    response_model=list[ProductionEvent],
)
def list_events(
    production_id: UUID,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> list[ProductionEvent]:
    return _run(lambda: service.productions.list_events(str(production_id)))


@chapter_production_router.patch(
    "/api/chapter-productions/{production_id}/outlines/{outline_id}",
    response_model=OutlineCandidate,
)
def edit_outline(
    production_id: UUID,
    outline_id: UUID,
    body: EditOutlineRequest,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> OutlineCandidate:
    return _run(
        lambda: service.productions.edit_outline_candidate(
            production_id=str(production_id),
            candidate_id=str(outline_id),
            expected_outline_revision=body.expected_outline_revision,
            expected_outline_content_sha256=body.expected_outline_content_sha256,
            outline=body.content,
        )
    )


@chapter_production_router.post(
    "/api/chapter-productions/{production_id}/outlines/{outline_id}/preflight",
    response_model=PreflightCheck,
)
def run_preflight(
    production_id: UUID,
    outline_id: UUID,
    body: OutlineGuard,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> PreflightCheck:
    if str(outline_id) != body.outline_candidate_id:
        raise _conflict(ChapterProductionConflictError("outline_candidate_changed"))
    return _run(lambda: service.preflight(str(production_id), body))


@chapter_production_router.post(
    "/api/chapter-productions/{production_id}/outline/preview",
    response_model=ChapterProductionOutboundPreview,
)
def preview_outline(
    production_id: UUID,
    body: GenerateOutlineRequest,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> ChapterProductionOutboundPreview:
    return _run(lambda: service.preview_outline(str(production_id), body))


@chapter_production_router.post(
    "/api/chapter-productions/{production_id}/outline/jobs",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_outline(
    production_id: UUID,
    body: SubmitOutlineJobRequest,
    request: Request,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> Job:
    job = _run(lambda: service.submit_outline(str(production_id), body))
    request.app.state.job_runtime.wake()
    return job


@chapter_production_router.get(
    "/api/chapter-productions/{production_id}/outline/jobs/{job_id}/result",
    response_model=OutlineCandidate,
)
def get_outline_result(
    production_id: UUID,
    job_id: UUID,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> OutlineCandidate:
    return _run(lambda: service.get_outline_result(str(production_id), str(job_id)))


@chapter_production_router.post(
    "/api/chapter-productions/{production_id}/draft/preview",
    response_model=ChapterProductionOutboundPreview,
)
def preview_draft(
    production_id: UUID,
    body: GenerateDraftRequest,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> ChapterProductionOutboundPreview:
    return _run(lambda: service.preview_draft(str(production_id), body))


@chapter_production_router.post(
    "/api/chapter-productions/{production_id}/draft/jobs",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_draft(
    production_id: UUID,
    body: SubmitDraftJobRequest,
    request: Request,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> Job:
    job = _run(lambda: service.submit_draft(str(production_id), body))
    request.app.state.job_runtime.wake()
    return job


@chapter_production_router.get(
    "/api/chapter-productions/{production_id}/draft/jobs/{job_id}/result",
    response_model=DraftCandidate,
)
def get_draft_result(
    production_id: UUID,
    job_id: UUID,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> DraftCandidate:
    return _run(
        lambda: service.get_candidate_result(
            str(production_id), str(job_id), DRAFT_WORKFLOW
        )
    )


@chapter_production_router.patch(
    "/api/chapter-productions/{production_id}/candidates/{candidate_id}",
    response_model=DraftCandidate,
)
def edit_candidate(
    production_id: UUID,
    candidate_id: UUID,
    body: EditCandidateRequest,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> DraftCandidate:
    return _run(
        lambda: service.edit_candidate_selection(
            str(production_id),
            str(candidate_id),
            expected_candidate_revision=body.expected_candidate_revision,
            expected_candidate_content_sha256=body.expected_candidate_content_sha256,
            selection=body.selection,
            replacement=body.replacement,
        )
    )


@chapter_production_router.get(
    "/api/chapter-productions/{production_id}/candidates/{candidate_id}/versions",
    response_model=list[DraftCandidateVersion],
)
def list_candidate_versions(
    production_id: UUID,
    candidate_id: UUID,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> list[DraftCandidateVersion]:
    return _run(
        lambda: service.productions.list_candidate_versions(
            str(production_id), str(candidate_id)
        )
    )


@chapter_production_router.post(
    "/api/chapter-productions/{production_id}/candidates/{candidate_id}/rewrite/preview",
    response_model=ChapterProductionOutboundPreview,
)
def preview_rewrite(
    production_id: UUID,
    candidate_id: UUID,
    body: RegenerateSelectionRequest,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> ChapterProductionOutboundPreview:
    return _run(
        lambda: service.preview_rewrite(
            str(production_id), str(candidate_id), body
        )
    )


@chapter_production_router.post(
    "/api/chapter-productions/{production_id}/candidates/{candidate_id}/rewrite/jobs",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_rewrite(
    production_id: UUID,
    candidate_id: UUID,
    body: SubmitRewriteJobRequest,
    request: Request,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> Job:
    job = _run(
        lambda: service.submit_rewrite(
            str(production_id), str(candidate_id), body
        )
    )
    request.app.state.job_runtime.wake()
    return job


@chapter_production_router.get(
    "/api/chapter-productions/{production_id}/candidates/{candidate_id}/rewrite/jobs/{job_id}/result",
    response_model=DraftCandidate,
)
def get_rewrite_result(
    production_id: UUID,
    candidate_id: UUID,
    job_id: UUID,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> DraftCandidate:
    return _run(
        lambda: service.get_candidate_result(
            str(production_id),
            str(job_id),
            REWRITE_WORKFLOW,
            candidate_id=str(candidate_id),
        )
    )


@chapter_production_router.post(
    "/api/chapter-productions/{production_id}/candidates/{candidate_id}/locks",
    response_model=CandidateLock,
    status_code=status.HTTP_201_CREATED,
)
def lock_selection(
    production_id: UUID,
    candidate_id: UUID,
    body: LockSelectionRequest,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> CandidateLock:
    return _run(
        lambda: service.productions.lock_selection(
            production_id=str(production_id),
            candidate_id=str(candidate_id),
            expected_candidate_revision=body.expected_candidate_revision,
            expected_candidate_content_sha256=body.expected_candidate_content_sha256,
            selection=body.selection,
        )
    )


@chapter_production_router.delete(
    "/api/chapter-productions/{production_id}/candidates/{candidate_id}/locks/{lock_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def unlock_selection(
    production_id: UUID,
    candidate_id: UUID,
    lock_id: UUID,
    body: Annotated[CandidateGuard, Body()],
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> Response:
    _run(
        lambda: service.productions.unlock_selection(
            production_id=str(production_id),
            candidate_id=str(candidate_id),
            lock_id=str(lock_id),
            expected_candidate_revision=body.expected_candidate_revision,
            expected_candidate_content_sha256=body.expected_candidate_content_sha256,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@chapter_production_router.post(
    "/api/chapter-productions/{production_id}/candidates/{candidate_id}/undo",
    response_model=DraftCandidate,
)
def undo_candidate(
    production_id: UUID,
    candidate_id: UUID,
    body: UndoCandidateRequest,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> DraftCandidate:
    return _run(
        lambda: service.productions.undo_candidate(
            production_id=str(production_id),
            candidate_id=str(candidate_id),
            expected_candidate_revision=body.expected_candidate_revision,
            expected_candidate_content_sha256=body.expected_candidate_content_sha256,
            target_version_id=body.target_version_id,
        )
    )


@chapter_production_router.post(
    "/api/chapter-productions/{production_id}/candidates/merge",
    response_model=DraftCandidate,
    status_code=status.HTTP_201_CREATED,
)
def merge_candidates(
    production_id: UUID,
    body: MergeCandidatesRequest,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> DraftCandidate:
    return _run(
        lambda: service.productions.merge_candidates(
            production_id=str(production_id), request=body
        )
    )


@chapter_production_router.get(
    "/api/chapter-productions/{production_id}/candidates/{candidate_id}/merge-sources",
    response_model=list[MergeSource],
)
def list_merge_sources(
    production_id: UUID,
    candidate_id: UUID,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> list[MergeSource]:
    return _run(
        lambda: service.productions.list_merge_sources(
            str(production_id), str(candidate_id)
        )
    )


@chapter_production_router.post(
    "/api/chapter-productions/{production_id}/candidates/{candidate_id}/review/preview",
    response_model=ChapterProductionOutboundPreview,
)
def preview_review(
    production_id: UUID,
    candidate_id: UUID,
    body: ReviewCandidateRequest,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> ChapterProductionOutboundPreview:
    return _run(
        lambda: service.preview_review(str(production_id), str(candidate_id), body)
    )


@chapter_production_router.post(
    "/api/chapter-productions/{production_id}/candidates/{candidate_id}/review/jobs",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_review(
    production_id: UUID,
    candidate_id: UUID,
    body: SubmitReviewJobRequest,
    request: Request,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> Job:
    job = _run(
        lambda: service.submit_review(str(production_id), str(candidate_id), body)
    )
    request.app.state.job_runtime.wake()
    return job


@chapter_production_router.get(
    "/api/chapter-productions/{production_id}/candidates/{candidate_id}/review/jobs/{job_id}/result",
    response_model=CandidateReview,
)
def get_review_result(
    production_id: UUID,
    candidate_id: UUID,
    job_id: UUID,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> CandidateReview:
    return _run(
        lambda: service.get_review_result(
            str(production_id), str(candidate_id), str(job_id)
        )
    )


@chapter_production_router.post(
    "/api/chapter-productions/{production_id}/candidates/{candidate_id}/adopt",
    response_model=WritingOutcome,
)
def adopt_candidate(
    production_id: UUID,
    candidate_id: UUID,
    body: AdoptCandidateRequest,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> WritingOutcome:
    return _run(
        lambda: service.productions.adopt_candidate(
            production_id=str(production_id),
            candidate_id=str(candidate_id),
            request=body,
        )
    )


@chapter_production_router.post(
    "/api/chapter-productions/{production_id}/candidates/{candidate_id}/reject",
    response_model=WritingOutcome,
)
def reject_candidate(
    production_id: UUID,
    candidate_id: UUID,
    body: RejectCandidateRequest,
    service: Annotated[ChapterProductionService, Depends(_service)],
) -> WritingOutcome:
    return _run(
        lambda: service.productions.reject_candidate(
            production_id=str(production_id),
            candidate_id=str(candidate_id),
            request=body,
        )
    )
