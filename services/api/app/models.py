from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class Genre(StrEnum):
    HISTORICAL_REBIRTH = "historical_rebirth"
    URBAN_REBIRTH = "urban_rebirth"


class ChapterStatus(StrEnum):
    PLANNED = "planned"
    DRAFTED = "drafted"
    REVIEWING = "reviewing"
    APPROVED = "approved"


class GenerationState(StrEnum):
    CONTEXT_READY = "context_ready"
    GENERATING = "generating"
    DRAFTED = "drafted"
    APPLIED = "applied"
    INTERRUPTED = "interrupted"


class TimelineLayer(StrEnum):
    ORIGINAL = "original"
    NOVEL = "novel"


class FactKind(StrEnum):
    STATE_CHANGE = "state_change"
    OPEN_THREAD = "open_thread"


class FactChangeSetState(StrEnum):
    CANDIDATE = "candidate"
    APPLIED = "applied"
    REJECTED = "rejected"


class KnowledgeConfidence(StrEnum):
    CERTAIN = "certain"
    LIKELY = "likely"
    UNCERTAIN = "uncertain"


class KnowledgeStatus(StrEnum):
    VALID = "valid"
    CANDIDATE_INVALID = "candidate_invalid"
    INVALID = "invalid"


class KnowledgeReviewAction(StrEnum):
    KEEP_VALID = "keep_valid"
    CONFIRM_INVALID = "confirm_invalid"


class StoryEntityKind(StrEnum):
    CHARACTER = "character"
    RESOURCE = "resource"


class StoryThreadStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    ABANDONED = "abandoned"


class SourceKind(StrEnum):
    HISTORICAL_RECORD = "historical_record"
    NEWS = "news"
    INDUSTRY = "industry"
    PERSONAL_NOTE = "personal_note"


class SourceConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ReferenceFormat(StrEnum):
    TXT = "txt"
    MARKDOWN = "markdown"
    PDF = "pdf"


class ReferenceRightsBasis(StrEnum):
    SELF_OWNED = "self_owned"
    AUTHORIZED = "authorized"
    PUBLIC_DOMAIN = "public_domain"


class ReferencePatternDimension(StrEnum):
    ERA = "era"
    CORE_DESIRE = "core_desire"
    CONFLICT_CAUSALITY = "conflict_causality"
    RESOURCE_SYSTEM = "resource_system"
    KEY_SCENE_SEQUENCE = "key_scene_sequence"
    ENDING = "ending"


class BlueprintMode(StrEnum):
    PRESERVE = "preserve"
    ADJUST = "adjust"
    RECONSTRUCT = "reconstruct"


class BlueprintEntityKind(StrEnum):
    CHARACTER = "character"
    LOCATION = "location"
    ORGANIZATION = "organization"
    PROPER_NOUN = "proper_noun"


class OriginalityRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class OriginalityStatus(StrEnum):
    NEEDS_CHECK = "needs_check"
    BLOCKED = "blocked"
    REVIEW_REQUIRED = "review_required"
    PASSED = "passed"


class OriginalitySignal(StrEnum):
    PHRASE_OVERLAP = "phrase_overlap"
    PROPER_NOUN = "proper_noun"
    CHARACTER_COMBINATION = "character_combination"
    BEAT_SEQUENCE = "beat_sequence"
    MULTI_DIMENSION = "multi_dimension"


class BookBlueprintField(StrEnum):
    TITLE = "title"
    GENRE = "genre"
    REBIRTH_YEAR = "rebirth_year"
    REBIRTH_LOCATION = "rebirth_location"
    TARGET_AUDIENCE = "target_audience"
    CORE_SELLING_POINTS = "core_selling_points"
    CORE_DESIRE = "core_desire"
    DIVERGENCE_POINT = "divergence_point"
    LONG_TERM_PROMISE = "long_term_promise"
    ENDING_DIRECTION = "ending_direction"
    PROTAGONIST_ARC = "protagonist_arc"
    RESOURCE_GROWTH = "resource_growth"
    RELATIONSHIP_DESIGN = "relationship_design"


class DirectorWorkflow(StrEnum):
    STARTUP = "director_startup"
    EXPANSION = "director_expansion"
    FIELD_REGENERATION = "director_field_regeneration"
    CHAPTER_PIPELINE = "director_chapter_pipeline"


class DirectorPipelineStage(StrEnum):
    CONTEXT = "context"
    BRIEF = "brief"
    PRE_REVIEW = "pre_review"
    DRAFT = "draft"


class ContinuitySeverity(StrEnum):
    WARNING = "warning"
    INFO = "info"


class ContinuityIssueKind(StrEnum):
    FUTURE_KNOWLEDGE_REVIEW = "future_knowledge_review"
    OVERDUE_THREAD = "overdue_thread"
    RHYTHM_GAP = "rhythm_gap"
    REPEATED_BEAT = "repeated_beat"
    ENTITY_STATE_GAP = "entity_state_gap"
    SOURCE_YEAR_MISMATCH = "source_year_mismatch"


class ReviewDimension(StrEnum):
    CONTINUITY = "continuity"
    SERIAL_RHYTHM = "serial_rhythm"
    CHARACTER = "character"
    REALISM = "realism"
    REBIRTH_LOGIC = "rebirth_logic"
    STYLE = "style"
    FORMAT = "format"


class ReviewSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ReviewFindingState(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    RESOLVED = "resolved"


class ReviewEvidenceKind(StrEnum):
    BODY = "body"
    STRUCTURED = "structured"


class ReviewDimensionState(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ChapterVersionSource(StrEnum):
    INITIAL = "initial"
    MANUAL_SAVE = "manual_save"
    GENERATION_CANDIDATE = "generation_candidate"
    GENERATION_APPLY = "generation_apply"
    CHANGE_SET_APPLY = "change_set_apply"
    ROLLBACK = "rollback"


class TextChangeSetState(StrEnum):
    CANDIDATE = "candidate"
    APPLIED = "applied"
    REJECTED = "rejected"


class AiProvider(StrEnum):
    UNAVAILABLE = "unavailable"
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=120)
    genre: Genre
    rebirth_year: int = Field(ge=-3000, le=2030)
    rebirth_location: str = Field(min_length=1, max_length=100)
    chapter_target_words: int = Field(default=3000, ge=500, le=20000)
    safety_buffer_chapters: int = Field(default=3, ge=0, le=100)


class Project(BaseModel):
    id: str
    title: str
    genre: Genre
    rebirth_year: int
    rebirth_location: str
    chapter_target_words: int
    safety_buffer_chapters: int
    created_at: str
    updated_at: str


class BookBlueprintContent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=120)
    genre: Genre
    rebirth_year: int = Field(ge=-3000, le=2030)
    rebirth_location: str = Field(min_length=1, max_length=100)
    target_audience: str = Field(min_length=1, max_length=500)
    core_selling_points: list[str] = Field(min_length=1, max_length=5)
    core_desire: str = Field(min_length=1, max_length=1000)
    divergence_point: str = Field(min_length=1, max_length=1200)
    long_term_promise: str = Field(min_length=1, max_length=1200)
    ending_direction: str = Field(min_length=1, max_length=1200)
    protagonist_arc: str = Field(min_length=1, max_length=1200)
    resource_growth: str = Field(min_length=1, max_length=1200)
    relationship_design: str = Field(min_length=1, max_length=1200)

    @field_validator(
        "title",
        "rebirth_location",
        "target_audience",
        "core_desire",
        "divergence_point",
        "long_term_promise",
        "ending_direction",
        "protagonist_arc",
        "resource_growth",
        "relationship_design",
    )
    @classmethod
    def reject_blueprint_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("整书蓝图不能包含空字节")
        return value

    @field_validator("core_selling_points")
    @classmethod
    def validate_selling_points(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 300 or "\x00" in item for item in value):
            raise ValueError("核心卖点格式无效")
        return value


class DirectorStartupCandidateDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    label: str = Field(min_length=1, max_length=80)
    blueprint: BookBlueprintContent
    why_distinct: str = Field(min_length=1, max_length=800)
    risks: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("risks")
    @classmethod
    def validate_risks(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 300 or "\x00" in item for item in value):
            raise ValueError("启动风险提示格式无效")
        return value


class DirectorStartupDraftSet(BaseModel):
    candidates: list[DirectorStartupCandidateDraft] = Field(min_length=2, max_length=3)


class DirectorStartupCandidate(DirectorStartupCandidateDraft):
    id: str
    ordinal: int = Field(ge=1, le=3)


class DirectorStartupProposalSet(BaseModel):
    job_id: str
    project_id: str
    idea: str = Field(min_length=1, max_length=3000)
    candidates: list[DirectorStartupCandidate] = Field(min_length=2, max_length=3)


class BookBlueprint(BaseModel):
    id: str
    project_id: str
    idea: str = Field(min_length=1, max_length=3000)
    content: BookBlueprintContent
    locks: dict[BookBlueprintField, bool]
    field_versions: dict[BookBlueprintField, int]
    stale_fields: list[BookBlueprintField] = Field(default_factory=list)
    plan_stale: bool = True
    source_candidate_id: str | None = None
    revision: int = Field(ge=0)
    created_at: str
    updated_at: str

    @model_validator(mode="after")
    def require_complete_field_state(self) -> BookBlueprint:
        expected = set(BookBlueprintField)
        if set(self.locks) != expected or set(self.field_versions) != expected:
            raise ValueError("整书蓝图字段状态不完整")
        if any(version < 1 for version in self.field_versions.values()):
            raise ValueError("整书蓝图字段版本无效")
        if len(set(self.stale_fields)) != len(self.stale_fields):
            raise ValueError("整书蓝图过期字段不能重复")
        return self


class DirectorStartupRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    idea: str = Field(min_length=1, max_length=3000)
    reality_anchor: str = Field(default="", max_length=1500)
    candidate_count: int = Field(default=3, ge=2, le=3)
    confirm_external_processing: bool = False
    max_estimated_cost_microusd: int | None = Field(default=None, ge=0)

    @field_validator("idea", "reality_anchor")
    @classmethod
    def reject_startup_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("创意约束不能包含空字节")
        return value


class SelectDirectorCandidateRequest(BaseModel):
    job_id: str = Field(min_length=36, max_length=36)
    candidate_id: str = Field(min_length=36, max_length=36)
    expected_blueprint_revision: int | None = Field(default=None, ge=0)


class UpdateBookBlueprintRequest(BaseModel):
    content: BookBlueprintContent
    changed_fields: list[BookBlueprintField] = Field(default_factory=list, max_length=13)
    lock_updates: dict[BookBlueprintField, bool] = Field(default_factory=dict)
    expected_revision: int = Field(ge=0)

    @model_validator(mode="after")
    def require_declared_blueprint_change(self) -> UpdateBookBlueprintRequest:
        if len(set(self.changed_fields)) != len(self.changed_fields):
            raise ValueError("整书蓝图变更字段不能重复")
        if not self.changed_fields and not self.lock_updates:
            raise ValueError("整书蓝图没有声明变更")
        return self


class DirectorRegenerationImpactRequest(BaseModel):
    target_field: BookBlueprintField


class DirectorRegenerationImpact(BaseModel):
    target_field: BookBlueprintField
    directly_affected: list[BookBlueprintField]
    downstream_affected: list[BookBlueprintField]
    locked_conflicts: list[BookBlueprintField]
    will_mark_plan_stale: bool


class DirectorFieldRegenerationRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    target_field: BookBlueprintField
    expected_revision: int = Field(ge=0)
    author_intent: str = Field(default="", max_length=1000)
    confirm_external_processing: bool = False
    max_estimated_cost_microusd: int | None = Field(default=None, ge=0)


class DirectorFieldProposal(BaseModel):
    job_id: str
    project_id: str
    blueprint_revision: int = Field(ge=0)
    target_field: BookBlueprintField
    value: str | list[str]
    rationale: str = Field(min_length=1, max_length=800)
    downstream_affected: list[BookBlueprintField]

    @field_validator("value")
    @classmethod
    def validate_field_value(cls, value: str | list[str]) -> str | list[str]:
        values = [value] if isinstance(value, str) else value
        if not values or any(
            not item.strip() or len(item) > 1200 or "\x00" in item for item in values
        ):
            raise ValueError("蓝图字段候选格式无效")
        return value


class DirectorFieldDraft(BaseModel):
    target_field: BookBlueprintField
    value: str | list[str]
    rationale: str = Field(min_length=1, max_length=800)

    @field_validator("value")
    @classmethod
    def validate_draft_value(cls, value: str | list[str]) -> str | list[str]:
        return DirectorFieldProposal.validate_field_value(value)


class ApplyDirectorProposalRequest(BaseModel):
    job_id: str = Field(min_length=36, max_length=36)
    expected_revision: int = Field(ge=0)


class DirectorSceneBeat(BaseModel):
    ordinal: int = Field(ge=1, le=20)
    summary: str = Field(min_length=1, max_length=500)
    state_change: str = Field(min_length=1, max_length=500)
    resource_change: str = Field(min_length=1, max_length=500)
    emotional_turn: str = Field(min_length=1, max_length=500)
    verification: str = Field(min_length=1, max_length=500)


class VolumePlanContent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    volume_number: int = Field(ge=1, le=100)
    title: str = Field(min_length=1, max_length=120)
    direction: str = Field(min_length=1, max_length=1200)
    central_conflict: str = Field(min_length=1, max_length=1200)
    state_goal: str = Field(min_length=1, max_length=1000)
    resource_goal: str = Field(min_length=1, max_length=1000)
    emotional_payoff: str = Field(min_length=1, max_length=1000)
    climax: str = Field(min_length=1, max_length=1000)
    verification: str = Field(min_length=1, max_length=800)


class VolumePlan(VolumePlanContent):
    id: str
    project_id: str
    revision: int = Field(ge=0)
    locked: bool = False
    created_at: str
    updated_at: str


class RollingChapterPlanContent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    chapter_number: int = Field(ge=1, le=10_000)
    title: str = Field(min_length=1, max_length=120)
    reader_promise: str = Field(min_length=1, max_length=300)
    opening_hook: str = Field(min_length=1, max_length=300)
    state_change: str = Field(min_length=1, max_length=300)
    resource_change: str = Field(min_length=1, max_length=300)
    emotional_payoff: str = Field(min_length=1, max_length=300)
    ending_cliffhanger: str = Field(min_length=1, max_length=300)
    verification: str = Field(min_length=1, max_length=500)
    scene_beats: list[DirectorSceneBeat] = Field(min_length=1, max_length=20)


class RollingChapterPlan(RollingChapterPlanContent):
    id: str
    project_id: str
    volume_plan_id: str
    revision: int = Field(ge=0)
    locked: bool = False
    created_at: str
    updated_at: str


class DirectorPlanningSnapshot(BaseModel):
    book_blueprint: BookBlueprint | None = None
    volume_plans: list[VolumePlan] = Field(default_factory=list)
    rolling_chapter_plans: list[RollingChapterPlan] = Field(default_factory=list)


class DirectorEntityProposal(BaseModel):
    kind: StoryEntityKind
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=300)
    goal: str = Field(min_length=1, max_length=500)
    initial_state: str = Field(min_length=1, max_length=1000)
    relationship_notes: str = Field(default="", max_length=1000)


class DirectorExpansionDraft(BaseModel):
    entities: list[DirectorEntityProposal] = Field(min_length=2, max_length=20)
    volumes: list[VolumePlanContent] = Field(min_length=1, max_length=3)
    chapters: list[RollingChapterPlanContent] = Field(min_length=3, max_length=5)
    why_writeable: str = Field(min_length=1, max_length=1000)
    risk_notes: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_plan_ordinals(self) -> DirectorExpansionDraft:
        volume_numbers = [item.volume_number for item in self.volumes]
        chapter_numbers = [item.chapter_number for item in self.chapters]
        if len(set(volume_numbers)) != len(volume_numbers):
            raise ValueError("卷级计划编号不能重复")
        if len(set(chapter_numbers)) != len(chapter_numbers):
            raise ValueError("滚动章纲编号不能重复")
        return self


class DirectorExpansionProposal(DirectorExpansionDraft):
    job_id: str
    project_id: str
    blueprint_revision: int = Field(ge=0)


class DirectorExpansionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    expected_revision: int = Field(ge=0)
    author_intent: str = Field(default="", max_length=1000)
    chapter_count: int = Field(default=3, ge=3, le=5)
    confirm_external_processing: bool = False
    max_estimated_cost_microusd: int | None = Field(default=None, ge=0)


class UpdateVolumePlanRequest(BaseModel):
    content: VolumePlanContent
    locked: bool
    expected_revision: int = Field(ge=0)


class UpdateRollingChapterPlanRequest(BaseModel):
    content: RollingChapterPlanContent
    locked: bool
    expected_revision: int = Field(ge=0)


class DirectorOutboundPreview(BaseModel):
    workflow: DirectorWorkflow
    profile_id: str | None
    profile_name: str
    provider: str
    model: str
    data_types: list[str]
    content_scope: str
    character_count: int = Field(ge=0)
    estimated_input_tokens: int = Field(ge=0)
    estimated_output_tokens: int = Field(ge=0)
    estimated_calls: int = Field(ge=1)
    estimated_cost_microusd: int | None = Field(default=None, ge=0)


class DirectorPreReviewFinding(BaseModel):
    severity: str = Field(pattern=r"^(warning|info)$")
    field: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)


class DirectorPreReview(BaseModel):
    passed: bool
    findings: list[DirectorPreReviewFinding] = Field(default_factory=list, max_length=20)


class DirectorChapterPipelineRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    expected_revision: int = Field(ge=0)
    author_intent: str = Field(default="", max_length=1000)
    context_token_budget: int = Field(default=24_000, ge=1000, le=200_000)
    confirm_external_processing: bool = False
    max_estimated_cost_microusd: int | None = Field(default=None, ge=0)
    rerun_from: DirectorPipelineStage = DirectorPipelineStage.CONTEXT
    parent_job_id: str | None = Field(default=None, min_length=36, max_length=36)


class CreateRecoveryPointRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    label: str = Field(min_length=1, max_length=80)

    @field_validator("label")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("恢复点备注不能包含空字节")
        return value


class RecoveryPointSummary(BaseModel):
    id: str
    project_id: str
    label: str
    kind: str
    archive_sha256: str
    uncompressed_bytes: int
    compressed_bytes: int
    created_at: str


class Chapter(BaseModel):
    id: str
    project_id: str
    volume_number: int
    chapter_number: int
    title: str
    content: str
    reader_promise: str
    opening_hook: str
    state_change: str
    emotional_payoff: str
    ending_cliffhanger: str
    status: ChapterStatus
    revision: int
    updated_at: str


class ChapterSummary(BaseModel):
    id: str
    project_id: str
    volume_number: int
    chapter_number: int
    title: str
    reader_promise: str
    opening_hook: str
    state_change: str
    emotional_payoff: str
    ending_cliffhanger: str
    status: ChapterStatus
    revision: int
    updated_at: str
    has_content: bool
    content_characters: int


class TimelineEvent(BaseModel):
    id: str
    project_id: str
    layer: TimelineLayer
    event_year: int
    title: str
    summary: str
    source_chapter_id: str | None
    created_at: str


class StoryFact(BaseModel):
    id: str
    project_id: str
    source_chapter_id: str
    kind: FactKind
    content: str
    created_at: str


class FactChange(BaseModel):
    id: str
    change_set_id: str
    kind: FactKind
    content: str
    event_year: int | None


class FactChangeSet(BaseModel):
    id: str
    chapter_id: str
    chapter_revision: int
    state: FactChangeSetState
    revision: int
    changes: list[FactChange]
    created_at: str
    updated_at: str


class FutureKnowledge(BaseModel):
    id: str
    project_id: str
    future_year: int
    content: str
    source_note: str
    confidence: KnowledgeConfidence
    status: KnowledgeStatus
    divergence_event_id: str | None
    revision: int
    created_at: str
    updated_at: str


class StoryEntity(BaseModel):
    id: str
    project_id: str
    kind: StoryEntityKind
    name: str
    role: str
    goal: str
    current_state: str
    relationship_notes: str
    revision: int
    created_at: str
    updated_at: str


class StoryThread(BaseModel):
    id: str
    project_id: str
    source_chapter_id: str | None
    title: str
    summary: str
    status: StoryThreadStatus
    planted_chapter_number: int | None
    resolved_chapter_id: str | None
    revision: int
    created_at: str
    updated_at: str


class SourceCard(BaseModel):
    id: str
    project_id: str
    source_kind: SourceKind
    title: str
    source_reference: str
    applicable_year_start: int
    applicable_year_end: int
    confidence: SourceConfidence
    excerpt: str
    source_document_id: str | None = None
    source_date: str | None = None
    page_number_start: int | None = None
    page_number_end: int | None = None
    start_char: int | None = None
    end_char: int | None = None
    confirmed: bool
    revision: int
    created_at: str
    updated_at: str


class ReferenceSegment(BaseModel):
    id: str
    reference_work_id: str
    ordinal: int
    start_char: int
    end_char: int
    character_count: int
    chapter_start: str | None
    chapter_end: str | None
    created_at: str


class ReferenceSourceSpan(BaseModel):
    page_number: int = Field(ge=1, le=2000)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> ReferenceSourceSpan:
        if self.end_char <= self.start_char:
            raise ValueError("来源页码字符范围无效")
        return self


class SourceDocument(BaseModel):
    id: str
    title: str
    source_filename: str
    source_format: ReferenceFormat
    source_sha256: str
    content_sha256: str
    source_encoding: str
    encoding_confidence: float
    import_state: str
    duplicate_of_id: str | None = None
    source_spans: list[ReferenceSourceSpan] = Field(default_factory=list)
    total_characters: int
    created_at: str
    updated_at: str


class ReferenceWork(BaseModel):
    id: str
    project_id: str | None = None
    project_ids: list[str] = Field(default_factory=list)
    title: str
    source_filename: str
    source_format: ReferenceFormat
    rights_basis: ReferenceRightsBasis
    total_characters: int
    segment_target_characters: int
    content_sha256: str
    source_sha256: str
    source_encoding: str
    encoding_confidence: float
    import_state: str
    duplicate_of_id: str | None = None
    source_spans: list[ReferenceSourceSpan] = Field(default_factory=list)
    segments: list[ReferenceSegment] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ContinuityIssue(BaseModel):
    id: str
    kind: ContinuityIssueKind
    severity: ContinuitySeverity
    title: str
    detail: str
    source_labels: list[str] = Field(default_factory=list)


class ReviewEvidence(BaseModel):
    kind: ReviewEvidenceKind
    chapter_id: str | None = None
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=0)
    excerpt: str | None = Field(default=None, min_length=1, max_length=240)
    source_type: str | None = Field(default=None, min_length=1, max_length=80)
    source_id: str | None = Field(default=None, min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> ReviewEvidence:
        if self.kind == ReviewEvidenceKind.BODY:
            if (
                self.chapter_id is None
                or self.start_char is None
                or self.end_char is None
                or self.excerpt is None
                or self.end_char <= self.start_char
            ):
                raise ValueError("正文证据范围不完整")
        elif self.source_type is None or self.source_id is None:
            raise ValueError("结构化证据来源不完整")
        return self


class ReviewFindingDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_:-]+$")
    severity: ReviewSeverity
    title: str = Field(min_length=1, max_length=160)
    evidence_text: str = Field(min_length=1, max_length=240)
    explanation: str = Field(min_length=1, max_length=1200)
    suggestion: str = Field(min_length=1, max_length=1200)
    suggested_replacement: str | None = Field(default=None, max_length=2000)
    confidence: float = Field(ge=0, le=1)

    @field_validator(
        "title",
        "evidence_text",
        "explanation",
        "suggestion",
        "suggested_replacement",
    )
    @classmethod
    def reject_review_null_bytes(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("审校结果不能包含空字节")
        return value


class ReviewFindingDraftSet(BaseModel):
    findings: list[ReviewFindingDraft] = Field(default_factory=list, max_length=20)


class ReviewFinding(BaseModel):
    id: str
    project_id: str
    chapter_id: str
    chapter_revision: int = Field(ge=0)
    review_job_id: str | None = None
    dimension: ReviewDimension
    severity: ReviewSeverity
    code: str
    title: str
    evidence: list[ReviewEvidence] = Field(min_length=1, max_length=8)
    explanation: str
    suggestion: str
    suggested_replacement: str | None = None
    confidence: float = Field(ge=0, le=1)
    dedupe_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: ReviewFindingState
    created_at: str


class ReviewDimensionOutcome(BaseModel):
    dimension: ReviewDimension
    state: ReviewDimensionState
    finding_count: int = Field(ge=0)
    error_code: str | None = None
    error_message: str | None = None


class ReviewJobResult(BaseModel):
    job_id: str
    project_id: str
    chapter_id: str
    chapter_revision: int = Field(ge=0)
    window_size: int = Field(ge=1, le=10)
    outcomes: list[ReviewDimensionOutcome]
    findings: list[ReviewFinding]


class ReviewOutboundPreview(BaseModel):
    profile_id: str | None
    profile_name: str
    provider: str
    model: str
    dimensions: list[ReviewDimension]
    local_dimensions: list[ReviewDimension]
    external_dimensions: list[ReviewDimension]
    data_types: list[str]
    content_scope: str
    character_count: int = Field(ge=0)
    estimated_input_tokens: int = Field(ge=0)
    estimated_output_tokens: int = Field(ge=0)
    estimated_calls: int = Field(ge=0)
    estimated_cost_microusd: int | None = Field(default=None, ge=0)
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReviewChapterRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    window_size: int = Field(default=3, ge=1, le=10)
    dimensions: list[ReviewDimension] = Field(
        default_factory=lambda: list(ReviewDimension),
        min_length=1,
        max_length=7,
    )
    confirm_external_processing: bool = False
    max_estimated_cost_microusd: int | None = Field(default=None, ge=0)
    parent_job_id: str | None = Field(default=None, min_length=36, max_length=36)

    @field_validator("dimensions")
    @classmethod
    def reject_duplicate_review_dimensions(
        cls,
        value: list[ReviewDimension],
    ) -> list[ReviewDimension]:
        if len(set(value)) != len(value):
            raise ValueError("审校维度不能重复")
        return value


class ChapterVersion(BaseModel):
    id: str
    chapter_id: str
    version_number: int = Field(ge=1)
    chapter_revision: int = Field(ge=0)
    content: str = Field(max_length=2_000_000)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: ChapterVersionSource
    source_id: str | None = None
    parent_version_id: str | None = None
    is_candidate: bool = False
    created_at: str


class RollbackChapterVersionRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class TextChange(BaseModel):
    id: str
    change_set_id: str
    ordinal: int = Field(ge=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    original_text: str = Field(max_length=4000)
    replacement_text: str = Field(max_length=4000)
    rationale: str = Field(min_length=1, max_length=1200)
    review_finding_id: str | None = None
    selected: bool | None = None
    applied_replacement: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_text_change_range(self) -> TextChange:
        if self.end_char <= self.start_char:
            raise ValueError("文本变更范围无效")
        if "\x00" in self.original_text or "\x00" in self.replacement_text:
            raise ValueError("文本变更不能包含空字节")
        return self


class TextChangeSet(BaseModel):
    id: str
    chapter_id: str
    base_chapter_revision: int = Field(ge=0)
    base_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str = Field(min_length=1, max_length=160)
    state: TextChangeSetState
    revision: int = Field(ge=0)
    changes: list[TextChange] = Field(min_length=1, max_length=50)
    created_at: str
    updated_at: str


class CreateTextChangeSetRequest(BaseModel):
    finding_ids: list[str] = Field(min_length=1, max_length=20)

    @field_validator("finding_ids")
    @classmethod
    def validate_finding_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("审校建议不能重复选择")
        for item in value:
            try:
                UUID(item)
            except (TypeError, ValueError) as error:
                raise ValueError("审校建议标识无效") from error
        return value


class ApplyTextChangeSetRequest(BaseModel):
    selected_change_ids: list[str] = Field(min_length=1, max_length=50)
    edited_replacements: dict[str, str] = Field(default_factory=dict, max_length=50)
    expected_set_revision: int = Field(ge=0)
    expected_chapter_revision: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_text_change_selection(self) -> ApplyTextChangeSetRequest:
        selected = set(self.selected_change_ids)
        if len(selected) != len(self.selected_change_ids):
            raise ValueError("文本变更不能重复选择")
        if not set(self.edited_replacements) <= selected:
            raise ValueError("作者编辑只允许作用于已选择变更")
        if any(len(value) > 4000 or "\x00" in value for value in self.edited_replacements.values()):
            raise ValueError("作者编辑文本格式无效")
        return self


class RejectTextChangeSetRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class ResumeCardItem(BaseModel):
    label: str
    detail: str
    source: str


class ResumeCard(BaseModel):
    chapter_id: str
    chapter_number: int
    chapter_title: str
    chapter_status: ChapterStatus
    last_progress: str
    next_entry: str
    open_threads: list[ResumeCardItem] = Field(default_factory=list)
    active_entities: list[ResumeCardItem] = Field(default_factory=list)
    pending_reviews: int = 0
    warning_count: int = 0


class AiStatus(BaseModel):
    configured: bool
    provider: AiProvider
    model: str
    key_source: str | None = None
    profile_id: str | None = None
    profile_name: str | None = None


class ConfigureAiRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    api_key: SecretStr
    model: str = Field(default="gpt-5.6", min_length=1, max_length=100, pattern=r"^[\w.:-]+$")


class AiChapterBriefRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    expected_revision: int = Field(ge=0)
    author_intent: str = Field(default="", max_length=1000)
    context_packet_id: str | None = Field(default=None, min_length=36, max_length=36)
    context_token_budget: int = Field(default=24_000, ge=1000, le=200_000)

    @field_validator("author_intent")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("创作意图不能包含空字节")
        return value

    @field_validator("context_packet_id")
    @classmethod
    def validate_context_packet_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            UUID(value)
        except (TypeError, ValueError) as error:
            raise ValueError("上下文包标识无效") from error
        return value


class AiChapterBriefProposal(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=120)
    reader_promise: str = Field(min_length=1, max_length=300)
    opening_hook: str = Field(min_length=1, max_length=300)
    state_change: str = Field(min_length=1, max_length=300)
    emotional_payoff: str = Field(min_length=1, max_length=300)
    ending_cliffhanger: str = Field(min_length=1, max_length=300)
    why_this_works: str = Field(min_length=1, max_length=600)
    risk_notes: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("risk_notes")
    @classmethod
    def validate_risk_notes(cls, value: list[str]) -> list[str]:
        if any(not note.strip() or len(note) > 300 or "\x00" in note for note in value):
            raise ValueError("风险提示格式无效")
        return value


class AiDraftRequest(AiChapterBriefRequest):
    pass


class ImportReferenceWorkRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    source_filename: str = Field(min_length=1, max_length=255)
    rights_basis: ReferenceRightsBasis
    segment_target_characters: int = Field(default=500_000, ge=100_000, le=1_000_000)
    content: str = Field(min_length=1, max_length=20_000_000)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or "\x00" in cleaned:
            raise ValueError("参考作品信息无效")
        return cleaned

    @field_validator("source_filename")
    @classmethod
    def clean_filename(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or "\x00" in cleaned:
            raise ValueError("参考文件名无效")
        if "/" in cleaned or "\\" in cleaned:
            raise ValueError("参考文件名不能包含路径")
        return cleaned

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("参考作品不能包含空字节")
        if not value.strip():
            raise ValueError("参考作品不能为空")
        if len(value.encode("utf-8")) > 20 * 1024 * 1024:
            raise ValueError("参考作品不能超过 20 MB")
        return value


class ReferenceFilePreview(BaseModel):
    source_filename: str
    source_format: ReferenceFormat
    source_encoding: str
    encoding_confidence: float = Field(ge=0, le=1)
    import_state: str
    source_sha256: str
    content_sha256: str
    total_characters: int
    page_count: int
    preview: str
    warnings: list[str] = Field(default_factory=list)
    source_spans: list[ReferenceSourceSpan] = Field(default_factory=list)


class ReferenceWorkImpactResponse(BaseModel):
    work: ReferenceWork
    projects: list[Project]
    cache_entries: int


class ReferenceSynthesisRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    selected_segment_ids: list[str] = Field(min_length=2, max_length=12)
    author_focus: str = Field(default="", max_length=1000)
    confirm_external_processing: bool

    @field_validator("selected_segment_ids")
    @classmethod
    def validate_segment_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("参考区段不能重复选择")
        for item in value:
            try:
                UUID(item)
            except (TypeError, ValueError) as error:
                raise ValueError("参考区段标识无效") from error
        return value

    @field_validator("author_focus")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("分析重点不能包含空字节")
        return value


class ReferenceChunkAnalysis(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    era: str = Field(min_length=1, max_length=1000)
    core_desire: str = Field(min_length=1, max_length=1000)
    conflict_causality: str = Field(min_length=1, max_length=1200)
    resource_system: str = Field(min_length=1, max_length=1200)
    key_scene_sequence: list[str] = Field(min_length=1, max_length=8)
    ending: str = Field(min_length=1, max_length=1000)

    @field_validator("key_scene_sequence")
    @classmethod
    def validate_scenes(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 500 or "\x00" in item for item in value):
            raise ValueError("关键场景格式无效")
        return value


class ReferenceBookAnalysis(ReferenceChunkAnalysis):
    work_id: str = Field(min_length=1, max_length=100)
    work_title: str = Field(min_length=1, max_length=200)
    source_segment_ids: list[str] = Field(min_length=1, max_length=12)


class ReferenceDimensionSynthesis(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    summary: str = Field(min_length=1, max_length=1200)
    source_segment_ids: list[str] = Field(min_length=1, max_length=12)
    transferable_logic: str = Field(min_length=1, max_length=1200)
    adaptation_risk: str = Field(min_length=1, max_length=1200)


class ReferenceSynthesisProposal(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    era: ReferenceDimensionSynthesis
    core_desire: ReferenceDimensionSynthesis
    conflict_causality: ReferenceDimensionSynthesis
    resource_system: ReferenceDimensionSynthesis
    key_scene_sequence: ReferenceDimensionSynthesis
    ending: ReferenceDimensionSynthesis
    shared_patterns: list[str] = Field(min_length=1, max_length=8)
    differences: list[str] = Field(min_length=1, max_length=8)
    relationship_recomposition: str = Field(min_length=1, max_length=1200)
    originality_risks: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("shared_patterns", "differences", "originality_risks")
    @classmethod
    def validate_list_items(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 500 or "\x00" in item for item in value):
            raise ValueError("参考分析列表格式无效")
        return value


class ReferencePatternCard(ReferenceSynthesisProposal):
    id: str
    project_id: str
    source_job_id: str | None = None
    selected_segment_ids: list[str]
    author_focus: str
    provider: AiProvider
    model: str
    created_at: str


class AppliedReferenceDimension(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    summary: str = Field(min_length=1, max_length=1200)
    transferable_logic: str = Field(min_length=1, max_length=1200)


class BlueprintNamedEntity(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    kind: BlueprintEntityKind
    name: str = Field(min_length=1, max_length=80)
    function: str = Field(default="", max_length=300)

    @field_validator("name", "function")
    @classmethod
    def reject_entity_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("蓝图实体不能包含空字节")
        return value


class BlueprintRelationship(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    left_role: str = Field(min_length=1, max_length=80)
    right_role: str = Field(min_length=1, max_length=80)
    relation: str = Field(min_length=1, max_length=120)
    notes: str = Field(default="", max_length=300)


class BlueprintDimensionState(BaseModel):
    source: ReferenceDimensionSynthesis
    mode: BlueprintMode
    author_edits: str = Field(default="", max_length=1200)
    generated_variant: AppliedReferenceDimension
    version: int = Field(default=1, ge=1)
    locked: bool = False
    named_entities: list[BlueprintNamedEntity] = Field(default_factory=list, max_length=20)
    source_beats: list[str] = Field(default_factory=list, max_length=20)
    key_beats: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("author_edits")
    @classmethod
    def reject_dimension_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("蓝图编辑不能包含空字节")
        return value

    @field_validator("source_beats", "key_beats")
    @classmethod
    def validate_blueprint_beats(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 240 or "\x00" in item for item in value):
            raise ValueError("场景节拍格式无效")
        return value


class BlueprintRelationshipState(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source: str = Field(min_length=1, max_length=1200)
    mode: BlueprintMode
    author_edits: str = Field(default="", max_length=1200)
    generated_variant: str = Field(min_length=1, max_length=1200)
    version: int = Field(default=1, ge=1)
    locked: bool = False
    relationships: list[BlueprintRelationship] = Field(default_factory=list, max_length=20)


class ReferenceBlueprintState(BaseModel):
    dimensions: dict[ReferencePatternDimension, BlueprintDimensionState]
    relationship: BlueprintRelationshipState

    @model_validator(mode="after")
    def require_dimensions(self) -> ReferenceBlueprintState:
        if not self.dimensions:
            raise ValueError("蓝图至少需要一个结构维度")
        return self


class OriginalityEvidence(BaseModel):
    signal: OriginalitySignal
    score: int = Field(ge=0, le=100)
    summary: str = Field(min_length=1, max_length=300)
    dimension: ReferencePatternDimension | None = None
    source_segment_id: str | None = None
    source_character_start: int | None = Field(default=None, ge=0)
    source_character_end: int | None = Field(default=None, ge=0)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OriginalityAssessment(BaseModel):
    risk_level: OriginalityRiskLevel
    score: int = Field(ge=0, le=100)
    threshold_version: str = Field(min_length=1, max_length=80)
    checked_dimensions: list[ReferencePatternDimension]
    evidence: list[OriginalityEvidence] = Field(max_length=30)
    source_segment_ids: list[str] = Field(max_length=72)
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    legal_notice: str = Field(min_length=1, max_length=200)


class OriginalityReport(OriginalityAssessment):
    id: str
    application_id: str
    blueprint_revision: int = Field(ge=0)
    viewed_at: str | None = None
    created_at: str


class ReferencePatternApplication(BaseModel):
    id: str
    project_id: str
    pattern_card_id: str
    selected_dimensions: list[ReferencePatternDimension]
    dimensions: dict[ReferencePatternDimension, AppliedReferenceDimension]
    relationship_recomposition: str
    application_note: str
    blueprint: ReferenceBlueprintState | None = None
    originality_status: OriginalityStatus = OriginalityStatus.NEEDS_CHECK
    risk_level: OriginalityRiskLevel | None = None
    latest_report_id: str | None = None
    threshold_version: str | None = None
    revision: int = Field(default=0, ge=0)
    created_at: str
    updated_at: str | None = None


class ApplyReferencePatternRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    selected_dimensions: list[ReferencePatternDimension] = Field(min_length=1, max_length=6)
    application_note: str = Field(default="", max_length=1000)
    confirm_original_adaptation: bool
    blueprint: ReferenceBlueprintState | None = None

    @field_validator("selected_dimensions")
    @classmethod
    def reject_duplicate_dimensions(
        cls,
        value: list[ReferencePatternDimension],
    ) -> list[ReferencePatternDimension]:
        if len(set(value)) != len(value):
            raise ValueError("参考结构维度不能重复")
        return value

    @field_validator("application_note")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("应用备注不能包含空字节")
        return value

    @field_validator("confirm_original_adaptation")
    @classmethod
    def require_original_adaptation(cls, value: bool) -> bool:
        if not value:
            raise ValueError("必须确认原创改编边界")
        return value


class UpdateReferenceBlueprintRequest(BaseModel):
    blueprint: ReferenceBlueprintState
    changed_dimensions: list[ReferencePatternDimension] = Field(max_length=6)
    relationship_changed: bool = False
    expected_revision: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_change_scope(self) -> UpdateReferenceBlueprintRequest:
        changed = set(self.changed_dimensions)
        if len(changed) != len(self.changed_dimensions):
            raise ValueError("蓝图变更维度不能重复")
        if not changed and not self.relationship_changed:
            raise ValueError("蓝图没有声明任何变更")
        if not changed <= set(self.blueprint.dimensions):
            raise ValueError("蓝图变更维度不存在")
        return self


class AcknowledgeOriginalityReportRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class Workspace(BaseModel):
    project: Project
    chapters: list[Chapter]
    book_blueprint: BookBlueprint | None = None
    volume_plans: list[VolumePlan] = Field(default_factory=list)
    rolling_chapter_plans: list[RollingChapterPlan] = Field(default_factory=list)
    timeline_events: list[TimelineEvent] = Field(default_factory=list)
    story_facts: list[StoryFact] = Field(default_factory=list)
    fact_change_sets: list[FactChangeSet] = Field(default_factory=list)
    future_knowledge: list[FutureKnowledge] = Field(default_factory=list)
    story_entities: list[StoryEntity] = Field(default_factory=list)
    story_threads: list[StoryThread] = Field(default_factory=list)
    source_cards: list[SourceCard] = Field(default_factory=list)
    reference_works: list[ReferenceWork] = Field(default_factory=list)
    reference_pattern_cards: list[ReferencePatternCard] = Field(default_factory=list)
    reference_pattern_applications: list[ReferencePatternApplication] = Field(default_factory=list)
    continuity_issues: list[ContinuityIssue] = Field(default_factory=list)
    resume_card: ResumeCard | None = None


class WorkspaceSummary(BaseModel):
    project: Project
    chapters: list[ChapterSummary]
    book_blueprint: BookBlueprint | None = None
    volume_plans: list[VolumePlan] = Field(default_factory=list)
    rolling_chapter_plans: list[RollingChapterPlan] = Field(default_factory=list)
    timeline_events: list[TimelineEvent] = Field(default_factory=list)
    story_facts: list[StoryFact] = Field(default_factory=list)
    fact_change_sets: list[FactChangeSet] = Field(default_factory=list)
    future_knowledge: list[FutureKnowledge] = Field(default_factory=list)
    story_entities: list[StoryEntity] = Field(default_factory=list)
    story_threads: list[StoryThread] = Field(default_factory=list)
    source_cards: list[SourceCard] = Field(default_factory=list)
    reference_works: list[ReferenceWork] = Field(default_factory=list)
    reference_pattern_cards: list[ReferencePatternCard] = Field(default_factory=list)
    reference_pattern_applications: list[ReferencePatternApplication] = Field(default_factory=list)
    continuity_issues: list[ContinuityIssue] = Field(default_factory=list)
    resume_card: ResumeCard | None = None


class CreateTimelineEventRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    event_year: int = Field(ge=-3000, le=2100)
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(default="", max_length=1000)

    @field_validator("title", "summary")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("时间线事件不能包含空字节")
        return value


class ApplyFactChangeSetRequest(BaseModel):
    selected_change_ids: list[str] = Field(min_length=1, max_length=20)
    expected_revision: int = Field(ge=0)

    @field_validator("selected_change_ids")
    @classmethod
    def validate_change_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("候选变更不能重复选择")
        for item in value:
            try:
                UUID(item)
            except (TypeError, ValueError) as error:
                raise ValueError("候选变更标识无效") from error
        return value


class RejectFactChangeSetRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class CreateFutureKnowledgeRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    future_year: int = Field(ge=-3000, le=2100)
    content: str = Field(min_length=1, max_length=500)
    source_note: str = Field(default="", max_length=500)
    confidence: KnowledgeConfidence = KnowledgeConfidence.LIKELY

    @field_validator("content", "source_note")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("未来知识不能包含空字节")
        return value


class ReviewFutureKnowledgeRequest(BaseModel):
    action: KnowledgeReviewAction
    expected_revision: int = Field(ge=0)


class StoryEntityFields(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="", max_length=300)
    goal: str = Field(default="", max_length=500)
    current_state: str = Field(default="", max_length=1000)
    relationship_notes: str = Field(default="", max_length=1000)

    @field_validator("name", "role", "goal", "current_state", "relationship_notes")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("人物或资源账本不能包含空字节")
        return value


class CreateStoryEntityRequest(StoryEntityFields):
    kind: StoryEntityKind


class UpdateStoryEntityRequest(StoryEntityFields):
    expected_revision: int = Field(ge=0)


class CreateStoryThreadRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(default="", max_length=1000)
    planted_chapter_number: int | None = Field(default=None, ge=1, le=10_000)

    @field_validator("title", "summary")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("伏笔账本不能包含空字节")
        return value


class TransitionStoryThreadRequest(BaseModel):
    target_status: StoryThreadStatus
    resolved_chapter_id: str | None = None
    expected_revision: int = Field(ge=0)

    @field_validator("resolved_chapter_id")
    @classmethod
    def validate_chapter_id(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                UUID(value)
            except (TypeError, ValueError) as error:
                raise ValueError("回收章节标识无效") from error
        return value


class CreateSourceCardRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_kind: SourceKind
    title: str = Field(min_length=1, max_length=200)
    source_reference: str = Field(min_length=1, max_length=1000)
    applicable_year_start: int = Field(ge=-3000, le=2100)
    applicable_year_end: int = Field(ge=-3000, le=2100)
    confidence: SourceConfidence = SourceConfidence.MEDIUM
    excerpt: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def validate_year_range(self) -> CreateSourceCardRequest:
        if self.applicable_year_end < self.applicable_year_start:
            raise ValueError("资料适用结束年份不能早于开始年份")
        return self

    @field_validator("title", "source_reference", "excerpt")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("资料卡不能包含空字节")
        return value


class SetSourceCardConfirmationRequest(BaseModel):
    confirmed: bool
    expected_revision: int = Field(ge=0)


class UpdateChapterRequest(BaseModel):
    content: str = Field(max_length=2_000_000)
    expected_revision: int = Field(ge=0)

    @field_validator("content")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("正文不能包含空字节")
        return value


class UpdateChapterBriefRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=120)
    reader_promise: str = Field(default="", max_length=300)
    opening_hook: str = Field(max_length=300)
    state_change: str = Field(max_length=300)
    emotional_payoff: str = Field(default="", max_length=300)
    ending_cliffhanger: str = Field(max_length=300)
    expected_revision: int = Field(ge=0)

    @field_validator("title")
    @classmethod
    def reject_title_null_bytes(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("章节标题不能包含空字节")
        return value

    @field_validator(
        "reader_promise",
        "opening_hook",
        "state_change",
        "emotional_payoff",
        "ending_cliffhanger",
    )
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("章纲不能包含空字节")
        return value


class CreateChapterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    expected_last_chapter_number: int = Field(ge=1, le=10_000)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    reader_promise: str = Field(default="", max_length=300)
    opening_hook: str = Field(default="", max_length=300)
    state_change: str = Field(default="", max_length=300)
    emotional_payoff: str = Field(default="", max_length=300)
    ending_cliffhanger: str = Field(default="", max_length=300)

    @field_validator("title")
    @classmethod
    def reject_title_null_bytes(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("章节标题不能包含空字节")
        return value

    @field_validator(
        "reader_promise",
        "opening_hook",
        "state_change",
        "emotional_payoff",
        "ending_cliffhanger",
    )
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("章纲不能包含空字节")
        return value


class TransitionChapterRequest(BaseModel):
    target_status: ChapterStatus
    expected_revision: int = Field(ge=0)


class StartGenerationRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class ApplyGenerationRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class GenerationRun(BaseModel):
    id: str
    chapter_id: str
    state: GenerationState
    expected_chapter_revision: int
    candidate_content: str | None
    error_message: str | None
    provider: str = "demo"
    model: str = "replay-v1"
    created_at: str
    updated_at: str


class DirectorChapterPipelineResult(BaseModel):
    job_id: str
    project_id: str
    chapter_id: str
    chapter_revision: int = Field(ge=0)
    completed_stages: list[DirectorPipelineStage]
    brief: AiChapterBriefProposal
    pre_review: DirectorPreReview
    draft: GenerationRun
