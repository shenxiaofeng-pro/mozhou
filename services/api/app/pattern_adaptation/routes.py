from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.ai import AiNotConfiguredError
from app.jobs.models import Job
from app.pattern_adaptation.models import (
    AdoptPatternAdaptationCandidateRequest,
    AdoptPatternAdaptationResult,
    EditPatternAdaptationCandidateRequest,
    PatternAdaptationCandidate,
    PatternAdaptationPreflight,
    PatternAdaptationPreflightRequest,
    PatternAdaptationProposal,
    PatternOriginalityGateState,
    PatternOriginalityReport,
    RunPatternOriginalityGuardRequest,
    SubmitPatternAdaptationRequest,
)
from app.pattern_adaptation.repository import (
    PatternAdaptationConflictError,
    PatternAdaptationNotFoundError,
)
from app.pattern_adaptation.service import (
    PatternAdaptationService,
    PatternOriginalityGateError,
)

pattern_adaptation_router = APIRouter()


def _service(request: Request) -> PatternAdaptationService:
    service: PatternAdaptationService = request.app.state.pattern_adaptation_service
    return service


def _domain_error(error: ValueError) -> HTTPException:
    code = str(error)
    messages = {
        "topic_not_confirmed": "请先确认当前选题",
        "topic_changed": "选题已更新，请重新预览",
        "profile_unavailable": "写作模式快照不可用",
        "profile_changed": "写作模式已更新，请重新预览",
        "recipe_changed": "写作配方已更新，请重新预览",
        "base_blueprint_changed": "整书蓝图已变化，请重新预览",
        "preview_changed": "预览条件已变化，请刷新后提交",
        "cost_unavailable": "远程模型费用未配置，不能提交",
        "cost_limit_required": "请设置本次任务费用上限",
        "estimated_cost_exceeds_limit": "预计费用超过本次上限",
        "external_processing_not_confirmed": "请先确认将已净化内容发送给外部模型",
        "candidate_changed": "候选已更新，请刷新后继续",
        "proposal_stale": "该候选基于旧版依赖，不能采用",
        "locked_field": "修改触及已锁定字段",
        "relationships_must_be_rebuilt": "人物关系未按要求重构",
        "declared_fields_do_not_match": "声明的修改字段与实际内容不一致",
        "guard_dependencies_changed": "蓝图或写作配方已变化，请重新检查",
        "high_risk_cannot_be_acknowledged": "高风险结果不能手动确认通过",
        "report_must_be_viewed": "请先查看完整原创性报告",
        "stale_originality_report": "原创性报告已过期，请按当前蓝图重新检查",
    }
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": messages.get(code, "原创迁移请求无效")},
    )


@pattern_adaptation_router.post(
    "/api/projects/{project_id}/pattern-adaptations/preview",
    response_model=PatternAdaptationPreflight,
)
def preview_pattern_adaptation(
    project_id: UUID,
    body: PatternAdaptationPreflightRequest,
    service: Annotated[PatternAdaptationService, Depends(_service)],
) -> PatternAdaptationPreflight:
    try:
        return service.preview(str(project_id), body)
    except AiNotConfiguredError as error:
        raise HTTPException(status_code=503, detail="AI 模型尚未配置") from error
    except (PatternAdaptationConflictError, PatternOriginalityGateError) as error:
        raise _domain_error(error) from error


@pattern_adaptation_router.post(
    "/api/projects/{project_id}/pattern-adaptations",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_pattern_adaptation(
    project_id: UUID,
    body: SubmitPatternAdaptationRequest,
    request: Request,
    service: Annotated[PatternAdaptationService, Depends(_service)],
) -> Job:
    try:
        job = service.submit(str(project_id), body)
        request.app.state.job_runtime.wake()
        return job
    except AiNotConfiguredError as error:
        raise HTTPException(status_code=503, detail="AI 模型尚未配置") from error
    except PatternAdaptationConflictError as error:
        raise _domain_error(error) from error


@pattern_adaptation_router.get(
    "/api/projects/{project_id}/pattern-adaptation-jobs/{job_id}/result",
    response_model=PatternAdaptationProposal,
)
def get_pattern_adaptation_result(
    project_id: UUID,
    job_id: UUID,
    service: Annotated[PatternAdaptationService, Depends(_service)],
) -> PatternAdaptationProposal:
    try:
        return service.get_result(str(project_id), str(job_id))
    except PatternAdaptationNotFoundError as error:
        raise HTTPException(status_code=404, detail="原创迁移任务或结果不存在") from error


@pattern_adaptation_router.patch(
    "/api/projects/{project_id}/pattern-adaptation-candidates/{candidate_id}",
    response_model=PatternAdaptationCandidate,
)
def edit_pattern_adaptation_candidate(
    project_id: UUID,
    candidate_id: UUID,
    body: EditPatternAdaptationCandidateRequest,
    service: Annotated[PatternAdaptationService, Depends(_service)],
) -> PatternAdaptationCandidate:
    try:
        return service.edit_candidate(str(project_id), str(candidate_id), body)
    except PatternAdaptationNotFoundError as error:
        raise HTTPException(status_code=404, detail="原创迁移候选不存在") from error
    except PatternAdaptationConflictError as error:
        raise _domain_error(error) from error


@pattern_adaptation_router.post(
    "/api/projects/{project_id}/pattern-adaptation-candidates/{candidate_id}/adopt",
    response_model=AdoptPatternAdaptationResult,
)
def adopt_pattern_adaptation_candidate(
    project_id: UUID,
    candidate_id: UUID,
    body: AdoptPatternAdaptationCandidateRequest,
    service: Annotated[PatternAdaptationService, Depends(_service)],
) -> AdoptPatternAdaptationResult:
    try:
        return service.adopt_candidate(str(project_id), str(candidate_id), body)
    except PatternAdaptationNotFoundError as error:
        raise HTTPException(status_code=404, detail="原创迁移候选不存在") from error
    except PatternAdaptationConflictError as error:
        raise _domain_error(error) from error


@pattern_adaptation_router.post(
    "/api/projects/{project_id}/pattern-originality-checks",
    response_model=PatternOriginalityReport,
)
def run_pattern_originality_guard(
    project_id: UUID,
    body: RunPatternOriginalityGuardRequest,
    service: Annotated[PatternAdaptationService, Depends(_service)],
) -> PatternOriginalityReport:
    try:
        return service.run_originality_guard(str(project_id), body)
    except (PatternAdaptationConflictError, PatternOriginalityGateError) as error:
        raise _domain_error(error) from error


@pattern_adaptation_router.get(
    "/api/projects/{project_id}/pattern-originality-gate",
    response_model=PatternOriginalityGateState,
)
def get_current_pattern_originality_gate(
    project_id: UUID,
    service: Annotated[PatternAdaptationService, Depends(_service)],
) -> PatternOriginalityGateState:
    try:
        return service.get_current_gate_state(str(project_id))
    except PatternAdaptationNotFoundError as error:
        raise HTTPException(status_code=404, detail="创作项目不存在") from error


@pattern_adaptation_router.get(
    "/api/pattern-originality-reports/{report_id}",
    response_model=PatternOriginalityReport,
)
def get_pattern_originality_report(
    report_id: UUID,
    service: Annotated[PatternAdaptationService, Depends(_service)],
) -> PatternOriginalityReport:
    try:
        return service.get_originality_report(str(report_id))
    except PatternAdaptationNotFoundError as error:
        raise HTTPException(status_code=404, detail="原创性报告不存在") from error


@pattern_adaptation_router.post(
    "/api/pattern-originality-reports/{report_id}/views",
    response_model=PatternOriginalityReport,
)
def view_pattern_originality_report(
    report_id: UUID,
    service: Annotated[PatternAdaptationService, Depends(_service)],
) -> PatternOriginalityReport:
    try:
        return service.view_originality_report(str(report_id))
    except PatternAdaptationNotFoundError as error:
        raise HTTPException(status_code=404, detail="原创性报告不存在") from error


@pattern_adaptation_router.post(
    "/api/pattern-originality-reports/{report_id}/acknowledgements",
    response_model=PatternOriginalityReport,
)
def acknowledge_pattern_originality_report(
    report_id: UUID,
    service: Annotated[PatternAdaptationService, Depends(_service)],
) -> PatternOriginalityReport:
    try:
        return service.acknowledge_originality_report(str(report_id))
    except PatternAdaptationNotFoundError as error:
        raise HTTPException(status_code=404, detail="原创性报告不存在") from error
    except PatternOriginalityGateError as error:
        raise _domain_error(error) from error
