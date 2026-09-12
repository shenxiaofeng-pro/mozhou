from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import RollingChapterPlanContent, TimelineLayer

SHA256_PATTERN = r"^[0-9a-f]{64}$"


def _contains_null_byte(value: object) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_contains_null_byte(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_null_byte(item) for item in value)
    return False


class StrictDomainModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    @model_validator(mode="after")
    def reject_null_bytes(self) -> StrictDomainModel:
        if _contains_null_byte(self.model_dump(mode="python")):
            raise ValueError("结构化内容不能包含空字节")
        return self


class CanonKind(StrEnum):
    CHARACTER_STATE = "character_state"
    RELATIONSHIP = "relationship"
    RESOURCE_STATE = "resource_state"
    LOCATION_STATE = "location_state"
    CHARACTER_KNOWLEDGE = "character_knowledge"
    FUTURE_KNOWLEDGE = "future_knowledge"
    STORY_THREAD = "story_thread"
    PROGRESSION = "progression"
    TIMELINE_EVENT = "timeline_event"


class CanonReconciliationState(StrEnum):
    PENDING = "pending"
    READY = "ready"
    DECIDED = "decided"
    STALE = "stale"
    FAILED = "failed"


class CanonCandidateState(StrEnum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    STALE = "stale"


class PreferenceCandidateState(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    STALE = "stale"


class CanonRecordState(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


class AuthorPreferenceState(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


class CandidateDecisionAction(StrEnum):
    ACCEPT = "accept"
    EDIT = "edit"
    REJECT = "reject"


class PreferenceScopeKind(StrEnum):
    PROJECT = "project"
    GENRE = "genre"
    CHAPTER = "chapter"


class AuthorPreferenceDimension(StrEnum):
    PACING = "pacing"
    PARAGRAPHING = "paragraphing"
    DIALOGUE_DENSITY = "dialogue_density"
    NARRATIVE_DISTANCE = "narrative_distance"
    TENSION = "tension"
    SENTENCE_STYLE = "sentence_style"


class CanonConflictKind(StrEnum):
    DUPLICATE = "duplicate"
    SUPERSEDES = "supersedes"
    INCONSISTENT = "inconsistent"


class RollingPlanReplenishmentState(StrEnum):
    CANDIDATE = "candidate"
    ADOPTED = "adopted"
    REJECTED = "rejected"
    STALE = "stale"
    NOT_NEEDED = "not_needed"


class CharacterStatePayload(StrictDomainModel):
    character_name: str = Field(min_length=1, max_length=120)
    state: str = Field(min_length=1, max_length=1_000)
    change: str = Field(min_length=1, max_length=1_000)


class RelationshipPayload(StrictDomainModel):
    source_name: str = Field(min_length=1, max_length=120)
    target_name: str = Field(min_length=1, max_length=120)
    relation_type: str = Field(min_length=1, max_length=80)
    summary: str = Field(default="", max_length=1_000)

    @model_validator(mode="after")
    def reject_self_relationship(self) -> RelationshipPayload:
        if self.source_name.casefold() == self.target_name.casefold():
            raise ValueError("人物关系的双方不能相同")
        return self


class ResourceStatePayload(StrictDomainModel):
    owner_name: str = Field(default="", max_length=120)
    resource_name: str = Field(min_length=1, max_length=120)
    delta: str = Field(min_length=1, max_length=500)
    state: str = Field(min_length=1, max_length=1_000)


class LocationStatePayload(StrictDomainModel):
    subject_name: str = Field(min_length=1, max_length=120)
    location: str = Field(min_length=1, max_length=160)
    movement: str = Field(min_length=1, max_length=1_000)


class CharacterKnowledgePayload(StrictDomainModel):
    character_name: str = Field(min_length=1, max_length=120)
    knowledge: str = Field(min_length=1, max_length=1_000)


class FutureKnowledgePayload(StrictDomainModel):
    holder_name: str = Field(min_length=1, max_length=120)
    knowledge: str = Field(min_length=1, max_length=500)
    confidence: Literal["certain", "likely", "uncertain"] = "likely"
    event_year: int | None = Field(default=None, ge=-3_000, le=2_100)


class StoryThreadPayload(StrictDomainModel):
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(default="", max_length=1_000)
    status: Literal["open", "resolved", "abandoned"] = "open"


class ProgressionPayload(StrictDomainModel):
    character_name: str = Field(min_length=1, max_length=120)
    system: str = Field(default="", max_length=160)
    rank: str = Field(min_length=1, max_length=160)
    change: str = Field(min_length=1, max_length=1_000)


class TimelineEventPayload(StrictDomainModel):
    layer: TimelineLayer = TimelineLayer.NOVEL
    event_year: int | None = Field(default=None, ge=-3_000, le=2_100)
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(default="", max_length=1_000)


CanonPayload = (
    CharacterStatePayload
    | RelationshipPayload
    | ResourceStatePayload
    | LocationStatePayload
    | CharacterKnowledgePayload
    | FutureKnowledgePayload
    | StoryThreadPayload
    | ProgressionPayload
    | TimelineEventPayload
)

CANON_PAYLOAD_MODELS: dict[CanonKind, type[StrictDomainModel]] = {
    CanonKind.CHARACTER_STATE: CharacterStatePayload,
    CanonKind.RELATIONSHIP: RelationshipPayload,
    CanonKind.RESOURCE_STATE: ResourceStatePayload,
    CanonKind.LOCATION_STATE: LocationStatePayload,
    CanonKind.CHARACTER_KNOWLEDGE: CharacterKnowledgePayload,
    CanonKind.FUTURE_KNOWLEDGE: FutureKnowledgePayload,
    CanonKind.STORY_THREAD: StoryThreadPayload,
    CanonKind.PROGRESSION: ProgressionPayload,
    CanonKind.TIMELINE_EVENT: TimelineEventPayload,
}


class CanonEvidence(StrictDomainModel):
    approval_version_id: str = Field(min_length=1, max_length=200)
    chapter_id: str = Field(min_length=1, max_length=200)
    chapter_revision: int = Field(gt=0)
    chapter_content_sha256: str = Field(pattern=SHA256_PATTERN)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    excerpt: str = Field(min_length=1, max_length=4_000)
    excerpt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_code_point_range(self) -> CanonEvidence:
        if self.end_char <= self.start_char:
            raise ValueError("证据范围无效")
        if self.end_char - self.start_char != len(self.excerpt):
            raise ValueError("证据范围与摘录长度不一致")
        return self


class CanonConflict(StrictDomainModel):
    kind: CanonConflictKind
    summary: str = Field(min_length=1, max_length=500)
    existing_record_id: str | None = Field(default=None, min_length=1, max_length=200)
    existing_record_revision: int | None = Field(
        default=None,
        ge=0,
        exclude_if=lambda value: value is None,
    )
    existing_record_payload_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def require_complete_record_snapshot(self) -> CanonConflict:
        snapshot = (
            self.existing_record_revision,
            self.existing_record_payload_sha256,
        )
        if self.existing_record_id is None and any(value is not None for value in snapshot):
            raise ValueError("Canon 冲突快照缺少记录标识")
        if (snapshot[0] is None) != (snapshot[1] is None):
            raise ValueError("Canon 冲突快照必须同时包含 revision 和载荷指纹")
        return self


class CanonDeltaCandidateDraft(StrictDomainModel):
    kind: CanonKind
    subject_key: str = Field(min_length=1, max_length=240)
    summary: str = Field(min_length=1, max_length=1_200)
    payload: CanonPayload
    evidence: CanonEvidence
    conflicts: list[CanonConflict] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def require_matching_payload_kind(self) -> CanonDeltaCandidateDraft:
        if not isinstance(self.payload, CANON_PAYLOAD_MODELS[self.kind]):
            raise ValueError("Canon 候选类型与载荷不一致")  # noqa: TRY004
        return self


class CanonDeltaCandidate(CanonDeltaCandidateDraft):
    id: str
    reconciliation_id: str
    project_id: str
    ordinal: int = Field(gt=0)
    payload_sha256: str = Field(pattern=SHA256_PATTERN)
    evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    state: CanonCandidateState
    revision: int = Field(ge=0)
    rejection_reason: str | None = None
    accepted_record_id: str | None = None
    created_at: str
    updated_at: str
    decided_at: str | None = None


MetricValue = int | float | str | bool


class AuthorPreferenceCandidateDraft(StrictDomainModel):
    scope_kind: PreferenceScopeKind
    scope_value: str = Field(min_length=1, max_length=200)
    dimension: AuthorPreferenceDimension
    compact_rule: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0, le=1)
    comparison_metrics: dict[str, MetricValue] = Field(default_factory=dict, max_length=40)
    source_writing_outcome_id: str = Field(min_length=1, max_length=200)
    source_candidate_version_id: str = Field(min_length=1, max_length=200)
    candidate_content_sha256: str = Field(pattern=SHA256_PATTERN)
    final_content_sha256: str = Field(pattern=SHA256_PATTERN)


class AuthorPreferenceCandidate(AuthorPreferenceCandidateDraft):
    id: str
    reconciliation_id: str
    project_id: str
    ordinal: int = Field(gt=0)
    rule_sha256: str = Field(pattern=SHA256_PATTERN)
    state: PreferenceCandidateState
    revision: int = Field(ge=0)
    rejection_reason: str | None = None
    confirmed_preference_id: str | None = None
    created_at: str
    updated_at: str
    decided_at: str | None = None


class ChapterApproval(BaseModel):
    id: str
    project_id: str
    chapter_id: str
    chapter_revision: int = Field(gt=0)
    chapter_content_sha256: str = Field(pattern=SHA256_PATTERN)
    chapter_version_id: str
    source_writing_outcome_id: str | None = None
    created_at: str


class CanonReconciliation(BaseModel):
    id: str
    approval_id: str
    project_id: str
    chapter_id: str
    job_id: str
    state: CanonReconciliationState
    revision: int = Field(ge=0)
    context_packet_id: str | None = None
    context_packet_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    context_dependency_fingerprint_sha256: str | None = Field(
        default=None, pattern=SHA256_PATTERN
    )
    analysis_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    preference_skip_reason: str | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None


class CanonReconciliationSnapshot(BaseModel):
    approval: ChapterApproval
    reconciliation: CanonReconciliation
    canon_candidates: list[CanonDeltaCandidate] = Field(default_factory=list)
    preference_candidates: list[AuthorPreferenceCandidate] = Field(default_factory=list)
    rolling_plan_replenishment: RollingPlanReplenishment | None = None


class CanonRecord(BaseModel):
    id: str
    project_id: str
    kind: CanonKind
    subject_key: str
    payload: CanonPayload
    payload_sha256: str = Field(pattern=SHA256_PATTERN)
    revision: int = Field(ge=0)
    state: CanonRecordState
    source_candidate_id: str | None = None
    created_at: str
    updated_at: str


class AuthorPreference(BaseModel):
    id: str
    project_id: str
    scope_kind: PreferenceScopeKind
    scope_value: str
    dimension: AuthorPreferenceDimension
    compact_rule: str
    rule_sha256: str = Field(pattern=SHA256_PATTERN)
    fingerprint_sha256: str = Field(pattern=SHA256_PATTERN)
    confidence: float = Field(ge=0, le=1)
    occurrence_count: int = Field(gt=0)
    state: AuthorPreferenceState
    revision: int = Field(ge=0)
    created_at: str
    updated_at: str


class ReconciliationAnalysis(StrictDomainModel):
    context_packet_id: str = Field(min_length=1, max_length=200)
    context_packet_sha256: str = Field(pattern=SHA256_PATTERN)
    context_dependency_fingerprint_sha256: str = Field(pattern=SHA256_PATTERN)
    canon_candidates: list[CanonDeltaCandidateDraft] = Field(default_factory=list, max_length=100)
    preference_candidates: list[AuthorPreferenceCandidateDraft] = Field(
        default_factory=list, max_length=20
    )
    preference_skip_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_preference_result(self) -> ReconciliationAnalysis:
        if self.preference_candidates and self.preference_skip_reason is not None:
            raise ValueError("偏好候选与跳过原因不能同时存在")
        if not self.preference_candidates and self.preference_skip_reason is None:
            raise ValueError("未产生偏好候选时必须记录原因")
        return self


class ApprovalTransactionResult(BaseModel):
    approval: ChapterApproval
    reconciliation: CanonReconciliation
    job_id: str
    chapter_revision: int = Field(gt=0)
    chapter_content_sha256: str = Field(pattern=SHA256_PATTERN)
    chapter_status: Literal["approved"] = "approved"


class CanonCandidateDecision(StrictDomainModel):
    candidate_id: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(ge=0)
    action: CandidateDecisionAction
    edited_subject_key: str | None = Field(default=None, min_length=1, max_length=240)
    edited_summary: str | None = Field(default=None, min_length=1, max_length=1_200)
    edited_payload: CanonPayload | None = None
    rejection_reason: str | None = Field(default=None, min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_action_fields(self) -> CanonCandidateDecision:
        edits = (self.edited_subject_key, self.edited_summary, self.edited_payload)
        if self.action == CandidateDecisionAction.EDIT:
            if any(value is None for value in edits) or self.rejection_reason is not None:
                raise ValueError("编辑 Canon 候选必须提供完整编辑值")
        elif any(value is not None for value in edits):
            raise ValueError("非编辑操作不能携带编辑值")
        if (self.action == CandidateDecisionAction.REJECT) != (
            self.rejection_reason is not None
        ):
            raise ValueError("只有拒绝操作才能携带拒绝原因")
        return self


class PreferenceCandidateDecision(StrictDomainModel):
    candidate_id: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(ge=0)
    action: CandidateDecisionAction
    edited_scope_kind: PreferenceScopeKind | None = None
    edited_scope_value: str | None = Field(default=None, min_length=1, max_length=200)
    edited_dimension: AuthorPreferenceDimension | None = None
    edited_compact_rule: str | None = Field(default=None, min_length=1, max_length=500)
    edited_confidence: float | None = Field(default=None, ge=0, le=1)
    rejection_reason: str | None = Field(default=None, min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_action_fields(self) -> PreferenceCandidateDecision:
        edits = (
            self.edited_scope_kind,
            self.edited_scope_value,
            self.edited_dimension,
            self.edited_compact_rule,
            self.edited_confidence,
        )
        if self.action == CandidateDecisionAction.EDIT:
            if any(value is None for value in edits) or self.rejection_reason is not None:
                raise ValueError("编辑偏好候选必须提供完整编辑值")
        elif any(value is not None for value in edits):
            raise ValueError("非编辑操作不能携带编辑值")
        if (self.action == CandidateDecisionAction.REJECT) != (
            self.rejection_reason is not None
        ):
            raise ValueError("只有拒绝操作才能携带拒绝原因")
        return self


class CanonDecisionBatchRequest(StrictDomainModel):
    reconciliation_id: str = Field(min_length=1, max_length=200)
    expected_reconciliation_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=160)
    canon_decisions: list[CanonCandidateDecision] = Field(default_factory=list, max_length=100)
    preference_decisions: list[PreferenceCandidateDecision] = Field(
        default_factory=list, max_length=20
    )

    @model_validator(mode="after")
    def validate_decisions(self) -> CanonDecisionBatchRequest:
        if not self.canon_decisions and not self.preference_decisions:
            raise ValueError("决策批次不能为空")
        canon_ids = [item.candidate_id for item in self.canon_decisions]
        preference_ids = [item.candidate_id for item in self.preference_decisions]
        if len(set(canon_ids)) != len(canon_ids):
            raise ValueError("Canon 候选不能重复决策")
        if len(set(preference_ids)) != len(preference_ids):
            raise ValueError("偏好候选不能重复决策")
        return self


class CanonDecisionBatchResult(BaseModel):
    batch_id: str
    reconciliation_id: str
    reconciliation_revision: int = Field(ge=0)
    replayed: bool = False
    accepted_canon_record_ids: list[str] = Field(default_factory=list)
    confirmed_preference_ids: list[str] = Field(default_factory=list)
    rejected_candidate_ids: list[str] = Field(default_factory=list)
    rolling_plan_replenishment_id: str | None = None


class DeleteAuthorPreferenceRequest(StrictDomainModel):
    expected_revision: int = Field(ge=0)


class RollingPlanReplenishmentDraft(StrictDomainModel):
    source_decision_batch_id: str | None = Field(default=None, min_length=1, max_length=200)
    source_chapter_id: str = Field(min_length=1, max_length=200)
    source_canon_record_ids: list[str] = Field(default_factory=list, max_length=100)
    volume_plan_id: str | None = Field(default=None, min_length=1, max_length=200)
    base_blueprint_id: str | None = Field(default=None, min_length=1, max_length=200)
    base_blueprint_revision: int | None = Field(default=None, ge=0)
    base_blueprint_content_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    protected_chapter_numbers: list[int] = Field(default_factory=list, max_length=100)
    plans: list[RollingChapterPlanContent] = Field(default_factory=list, max_length=5)
    blocked_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_draft(self) -> RollingPlanReplenishmentDraft:
        if len(set(self.source_canon_record_ids)) != len(self.source_canon_record_ids):
            raise ValueError("Canon 来源不能重复")
        if len(set(self.protected_chapter_numbers)) != len(self.protected_chapter_numbers):
            raise ValueError("受保护章号不能重复")
        if any(number < 1 or number > 10_000 for number in self.protected_chapter_numbers):
            raise ValueError("受保护章号无效")
        blueprint_fields = (
            self.base_blueprint_id,
            self.base_blueprint_revision,
            self.base_blueprint_content_sha256,
        )
        if any(value is None for value in blueprint_fields) != all(
            value is None for value in blueprint_fields
        ):
            raise ValueError("整书蓝图快照必须成组提供")
        if self.plans:
            if not 3 <= len(self.plans) <= 5:
                raise ValueError("滚动计划候选必须包含 3–5 章")
            if self.volume_plan_id is None:
                raise ValueError("滚动计划候选缺少卷计划")
            if self.blocked_reason is not None:
                raise ValueError("有候选计划时不能设置阻塞原因")
        elif self.blocked_reason is None:
            raise ValueError("无候选计划时必须记录原因")
        return self


class AdoptRollingPlanReplenishmentRequest(StrictDomainModel):
    expected_revision: int = Field(ge=0)
    expected_plans_sha256: str = Field(pattern=SHA256_PATTERN)
    idempotency_key: str = Field(min_length=8, max_length=160)


class RejectRollingPlanReplenishmentRequest(StrictDomainModel):
    expected_revision: int = Field(ge=0)


class RollingPlanReplenishment(BaseModel):
    id: str
    project_id: str
    reconciliation_id: str
    source_decision_batch_id: str | None = None
    source_chapter_id: str
    source_canon_record_ids: list[str] = Field(default_factory=list)
    state: RollingPlanReplenishmentState
    revision: int = Field(ge=0)
    volume_plan_id: str | None = None
    base_blueprint_id: str | None = None
    base_blueprint_revision: int | None = Field(default=None, ge=0)
    base_blueprint_content_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    protected_chapter_numbers: list[int] = Field(default_factory=list)
    plans: list[RollingChapterPlanContent] = Field(default_factory=list, max_length=5)
    plans_sha256: str = Field(pattern=SHA256_PATTERN)
    blocked_reason: str | None = None
    adoption_idempotency_key: str | None = None
    created_at: str
    updated_at: str
    decided_at: str | None = None

    @field_validator("protected_chapter_numbers")
    @classmethod
    def validate_protected_numbers(cls, value: list[int]) -> list[int]:
        if any(number < 1 or number > 10_000 for number in value):
            raise ValueError("受保护章号无效")
        if len(set(value)) != len(value):
            raise ValueError("受保护章号不能重复")
        return value

    @model_validator(mode="after")
    def validate_state_payload(self) -> RollingPlanReplenishment:
        if self.state == RollingPlanReplenishmentState.CANDIDATE and not (
            3 <= len(self.plans) <= 5
        ):
            raise ValueError("滚动计划候选必须包含 3–5 章")
        if self.state == RollingPlanReplenishmentState.NOT_NEEDED and self.plans:
            raise ValueError("无需补计划时不应包含章级候选")
        return self


CanonReconciliationSnapshot.model_rebuild()
