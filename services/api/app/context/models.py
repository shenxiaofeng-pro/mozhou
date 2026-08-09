from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ContextTaskType(StrEnum):
    CHAPTER_BRIEF = "chapter_brief"
    CHAPTER_DRAFT = "chapter_draft"


class ContextTier(StrEnum):
    HARD_CONSTRAINT = "hard_constraint"
    CANON = "canon"
    CURRENT_STATE = "current_state"
    RECENT_CHAPTER = "recent_chapter"
    DISTANT_CHAPTER = "distant_chapter"
    TIMELINE = "timeline"
    REALITY_SOURCE = "reality_source"
    BLUEPRINT = "blueprint"


class ContextItemKind(StrEnum):
    SECURITY_BOUNDARY = "security_boundary"
    AUTHOR_INTENT = "author_intent"
    PROJECT_ANCHOR = "project_anchor"
    CURRENT_CHAPTER = "current_chapter"
    CANONICAL_FACT = "canonical_fact"
    STORY_ENTITY = "story_entity"
    STORY_THREAD = "story_thread"
    RECENT_CHAPTER_EXCERPT = "recent_chapter_excerpt"
    DISTANT_CHAPTER_SUMMARY = "distant_chapter_summary"
    TIMELINE_EVENT = "timeline_event"
    FUTURE_KNOWLEDGE = "future_knowledge"
    REALITY_SOURCE = "reality_source"
    APPROVED_BLUEPRINT = "approved_blueprint"


class ContextDirectiveAction(StrEnum):
    PIN = "pin"
    EXCLUDE = "exclude"


class ContextSourceRef(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    source_id: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=240)
    chapter_id: str | None = None
    chapter_number: int | None = Field(default=None, ge=1)
    character_start: int | None = Field(default=None, ge=0)
    character_end: int | None = Field(default=None, ge=1)
    updated_at: str | None = None


class ContextItem(BaseModel):
    id: str = Field(min_length=1, max_length=300)
    kind: ContextItemKind
    tier: ContextTier
    label: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=200_000)
    token_estimate: int = Field(ge=1)
    priority: int = Field(ge=0, le=10_000)
    required: bool = False
    included: bool
    directive: ContextDirectiveAction | None = None
    selection_reason: str = Field(min_length=1, max_length=500)
    exclusion_reason: str | None = Field(default=None, max_length=500)
    source_refs: list[ContextSourceRef] = Field(default_factory=list, max_length=20)
    conflict_notes: list[str] = Field(default_factory=list, max_length=20)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ContextTierUsage(BaseModel):
    tier: ContextTier
    budget_tokens: int = Field(ge=0)
    used_tokens: int = Field(ge=0)
    included_count: int = Field(ge=0)
    excluded_count: int = Field(ge=0)


class ContextPacket(BaseModel):
    id: str
    project_id: str
    chapter_id: str
    chapter_revision: int = Field(ge=0)
    task_type: ContextTaskType
    compiler_version: str = Field(min_length=1, max_length=80)
    token_budget: int = Field(ge=1000, le=200_000)
    used_tokens: int = Field(gt=0)
    overflow_tokens: int = Field(ge=0)
    packet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rendered_context: str = Field(min_length=2, max_length=5_000_000)
    items: list[ContextItem] = Field(min_length=1, max_length=20_000)
    tier_usage: list[ContextTierUsage] = Field(min_length=1, max_length=20)
    conflict_notes: list[str] = Field(default_factory=list, max_length=100)
    created_at: str


class CompileContextRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    expected_revision: int = Field(ge=0)
    author_intent: str = Field(default="", max_length=1000)
    task_type: ContextTaskType
    token_budget: int = Field(default=24_000, ge=1000, le=200_000)

    @field_validator("author_intent")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("创作意图不能包含空字节")
        return value


class ContextDirective(BaseModel):
    id: str
    project_id: str
    chapter_id: str
    source_kind: str = Field(min_length=1, max_length=40)
    source_id: str = Field(min_length=1, max_length=200)
    action: ContextDirectiveAction
    revision: int = Field(ge=0)
    created_at: str
    updated_at: str


class ContextDirectiveRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_kind: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    source_id: str = Field(min_length=1, max_length=200)
    action: ContextDirectiveAction
    expected_revision: int | None = Field(default=None, ge=0)

    @field_validator("source_id")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("上下文来源标识无效")
        return value
