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


class AiProvider(StrEnum):
    UNAVAILABLE = "unavailable"
    OPENAI = "openai"


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


class ReferenceWork(BaseModel):
    id: str
    project_id: str
    title: str
    source_filename: str
    source_format: ReferenceFormat
    rights_basis: ReferenceRightsBasis
    total_characters: int
    segment_target_characters: int
    segments: list[ReferenceSegment] = Field(default_factory=list)
    created_at: str


class ContinuityIssue(BaseModel):
    id: str
    kind: ContinuityIssueKind
    severity: ContinuitySeverity
    title: str
    detail: str
    source_labels: list[str] = Field(default_factory=list)


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


class ConfigureAiRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    api_key: SecretStr
    model: str = Field(default="gpt-5.6", min_length=1, max_length=100, pattern=r"^[\w.:-]+$")


class AiChapterBriefRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    expected_revision: int = Field(ge=0)
    author_intent: str = Field(default="", max_length=1000)

    @field_validator("author_intent")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("创作意图不能包含空字节")
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
    summary: str
    transferable_logic: str


class ReferencePatternApplication(BaseModel):
    id: str
    project_id: str
    pattern_card_id: str
    selected_dimensions: list[ReferencePatternDimension]
    dimensions: dict[ReferencePatternDimension, AppliedReferenceDimension]
    relationship_recomposition: str
    application_note: str
    created_at: str


class ApplyReferencePatternRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    selected_dimensions: list[ReferencePatternDimension] = Field(min_length=1, max_length=6)
    application_note: str = Field(default="", max_length=1000)
    confirm_original_adaptation: bool

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


class Workspace(BaseModel):
    project: Project
    chapters: list[Chapter]
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
