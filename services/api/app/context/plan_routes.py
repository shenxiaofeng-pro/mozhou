from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.context.plan_models import (
    AdoptPlanRebaseCandidateRequest,
    AdoptPlanRebaseCandidateResult,
    CreatePlanRebaseCandidateRequest,
    CreativePlanImpactPreview,
    PlanRebaseCandidate,
    UpdatePlanRebaseCandidateRequest,
)
from app.context.plan_repository import (
    PlanRebaseConflictError,
    PlanRebaseNotFoundError,
    PlanRebaseRepository,
)

plan_rebase_router = APIRouter()


def _service(request: Request) -> PlanRebaseRepository:
    service: PlanRebaseRepository = request.app.state.plan_rebase_service
    return service


def _conflict(error: PlanRebaseConflictError) -> HTTPException:
    code = str(error)
    messages = {
        "creative_context_dependency_changed": "创作依赖已变化，请重新查看影响预览",
        "rebase_candidate_changed": "重基候选或正式计划已变化，请刷新后再继续",
        "rebase_candidate_not_editable": "该重基候选已不可编辑",
        "locked_blueprint_field": "候选修改了作者锁定的蓝图字段",
        "locked_volume_plan": "候选修改了作者锁定的卷纲",
        "locked_rolling_plan": "候选修改了作者锁定的滚动章纲",
        "context_blocked": "当前创作上下文存在阻断项，暂不能重基",
        "plan_rebase_not_required": "当前计划没有需要重基的依赖变化",
        "plan_rebase_unavailable": "当前项目尚无可重基的整书蓝图",
    }
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": messages.get(code, "计划重基请求无效")},
    )


@plan_rebase_router.get(
    "/api/projects/{project_id}/creative-context/impact",
    response_model=CreativePlanImpactPreview,
)
def get_creative_plan_impact(
    project_id: UUID,
    service: Annotated[PlanRebaseRepository, Depends(_service)],
) -> CreativePlanImpactPreview:
    try:
        return service.get_impact(str(project_id))
    except PlanRebaseNotFoundError as error:
        raise HTTPException(status_code=404, detail="创作项目不存在") from error


@plan_rebase_router.post(
    "/api/projects/{project_id}/plan-rebase-candidates",
    response_model=PlanRebaseCandidate,
    status_code=status.HTTP_201_CREATED,
)
def create_plan_rebase_candidate(
    project_id: UUID,
    body: CreatePlanRebaseCandidateRequest,
    service: Annotated[PlanRebaseRepository, Depends(_service)],
) -> PlanRebaseCandidate:
    try:
        return service.create_candidate(str(project_id), body)
    except PlanRebaseNotFoundError as error:
        raise HTTPException(status_code=404, detail="创作项目不存在") from error
    except PlanRebaseConflictError as error:
        raise _conflict(error) from error


@plan_rebase_router.get(
    "/api/projects/{project_id}/plan-rebase-candidates/{candidate_id}",
    response_model=PlanRebaseCandidate,
)
def get_plan_rebase_candidate(
    project_id: UUID,
    candidate_id: UUID,
    service: Annotated[PlanRebaseRepository, Depends(_service)],
) -> PlanRebaseCandidate:
    try:
        return service.get_candidate(str(project_id), str(candidate_id))
    except PlanRebaseNotFoundError as error:
        raise HTTPException(status_code=404, detail="重基候选不存在") from error


@plan_rebase_router.put(
    "/api/projects/{project_id}/plan-rebase-candidates/{candidate_id}",
    response_model=PlanRebaseCandidate,
)
def update_plan_rebase_candidate(
    project_id: UUID,
    candidate_id: UUID,
    body: UpdatePlanRebaseCandidateRequest,
    service: Annotated[PlanRebaseRepository, Depends(_service)],
) -> PlanRebaseCandidate:
    try:
        return service.update_candidate(str(project_id), str(candidate_id), body)
    except PlanRebaseNotFoundError as error:
        raise HTTPException(status_code=404, detail="重基候选不存在") from error
    except PlanRebaseConflictError as error:
        raise _conflict(error) from error


@plan_rebase_router.post(
    "/api/projects/{project_id}/plan-rebase-candidates/{candidate_id}/adopt",
    response_model=AdoptPlanRebaseCandidateResult,
)
def adopt_plan_rebase_candidate(
    project_id: UUID,
    candidate_id: UUID,
    body: AdoptPlanRebaseCandidateRequest,
    service: Annotated[PlanRebaseRepository, Depends(_service)],
) -> AdoptPlanRebaseCandidateResult:
    try:
        return service.adopt_candidate(str(project_id), str(candidate_id), body)
    except PlanRebaseNotFoundError as error:
        raise HTTPException(status_code=404, detail="重基候选不存在") from error
    except PlanRebaseConflictError as error:
        raise _conflict(error) from error
