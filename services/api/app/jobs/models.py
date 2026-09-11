from enum import StrEnum

from pydantic import BaseModel, Field


class JobKind(StrEnum):
    CHAPTER_BRIEF = "chapter_brief"
    CHAPTER_DRAFT = "chapter_draft"
    REFERENCE_SEGMENT_MAP = "reference_segment_map"
    REFERENCE_BOOK_REDUCE = "reference_book_reduce"
    REFERENCE_FUSION = "reference_fusion"
    REVIEW = "review"
    SANDBOX_AI_ROUND = "sandbox_ai_round"
    RESEARCH_EXTRACTION = "research_extraction"
    COMIC_SEASON_PLAN = "comic_season_plan"
    COMIC_EPISODE_SCRIPT = "comic_episode_script"
    TOPIC_DECISION = "topic_decision"
    PATTERN_ADAPTATION = "pattern_adaptation"


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSE_REQUESTED = "pause_requested"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class AttemptState(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


class ChunkState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class Job(BaseModel):
    id: str
    project_id: str
    chapter_id: str | None
    parent_job_id: str | None
    kind: JobKind
    workflow: str = ""
    state: JobState
    idempotency_key: str
    progress_current: int
    progress_total: int
    current_step: str
    estimated_calls: int
    completed_calls: int
    provider: str
    provider_profile_id: str | None
    model: str
    lease_owner: str | None
    lease_expires_at: str | None
    heartbeat_at: str | None
    error_code: str | None
    error_message: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None


class JobChunk(BaseModel):
    id: str
    job_id: str
    kind: JobKind
    ordinal: int
    state: ChunkState
    idempotency_key: str
    attempt_count: int
    error_code: str | None
    error_message: str | None
    created_at: str
    updated_at: str


class JobAttempt(BaseModel):
    id: str
    job_id: str
    chunk_id: str | None
    ordinal: int
    state: AttemptState
    provider: str
    provider_profile_id: str | None
    model: str
    input_tokens: int | None
    output_tokens: int | None
    duration_ms: int | None
    estimated_cost_microusd: int | None
    error_code: str | None
    error_message: str | None
    started_at: str
    completed_at: str | None


class JobArtifact(BaseModel):
    id: str
    job_id: str
    chunk_id: str | None
    kind: str
    artifact_key: str
    content_type: str
    payload_sha256: str
    metadata: dict[str, object] = Field(default_factory=dict)
    provider: str
    provider_profile_id: str | None
    model: str
    created_at: str


class JobArtifactContent(JobArtifact):
    payload: str


class JobEvent(BaseModel):
    id: str
    job_id: str
    sequence: int
    event_type: str
    from_state: JobState | None
    to_state: JobState | None
    detail: dict[str, object] = Field(default_factory=dict)
    created_at: str


class JobDetail(Job):
    chunks: list[JobChunk] = Field(default_factory=list)
    attempts: list[JobAttempt] = Field(default_factory=list)
    artifacts: list[JobArtifact] = Field(default_factory=list)
    events: list[JobEvent] = Field(default_factory=list)
