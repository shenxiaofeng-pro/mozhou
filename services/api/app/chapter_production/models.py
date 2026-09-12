from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.context.models import CreativeContextPurpose
from app.models import ChapterStatus, ReviewDimension, ReviewSeverity

SHA256_PATTERN = r"^[0-9a-f]{64}$"
PREWRITE_FIELDS = (
    "reader_promise",
    "opening_hook",
    "state_change",
    "emotional_payoff",
    "ending_cliffhanger",
)


class ChapterProductionState(StrEnum):
    CREATED = "created"
    OUTLINE_READY = "outline_ready"
    PREFLIGHT_BLOCKED = "preflight_blocked"
    DRAFT_READY = "draft_ready"
    CANDIDATE_READY = "candidate_ready"
    REVIEWED = "reviewed"
    ADOPTED = "adopted"
    REJECTED = "rejected"


class CandidateState(StrEnum):
    AVAILABLE = "available"
    ADOPTED = "adopted"
    REJECTED = "rejected"


class CandidateVersionOperation(StrEnum):
    MODEL_DRAFT = "model_draft"
    AUTHOR_EDIT = "author_edit"
    LOCAL_REWRITE = "local_rewrite"
    UNDO = "undo"
    MERGE = "merge"


class OutlineVersionOperation(StrEnum):
    MODEL_DRAFT = "model_draft"
    AUTHOR_EDIT = "author_edit"


class RewriteIntent(StrEnum):
    EXPAND = "expand"
    COMPRESS = "compress"
    REWRITE = "rewrite"
    STRENGTHEN_CONFLICT = "strengthen_conflict"
    STRENGTHEN_EMOTION = "strengthen_emotion"
    CUSTOM = "custom"


class WritingDecision(StrEnum):
    ADOPTED = "adopted"
    REJECTED = "rejected"


class AdoptionMode(StrEnum):
    WHOLE = "whole"
    PARTIAL = "partial"


class ChapterOutline(BaseModel):
    """A draft outline may be incomplete; preflight, not parsing, blocks drafting."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(default="", max_length=160)
    reader_promise: str = Field(default="", max_length=1_500)
    opening_hook: str = Field(default="", max_length=1_500)
    state_change: str = Field(default="", max_length=1_500)
    emotional_payoff: str = Field(default="", max_length=1_500)
    ending_cliffhanger: str = Field(default="", max_length=1_500)
    scene_beats: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("title", *PREWRITE_FIELDS)
    @classmethod
    def reject_null_text(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("章纲不能包含空字节")
        return value

    @field_validator("scene_beats")
    @classmethod
    def validate_scene_beats(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 800 or "\x00" in item for item in value):
            raise ValueError("场景节拍格式无效")
        return value


class CreativeContextSnapshot(BaseModel):
    """The only model-facing context accepted by ChapterProduction adapters."""

    model_config = ConfigDict(extra="forbid")

    purpose: CreativeContextPurpose
    packet_id: str = Field(min_length=1, max_length=200)
    packet_sha256: str = Field(pattern=SHA256_PATTERN)
    dependency_fingerprint_sha256: str = Field(pattern=SHA256_PATTERN)
    compiler_version: str = Field(min_length=1, max_length=80)
    profile_fingerprint_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    rendered_context: str = Field(min_length=2, max_length=5_000_000)


class ModelTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: CreativeContextPurpose
    context_packet_id: str
    context_packet_sha256: str = Field(pattern=SHA256_PATTERN)
    context_dependency_fingerprint_sha256: str = Field(pattern=SHA256_PATTERN)
    context_compiler_version: str
    profile_fingerprint_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    provider: str = Field(min_length=1, max_length=40)
    model: str = Field(min_length=1, max_length=100)
    prompt_version: str = Field(min_length=1, max_length=100)


class ChapterProduction(BaseModel):
    id: str
    project_id: str
    chapter_id: str
    base_chapter_revision: int = Field(ge=0)
    base_chapter_content_sha256: str = Field(pattern=SHA256_PATTERN)
    state: ChapterProductionState
    revision: int = Field(ge=0)
    current_outline_candidate_id: str | None = None
    created_at: str
    updated_at: str


class OutlineCandidateVersion(BaseModel):
    id: str
    candidate_id: str
    revision: int = Field(ge=0)
    content: ChapterOutline
    content_sha256: str = Field(pattern=SHA256_PATTERN)
    operation: OutlineVersionOperation
    parent_version_id: str | None = None
    trace: ModelTrace | None = None
    source_job_id: str | None = None
    created_at: str


class OutlineCandidate(BaseModel):
    id: str
    production_id: str
    ordinal: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=120)
    state: CandidateState
    current_version: OutlineCandidateVersion
    created_at: str
    updated_at: str


class PreflightCheck(BaseModel):
    id: str
    production_id: str
    outline_candidate_id: str
    outline_version_id: str
    outline_revision: int = Field(ge=0)
    outline_content_sha256: str = Field(pattern=SHA256_PATTERN)
    reader_promise: bool
    opening_hook: bool
    state_change: bool
    emotional_payoff: bool
    ending_cliffhanger: bool
    missing_fields: list[str]
    passed: bool
    created_at: str

    @model_validator(mode="after")
    def validate_result(self) -> PreflightCheck:
        checks = {field: bool(getattr(self, field)) for field in PREWRITE_FIELDS}
        missing = [field for field in PREWRITE_FIELDS if not checks[field]]
        if self.missing_fields != missing or self.passed != (not missing):
            raise ValueError("写前检查结果不一致")
        return self


class CandidateLock(BaseModel):
    id: str
    candidate_id: str
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    locked_text: str = Field(min_length=1, max_length=200_000)
    locked_text_sha256: str = Field(pattern=SHA256_PATTERN)
    created_from_version_id: str
    created_at: str

    @model_validator(mode="after")
    def validate_range(self) -> CandidateLock:
        if self.end_char <= self.start_char:
            raise ValueError("锁定范围无效")
        return self


class DraftCandidateVersion(BaseModel):
    id: str
    candidate_id: str
    revision: int = Field(ge=0)
    content: str = Field(max_length=2_000_000)
    content_sha256: str = Field(pattern=SHA256_PATTERN)
    operation: CandidateVersionOperation
    parent_version_id: str | None = None
    restored_from_version_id: str | None = None
    trace: ModelTrace | None = None
    source_job_id: str | None = None
    instruction: str = Field(default="", max_length=2_000)
    created_at: str

    @field_validator("content", "instruction")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("候选文本不能包含空字节")
        return value


class DraftCandidate(BaseModel):
    id: str
    production_id: str
    label: str = Field(min_length=1, max_length=120)
    state: CandidateState
    source_outline_candidate_id: str | None = None
    source_outline_version_id: str | None = None
    source_outline_revision: int | None = Field(default=None, ge=0)
    source_outline_content_sha256: str | None = Field(
        default=None, pattern=SHA256_PATTERN
    )
    current_version: DraftCandidateVersion
    locks: list[CandidateLock] = Field(default_factory=list)
    created_at: str
    updated_at: str


class MergeSource(BaseModel):
    candidate_id: str
    candidate_version_id: str
    candidate_revision: int = Field(ge=0)
    candidate_content_sha256: str = Field(pattern=SHA256_PATTERN)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    selected_text_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_range(self) -> MergeSource:
        if self.end_char <= self.start_char:
            raise ValueError("合并范围无效")
        return self


class CandidateReviewFinding(BaseModel):
    dimension: ReviewDimension
    severity: ReviewSeverity
    summary: str = Field(min_length=1, max_length=1_200)
    suggestion: str = Field(default="", max_length=1_200)


class CandidateReviewDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[CandidateReviewFinding] = Field(default_factory=list, max_length=100)


class CandidateReview(BaseModel):
    id: str
    candidate_id: str
    candidate_version_id: str
    candidate_revision: int = Field(ge=0)
    candidate_content_sha256: str = Field(pattern=SHA256_PATTERN)
    trace: ModelTrace
    source_job_id: str | None = None
    findings: list[CandidateReviewFinding]
    created_at: str


class WritingOutcome(BaseModel):
    id: str
    production_id: str
    candidate_id: str
    candidate_version_id: str
    candidate_revision: int = Field(ge=0)
    candidate_content_sha256: str = Field(pattern=SHA256_PATTERN)
    source_outline_candidate_id: str | None = None
    source_outline_version_id: str | None = None
    source_outline_revision: int | None = Field(default=None, ge=0)
    source_outline_content_sha256: str | None = Field(
        default=None, pattern=SHA256_PATTERN
    )
    decision: WritingDecision
    adoption_mode: AdoptionMode | None = None
    base_chapter_revision: int = Field(ge=0)
    base_chapter_content_sha256: str = Field(pattern=SHA256_PATTERN)
    final_chapter_revision: int = Field(ge=0)
    final_chapter_content_sha256: str = Field(pattern=SHA256_PATTERN)
    final_chapter_status: ChapterStatus
    chapter_version_id: str | None = None
    adoption_detail: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str
    reason: str = ""
    created_at: str


class CreateProductionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_chapter_revision: int = Field(ge=0)
    expected_chapter_content_sha256: str = Field(pattern=SHA256_PATTERN)


class CandidateGuard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_candidate_revision: int = Field(ge=0)
    expected_candidate_content_sha256: str = Field(pattern=SHA256_PATTERN)


class OutlineGuard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outline_candidate_id: str
    expected_outline_revision: int = Field(ge=0)
    expected_outline_content_sha256: str = Field(pattern=SHA256_PATTERN)


class GenerateOutlineRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    author_intent: str = Field(default="", max_length=1_000)
    token_budget: int = Field(default=8_000, ge=1_000, le=200_000)
    label: str = Field(default="AI 章纲", min_length=1, max_length=120)


class EditOutlineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_outline_revision: int = Field(ge=0)
    expected_outline_content_sha256: str = Field(pattern=SHA256_PATTERN)
    content: ChapterOutline


class GenerateDraftRequest(OutlineGuard):
    author_intent: str = Field(default="", max_length=1_000)
    token_budget: int = Field(default=24_000, ge=1_000, le=200_000)
    label: str = Field(default="AI 正文候选", min_length=1, max_length=120)


class TextSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    selected_text_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_range(self) -> TextSelection:
        if self.end_char <= self.start_char:
            raise ValueError("文本选区无效")
        return self


class EditableTextSelection(BaseModel):
    """Author edits may insert at a zero-width, hash-guarded cursor."""

    model_config = ConfigDict(extra="forbid")

    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    selected_text_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_range(self) -> EditableTextSelection:
        if self.end_char < self.start_char:
            raise ValueError("文本选区无效")
        return self


class EditCandidateRequest(CandidateGuard):
    selection: EditableTextSelection
    replacement: str = Field(max_length=200_000)

    @field_validator("replacement")
    @classmethod
    def reject_replacement_null_byte(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("替换文本不能包含空字节")
        return value


class RegenerateSelectionRequest(CandidateGuard):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    selection: TextSelection
    intent: RewriteIntent
    custom_instruction: str = Field(default="", max_length=1_000)
    token_budget: int = Field(default=8_000, ge=1_000, le=200_000)

    @model_validator(mode="after")
    def require_custom_instruction(self) -> RegenerateSelectionRequest:
        if self.intent == RewriteIntent.CUSTOM and not self.custom_instruction:
            raise ValueError("自定义改写必须填写意图")
        return self


class LockSelectionRequest(CandidateGuard):
    selection: TextSelection


class UndoCandidateRequest(CandidateGuard):
    target_version_id: str | None = None


class MergeCandidatesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[MergeSource] = Field(min_length=2, max_length=20)
    label: str = Field(default="合并候选", min_length=1, max_length=120)
    separator: str = Field(default="\n\n", max_length=20)

    @field_validator("sources")
    @classmethod
    def require_distinct_sources(cls, value: list[MergeSource]) -> list[MergeSource]:
        identities = [(item.candidate_id, item.candidate_version_id) for item in value]
        if len(identities) != len(set(identities)):
            raise ValueError("合并来源不能重复")
        return value


class ReviewCandidateRequest(CandidateGuard):
    token_budget: int = Field(default=16_000, ge=1_000, le=200_000)


class SubmitModelCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_packet_id: str = Field(min_length=1, max_length=200)
    context_packet_sha256: str = Field(pattern=SHA256_PATTERN)
    confirm_external_processing: bool = False
    confirm_unknown_cost: bool = False
    max_estimated_cost_microusd: int | None = Field(default=None, ge=0)


class SubmitOutlineJobRequest(GenerateOutlineRequest, SubmitModelCall):
    pass


class SubmitDraftJobRequest(GenerateDraftRequest, SubmitModelCall):
    pass


class SubmitRewriteJobRequest(RegenerateSelectionRequest, SubmitModelCall):
    pass


class SubmitReviewJobRequest(ReviewCandidateRequest, SubmitModelCall):
    pass


class AdoptCandidateRequest(CandidateGuard):
    expected_chapter_revision: int = Field(ge=0)
    expected_chapter_content_sha256: str = Field(pattern=SHA256_PATTERN)
    mode: AdoptionMode = AdoptionMode.WHOLE
    candidate_selection: TextSelection | None = None
    chapter_selection: TextSelection | None = None
    idempotency_key: str = Field(min_length=8, max_length=160)

    @model_validator(mode="after")
    def validate_partial_selection(self) -> AdoptCandidateRequest:
        has_candidate = self.candidate_selection is not None
        has_chapter = self.chapter_selection is not None
        if self.mode == AdoptionMode.PARTIAL and not (has_candidate and has_chapter):
            raise ValueError("局部采用必须指定候选和正文选区")
        if self.mode == AdoptionMode.WHOLE and (has_candidate or has_chapter):
            raise ValueError("整章采用不接受选区")
        return self


class RejectCandidateRequest(CandidateGuard):
    reason: str = Field(min_length=1, max_length=1_000)
    idempotency_key: str = Field(min_length=8, max_length=160)


class OutlineGenerationInput(BaseModel):
    context: CreativeContextSnapshot
    author_intent: str


class DraftGenerationInput(BaseModel):
    context: CreativeContextSnapshot
    outline: ChapterOutline
    author_intent: str


class RewriteGenerationInput(BaseModel):
    context: CreativeContextSnapshot
    full_content: str
    selected_text: str
    intent: RewriteIntent
    custom_instruction: str = ""


class ReviewGenerationInput(BaseModel):
    context: CreativeContextSnapshot
    candidate_content: str


class AdapterOutlineResult(BaseModel):
    outline: ChapterOutline
    prompt_version: str = Field(min_length=1, max_length=100)


class AdapterTextResult(BaseModel):
    content: str = Field(min_length=1, max_length=2_000_000)
    prompt_version: str = Field(min_length=1, max_length=100)


class AdapterReviewResult(BaseModel):
    review: CandidateReviewDraft
    prompt_version: str = Field(min_length=1, max_length=100)


class ChapterProductionOutboundPreview(BaseModel):
    purpose: CreativeContextPurpose
    profile_id: str | None = None
    profile_name: str
    provider: str
    model: str
    data_types: list[str]
    content_scope: str
    character_count: int = Field(ge=0)
    estimated_input_tokens: int = Field(ge=0)
    estimated_output_tokens: int = Field(ge=0)
    estimated_cost_microusd: int | None = Field(default=None, ge=0)
    context_packet_id: str
    context_packet_sha256: str = Field(pattern=SHA256_PATTERN)
    context_dependency_fingerprint_sha256: str = Field(pattern=SHA256_PATTERN)
    context_compiler_version: str


class ProductionEvent(BaseModel):
    id: str
    production_id: str
    sequence: int = Field(ge=1)
    event_type: str
    from_state: ChapterProductionState | None
    to_state: ChapterProductionState
    detail: dict[str, object] = Field(default_factory=dict)
    created_at: str


class AppliedChapterVersion(BaseModel):
    id: str
    chapter_id: str
    chapter_revision: int = Field(ge=0)
    content: str
    content_sha256: str = Field(pattern=SHA256_PATTERN)
    outcome_id: str
    created_at: str


class ProductionSnapshot(BaseModel):
    production: ChapterProduction
    outlines: list[OutlineCandidate] = Field(default_factory=list)
    candidates: list[DraftCandidate] = Field(default_factory=list)
    preflight_checks: list[PreflightCheck] = Field(default_factory=list)
    reviews: list[CandidateReview] = Field(default_factory=list)
    outcomes: list[WritingOutcome] = Field(default_factory=list)


DecisionLiteral = Literal["adopted", "rejected"]
