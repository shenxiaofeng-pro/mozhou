from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import (
    BookBlueprint,
    BookBlueprintContent,
    BookBlueprintField,
    OriginalityRiskLevel,
    OriginalityStatus,
)
from app.writing_patterns.models import WritingPatternSafetyBasis


class PatternDistinctAxis(StrEnum):
    CORE_CONFLICT = "core_conflict"
    CHARACTER_RELATIONSHIPS = "character_relationships"
    RESOURCE_PROGRESSION = "resource_progression"
    SCENE_ORGANIZATION = "scene_organization"
    ENDING = "ending"


class PatternAdaptationResultState(StrEnum):
    PENDING = "pending"
    AVAILABLE = "available"
    STALE = "stale"
    INVALID = "invalid"


class PatternAdaptationCostStatus(StrEnum):
    FREE = "free"
    KNOWN = "known"
    UNAVAILABLE = "unavailable"


class PatternAdaptationCandidateSource(StrEnum):
    MODEL = "model"
    AUTHOR_EDIT = "author_edit"


class PatternAdaptationDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    blueprint: BookBlueprintContent
    why_distinct: str = Field(min_length=1, max_length=800)
    distinct_axes: list[PatternDistinctAxis] = Field(min_length=2, max_length=5)
    risk_hypotheses: list[str] = Field(default_factory=list, max_length=5)
    key_scene_sequence: list[str] = Field(min_length=3, max_length=8)
    transformation_notes: list[str] = Field(min_length=1, max_length=8)

    @field_validator(
        "distinct_axes",
        "risk_hypotheses",
        "key_scene_sequence",
        "transformation_notes",
    )
    @classmethod
    def validate_unique_lists(cls, value: list[object]) -> list[object]:
        normalized = [str(item).strip().casefold() for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("候选结构项不能重复")
        return value

    @field_validator("risk_hypotheses", "key_scene_sequence", "transformation_notes")
    @classmethod
    def validate_text_lists(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 500 or "\x00" in item for item in value):
            raise ValueError("候选结构文本无效")
        return value


class PatternAdaptationDraftSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[PatternAdaptationDraft] = Field(min_length=3, max_length=3)


class PatternAdaptationPreflightRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    profile_version_id: str = Field(min_length=36, max_length=36)
    expected_profile_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_topic_revision: int = Field(gt=0)
    expected_topic_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_base_blueprint_revision: int | None = Field(default=None, ge=0)
    expected_base_blueprint_content_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    author_intent: str = Field(default="", max_length=1000)
    provider_profile_id: str | None = Field(default=None, min_length=36, max_length=36)

    @field_validator("author_intent")
    @classmethod
    def reject_null_byte(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("作者意图不能包含空字节")
        return value

    @model_validator(mode="after")
    def require_coupled_blueprint_dependency(self) -> PatternAdaptationPreflightRequest:
        if (self.expected_base_blueprint_revision is None) != (
            self.expected_base_blueprint_content_sha256 is None
        ):
            raise ValueError("基准蓝图修订与指纹必须同时提供")
        return self


class SubmitPatternAdaptationRequest(PatternAdaptationPreflightRequest):
    expected_preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirm_external_processing: bool = False
    max_estimated_cost_microusd: int | None = Field(default=None, ge=0)


class PatternAdaptationPreflight(BaseModel):
    profile_version_id: str
    profile_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recipe_version_id: str
    recipe_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_availability: WritingPatternSafetyBasis
    topic_decision_version_id: str
    topic_revision: int = Field(gt=0)
    topic_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_blueprint_id: str | None = None
    base_blueprint_revision: int | None = Field(default=None, ge=0)
    base_blueprint_content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    dependency_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    safe_context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    lock_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str
    provider_profile_id: str | None = None
    provider_profile_name: str
    provider_profile_revision: int | None = Field(default=None, ge=0)
    model: str
    estimated_input_tokens: int = Field(ge=0)
    estimated_output_tokens: int = Field(ge=0)
    estimated_calls: Literal[1] = 1
    estimated_cost_microusd: int | None = Field(default=None, ge=0)
    cost_status: PatternAdaptationCostStatus
    data_types: list[str]
    content_scope: str
    locked_fields: list[BookBlueprintField]
    relationship_mode: Literal["rebuild_by_default"] = "rebuild_by_default"
    preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PatternAdaptationCandidateVersion(BaseModel):
    id: str
    candidate_id: str
    revision: int = Field(ge=0)
    blueprint: BookBlueprintContent
    key_scene_sequence: list[str] = Field(min_length=3, max_length=8)
    transformation_notes: list[str] = Field(min_length=1, max_length=8)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    changed_fields: list[BookBlueprintField]
    source: PatternAdaptationCandidateSource
    created_at: str


class PatternAdaptationCandidate(BaseModel):
    id: str
    proposal_id: str
    ordinal: int = Field(ge=1, le=3)
    label: str
    why_distinct: str
    distinct_axes: list[PatternDistinctAxis]
    risk_hypotheses: list[str]
    current_version: PatternAdaptationCandidateVersion
    created_at: str
    updated_at: str


class PatternAdaptationProposal(BaseModel):
    id: str
    job_id: str
    project_id: str
    profile_version_id: str
    profile_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recipe_version_id: str
    recipe_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    topic_decision_version_id: str
    topic_revision: int
    topic_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_blueprint_id: str | None = None
    base_blueprint_revision: int | None = None
    base_blueprint_content_sha256: str | None = None
    dependency_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    safe_context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    lock_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str
    provider_profile_id: str | None = None
    provider_profile_revision: int | None = None
    model: str
    input_cost_microusd_per_million: int | None = None
    output_cost_microusd_per_million: int | None = None
    result_state: PatternAdaptationResultState
    stale_reason: str | None = None
    candidates: list[PatternAdaptationCandidate] = Field(default_factory=list)
    created_at: str
    updated_at: str


class EditPatternAdaptationCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blueprint: BookBlueprintContent
    key_scene_sequence: list[str] = Field(min_length=3, max_length=8)
    transformation_notes: list[str] = Field(min_length=1, max_length=8)
    changed_fields: list[BookBlueprintField]
    expected_revision: int = Field(ge=0)
    expected_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AdoptPatternAdaptationCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_candidate_revision: int = Field(ge=0)
    expected_candidate_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_profile_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_recipe_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_topic_revision: int = Field(gt=0)
    expected_topic_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_base_blueprint_revision: int | None = Field(default=None, ge=0)
    expected_base_blueprint_content_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    idempotency_key: str = Field(min_length=8, max_length=160)

    @field_validator("idempotency_key")
    @classmethod
    def reject_idempotency_null_byte(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("幂等键不能包含空字节")
        return value


class PatternAdaptationAdoption(BaseModel):
    id: str
    project_id: str
    proposal_id: str
    candidate_id: str
    candidate_version_id: str
    blueprint_id: str
    blueprint_revision: int = Field(ge=0)
    blueprint_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recipe_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: str


class AdoptPatternAdaptationResult(BaseModel):
    adoption: PatternAdaptationAdoption
    blueprint: BookBlueprint
    originality_status: Literal["needs_check"] = "needs_check"


class RunPatternOriginalityGuardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_blueprint_revision: int = Field(ge=0)
    expected_blueprint_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_profile_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_recipe_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PatternOriginalityFindingRecord(BaseModel):
    id: str
    ordinal: int = Field(ge=0)
    signal: str
    score: int = Field(ge=0, le=100)
    summary: str
    source_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PatternOriginalityReport(BaseModel):
    id: str
    project_id: str
    adoption_id: str
    profile_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recipe_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    blueprint_id: str
    blueprint_revision: int = Field(ge=0)
    blueprint_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_version_id: str
    candidate_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    risk_level: OriginalityRiskLevel
    status: OriginalityStatus
    score: int = Field(ge=0, le=100)
    threshold_version: str
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_availability: WritingPatternSafetyBasis
    findings: list[PatternOriginalityFindingRecord]
    viewed_at: str | None = None
    acknowledged_at: str | None = None
    created_at: str


class PatternOriginalityGateState(BaseModel):
    project_id: str
    state: Literal[
        "legacy",
        "needs_adaptation",
        "needs_check",
        "review_required",
        "blocked",
        "passed",
        "stale",
    ]
    reason: str | None = None
    requires_check: bool
    adoption: PatternAdaptationAdoption | None = None
    blueprint_id: str | None = None
    blueprint_revision: int | None = Field(default=None, ge=0)
    blueprint_content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    latest_report: PatternOriginalityReport | None = None
    report_is_current: bool = False
