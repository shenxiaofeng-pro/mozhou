from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.context.models import ContextDependencySnapshot
from app.models import (
    BookBlueprintContent,
    BookBlueprintField,
    DirectorPlanningSnapshot,
    RollingChapterPlanContent,
    VolumePlanContent,
)


class CreativePlanSubjectKind(StrEnum):
    BOOK_BLUEPRINT = "book_blueprint"
    VOLUME_PLAN = "volume_plan"
    ROLLING_PLAN = "rolling_plan"


class CreativePlanDependencyState(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    LEGACY = "legacy"


class PlanRebaseCandidateState(StrEnum):
    CANDIDATE = "candidate"
    ADOPTED = "adopted"
    STALE = "stale"
    REJECTED = "rejected"


class CreativePlanImpactTarget(BaseModel):
    kind: CreativePlanSubjectKind
    id: str
    revision: int = Field(ge=0)
    locked: bool
    state: CreativePlanDependencyState
    stale_reasons: list[str] = Field(default_factory=list, max_length=10)


class CreativePlanImpactPreview(BaseModel):
    project_id: str
    current_dependency: ContextDependencySnapshot
    current_dependency_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reasons: list[str] = Field(default_factory=list, max_length=10)
    affected_blueprint_fields: list[BookBlueprintField]
    locked_blueprint_fields: list[BookBlueprintField]
    targets: list[CreativePlanImpactTarget]
    approved_chapter_count: int = Field(ge=0)
    can_rebase: bool


class PlanRebaseBlueprintDraft(BaseModel):
    id: str
    expected_revision: int = Field(ge=0)
    content: BookBlueprintContent
    locks: dict[BookBlueprintField, bool]

    @model_validator(mode="after")
    def require_all_locks(self) -> PlanRebaseBlueprintDraft:
        if set(self.locks) != set(BookBlueprintField):
            raise ValueError("重基候选的蓝图锁不完整")
        return self


class PlanRebaseVolumeDraft(BaseModel):
    id: str
    expected_revision: int = Field(ge=0)
    locked: bool
    content: VolumePlanContent


class PlanRebaseRollingDraft(BaseModel):
    id: str
    expected_revision: int = Field(ge=0)
    locked: bool
    content: RollingChapterPlanContent


class PlanRebaseCandidate(BaseModel):
    id: str
    project_id: str
    state: PlanRebaseCandidateState
    revision: int = Field(ge=0)
    based_on_dependency_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_dependency_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    impact: CreativePlanImpactPreview
    book_blueprint: PlanRebaseBlueprintDraft | None = None
    volume_plans: list[PlanRebaseVolumeDraft]
    rolling_chapter_plans: list[PlanRebaseRollingDraft]
    created_at: str
    updated_at: str
    adopted_at: str | None = None


class CreatePlanRebaseCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_dependency_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PlanRebaseVolumeEdit(BaseModel):
    id: str
    content: VolumePlanContent


class PlanRebaseRollingEdit(BaseModel):
    id: str
    content: RollingChapterPlanContent


class UpdatePlanRebaseCandidateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    expected_revision: int = Field(ge=0)
    book_blueprint_content: BookBlueprintContent | None = None
    volume_plans: list[PlanRebaseVolumeEdit]
    rolling_chapter_plans: list[PlanRebaseRollingEdit]


class AdoptPlanRebaseCandidateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    expected_revision: int = Field(ge=0)
    expected_dependency_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=200)


class AdoptPlanRebaseCandidateResult(BaseModel):
    candidate: PlanRebaseCandidate
    planning: DirectorPlanningSnapshot
