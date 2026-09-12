from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from .models import (
    AdoptRollingPlanReplenishmentRequest,
    AuthorPreference,
    CanonDecisionBatchRequest,
    CanonDecisionBatchResult,
    CanonReconciliationSnapshot,
    DeleteAuthorPreferenceRequest,
    RejectRollingPlanReplenishmentRequest,
    RollingPlanReplenishment,
)
from .repository import (
    CanonDecisionIdempotencyError,
    CanonReconciliationConflictError,
    CanonReconciliationNotFoundError,
    CanonReconciliationRepository,
    CanonReconciliationStaleError,
)
from .service import CanonReconciliationService

canon_reconciliation_router = APIRouter()


def _repository(request: Request) -> CanonReconciliationRepository:
    repository: CanonReconciliationRepository = (
        request.app.state.canon_reconciliation_repository
    )
    return repository


def _service(request: Request) -> CanonReconciliationService:
    service: CanonReconciliationService = request.app.state.canon_reconciliation_service
    return service


def _run[T](call: Callable[[], T]) -> T:
    try:
        return call()
    except CanonReconciliationNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "定稿回流记录不存在"},
        ) from error
    except CanonDecisionIdempotencyError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "idempotency_key_reused", "message": "同一幂等键对应了不同决定"},
        ) from error
    except CanonReconciliationStaleError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "stale_revision", "message": "内容已变化，请刷新后重试"},
        ) from error
    except CanonReconciliationConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": str(error), "message": "当前状态不允许该操作"},
        ) from error


@canon_reconciliation_router.get(
    "/api/projects/{project_id}/chapters/{chapter_id}/canon-reconciliation/latest",
    response_model=CanonReconciliationSnapshot | None,
)
def get_latest_reconciliation(
    project_id: UUID,
    chapter_id: UUID,
    repository: Annotated[CanonReconciliationRepository, Depends(_repository)],
) -> CanonReconciliationSnapshot | None:
    try:
        return repository.get_latest_snapshot(
            project_id=str(project_id),
            chapter_id=str(chapter_id),
        )
    except CanonReconciliationNotFoundError:
        return None


@canon_reconciliation_router.post(
    "/api/projects/{project_id}/canon-reconciliations/{reconciliation_id}/decisions",
    response_model=CanonDecisionBatchResult,
)
def decide_reconciliation(
    project_id: UUID,
    reconciliation_id: UUID,
    body: CanonDecisionBatchRequest,
    service: Annotated[CanonReconciliationService, Depends(_service)],
) -> CanonDecisionBatchResult:
    if str(reconciliation_id) != body.reconciliation_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "reconciliation_mismatch", "message": "定稿回流标识不一致"},
        )
    return _run(
        lambda: service.decide_batch(project_id=str(project_id), request=body)
    )


@canon_reconciliation_router.get(
    "/api/projects/{project_id}/author-preferences",
    response_model=list[AuthorPreference],
)
def list_author_preferences(
    project_id: UUID,
    repository: Annotated[CanonReconciliationRepository, Depends(_repository)],
) -> list[AuthorPreference]:
    return _run(lambda: repository.list_author_preferences(str(project_id)))


@canon_reconciliation_router.delete(
    "/api/projects/{project_id}/author-preferences/{preference_id}",
    response_model=AuthorPreference,
)
def delete_author_preference(
    project_id: UUID,
    preference_id: UUID,
    body: DeleteAuthorPreferenceRequest,
    repository: Annotated[CanonReconciliationRepository, Depends(_repository)],
) -> AuthorPreference:
    return _run(
        lambda: repository.delete_author_preference(
            project_id=str(project_id),
            preference_id=str(preference_id),
            expected_revision=body.expected_revision,
        )
    )


@canon_reconciliation_router.post(
    "/api/projects/{project_id}/rolling-plan-replenishments/{replenishment_id}/adopt",
    response_model=RollingPlanReplenishment,
)
def adopt_rolling_plan_replenishment(
    project_id: UUID,
    replenishment_id: UUID,
    body: AdoptRollingPlanReplenishmentRequest,
    repository: Annotated[CanonReconciliationRepository, Depends(_repository)],
) -> RollingPlanReplenishment:
    return _run(
        lambda: repository.adopt_rolling_plan_replenishment(
            project_id=str(project_id),
            replenishment_id=str(replenishment_id),
            request=body,
        )
    )


@canon_reconciliation_router.post(
    "/api/projects/{project_id}/rolling-plan-replenishments/{replenishment_id}/reject",
    response_model=RollingPlanReplenishment,
)
def reject_rolling_plan_replenishment(
    project_id: UUID,
    replenishment_id: UUID,
    body: RejectRollingPlanReplenishmentRequest,
    repository: Annotated[CanonReconciliationRepository, Depends(_repository)],
) -> RollingPlanReplenishment:
    return _run(
        lambda: repository.reject_rolling_plan_replenishment(
            project_id=str(project_id),
            replenishment_id=str(replenishment_id),
            request=body,
        )
    )
