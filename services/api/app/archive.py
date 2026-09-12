import hashlib
import json
import sqlite3
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from hmac import compare_digest
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import ValidationError

from app.chapter_production.models import (
    CandidateLock,
    CandidateReview,
    ChapterOutline,
    ChapterProduction,
    DraftCandidateVersion,
    MergeSource,
    ModelTrace,
    OutlineCandidateVersion,
    PreflightCheck,
    ProductionEvent,
    WritingOutcome,
)
from app.context import ContextDependencySnapshot, ContextDirective, ContextPacket
from app.context.plan_models import PlanRebaseCandidate, PlanRebaseCandidateState
from app.database import CURRENT_SCHEMA_VERSION, Database
from app.jobs.models import Job, JobArtifact, JobAttempt, JobChunk, JobEvent
from app.models import (
    BookBlueprint,
    BookBlueprintContent,
    Chapter,
    ChapterStatus,
    ChapterVersion,
    ComicEpisode,
    ComicProject,
    ComicScene,
    ComicVersion,
    CraftPatternAssetType,
    CraftPatternMaterial,
    FactChange,
    FactChangeSet,
    FutureKnowledge,
    GenerationRun,
    GenerationState,
    Genre,
    ManuscriptScene,
    ManuscriptVolume,
    OriginalityReport,
    Project,
    RecoveryPointSummary,
    ReferenceBlueprintState,
    ReferencePatternApplication,
    ReferencePatternCard,
    ReferenceSegment,
    ReferenceWork,
    ReviewFinding,
    RollingChapterPlan,
    RollingChapterPlanContent,
    SceneOriginalityCheck,
    SceneOriginalityFinding,
    SourceCard,
    SourceDocument,
    StoryEntity,
    StoryFact,
    StoryThread,
    TextChange,
    TextChangeSet,
    TimelineEvent,
    TopicDecision,
    TopicDecisionCandidate,
    TopicDecisionCandidateSet,
    TopicDecisionContent,
    TopicDecisionField,
    TopicDecisionStatus,
    TopicDecisionVersion,
    VolumePlan,
    VolumePlanContent,
)
from app.originality_guard import LEGAL_NOTICE
from app.pattern_adaptation.repository import candidate_content_sha256
from app.repository import NotFoundError
from app.topic_decisions import topic_subgenre_label
from app.writing_patterns.archive import (
    InvalidWritingPatternArchiveError,
    rebind_writing_pattern_rows,
    validate_writing_pattern_tables,
)

ARCHIVE_FORMAT = "mozhou-project"
ARCHIVE_FORMAT_VERSION = 17
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class ArchiveTable:
    name: str
    columns: tuple[str, ...]
    scope: str
    foreign_keys: tuple[tuple[str, str, bool], ...] = ()
    json_columns: tuple[str, ...] = ()
    identity_column: str | None = "id"


ARCHIVE_TABLES = (
    ArchiveTable(
        "projects",
        (
            "id",
            "title",
            "genre",
            "rebirth_year",
            "rebirth_location",
            "chapter_target_words",
            "safety_buffer_chapters",
            "created_at",
            "updated_at",
        ),
        "id = ?",
    ),
    ArchiveTable(
        "author_ideas",
        (
            "id",
            "project_id",
            "title",
            "content",
            "tags_json",
            "status",
            "target_kind",
            "target_id",
            "revision",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (("project_id", "projects", True),),
        ("tags_json",),
    ),
    ArchiveTable(
        "book_blueprints",
        (
            "id",
            "project_id",
            "idea",
            "content_json",
            "locks_json",
            "field_versions_json",
            "stale_fields_json",
            "plan_stale",
            "source_candidate_id",
            "revision",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (("project_id", "projects", False),),
        ("content_json", "locks_json", "field_versions_json", "stale_fields_json"),
    ),
    ArchiveTable(
        "volume_plans",
        (
            "id",
            "project_id",
            "volume_number",
            "content_json",
            "locked",
            "revision",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (("project_id", "projects", False),),
        ("content_json",),
    ),
    ArchiveTable(
        "rolling_chapter_plans",
        (
            "id",
            "project_id",
            "volume_plan_id",
            "chapter_number",
            "content_json",
            "locked",
            "revision",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("volume_plan_id", "volume_plans", False),
        ),
        ("content_json",),
    ),
    ArchiveTable(
        "creative_plan_dependencies",
        (
            "project_id",
            "subject_kind",
            "subject_id",
            "subject_revision",
            "dependency_snapshot_json",
            "dependency_fingerprint_sha256",
            "baseline_state",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (("project_id", "projects", False),),
        ("dependency_snapshot_json",),
        None,
    ),
    ArchiveTable(
        "plan_rebase_candidates",
        (
            "id",
            "project_id",
            "state",
            "revision",
            "based_on_dependency_fingerprint_sha256",
            "target_dependency_fingerprint_sha256",
            "impact_json",
            "book_blueprint_json",
            "volume_plans_json",
            "rolling_chapter_plans_json",
            "adoption_idempotency_key",
            "created_at",
            "updated_at",
            "adopted_at",
        ),
        "project_id = ?",
        (("project_id", "projects", False),),
        ("impact_json", "volume_plans_json", "rolling_chapter_plans_json"),
    ),
    ArchiveTable(
        "manuscript_volumes",
        (
            "id",
            "project_id",
            "volume_number",
            "title",
            "sort_key",
            "revision",
            "deleted_at",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (("project_id", "projects", False),),
    ),
    ArchiveTable(
        "chapters",
        (
            "id",
            "project_id",
            "volume_id",
            "volume_number",
            "chapter_number",
            "sort_key",
            "title",
            "content",
            "reader_promise",
            "opening_hook",
            "state_change",
            "emotional_payoff",
            "ending_cliffhanger",
            "status",
            "revision",
            "deleted_at",
            "updated_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("volume_id", "manuscript_volumes", False),
        ),
    ),
    ArchiveTable(
        "manuscript_scenes",
        (
            "id",
            "project_id",
            "chapter_id",
            "title",
            "summary",
            "sort_key",
            "revision",
            "deleted_at",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("chapter_id", "chapters", False),
        ),
    ),
    ArchiveTable(
        "directory_events",
        (
            "id",
            "project_id",
            "action",
            "node_kind",
            "node_id",
            "payload_json",
            "undone_at",
            "created_at",
        ),
        "project_id = ?",
        (("project_id", "projects", False),),
        ("payload_json",),
    ),
    ArchiveTable(
        "serial_daily_goals",
        (
            "id",
            "project_id",
            "goal_date",
            "target_characters",
            "revision",
            "updated_at",
        ),
        "project_id = ?",
        (("project_id", "projects", False),),
    ),
    ArchiveTable(
        "chapter_versions",
        (
            "id",
            "chapter_id",
            "version_number",
            "chapter_revision",
            "content",
            "content_sha256",
            "source",
            "source_id",
            "parent_version_id",
            "is_candidate",
            "created_at",
        ),
        "chapter_id IN (SELECT id FROM chapters WHERE project_id = ?)",
        (
            ("chapter_id", "chapters", False),
            ("parent_version_id", "chapter_versions", True),
        ),
    ),
    ArchiveTable(
        "context_packets",
        (
            "id",
            "project_id",
            "chapter_id",
            "chapter_revision",
            "task_type",
            "purpose",
            "subject_json",
            "profile_fingerprint_sha256",
            "dependency_snapshot_json",
            "dependency_fingerprint_sha256",
            "blocking_reasons_json",
            "compiler_version",
            "token_budget",
            "used_tokens",
            "overflow_tokens",
            "packet_sha256",
            "source_fingerprint_sha256",
            "packet_json",
            "rendered_context",
            "created_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("chapter_id", "chapters", True),
        ),
        (
            "subject_json",
            "dependency_snapshot_json",
            "blocking_reasons_json",
            "packet_json",
        ),
    ),
    ArchiveTable(
        "context_directives",
        (
            "id",
            "project_id",
            "chapter_id",
            "source_kind",
            "source_id",
            "action",
            "revision",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("chapter_id", "chapters", False),
        ),
    ),
    ArchiveTable(
        "chapter_annotations",
        (
            "id",
            "project_id",
            "chapter_id",
            "chapter_revision",
            "content_sha256",
            "start_char",
            "end_char",
            "selected_text",
            "context_before",
            "context_after",
            "comment",
            "status",
            "revision",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (("project_id", "projects", False), ("chapter_id", "chapters", False)),
    ),
    ArchiveTable(
        "generation_runs",
        (
            "id",
            "chapter_id",
            "state",
            "expected_chapter_revision",
            "candidate_content",
            "error_message",
            "provider",
            "model",
            "creative_safety_json",
            "created_at",
            "updated_at",
        ),
        "chapter_id IN (SELECT id FROM chapters WHERE project_id = ?)",
        (("chapter_id", "chapters", False),),
        ("creative_safety_json",),
    ),
    ArchiveTable(
        "chapter_events",
        ("id", "chapter_id", "from_status", "to_status", "revision", "created_at"),
        "chapter_id IN (SELECT id FROM chapters WHERE project_id = ?)",
        (("chapter_id", "chapters", False),),
    ),
    ArchiveTable(
        "run_events",
        ("id", "run_id", "sequence", "state", "created_at"),
        "run_id IN ("
        "SELECT r.id FROM generation_runs r "
        "JOIN chapters c ON c.id = r.chapter_id WHERE c.project_id = ?"
        ")",
        (("run_id", "generation_runs", False),),
    ),
    ArchiveTable(
        "jobs",
        (
            "id",
            "project_id",
            "chapter_id",
            "parent_job_id",
            "kind",
            "workflow",
            "state",
            "idempotency_key",
            "input_json",
            "progress_current",
            "progress_total",
            "current_step",
            "estimated_calls",
            "completed_calls",
            "provider",
            "provider_profile_id",
            "model",
            "lease_owner",
            "lease_expires_at",
            "heartbeat_at",
            "error_code",
            "error_message",
            "created_at",
            "updated_at",
            "started_at",
            "completed_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("chapter_id", "chapters", True),
            ("parent_job_id", "jobs", True),
        ),
        ("input_json",),
    ),
    ArchiveTable(
        "job_chunks",
        (
            "id",
            "job_id",
            "kind",
            "ordinal",
            "state",
            "idempotency_key",
            "input_json",
            "attempt_count",
            "error_code",
            "error_message",
            "created_at",
            "updated_at",
        ),
        "job_id IN (SELECT id FROM jobs WHERE project_id = ?)",
        (("job_id", "jobs", False),),
        ("input_json",),
    ),
    ArchiveTable(
        "job_attempts",
        (
            "id",
            "job_id",
            "chunk_id",
            "ordinal",
            "state",
            "provider",
            "provider_profile_id",
            "model",
            "input_tokens",
            "output_tokens",
            "duration_ms",
            "estimated_cost_microusd",
            "error_code",
            "error_message",
            "started_at",
            "completed_at",
        ),
        "job_id IN (SELECT id FROM jobs WHERE project_id = ?)",
        (
            ("job_id", "jobs", False),
            ("chunk_id", "job_chunks", True),
        ),
    ),
    ArchiveTable(
        "job_artifacts",
        (
            "id",
            "job_id",
            "chunk_id",
            "kind",
            "artifact_key",
            "content_type",
            "payload",
            "payload_sha256",
            "metadata_json",
            "provider",
            "provider_profile_id",
            "model",
            "created_at",
        ),
        "job_id IN (SELECT id FROM jobs WHERE project_id = ?)",
        (
            ("job_id", "jobs", False),
            ("chunk_id", "job_chunks", True),
        ),
        ("metadata_json",),
    ),
    ArchiveTable(
        "job_events",
        (
            "id",
            "job_id",
            "sequence",
            "event_type",
            "from_state",
            "to_state",
            "detail_json",
            "created_at",
        ),
        "job_id IN (SELECT id FROM jobs WHERE project_id = ?)",
        (("job_id", "jobs", False),),
        ("detail_json",),
    ),
    ArchiveTable(
        "chapter_productions",
        (
            "id",
            "project_id",
            "chapter_id",
            "base_chapter_revision",
            "base_chapter_content_sha256",
            "state",
            "revision",
            "current_outline_candidate_id",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("chapter_id", "chapters", False),
            ("current_outline_candidate_id", "chapter_outline_candidates", True),
        ),
    ),
    ArchiveTable(
        "chapter_production_events",
        (
            "id",
            "production_id",
            "sequence",
            "event_type",
            "from_state",
            "to_state",
            "detail_json",
            "created_at",
        ),
        "production_id IN (SELECT id FROM chapter_productions WHERE project_id = ?)",
        (("production_id", "chapter_productions", False),),
        ("detail_json",),
    ),
    ArchiveTable(
        "chapter_outline_candidates",
        (
            "id",
            "production_id",
            "ordinal",
            "label",
            "state",
            "current_revision",
            "current_content_sha256",
            "created_at",
            "updated_at",
        ),
        "production_id IN (SELECT id FROM chapter_productions WHERE project_id = ?)",
        (("production_id", "chapter_productions", False),),
    ),
    ArchiveTable(
        "chapter_outline_candidate_versions",
        (
            "id",
            "candidate_id",
            "revision",
            "content_json",
            "content_sha256",
            "operation",
            "parent_version_id",
            "source_job_id",
            "context_purpose",
            "context_packet_id",
            "context_packet_sha256",
            "context_dependency_fingerprint_sha256",
            "context_compiler_version",
            "profile_fingerprint_sha256",
            "provider",
            "model",
            "prompt_version",
            "created_at",
        ),
        "candidate_id IN (SELECT oc.id FROM chapter_outline_candidates oc "
        "JOIN chapter_productions p ON p.id = oc.production_id WHERE p.project_id = ?)",
        (
            ("candidate_id", "chapter_outline_candidates", False),
            ("parent_version_id", "chapter_outline_candidate_versions", True),
            ("source_job_id", "jobs", True),
            ("context_packet_id", "context_packets", True),
        ),
        ("content_json",),
    ),
    ArchiveTable(
        "chapter_preflight_checks",
        (
            "id",
            "production_id",
            "outline_candidate_id",
            "outline_version_id",
            "outline_revision",
            "outline_content_sha256",
            "reader_promise",
            "opening_hook",
            "state_change",
            "emotional_payoff",
            "ending_cliffhanger",
            "missing_fields_json",
            "passed",
            "created_at",
        ),
        "production_id IN (SELECT id FROM chapter_productions WHERE project_id = ?)",
        (
            ("production_id", "chapter_productions", False),
            ("outline_candidate_id", "chapter_outline_candidates", False),
            ("outline_version_id", "chapter_outline_candidate_versions", False),
        ),
        ("missing_fields_json",),
    ),
    ArchiveTable(
        "chapter_draft_candidates",
        (
            "id",
            "production_id",
            "label",
            "state",
            "source_outline_candidate_id",
            "source_outline_version_id",
            "source_outline_revision",
            "source_outline_content_sha256",
            "current_revision",
            "current_content_sha256",
            "created_at",
            "updated_at",
        ),
        "production_id IN (SELECT id FROM chapter_productions WHERE project_id = ?)",
        (
            ("production_id", "chapter_productions", False),
            ("source_outline_candidate_id", "chapter_outline_candidates", True),
            ("source_outline_version_id", "chapter_outline_candidate_versions", True),
        ),
    ),
    ArchiveTable(
        "chapter_draft_candidate_versions",
        (
            "id",
            "candidate_id",
            "revision",
            "content",
            "content_sha256",
            "operation",
            "parent_version_id",
            "restored_from_version_id",
            "source_job_id",
            "context_purpose",
            "context_packet_id",
            "context_packet_sha256",
            "context_dependency_fingerprint_sha256",
            "context_compiler_version",
            "profile_fingerprint_sha256",
            "provider",
            "model",
            "prompt_version",
            "instruction",
            "created_at",
        ),
        "candidate_id IN (SELECT dc.id FROM chapter_draft_candidates dc "
        "JOIN chapter_productions p ON p.id = dc.production_id WHERE p.project_id = ?)",
        (
            ("candidate_id", "chapter_draft_candidates", False),
            ("parent_version_id", "chapter_draft_candidate_versions", True),
            ("restored_from_version_id", "chapter_draft_candidate_versions", True),
            ("source_job_id", "jobs", True),
            ("context_packet_id", "context_packets", True),
        ),
    ),
    ArchiveTable(
        "chapter_draft_candidate_locks",
        (
            "id",
            "candidate_id",
            "start_char",
            "end_char",
            "locked_text",
            "locked_text_sha256",
            "created_from_version_id",
            "created_at",
        ),
        "candidate_id IN (SELECT dc.id FROM chapter_draft_candidates dc "
        "JOIN chapter_productions p ON p.id = dc.production_id WHERE p.project_id = ?)",
        (
            ("candidate_id", "chapter_draft_candidates", False),
            ("created_from_version_id", "chapter_draft_candidate_versions", False),
        ),
    ),
    ArchiveTable(
        "chapter_candidate_reviews",
        (
            "id",
            "candidate_id",
            "candidate_version_id",
            "candidate_revision",
            "candidate_content_sha256",
            "source_job_id",
            "context_purpose",
            "context_packet_id",
            "context_packet_sha256",
            "context_dependency_fingerprint_sha256",
            "context_compiler_version",
            "profile_fingerprint_sha256",
            "provider",
            "model",
            "prompt_version",
            "findings_json",
            "created_at",
        ),
        "candidate_id IN (SELECT dc.id FROM chapter_draft_candidates dc "
        "JOIN chapter_productions p ON p.id = dc.production_id WHERE p.project_id = ?)",
        (
            ("candidate_id", "chapter_draft_candidates", False),
            ("candidate_version_id", "chapter_draft_candidate_versions", False),
            ("source_job_id", "jobs", True),
            ("context_packet_id", "context_packets", False),
        ),
        ("findings_json",),
    ),
    ArchiveTable(
        "chapter_candidate_merge_sources",
        (
            "result_candidate_id",
            "result_version_id",
            "ordinal",
            "source_candidate_id",
            "source_version_id",
            "source_revision",
            "source_content_sha256",
            "start_char",
            "end_char",
            "selected_text_sha256",
        ),
        "result_candidate_id IN (SELECT dc.id FROM chapter_draft_candidates dc "
        "JOIN chapter_productions p ON p.id = dc.production_id WHERE p.project_id = ?)",
        (
            ("result_candidate_id", "chapter_draft_candidates", False),
            ("result_version_id", "chapter_draft_candidate_versions", False),
            ("source_candidate_id", "chapter_draft_candidates", False),
            ("source_version_id", "chapter_draft_candidate_versions", False),
        ),
        identity_column=None,
    ),
    ArchiveTable(
        "chapter_writing_outcomes",
        (
            "id",
            "production_id",
            "candidate_id",
            "candidate_version_id",
            "candidate_revision",
            "candidate_content_sha256",
            "source_outline_candidate_id",
            "source_outline_version_id",
            "source_outline_revision",
            "source_outline_content_sha256",
            "decision",
            "adoption_mode",
            "base_chapter_revision",
            "base_chapter_content_sha256",
            "final_chapter_revision",
            "final_chapter_content_sha256",
            "final_chapter_status",
            "chapter_version_id",
            "adoption_detail_json",
            "idempotency_key",
            "request_sha256",
            "reason",
            "created_at",
        ),
        "production_id IN (SELECT id FROM chapter_productions WHERE project_id = ?)",
        (
            ("production_id", "chapter_productions", False),
            ("candidate_id", "chapter_draft_candidates", False),
            ("candidate_version_id", "chapter_draft_candidate_versions", False),
            ("source_outline_candidate_id", "chapter_outline_candidates", True),
            ("source_outline_version_id", "chapter_outline_candidate_versions", True),
            ("chapter_version_id", "chapter_versions", True),
        ),
        ("adoption_detail_json",),
    ),
    ArchiveTable(
        "craft_pattern_assets",
        (
            "id",
            "series_id",
            "schema_version",
            "asset_type",
            "version",
            "generation_fingerprint_sha256",
            "source_job_id",
            "source_work_ids_json",
            "source_segment_ids_json",
            "source_asset_version_ids_json",
            "title",
            "summary",
            "author_focus",
            "craft_items_json",
            "provider",
            "provider_profile_id",
            "profile_revision",
            "model",
            "prompt_version",
            "evidence_validator_version",
            "source_fingerprint_sha256",
            "content_sha256",
            "created_at",
        ),
        "id IN ("
        "WITH RECURSIVE asset_tree(id) AS ("
        "SELECT asset_version_id FROM project_craft_pattern_assets WHERE project_id = ?1 "
        "UNION SELECT o.asset_version_id FROM craft_pattern_job_outputs o "
        "JOIN jobs j ON j.id = o.job_id WHERE j.project_id = ?1 "
        "UNION SELECT s.asset_version_id FROM writing_pattern_recipe_sources s "
        "JOIN writing_pattern_recipe_versions rv ON rv.id = s.recipe_version_id "
        "WHERE rv.recipe_id IN ("
        "SELECT r.id FROM writing_pattern_recipes r "
        "WHERE r.created_from_project_id = ?1 "
        "UNION SELECT used.recipe_id FROM writing_pattern_profile_versions p "
        "JOIN writing_pattern_recipe_versions used ON used.id = p.recipe_version_id "
        "WHERE p.project_id = ?1"
        ") "
        "UNION SELECT child.value FROM asset_tree tree "
        "JOIN craft_pattern_assets parent ON parent.id = tree.id "
        "JOIN json_each(parent.source_asset_version_ids_json) child"
        ") SELECT id FROM asset_tree)",
        (("source_job_id", "jobs", True),),
        (
            "source_work_ids_json",
            "source_segment_ids_json",
            "source_asset_version_ids_json",
            "craft_items_json",
        ),
    ),
    ArchiveTable(
        "project_craft_pattern_assets",
        (
            "id",
            "project_id",
            "asset_version_id",
            "lifecycle_state",
            "lifecycle_revision",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("asset_version_id", "craft_pattern_assets", False),
        ),
    ),
    ArchiveTable(
        "craft_pattern_job_outputs",
        ("id", "job_id", "asset_version_id", "ordinal", "created_at"),
        "job_id IN (SELECT id FROM jobs WHERE project_id = ?)",
        (
            ("job_id", "jobs", False),
            ("asset_version_id", "craft_pattern_assets", False),
        ),
    ),
    ArchiveTable(
        "topic_decisions",
        (
            "id",
            "project_id",
            "content_json",
            "locks_json",
            "field_versions_json",
            "rejection_reasons_json",
            "source_template_id",
            "source_job_id",
            "source_candidate_ids_json",
            "revision",
            "confirmed_revision",
            "plan_stale",
            "onboarding_required",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("source_job_id", "jobs", True),
        ),
        ("source_candidate_ids_json",),
    ),
    ArchiveTable(
        "topic_decision_versions",
        (
            "id",
            "topic_decision_id",
            "project_id",
            "revision",
            "content_json",
            "locks_json",
            "field_versions_json",
            "rejection_reasons_json",
            "source_template_id",
            "source_job_id",
            "source_candidate_ids_json",
            "content_sha256",
            "created_at",
        ),
        "project_id = ?",
        (
            ("topic_decision_id", "topic_decisions", False),
            ("project_id", "projects", False),
            ("source_job_id", "jobs", True),
        ),
        ("source_candidate_ids_json",),
    ),
    ArchiveTable(
        "topic_decision_candidate_sets",
        (
            "id",
            "topic_decision_id",
            "project_id",
            "source_job_id",
            "based_on_revision",
            "target_field",
            "created_at",
        ),
        "project_id = ?",
        (
            ("topic_decision_id", "topic_decisions", False),
            ("project_id", "projects", False),
            ("source_job_id", "jobs", False),
        ),
    ),
    ArchiveTable(
        "topic_decision_candidates",
        (
            "id",
            "candidate_set_id",
            "project_id",
            "ordinal",
            "label",
            "content_json",
            "changed_fields_json",
            "rationale",
            "risks_json",
            "state",
            "rejection_reason",
            "created_at",
            "updated_at",
            "decided_at",
        ),
        "project_id = ?",
        (
            ("candidate_set_id", "topic_decision_candidate_sets", False),
            ("project_id", "projects", False),
        ),
    ),
    ArchiveTable(
        "writing_pattern_recipes",
        (
            "id",
            "created_from_project_id",
            "lifecycle_state",
            "lifecycle_revision",
            "created_at",
            "updated_at",
        ),
        "created_from_project_id = ?1 OR id IN ("
        "SELECT rv.recipe_id FROM writing_pattern_profile_versions p "
        "JOIN writing_pattern_recipe_versions rv ON rv.id = p.recipe_version_id "
        "WHERE p.project_id = ?1)",
        (("created_from_project_id", "projects", True),),
    ),
    ArchiveTable(
        "writing_pattern_recipe_versions",
        (
            "id",
            "recipe_id",
            "version",
            "name",
            "description",
            "conflict_decisions_json",
            "conflicts_json",
            "source_asset_count",
            "source_work_count",
            "safety_basis",
            "source_snapshot_sha256",
            "content_sha256",
            "created_at",
        ),
        "recipe_id IN ("
        "SELECT r.id FROM writing_pattern_recipes r "
        "WHERE r.created_from_project_id = ?1 "
        "UNION SELECT used.recipe_id FROM writing_pattern_profile_versions p "
        "JOIN writing_pattern_recipe_versions used ON used.id = p.recipe_version_id "
        "WHERE p.project_id = ?1)",
        (("recipe_id", "writing_pattern_recipes", False),),
        ("conflict_decisions_json", "conflicts_json"),
    ),
    ArchiveTable(
        "writing_pattern_recipe_sources",
        (
            "id",
            "recipe_version_id",
            "ordinal",
            "entry_key",
            "asset_version_id",
            "asset_series_id",
            "asset_version",
            "asset_content_sha256",
            "asset_type",
            "dimension",
            "pattern_name",
            "transferable_rule",
            "adaptation_risk",
            "purpose",
            "strategy",
            "weight",
            "applicable_stages_json",
            "chapter_start",
            "chapter_end",
            "note",
            "source_work_fingerprints_json",
            "source_snapshot_sha256",
        ),
        "recipe_version_id IN ("
        "SELECT rv.id FROM writing_pattern_recipe_versions rv "
        "WHERE rv.recipe_id IN ("
        "SELECT r.id FROM writing_pattern_recipes r "
        "WHERE r.created_from_project_id = ?1 "
        "UNION SELECT used.recipe_id FROM writing_pattern_profile_versions p "
        "JOIN writing_pattern_recipe_versions used ON used.id = p.recipe_version_id "
        "WHERE p.project_id = ?1))",
        (
            ("recipe_version_id", "writing_pattern_recipe_versions", False),
            ("asset_version_id", "craft_pattern_assets", False),
        ),
        ("applicable_stages_json", "source_work_fingerprints_json"),
    ),
    ArchiveTable(
        "writing_pattern_profile_versions",
        (
            "id",
            "project_id",
            "recipe_version_id",
            "recipe_content_sha256",
            "topic_decision_version_id",
            "topic_revision",
            "topic_content_sha256",
            "compiler_version",
            "safety_basis",
            "source_snapshot_sha256",
            "profile_json",
            "conflicts_json",
            "decisions_json",
            "excluded_entry_keys_json",
            "profile_fingerprint_sha256",
            "created_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("recipe_version_id", "writing_pattern_recipe_versions", False),
            ("topic_decision_version_id", "topic_decision_versions", False),
        ),
        (
            "profile_json",
            "conflicts_json",
            "decisions_json",
            "excluded_entry_keys_json",
        ),
    ),
    ArchiveTable(
        "project_writing_pattern_profiles",
        (
            "id",
            "project_id",
            "profile_version_id",
            "lifecycle_state",
            "lifecycle_revision",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("profile_version_id", "writing_pattern_profile_versions", False),
        ),
    ),
    ArchiveTable(
        "writing_pattern_adaptation_proposals",
        (
            "id",
            "job_id",
            "project_id",
            "profile_version_id",
            "profile_fingerprint_sha256",
            "recipe_version_id",
            "recipe_content_sha256",
            "topic_decision_version_id",
            "topic_revision",
            "topic_content_sha256",
            "base_blueprint_id",
            "base_blueprint_revision",
            "base_blueprint_content_sha256",
            "lock_snapshot_json",
            "lock_snapshot_sha256",
            "dependency_fingerprint_sha256",
            "safe_context_sha256",
            "provider",
            "provider_profile_id",
            "provider_profile_revision",
            "model",
            "input_cost_microusd_per_million",
            "output_cost_microusd_per_million",
            "prompt_version",
            "estimated_input_tokens",
            "estimated_output_tokens",
            "estimated_cost_microusd",
            "cost_status",
            "result_state",
            "stale_reason",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (
            ("job_id", "jobs", False),
            ("project_id", "projects", False),
            ("profile_version_id", "writing_pattern_profile_versions", False),
            ("recipe_version_id", "writing_pattern_recipe_versions", False),
            ("topic_decision_version_id", "topic_decision_versions", False),
            ("base_blueprint_id", "book_blueprints", True),
        ),
        ("lock_snapshot_json",),
    ),
    ArchiveTable(
        "writing_pattern_adaptation_candidates",
        (
            "id",
            "proposal_id",
            "ordinal",
            "label",
            "why_distinct",
            "distinct_axes_json",
            "risk_hypotheses_json",
            "current_revision",
            "current_content_sha256",
            "created_at",
            "updated_at",
        ),
        "proposal_id IN (SELECT id FROM writing_pattern_adaptation_proposals WHERE project_id = ?)",
        (("proposal_id", "writing_pattern_adaptation_proposals", False),),
        ("distinct_axes_json", "risk_hypotheses_json"),
    ),
    ArchiveTable(
        "writing_pattern_adaptation_candidate_versions",
        (
            "id",
            "candidate_id",
            "revision",
            "blueprint_json",
            "key_scene_sequence_json",
            "transformation_notes_json",
            "content_sha256",
            "changed_fields_json",
            "source",
            "created_at",
        ),
        "candidate_id IN ("
        "SELECT c.id FROM writing_pattern_adaptation_candidates c "
        "JOIN writing_pattern_adaptation_proposals p ON p.id = c.proposal_id "
        "WHERE p.project_id = ?)",
        (("candidate_id", "writing_pattern_adaptation_candidates", False),),
        (
            "blueprint_json",
            "key_scene_sequence_json",
            "transformation_notes_json",
            "changed_fields_json",
        ),
    ),
    ArchiveTable(
        "writing_pattern_adoptions",
        (
            "id",
            "project_id",
            "proposal_id",
            "candidate_id",
            "candidate_version_id",
            "blueprint_id",
            "blueprint_revision",
            "blueprint_content_sha256",
            "profile_fingerprint_sha256",
            "recipe_content_sha256",
            "idempotency_key",
            "created_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("proposal_id", "writing_pattern_adaptation_proposals", False),
            ("candidate_id", "writing_pattern_adaptation_candidates", False),
            (
                "candidate_version_id",
                "writing_pattern_adaptation_candidate_versions",
                False,
            ),
            ("blueprint_id", "book_blueprints", False),
        ),
    ),
    ArchiveTable(
        "writing_pattern_originality_reports",
        (
            "id",
            "project_id",
            "adoption_id",
            "profile_fingerprint_sha256",
            "recipe_content_sha256",
            "blueprint_id",
            "blueprint_revision",
            "blueprint_content_sha256",
            "candidate_version_id",
            "candidate_content_sha256",
            "risk_level",
            "status",
            "score",
            "threshold_version",
            "input_sha256",
            "source_availability",
            "viewed_at",
            "acknowledged_at",
            "created_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("adoption_id", "writing_pattern_adoptions", False),
            ("blueprint_id", "book_blueprints", False),
            (
                "candidate_version_id",
                "writing_pattern_adaptation_candidate_versions",
                False,
            ),
        ),
    ),
    ArchiveTable(
        "writing_pattern_originality_findings",
        (
            "id",
            "report_id",
            "ordinal",
            "signal",
            "score",
            "summary",
            "source_fingerprint_sha256",
            "evidence_sha256",
        ),
        "report_id IN (SELECT id FROM writing_pattern_originality_reports WHERE project_id = ?)",
        (("report_id", "writing_pattern_originality_reports", False),),
    ),
    ArchiveTable(
        "comic_projects",
        (
            "id",
            "project_id",
            "title",
            "source_chapter_ids_json",
            "source_snapshot_json",
            "source_snapshot_sha256",
            "episode_target_count",
            "episode_duration_seconds",
            "aspect_ratio",
            "art_style",
            "adaptation_mode",
            "narration_preference",
            "author_requirements",
            "state",
            "season_revision",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (("project_id", "projects", False),),
        ("source_chapter_ids_json", "source_snapshot_json"),
    ),
    ArchiveTable(
        "comic_episodes",
        (
            "id",
            "comic_project_id",
            "episode_number",
            "title",
            "source_chapter_ids_json",
            "outline_state",
            "script_state",
            "outline_revision",
            "script_revision",
            "created_at",
            "updated_at",
        ),
        "comic_project_id IN (SELECT id FROM comic_projects WHERE project_id = ?)",
        (("comic_project_id", "comic_projects", False),),
        ("source_chapter_ids_json",),
    ),
    ArchiveTable(
        "comic_versions",
        (
            "id",
            "comic_project_id",
            "episode_id",
            "target_kind",
            "target_id",
            "version_number",
            "state",
            "content_json",
            "content_sha256",
            "source_snapshot_sha256",
            "job_id",
            "created_at",
            "reviewed_at",
        ),
        "comic_project_id IN (SELECT id FROM comic_projects WHERE project_id = ?)",
        (
            ("comic_project_id", "comic_projects", False),
            ("episode_id", "comic_episodes", True),
            ("job_id", "jobs", True),
        ),
        ("content_json",),
    ),
    ArchiveTable(
        "comic_scenes",
        (
            "id",
            "comic_project_id",
            "episode_id",
            "script_version_id",
            "scene_number",
            "content_json",
            "source_chapter_ids_json",
            "created_at",
        ),
        "comic_project_id IN (SELECT id FROM comic_projects WHERE project_id = ?)",
        (
            ("comic_project_id", "comic_projects", False),
            ("episode_id", "comic_episodes", False),
            ("script_version_id", "comic_versions", False),
        ),
        ("content_json", "source_chapter_ids_json"),
    ),
    ArchiveTable(
        "review_findings",
        (
            "id",
            "project_id",
            "chapter_id",
            "chapter_revision",
            "review_job_id",
            "dimension",
            "severity",
            "code",
            "title",
            "evidence_json",
            "explanation",
            "suggestion",
            "suggested_replacement",
            "confidence",
            "dedupe_key",
            "state",
            "created_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("chapter_id", "chapters", False),
            ("review_job_id", "jobs", True),
        ),
        ("evidence_json",),
    ),
    ArchiveTable(
        "text_change_sets",
        (
            "id",
            "chapter_id",
            "base_chapter_revision",
            "base_content_sha256",
            "title",
            "state",
            "revision",
            "creative_safety_json",
            "created_at",
            "updated_at",
        ),
        "chapter_id IN (SELECT id FROM chapters WHERE project_id = ?)",
        (("chapter_id", "chapters", False),),
        ("creative_safety_json",),
    ),
    ArchiveTable(
        "text_changes",
        (
            "id",
            "change_set_id",
            "ordinal",
            "start_char",
            "end_char",
            "original_text",
            "replacement_text",
            "rationale",
            "review_finding_id",
            "selected",
            "applied_replacement",
        ),
        "change_set_id IN ("
        "SELECT s.id FROM text_change_sets s "
        "JOIN chapters c ON c.id = s.chapter_id WHERE c.project_id = ?"
        ")",
        (
            ("change_set_id", "text_change_sets", False),
            ("review_finding_id", "review_findings", True),
        ),
    ),
    ArchiveTable(
        "timeline_events",
        (
            "id",
            "project_id",
            "layer",
            "event_year",
            "title",
            "summary",
            "source_chapter_id",
            "created_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("source_chapter_id", "chapters", True),
        ),
    ),
    ArchiveTable(
        "story_facts",
        ("id", "project_id", "source_chapter_id", "kind", "content", "created_at"),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("source_chapter_id", "chapters", False),
        ),
    ),
    ArchiveTable(
        "fact_change_sets",
        (
            "id",
            "chapter_id",
            "chapter_revision",
            "state",
            "revision",
            "creative_safety_json",
            "created_at",
            "updated_at",
        ),
        "chapter_id IN (SELECT id FROM chapters WHERE project_id = ?)",
        (("chapter_id", "chapters", False),),
        ("creative_safety_json",),
    ),
    ArchiveTable(
        "fact_changes",
        ("id", "change_set_id", "kind", "content", "event_year"),
        "change_set_id IN ("
        "SELECT s.id FROM fact_change_sets s "
        "JOIN chapters c ON c.id = s.chapter_id WHERE c.project_id = ?"
        ")",
        (("change_set_id", "fact_change_sets", False),),
    ),
    ArchiveTable(
        "future_knowledge",
        (
            "id",
            "project_id",
            "future_year",
            "content",
            "source_note",
            "confidence",
            "status",
            "divergence_event_id",
            "revision",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("divergence_event_id", "timeline_events", True),
        ),
    ),
    ArchiveTable(
        "story_entities",
        (
            "id",
            "project_id",
            "kind",
            "name",
            "role",
            "goal",
            "current_state",
            "relationship_notes",
            "revision",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (("project_id", "projects", False),),
    ),
    ArchiveTable(
        "story_threads",
        (
            "id",
            "project_id",
            "source_chapter_id",
            "title",
            "summary",
            "status",
            "planted_chapter_number",
            "resolved_chapter_id",
            "revision",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("source_chapter_id", "chapters", True),
            ("resolved_chapter_id", "chapters", True),
        ),
    ),
    ArchiveTable(
        "story_relationships",
        (
            "id",
            "project_id",
            "source_entity_id",
            "target_entity_id",
            "relation_type",
            "summary",
            "status",
            "source_chapter_id",
            "revision",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("source_entity_id", "story_entities", False),
            ("target_entity_id", "story_entities", False),
            ("source_chapter_id", "chapters", True),
        ),
    ),
    ArchiveTable(
        "source_documents",
        (
            "id",
            "title",
            "source_filename",
            "source_format",
            "source_sha256",
            "content_sha256",
            "source_encoding",
            "encoding_confidence",
            "import_state",
            "source_spans_json",
            "duplicate_of_id",
            "content",
            "created_at",
            "updated_at",
        ),
        "id IN (SELECT source_document_id FROM source_cards WHERE project_id = ? AND source_document_id IS NOT NULL) "
        "OR id IN (SELECT rs.source_document_id FROM research_sources rs JOIN research_sessions s ON s.id = rs.session_id WHERE s.project_id = ? AND rs.source_document_id IS NOT NULL)",
        (),
        ("source_spans_json",),
    ),
    ArchiveTable(
        "source_cards",
        (
            "id",
            "project_id",
            "source_kind",
            "title",
            "source_reference",
            "applicable_year_start",
            "applicable_year_end",
            "confidence",
            "excerpt",
            "source_document_id",
            "source_date",
            "page_number_start",
            "page_number_end",
            "start_char",
            "end_char",
            "confirmed",
            "revision",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("source_document_id", "source_documents", True),
        ),
    ),
    ArchiveTable(
        "research_sessions",
        (
            "id",
            "project_id",
            "title",
            "question",
            "era_start",
            "era_end",
            "region",
            "material_type",
            "mode",
            "state",
            "source_set_sha256",
            "job_id",
            "invalid_ai_findings",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (("project_id", "projects", False), ("job_id", "jobs", True)),
    ),
    ArchiveTable(
        "research_sources",
        (
            "id",
            "session_id",
            "source_document_id",
            "label",
            "source_format",
            "content",
            "content_sha256",
            "source_spans_json",
            "ordinal",
            "created_at",
        ),
        "session_id IN (SELECT id FROM research_sessions WHERE project_id = ?)",
        (
            ("session_id", "research_sessions", False),
            ("source_document_id", "source_documents", True),
        ),
        ("source_spans_json",),
    ),
    ArchiveTable(
        "research_findings",
        (
            "id",
            "session_id",
            "research_source_id",
            "source_document_id",
            "category",
            "title",
            "summary",
            "evidence_excerpt",
            "evidence_sha256",
            "start_char",
            "end_char",
            "page_number_start",
            "page_number_end",
            "applicable_year_start",
            "applicable_year_end",
            "region",
            "confidence",
            "conflict_key",
            "origin",
            "state",
            "source_card_id",
            "revision",
            "created_at",
            "updated_at",
        ),
        "session_id IN (SELECT id FROM research_sessions WHERE project_id = ?)",
        (
            ("session_id", "research_sessions", False),
            ("research_source_id", "research_sources", False),
            ("source_document_id", "source_documents", True),
            ("source_card_id", "source_cards", True),
        ),
    ),
    ArchiveTable(
        "reference_works",
        (
            "id",
            "title",
            "source_filename",
            "source_format",
            "rights_basis",
            "total_characters",
            "segment_target_characters",
            "content_sha256",
            "source_sha256",
            "source_encoding",
            "encoding_confidence",
            "import_state",
            "source_spans_json",
            "duplicate_of_id",
            "created_at",
            "updated_at",
        ),
        "id IN (SELECT reference_work_id FROM project_reference_works WHERE project_id = ?)",
        (),
        ("source_spans_json",),
    ),
    ArchiveTable(
        "reference_segments",
        (
            "id",
            "reference_work_id",
            "ordinal",
            "start_char",
            "end_char",
            "character_count",
            "chapter_start",
            "chapter_end",
            "content",
            "created_at",
        ),
        "reference_work_id IN (SELECT reference_work_id FROM project_reference_works WHERE project_id = ?)",
        (("reference_work_id", "reference_works", False),),
    ),
    ArchiveTable(
        "reference_pattern_cards",
        (
            "id",
            "project_id",
            "selected_segment_ids_json",
            "author_focus",
            "proposal_json",
            "provider",
            "model",
            "source_job_id",
            "created_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("source_job_id", "jobs", True),
        ),
        ("selected_segment_ids_json", "proposal_json"),
    ),
    ArchiveTable(
        "reference_pattern_applications",
        (
            "id",
            "project_id",
            "pattern_card_id",
            "lifecycle_state",
            "lifecycle_revision",
            "selected_dimensions_json",
            "dimensions_json",
            "relationship_recomposition",
            "application_note",
            "blueprint_json",
            "originality_status",
            "risk_level",
            "latest_report_id",
            "threshold_version",
            "revision",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("pattern_card_id", "reference_pattern_cards", False),
            ("latest_report_id", "originality_reports", True),
        ),
        ("selected_dimensions_json", "dimensions_json", "blueprint_json"),
    ),
    ArchiveTable(
        "reference_blueprint_versions",
        (
            "id",
            "application_id",
            "blueprint_revision",
            "blueprint_json",
            "changed_dimensions_json",
            "relationship_changed",
            "created_at",
        ),
        "application_id IN (SELECT id FROM reference_pattern_applications WHERE project_id = ?)",
        (("application_id", "reference_pattern_applications", False),),
        ("blueprint_json", "changed_dimensions_json"),
    ),
    ArchiveTable(
        "originality_reports",
        (
            "id",
            "application_id",
            "blueprint_revision",
            "risk_level",
            "score",
            "threshold_version",
            "checked_dimensions_json",
            "evidence_json",
            "source_segment_ids_json",
            "input_sha256",
            "viewed_at",
            "acknowledged_at",
            "created_at",
        ),
        "application_id IN (SELECT id FROM reference_pattern_applications WHERE project_id = ?)",
        (("application_id", "reference_pattern_applications", False),),
        (
            "checked_dimensions_json",
            "evidence_json",
            "source_segment_ids_json",
        ),
    ),
    ArchiveTable(
        "scene_originality_checks",
        (
            "id",
            "application_id",
            "blueprint_revision",
            "risk_level",
            "score",
            "threshold_version",
            "candidate_graph_json",
            "source_segment_ids_json",
            "source_work_count",
            "input_sha256",
            "viewed_at",
            "acknowledged_at",
            "created_at",
        ),
        "application_id IN (SELECT id FROM reference_pattern_applications WHERE project_id = ?)",
        (("application_id", "reference_pattern_applications", False),),
        ("candidate_graph_json", "source_segment_ids_json"),
    ),
    ArchiveTable(
        "scene_originality_findings",
        (
            "id",
            "check_id",
            "ordinal",
            "signal",
            "score",
            "summary",
            "source_segment_ids_json",
            "evidence_sha256",
        ),
        "check_id IN (SELECT s.id FROM scene_originality_checks s "
        "JOIN reference_pattern_applications a ON a.id = s.application_id "
        "WHERE a.project_id = ?)",
        (("check_id", "scene_originality_checks", False),),
        ("source_segment_ids_json",),
    ),
)


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class InvalidProjectArchiveError(ValueError):
    pass


class ProjectArchiveTooLargeError(ValueError):
    pass


def _reject_json_constant(value: str) -> None:
    raise InvalidProjectArchiveError(f"invalid_json_constant:{value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidProjectArchiveError("duplicate_json_key")
        result[key] = value
    return result


def _parse_json(raw: bytes | str) -> Any:
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except InvalidProjectArchiveError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise InvalidProjectArchiveError("invalid_json") from error


def _valid_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise InvalidProjectArchiveError("invalid_uuid")
    try:
        return str(UUID(value))
    except ValueError as error:
        raise InvalidProjectArchiveError("invalid_uuid") from error


def _remap_json(value: Any, id_map: dict[str, str]) -> Any:
    if isinstance(value, str):
        return id_map.get(value, value)
    if isinstance(value, list):
        return [_remap_json(item, id_map) for item in value]
    if isinstance(value, dict):
        return {key: _remap_json(item, id_map) for key, item in value.items()}
    return value


def _sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _validate_m32_archive_rows(tables: dict[str, Any]) -> None:
    for row in tables["context_packets"]:
        packet = ContextPacket.model_validate_json(str(row["packet_json"]))
        if (
            packet.id != row["id"]
            or packet.project_id != row["project_id"]
            or packet.chapter_id != row["chapter_id"]
            or packet.chapter_revision != row["chapter_revision"]
            or (packet.task_type.value if packet.task_type is not None else None)
            != row["task_type"]
            or packet.purpose.value != row["purpose"]
            or packet.packet_sha256 != row["packet_sha256"]
            or packet.source_fingerprint_sha256 != row["source_fingerprint_sha256"]
            or packet.dependency_fingerprint_sha256
            != row["dependency_fingerprint_sha256"]
        ):
            raise InvalidProjectArchiveError("invalid_context_packet")

    for row in tables["creative_plan_dependencies"]:
        dependency = ContextDependencySnapshot.model_validate_json(
            str(row["dependency_snapshot_json"])
        )
        if (
            row["subject_kind"]
            not in {"book_blueprint", "volume_plan", "rolling_plan"}
            or row["baseline_state"] not in {"current", "legacy"}
            or not isinstance(row["subject_revision"], int)
            or row["subject_revision"] < 0
            or not compare_digest(
                _sha256_json(dependency.model_dump(mode="json")),
                str(row["dependency_fingerprint_sha256"]),
            )
        ):
            raise InvalidProjectArchiveError("invalid_creative_plan_dependency")

    for row in tables["plan_rebase_candidates"]:
        PlanRebaseCandidate.model_validate(
            {
                **row,
                "impact": _parse_json(row["impact_json"]),
                "book_blueprint": (
                    _parse_json(row["book_blueprint_json"])
                    if row["book_blueprint_json"] is not None
                    else None
                ),
                "volume_plans": _parse_json(row["volume_plans_json"]),
                "rolling_chapter_plans": _parse_json(
                    row["rolling_chapter_plans_json"]
                ),
            }
        )


def _chapter_production_trace(row: dict[str, Any]) -> ModelTrace | None:
    purpose = row["context_purpose"]
    trace_columns = (
        "context_packet_id",
        "context_packet_sha256",
        "context_dependency_fingerprint_sha256",
        "context_compiler_version",
        "provider",
        "model",
        "prompt_version",
    )
    if purpose is None:
        if any(row[column] is not None for column in trace_columns):
            raise InvalidProjectArchiveError("invalid_chapter_production_trace")
        return None
    return ModelTrace.model_validate(
        {
            "purpose": purpose,
            "context_packet_id": row["context_packet_id"],
            "context_packet_sha256": row["context_packet_sha256"],
            "context_dependency_fingerprint_sha256": row[
                "context_dependency_fingerprint_sha256"
            ],
            "context_compiler_version": row["context_compiler_version"],
            "profile_fingerprint_sha256": row["profile_fingerprint_sha256"],
            "provider": row["provider"],
            "model": row["model"],
            "prompt_version": row["prompt_version"],
        }
    )


def _validate_m33_archive_rows(tables: dict[str, Any]) -> None:
    """Validate the complete candidate graph, not only its SQL-shaped rows."""

    chapters = {str(row["id"]): row for row in tables["chapters"]}
    chapter_versions = {str(row["id"]): row for row in tables["chapter_versions"]}
    productions: dict[str, dict[str, Any]] = {}
    for row in tables["chapter_productions"]:
        production_model = ChapterProduction.model_validate(row)
        chapter = chapters.get(production_model.chapter_id)
        if chapter is None or chapter["project_id"] != production_model.project_id:
            raise InvalidProjectArchiveError("invalid_chapter_production")
        productions[production_model.id] = row

    event_sequences: dict[str, set[int]] = {}
    for row in tables["chapter_production_events"]:
        detail = _parse_json(row["detail_json"])
        if not isinstance(detail, dict):
            raise InvalidProjectArchiveError("invalid_chapter_production_event")
        event = ProductionEvent.model_validate({**row, "detail": detail})
        if event.production_id not in productions:
            raise InvalidProjectArchiveError("invalid_chapter_production_event")
        sequences = event_sequences.setdefault(event.production_id, set())
        if event.sequence in sequences:
            raise InvalidProjectArchiveError("invalid_chapter_production_event_sequence")
        sequences.add(event.sequence)

    outline_versions: dict[str, tuple[dict[str, Any], ChapterOutline]] = {}
    outline_versions_by_candidate_revision: dict[tuple[str, int], dict[str, Any]] = {}
    for row in tables["chapter_outline_candidate_versions"]:
        content = ChapterOutline.model_validate_json(str(row["content_json"]))
        trace = _chapter_production_trace(row)
        outline_version_model = OutlineCandidateVersion.model_validate(
            {
                **row,
                "content": content,
                "trace": trace,
            }
        )
        if not compare_digest(
            _sha256_json(content.model_dump(mode="json")),
            outline_version_model.content_sha256,
        ):
            raise InvalidProjectArchiveError("invalid_chapter_outline_hash")
        key = (outline_version_model.candidate_id, outline_version_model.revision)
        if key in outline_versions_by_candidate_revision:
            raise InvalidProjectArchiveError("invalid_chapter_outline_revision")
        outline_versions[outline_version_model.id] = (row, content)
        outline_versions_by_candidate_revision[key] = row

    outline_candidates: dict[str, dict[str, Any]] = {}
    for row in tables["chapter_outline_candidates"]:
        production_row = productions.get(str(row["production_id"]))
        current_outline_version_row = outline_versions_by_candidate_revision.get(
            (str(row["id"]), int(row["current_revision"]))
        )
        if (
            production_row is None
            or current_outline_version_row is None
            or current_outline_version_row["content_sha256"]
            != row["current_content_sha256"]
        ):
            raise InvalidProjectArchiveError("invalid_chapter_outline_candidate")
        outline_candidates[str(row["id"])] = row

    for production_row in productions.values():
        current_outline_id = production_row["current_outline_candidate_id"]
        if current_outline_id is None:
            continue
        outline = outline_candidates.get(str(current_outline_id))
        if outline is None or outline["production_id"] != production_row["id"]:
            raise InvalidProjectArchiveError("invalid_current_chapter_outline")

    for row in tables["chapter_preflight_checks"]:
        missing_fields = _parse_json(row["missing_fields_json"])
        if not isinstance(missing_fields, list):
            raise InvalidProjectArchiveError("invalid_chapter_preflight")
        check = PreflightCheck.model_validate(
            {
                **row,
                "reader_promise": bool(row["reader_promise"]),
                "opening_hook": bool(row["opening_hook"]),
                "state_change": bool(row["state_change"]),
                "emotional_payoff": bool(row["emotional_payoff"]),
                "ending_cliffhanger": bool(row["ending_cliffhanger"]),
                "missing_fields": missing_fields,
                "passed": bool(row["passed"]),
            }
        )
        version_entry = outline_versions.get(check.outline_version_id)
        candidate = outline_candidates.get(check.outline_candidate_id)
        if (
            version_entry is None
            or candidate is None
            or candidate["production_id"] != check.production_id
            or version_entry[0]["candidate_id"] != check.outline_candidate_id
            or version_entry[0]["revision"] != check.outline_revision
            or version_entry[0]["content_sha256"] != check.outline_content_sha256
        ):
            raise InvalidProjectArchiveError("invalid_chapter_preflight_lineage")

    draft_versions: dict[str, dict[str, Any]] = {}
    draft_versions_by_candidate_revision: dict[tuple[str, int], dict[str, Any]] = {}
    for row in tables["chapter_draft_candidate_versions"]:
        trace = _chapter_production_trace(row)
        draft_version_model = DraftCandidateVersion.model_validate({**row, "trace": trace})
        if not draft_version_model.content or not compare_digest(
            hashlib.sha256(draft_version_model.content.encode("utf-8")).hexdigest(),
            draft_version_model.content_sha256,
        ):
            raise InvalidProjectArchiveError("invalid_chapter_draft_hash")
        key = (draft_version_model.candidate_id, draft_version_model.revision)
        if key in draft_versions_by_candidate_revision:
            raise InvalidProjectArchiveError("invalid_chapter_draft_revision")
        draft_versions[draft_version_model.id] = row
        draft_versions_by_candidate_revision[key] = row

    draft_candidates: dict[str, dict[str, Any]] = {}
    for row in tables["chapter_draft_candidates"]:
        production_row = productions.get(str(row["production_id"]))
        current_draft_version_row = draft_versions_by_candidate_revision.get(
            (str(row["id"]), int(row["current_revision"]))
        )
        if (
            production_row is None
            or current_draft_version_row is None
            or current_draft_version_row["content_sha256"]
            != row["current_content_sha256"]
        ):
            raise InvalidProjectArchiveError("invalid_chapter_draft_candidate")
        lineage = (
            row["source_outline_candidate_id"],
            row["source_outline_version_id"],
            row["source_outline_revision"],
            row["source_outline_content_sha256"],
        )
        if any(value is not None for value in lineage):
            if not all(value is not None for value in lineage):
                raise InvalidProjectArchiveError("invalid_chapter_outline_lineage")
            outline = outline_candidates.get(str(lineage[0]))
            outline_version = outline_versions.get(str(lineage[1]))
            if (
                outline is None
                or outline["production_id"] != row["production_id"]
                or outline_version is None
                or outline_version[0]["candidate_id"] != lineage[0]
                or outline_version[0]["revision"] != lineage[2]
                or outline_version[0]["content_sha256"] != lineage[3]
            ):
                raise InvalidProjectArchiveError("invalid_chapter_outline_lineage")
        draft_candidates[str(row["id"])] = row

    for row in tables["chapter_draft_candidate_locks"]:
        lock = CandidateLock.model_validate(row)
        candidate = draft_candidates.get(lock.candidate_id)
        created_from = draft_versions.get(lock.created_from_version_id)
        current = (
            draft_versions_by_candidate_revision.get(
                (lock.candidate_id, int(candidate["current_revision"]))
            )
            if candidate is not None
            else None
        )
        if (
            candidate is None
            or created_from is None
            or created_from["candidate_id"] != lock.candidate_id
            or current is None
            or lock.end_char > len(str(current["content"]))
            or str(current["content"])[lock.start_char : lock.end_char] != lock.locked_text
            or not compare_digest(
                hashlib.sha256(lock.locked_text.encode("utf-8")).hexdigest(),
                lock.locked_text_sha256,
            )
        ):
            raise InvalidProjectArchiveError("invalid_chapter_candidate_lock")

    for row in tables["chapter_candidate_reviews"]:
        findings = _parse_json(row["findings_json"])
        trace = _chapter_production_trace(row)
        if not isinstance(findings, list) or trace is None:
            raise InvalidProjectArchiveError("invalid_chapter_candidate_review")
        review = CandidateReview.model_validate({**row, "trace": trace, "findings": findings})
        candidate = draft_candidates.get(review.candidate_id)
        review_version_row = draft_versions.get(review.candidate_version_id)
        if (
            candidate is None
            or review_version_row is None
            or review_version_row["candidate_id"] != review.candidate_id
            or review_version_row["revision"] != review.candidate_revision
            or review_version_row["content_sha256"] != review.candidate_content_sha256
        ):
            raise InvalidProjectArchiveError("invalid_chapter_candidate_review_lineage")

    merge_ordinals: set[tuple[str, int]] = set()
    for row in tables["chapter_candidate_merge_sources"]:
        source = MergeSource.model_validate(
            {
                "candidate_id": row["source_candidate_id"],
                "candidate_version_id": row["source_version_id"],
                "candidate_revision": row["source_revision"],
                "candidate_content_sha256": row["source_content_sha256"],
                "start_char": row["start_char"],
                "end_char": row["end_char"],
                "selected_text_sha256": row["selected_text_sha256"],
            }
        )
        result_candidate = draft_candidates.get(str(row["result_candidate_id"]))
        result_version = draft_versions.get(str(row["result_version_id"]))
        source_candidate = draft_candidates.get(source.candidate_id)
        source_version = draft_versions.get(source.candidate_version_id)
        key = (str(row["result_candidate_id"]), int(row["ordinal"]))
        source_content = str(source_version["content"]) if source_version is not None else ""
        if (
            key in merge_ordinals
            or result_candidate is None
            or result_version is None
            or result_version["candidate_id"] != row["result_candidate_id"]
            or source_candidate is None
            or source_version is None
            or source_version["candidate_id"] != source.candidate_id
            or source_version["revision"] != source.candidate_revision
            or source_version["content_sha256"] != source.candidate_content_sha256
            or source.end_char > len(source_content)
            or not compare_digest(
                hashlib.sha256(
                    source_content[source.start_char : source.end_char].encode("utf-8")
                ).hexdigest(),
                source.selected_text_sha256,
            )
        ):
            raise InvalidProjectArchiveError("invalid_chapter_candidate_merge")
        merge_ordinals.add(key)

    for row in tables["chapter_writing_outcomes"]:
        adoption_detail = _parse_json(row["adoption_detail_json"])
        if not isinstance(adoption_detail, dict):
            raise InvalidProjectArchiveError("invalid_chapter_writing_outcome")
        outcome = WritingOutcome.model_validate({**row, "adoption_detail": adoption_detail})
        outcome_production_row = productions.get(outcome.production_id)
        candidate = draft_candidates.get(outcome.candidate_id)
        outcome_version_row = draft_versions.get(outcome.candidate_version_id)
        if (
            outcome_production_row is None
            or candidate is None
            or candidate["production_id"] != outcome.production_id
            or outcome_version_row is None
            or outcome_version_row["candidate_id"] != outcome.candidate_id
            or outcome_version_row["revision"] != outcome.candidate_revision
            or outcome_version_row["content_sha256"] != outcome.candidate_content_sha256
            or candidate["source_outline_candidate_id"]
            != outcome.source_outline_candidate_id
            or candidate["source_outline_version_id"] != outcome.source_outline_version_id
            or candidate["source_outline_revision"] != outcome.source_outline_revision
            or candidate["source_outline_content_sha256"]
            != outcome.source_outline_content_sha256
        ):
            raise InvalidProjectArchiveError("invalid_chapter_writing_outcome_lineage")
        if outcome.decision.value == "adopted":
            canonical = chapter_versions.get(str(outcome.chapter_version_id))
            if (
                canonical is None
                or canonical["chapter_id"] != outcome_production_row["chapter_id"]
                or canonical["chapter_revision"] != outcome.final_chapter_revision
                or canonical["content_sha256"] != outcome.final_chapter_content_sha256
                or bool(canonical["is_candidate"])
            ):
                raise InvalidProjectArchiveError("invalid_chapter_writing_outcome_version")


def _rebind_context_packet_row(
    row: dict[str, Any],
    *,
    old_id: str,
    old_packet_sha256: object,
    old_source_fingerprint_sha256: object,
    old_dependency_fingerprint_sha256: object,
    id_map: dict[str, str],
) -> None:
    packet = _parse_json(row["packet_json"])
    if not isinstance(packet, dict):
        raise InvalidProjectArchiveError("invalid_context_packet")
    subject = _parse_json(row["subject_json"])
    dependency_value = _parse_json(row["dependency_snapshot_json"])
    blocking_reasons = _parse_json(row["blocking_reasons_json"])
    if (
        not isinstance(subject, dict)
        or not isinstance(dependency_value, dict)
        or not isinstance(blocking_reasons, list)
        or not isinstance(packet.get("items"), list)
        or not isinstance(packet.get("conflict_notes"), list)
    ):
        raise InvalidProjectArchiveError("invalid_context_packet")
    if "restored_dependency_snapshot" not in blocking_reasons:
        blocking_reasons.append("restored_dependency_snapshot")
    dependency = ContextDependencySnapshot.model_validate(dependency_value)
    dependency_fingerprint = _sha256_json(dependency.model_dump(mode="json"))
    rendered_value = _parse_json(str(row["rendered_context"]))
    rendered_context = json.dumps(
        _remap_json(rendered_value, id_map),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    profile = dependency.writing_pattern_profile
    profile_fingerprint = profile.content_sha256 if profile is not None else None
    source_fingerprint = _sha256_json(
        {
            "compiler_version": row["compiler_version"],
            "purpose": row["purpose"],
            "subject": subject,
            "dependencies": dependency.model_dump(mode="json"),
            "items": packet["items"],
        }
    )
    hash_payload = {
        "project_id": row["project_id"],
        "purpose": row["purpose"],
        "subject": subject,
        "task_type": row["task_type"],
        "compiler_version": row["compiler_version"],
        "token_budget": row["token_budget"],
        "used_tokens": row["used_tokens"],
        "source_fingerprint_sha256": source_fingerprint,
        "profile_fingerprint_sha256": profile_fingerprint,
        "dependency_fingerprint_sha256": dependency_fingerprint,
        "rendered_context": rendered_context,
        "items": packet["items"],
        "conflict_notes": packet["conflict_notes"],
        "blocking_reasons": blocking_reasons,
    }
    packet_sha256 = _sha256_json(hash_payload)
    packet_id = str(uuid5(NAMESPACE_URL, f"mozhou:creative-context:{packet_sha256}"))
    packet.update(
        {
            "id": packet_id,
            "project_id": row["project_id"],
            "chapter_id": row["chapter_id"],
            "chapter_revision": row["chapter_revision"],
            "task_type": row["task_type"],
            "purpose": row["purpose"],
            "subject": subject,
            "profile_fingerprint_sha256": profile_fingerprint,
            "dependency_snapshot": dependency.model_dump(mode="json"),
            "dependency_fingerprint_sha256": dependency_fingerprint,
            "blocking_reasons": blocking_reasons,
            "packet_sha256": packet_sha256,
            "source_fingerprint_sha256": source_fingerprint,
            "rendered_context": rendered_context,
        }
    )
    ContextPacket.model_validate(packet)
    row.update(
        {
            "id": packet_id,
            "profile_fingerprint_sha256": profile_fingerprint,
            "dependency_fingerprint_sha256": dependency_fingerprint,
            "blocking_reasons_json": json.dumps(
                blocking_reasons,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "packet_sha256": packet_sha256,
            "source_fingerprint_sha256": source_fingerprint,
            "rendered_context": rendered_context,
            "packet_json": json.dumps(
                packet,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
    )
    id_map[old_id] = packet_id
    for old_value, new_value in (
        (old_packet_sha256, packet_sha256),
        (old_source_fingerprint_sha256, source_fingerprint),
        (old_dependency_fingerprint_sha256, dependency_fingerprint),
    ):
        if isinstance(old_value, str):
            id_map[old_value] = new_value


def _craft_asset_material(row: dict[str, Any]) -> CraftPatternMaterial:
    return CraftPatternMaterial.model_validate(
        {
            "title": row["title"],
            "summary": row["summary"],
            "craft_items": _parse_json(row["craft_items_json"]),
        }
    )


def _craft_asset_content_hash(row: dict[str, Any]) -> str:
    material = _craft_asset_material(row)
    payload = {
        "schema_version": row["schema_version"],
        "asset_type": row["asset_type"],
        "source_work_ids": _parse_json(row["source_work_ids_json"]),
        "source_segment_ids": _parse_json(row["source_segment_ids_json"]),
        "source_asset_version_ids": _parse_json(row["source_asset_version_ids_json"]),
        "title": material.title,
        "summary": material.summary,
        "author_focus": row["author_focus"],
        "craft_items": [item.model_dump(mode="json") for item in material.craft_items],
        "provider": row["provider"],
        "model": row["model"],
        "prompt_version": row["prompt_version"],
        "evidence_validator_version": row["evidence_validator_version"],
        "source_fingerprint_sha256": row["source_fingerprint_sha256"],
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _craft_asset_series_id(row: dict[str, Any]) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "asset_type": row["asset_type"],
                "source_work_ids": _parse_json(row["source_work_ids_json"]),
                "source_segment_ids": _parse_json(row["source_segment_ids_json"]),
                "source_asset_version_ids": _parse_json(row["source_asset_version_ids_json"]),
            }
        )
    ).hexdigest()


def _validate_craft_pattern_rows(tables: dict[str, Any]) -> None:
    required_dimensions = {
        "era",
        "core_desire",
        "conflict_causality",
        "resource_system",
        "key_scene_sequence",
        "ending",
        "hook_mechanics",
        "promise_payoff_cadence",
        "emotional_rhythm",
        "scene_design",
        "pov_narrative_distance",
        "expression_parameters",
        "information_reveal",
        "foreshadowing_cycle",
        "power_progression",
    }
    assets: dict[str, tuple[dict[str, Any], CraftPatternMaterial]] = {}
    for row in tables["craft_pattern_assets"]:
        if row["schema_version"] != 2:
            raise InvalidProjectArchiveError("invalid_craft_schema_version")
        asset_type = CraftPatternAssetType(str(row["asset_type"]))
        work_ids = _parse_json(row["source_work_ids_json"])
        segment_ids = _parse_json(row["source_segment_ids_json"])
        parent_ids = _parse_json(row["source_asset_version_ids_json"])
        if not all(
            isinstance(items, list)
            and all(isinstance(item, str) for item in items)
            and len(items) == len(set(items))
            for items in (work_ids, segment_ids, parent_ids)
        ):
            raise InvalidProjectArchiveError("invalid_craft_sources")
        if len(work_ids) > 30 or len(segment_ids) > 64 or len(parent_ids) > 64:
            raise InvalidProjectArchiveError("invalid_craft_sources")
        if any(
            _valid_uuid(item) != item
            for items in (work_ids, segment_ids, parent_ids)
            for item in items
        ):
            raise InvalidProjectArchiveError("invalid_craft_sources")
        if not work_ids or not segment_ids:
            raise InvalidProjectArchiveError("invalid_craft_sources")
        material = _craft_asset_material(row)
        dimensions = {item.dimension.value for item in material.craft_items}
        if not required_dimensions <= dimensions:
            raise InvalidProjectArchiveError("invalid_craft_dimensions")
        evidence = [entry for item in material.craft_items for entry in item.evidence]
        if any(
            entry.work_id not in work_ids or entry.segment_id not in segment_ids
            for entry in evidence
        ):
            raise InvalidProjectArchiveError("invalid_craft_evidence_source")
        if asset_type == CraftPatternAssetType.STAGE:
            if len(work_ids) != 1 or len(segment_ids) != 1 or parent_ids:
                raise InvalidProjectArchiveError("invalid_craft_stage")
        elif asset_type == CraftPatternAssetType.BOOK_EVOLUTION:
            if len(work_ids) != 1 or not parent_ids:
                raise InvalidProjectArchiveError("invalid_craft_book")
            if {entry.segment_id for entry in evidence} != set(segment_ids):
                raise InvalidProjectArchiveError("invalid_craft_book_evidence")
        else:
            if len(work_ids) < 2 or not parent_ids:
                raise InvalidProjectArchiveError("invalid_craft_fusion")
            if {entry.work_id for entry in evidence} != set(work_ids):
                raise InvalidProjectArchiveError("invalid_craft_fusion_evidence")
        if not compare_digest(_craft_asset_content_hash(row), row["content_sha256"]):
            raise InvalidProjectArchiveError("invalid_craft_content_hash")
        assets[str(row["id"])] = (row, material)

    for row, material in assets.values():
        asset_type = CraftPatternAssetType(str(row["asset_type"]))
        parent_ids = _parse_json(row["source_asset_version_ids_json"])
        if not parent_ids:
            continue
        if any(parent_id not in assets for parent_id in parent_ids):
            raise InvalidProjectArchiveError("external_craft_parent")
        parent_values = [assets[parent_id] for parent_id in parent_ids]
        if asset_type == CraftPatternAssetType.BOOK_EVOLUTION and any(
            CraftPatternAssetType(str(parent[0]["asset_type"])) != CraftPatternAssetType.STAGE
            for parent in parent_values
        ):
            raise InvalidProjectArchiveError("invalid_craft_book_parent")
        if asset_type == CraftPatternAssetType.FUSION_MATERIAL and any(
            CraftPatternAssetType(str(parent[0]["asset_type"]))
            == CraftPatternAssetType.FUSION_MATERIAL
            for parent in parent_values
        ):
            raise InvalidProjectArchiveError("invalid_craft_fusion_parent")
        allowed = {
            evidence.id: evidence
            for _parent_row, parent_material in parent_values
            for item in parent_material.craft_items
            for evidence in item.evidence
        }
        for item in material.craft_items:
            for entry in item.evidence:
                if allowed.get(entry.id) != entry:
                    raise InvalidProjectArchiveError("invalid_craft_evidence_reference")
        if asset_type == CraftPatternAssetType.FUSION_MATERIAL:
            cited_ids = {entry.id for item in material.craft_items for entry in item.evidence}
            for _parent_row, parent_material in parent_values:
                parent_ids = {
                    entry.id for item in parent_material.craft_items for entry in item.evidence
                }
                if cited_ids.isdisjoint(parent_ids):
                    raise InvalidProjectArchiveError("invalid_craft_fusion_parent_evidence")

    for row in tables["project_craft_pattern_assets"]:
        if (
            row["lifecycle_state"] not in {"active", "archived"}
            or not isinstance(row["lifecycle_revision"], int)
            or row["lifecycle_revision"] < 0
        ):
            raise InvalidProjectArchiveError("invalid_craft_lifecycle")
    ordinals_by_job: set[tuple[str, int]] = set()
    for row in tables["craft_pattern_job_outputs"]:
        marker = (str(row["job_id"]), int(row["ordinal"]))
        if marker in ordinals_by_job or marker[1] < 0:
            raise InvalidProjectArchiveError("invalid_craft_job_output")
        ordinals_by_job.add(marker)


def _validate_pattern_adaptation_rows(tables: dict[str, Any]) -> None:
    proposals = {str(row["id"]): row for row in tables["writing_pattern_adaptation_proposals"]}
    versions: dict[str, dict[str, Any]] = {}
    versions_by_candidate: dict[str, dict[int, dict[str, Any]]] = {}
    for row in tables["writing_pattern_adaptation_candidate_versions"]:
        blueprint = BookBlueprintContent.model_validate(_parse_json(row["blueprint_json"]))
        scenes = _parse_json(row["key_scene_sequence_json"])
        notes = _parse_json(row["transformation_notes_json"])
        if not isinstance(scenes, list) or not all(isinstance(item, str) for item in scenes):
            raise InvalidProjectArchiveError("invalid_pattern_candidate_version")
        if not isinstance(notes, list) or not all(isinstance(item, str) for item in notes):
            raise InvalidProjectArchiveError("invalid_pattern_candidate_version")
        if not compare_digest(
            candidate_content_sha256(blueprint, scenes, notes),
            str(row["content_sha256"]),
        ):
            raise InvalidProjectArchiveError("invalid_pattern_candidate_hash")
        revision = int(row["revision"])
        by_revision = versions_by_candidate.setdefault(str(row["candidate_id"]), {})
        if revision in by_revision:
            raise InvalidProjectArchiveError("invalid_pattern_candidate_version")
        by_revision[revision] = row
        versions[str(row["id"])] = row

    candidates: dict[str, dict[str, Any]] = {}
    for row in tables["writing_pattern_adaptation_candidates"]:
        proposal = proposals.get(str(row["proposal_id"]))
        current = versions_by_candidate.get(str(row["id"]), {}).get(int(row["current_revision"]))
        if (
            proposal is None
            or current is None
            or not compare_digest(
                str(row["current_content_sha256"]), str(current["content_sha256"])
            )
        ):
            raise InvalidProjectArchiveError("invalid_pattern_adaptation_candidate")
        candidates[str(row["id"])] = row
    if set(versions_by_candidate) - set(candidates):
        raise InvalidProjectArchiveError("orphan_pattern_candidate_version")

    adoptions: dict[str, dict[str, Any]] = {}
    for row in tables["writing_pattern_adoptions"]:
        proposal = proposals.get(str(row["proposal_id"]))
        candidate = candidates.get(str(row["candidate_id"]))
        version = versions.get(str(row["candidate_version_id"]))
        if (
            proposal is None
            or candidate is None
            or version is None
            or candidate["proposal_id"] != proposal["id"]
            or version["candidate_id"] != candidate["id"]
            or proposal["project_id"] != row["project_id"]
            or proposal["profile_fingerprint_sha256"] != row["profile_fingerprint_sha256"]
            or proposal["recipe_content_sha256"] != row["recipe_content_sha256"]
        ):
            raise InvalidProjectArchiveError("invalid_pattern_adoption")
        adopted_content = _parse_json(version["blueprint_json"])
        if not isinstance(adopted_content, dict) or not compare_digest(
            hashlib.sha256(canonical_json(adopted_content)).hexdigest(),
            str(row["blueprint_content_sha256"]),
        ):
            raise InvalidProjectArchiveError("invalid_pattern_adoption_hash")
        adoptions[str(row["id"])] = row

    reports: dict[str, dict[str, Any]] = {}
    for row in tables["writing_pattern_originality_reports"]:
        adoption = adoptions.get(str(row["adoption_id"]))
        version = versions.get(str(row["candidate_version_id"]))
        if (
            adoption is None
            or version is None
            or adoption["project_id"] != row["project_id"]
            or adoption["candidate_version_id"] != version["id"]
            or adoption["profile_fingerprint_sha256"] != row["profile_fingerprint_sha256"]
            or adoption["recipe_content_sha256"] != row["recipe_content_sha256"]
            or version["content_sha256"] != row["candidate_content_sha256"]
        ):
            raise InvalidProjectArchiveError("invalid_pattern_originality_report")
        reports[str(row["id"])] = row
    for row in tables["writing_pattern_originality_findings"]:
        if str(row["report_id"]) not in reports:
            raise InvalidProjectArchiveError("orphan_pattern_originality_finding")


def _validate_business_rows(
    tables: dict[str, Any],
    ids_by_table: dict[str, set[str]],
) -> None:
    try:
        if not tables["chapters"]:
            raise InvalidProjectArchiveError("project_without_chapters")
        for row in tables["projects"]:
            Project.model_validate(row)
        for row in tables["book_blueprints"]:
            BookBlueprint.model_validate(
                {
                    **row,
                    "content": _parse_json(row["content_json"]),
                    "locks": _parse_json(row["locks_json"]),
                    "field_versions": _parse_json(row["field_versions_json"]),
                    "stale_fields": _parse_json(row["stale_fields_json"]),
                    "plan_stale": bool(row["plan_stale"]),
                }
            )
        if len(tables["topic_decisions"]) > 1:
            raise InvalidProjectArchiveError("invalid_topic_decision_count")
        topic_decisions_by_id: dict[str, TopicDecision] = {}
        for row in tables["topic_decisions"]:
            if row["onboarding_required"] not in {0, 1}:
                raise InvalidProjectArchiveError("invalid_topic_onboarding_state")
            confirmed_revision = row["confirmed_revision"]
            status = (
                TopicDecisionStatus.DRAFT
                if confirmed_revision is None
                else TopicDecisionStatus.CONFIRMED
                if confirmed_revision == row["revision"]
                else TopicDecisionStatus.PENDING_RECONFIRMATION
            )
            topic = TopicDecision.model_validate(
                {
                    **row,
                    "content": _parse_json(row["content_json"]),
                    "status": status,
                    "locks": _parse_json(row["locks_json"]),
                    "field_versions": _parse_json(row["field_versions_json"]),
                    "rejection_reasons": _parse_json(row["rejection_reasons_json"]),
                    "source_candidate_ids": _parse_json(row["source_candidate_ids_json"]),
                    "plan_stale": bool(row["plan_stale"]),
                }
            )
            topic_decisions_by_id[topic.id] = topic

        topic_versions_by_revision: dict[int, TopicDecisionVersion] = {}
        for row in tables["topic_decision_versions"]:
            content = _parse_json(row["content_json"])
            topic_version = TopicDecisionVersion.model_validate(
                {
                    **row,
                    "content": content,
                    "locks": _parse_json(row["locks_json"]),
                    "field_versions": _parse_json(row["field_versions_json"]),
                    "rejection_reasons": _parse_json(row["rejection_reasons_json"]),
                    "source_candidate_ids": _parse_json(row["source_candidate_ids_json"]),
                }
            )
            if (
                set(topic_version.locks) != set(TopicDecisionField)
                or set(topic_version.field_versions) != set(TopicDecisionField)
                or any(value < 1 for value in topic_version.field_versions.values())
            ):
                raise InvalidProjectArchiveError("invalid_topic_version_field_state")
            decision = topic_decisions_by_id.get(topic_version.topic_decision_id)
            if (
                decision is None
                or decision.project_id != topic_version.project_id
                or topic_version.revision > decision.revision
                or topic_version.revision in topic_versions_by_revision
            ):
                raise InvalidProjectArchiveError("invalid_topic_version")
            expected_hash = hashlib.sha256(canonical_json(content)).hexdigest()
            if not compare_digest(expected_hash, topic_version.content_sha256):
                raise InvalidProjectArchiveError("invalid_topic_version_hash")
            topic_versions_by_revision[topic_version.revision] = topic_version
        if topic_decisions_by_id:
            topic = next(iter(topic_decisions_by_id.values()))
            if (
                topic.confirmed_revision is not None
                and topic.confirmed_revision not in topic_versions_by_revision
            ):
                raise InvalidProjectArchiveError("missing_confirmed_topic_version")

        candidates_by_set: dict[str, list[TopicDecisionCandidate]] = {}
        candidate_projects: dict[str, str] = {}
        for row in tables["topic_decision_candidates"]:
            candidate = TopicDecisionCandidate.model_validate(
                {
                    **row,
                    "content": _parse_json(row["content_json"]),
                    "changed_fields": _parse_json(row["changed_fields_json"]),
                    "risks": _parse_json(row["risks_json"]),
                }
            )
            candidates_by_set.setdefault(row["candidate_set_id"], []).append(candidate)
            candidate_projects[candidate.id] = row["project_id"]
        seen_candidate_sets: set[str] = set()
        for row in tables["topic_decision_candidate_sets"]:
            decision = topic_decisions_by_id.get(row["topic_decision_id"])
            if decision is None or decision.project_id != row["project_id"]:
                raise InvalidProjectArchiveError("invalid_topic_candidate_set")
            candidates = sorted(
                candidates_by_set.get(row["id"], []),
                key=lambda candidate: candidate.ordinal,
            )
            if any(
                candidate_projects[candidate.id] != row["project_id"] for candidate in candidates
            ):
                raise InvalidProjectArchiveError("invalid_topic_candidate")
            TopicDecisionCandidateSet.model_validate(
                {
                    "job_id": row["source_job_id"],
                    "project_id": row["project_id"],
                    "based_on_revision": row["based_on_revision"],
                    "target_field": row["target_field"],
                    "candidates": candidates,
                }
            )
            seen_candidate_sets.add(row["id"])
        if set(candidates_by_set) != seen_candidate_sets:
            raise InvalidProjectArchiveError("orphan_topic_candidate")

        archived_candidate_ids = ids_by_table["topic_decision_candidates"]
        for topic in topic_decisions_by_id.values():
            if not set(topic.source_candidate_ids) <= archived_candidate_ids:
                raise InvalidProjectArchiveError("external_topic_candidate")
        for confirmed_topic_version in topic_versions_by_revision.values():
            if not set(confirmed_topic_version.source_candidate_ids) <= archived_candidate_ids:
                raise InvalidProjectArchiveError("external_topic_candidate")
        for row in tables["volume_plans"]:
            volume_content = VolumePlanContent.model_validate(_parse_json(row["content_json"]))
            VolumePlan.model_validate(
                {
                    **volume_content.model_dump(mode="json"),
                    "id": row["id"],
                    "project_id": row["project_id"],
                    "revision": row["revision"],
                    "locked": bool(row["locked"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        for row in tables["rolling_chapter_plans"]:
            rolling_content = RollingChapterPlanContent.model_validate(
                _parse_json(row["content_json"])
            )
            RollingChapterPlan.model_validate(
                {
                    **rolling_content.model_dump(mode="json"),
                    "id": row["id"],
                    "project_id": row["project_id"],
                    "volume_plan_id": row["volume_plan_id"],
                    "revision": row["revision"],
                    "locked": bool(row["locked"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        for row in tables["manuscript_volumes"]:
            ManuscriptVolume.model_validate(row)
        for row in tables["chapters"]:
            Chapter.model_validate(row)
        for row in tables["manuscript_scenes"]:
            ManuscriptScene.model_validate(row)
        directory_target_tables = {
            "volume": "manuscript_volumes",
            "chapter": "chapters",
            "scene": "manuscript_scenes",
        }
        for row in tables["directory_events"]:
            target_table = directory_target_tables.get(row["node_kind"])
            if (
                target_table is None
                or row["node_id"] not in ids_by_table[target_table]
                or not isinstance(_parse_json(row["payload_json"]), dict)
            ):
                raise InvalidProjectArchiveError("invalid_directory_event")
        for row in tables["serial_daily_goals"]:
            if (
                not isinstance(row["target_characters"], int)
                or not 0 <= row["target_characters"] <= 100_000
                or not isinstance(row["revision"], int)
                or row["revision"] < 0
            ):
                raise InvalidProjectArchiveError("invalid_serial_goal")
            datetime.fromisoformat(row["goal_date"])
        for row in tables["chapter_versions"]:
            chapter_version = ChapterVersion.model_validate(
                {**row, "is_candidate": bool(row["is_candidate"])}
            )
            if not compare_digest(
                hashlib.sha256(chapter_version.content.encode("utf-8")).hexdigest(),
                chapter_version.content_sha256,
            ):
                raise InvalidProjectArchiveError("invalid_chapter_version_hash")
        for row in tables["context_directives"]:
            directive = ContextDirective.model_validate(row)
            target_table = {
                "chapter": "chapters",
                "fact": "story_facts",
                "entity": "story_entities",
                "thread": "story_threads",
                "timeline": "timeline_events",
                "future_knowledge": "future_knowledge",
                "source_card": "source_cards",
                "blueprint": "reference_pattern_applications",
            }.get(directive.source_kind)
            if target_table is None or directive.source_id not in ids_by_table[target_table]:
                raise InvalidProjectArchiveError("external_context_directive_source")
        for row in tables["generation_runs"]:
            GenerationRun.model_validate(row)
        for row in tables["timeline_events"]:
            TimelineEvent.model_validate(row)
        for row in tables["story_facts"]:
            StoryFact.model_validate(row)
        for row in tables["future_knowledge"]:
            FutureKnowledge.model_validate(row)
        for row in tables["story_entities"]:
            StoryEntity.model_validate(row)
        for row in tables["story_threads"]:
            StoryThread.model_validate(row)
        for row in tables["source_cards"]:
            SourceCard.model_validate(row)
        for row in tables["source_documents"]:
            spans = _parse_json(row["source_spans_json"])
            content = row["content"]
            if not isinstance(spans, list) or not isinstance(content, str) or not content:
                raise InvalidProjectArchiveError("invalid_source_document")
            SourceDocument.model_validate(
                {
                    **row,
                    "source_spans": spans,
                    "total_characters": len(content),
                }
            )

        changes_by_set: dict[str, list[dict[str, Any]]] = {}
        for row in tables["fact_changes"]:
            FactChange.model_validate(row)
            changes_by_set.setdefault(row["change_set_id"], []).append(row)
        for row in tables["fact_change_sets"]:
            FactChangeSet.model_validate({**row, "changes": changes_by_set.get(row["id"], [])})

        segments_by_work: dict[str, list[dict[str, Any]]] = {}
        for row in tables["reference_segments"]:
            if not isinstance(row["content"], str):
                raise InvalidProjectArchiveError("invalid_reference_content")
            if (
                row["character_count"] != len(row["content"])
                or row["end_char"] - row["start_char"] != row["character_count"]
            ):
                raise InvalidProjectArchiveError("invalid_reference_segment_range")
            ReferenceSegment.model_validate(row)
            segments_by_work.setdefault(row["reference_work_id"], []).append(row)
        for row in tables["reference_works"]:
            spans = _parse_json(row["source_spans_json"])
            if not isinstance(spans, list):
                raise InvalidProjectArchiveError("invalid_reference_spans")
            ReferenceWork.model_validate(
                {
                    **row,
                    "source_spans": spans,
                    "segments": segments_by_work.get(row["id"], []),
                }
            )

        segment_ids = ids_by_table["reference_segments"]
        for row in tables["reference_pattern_cards"]:
            selected_ids = _parse_json(row["selected_segment_ids_json"])
            proposal = _parse_json(row["proposal_json"])
            if not isinstance(selected_ids, list) or not isinstance(proposal, dict):
                raise InvalidProjectArchiveError("invalid_pattern_card_json")
            card = ReferencePatternCard.model_validate(
                {**row, **proposal, "selected_segment_ids": selected_ids}
            )
            referenced_ids = set(card.selected_segment_ids)
            for dimension in (
                card.era,
                card.core_desire,
                card.conflict_causality,
                card.resource_system,
                card.key_scene_sequence,
                card.ending,
            ):
                referenced_ids.update(dimension.source_segment_ids)
            if segment_ids and not referenced_ids <= segment_ids:
                raise InvalidProjectArchiveError("external_pattern_segment")
        for row in tables["reference_pattern_applications"]:
            selected_dimensions = _parse_json(row["selected_dimensions_json"])
            dimensions = _parse_json(row["dimensions_json"])
            blueprint = _parse_json(row["blueprint_json"])
            ReferencePatternApplication.model_validate(
                {
                    **row,
                    "selected_dimensions": selected_dimensions,
                    "dimensions": dimensions,
                    "blueprint": blueprint,
                }
            )
        for row in tables["reference_blueprint_versions"]:
            blueprint = _parse_json(row["blueprint_json"])
            changed_dimensions = _parse_json(row["changed_dimensions_json"])
            state = ReferenceBlueprintState.model_validate(blueprint)
            if (
                not isinstance(changed_dimensions, list)
                or not set(changed_dimensions)
                <= {dimension.value for dimension in state.dimensions}
                or row["relationship_changed"] not in {0, 1}
            ):
                raise InvalidProjectArchiveError("invalid_blueprint_version")
        for row in tables["originality_reports"]:
            checked_dimensions = _parse_json(row["checked_dimensions_json"])
            evidence = _parse_json(row["evidence_json"])
            source_segment_ids = _parse_json(row["source_segment_ids_json"])
            OriginalityReport.model_validate(
                {
                    **row,
                    "checked_dimensions": checked_dimensions,
                    "evidence": evidence,
                    "source_segment_ids": source_segment_ids,
                    "legal_notice": LEGAL_NOTICE,
                }
            )
        findings_by_check: dict[str, list[dict[str, Any]]] = {}
        for row in tables["scene_originality_findings"]:
            finding = SceneOriginalityFinding.model_validate(
                {
                    **row,
                    "source_segment_ids": _parse_json(row["source_segment_ids_json"]),
                }
            )
            findings_by_check.setdefault(row["check_id"], []).append(
                finding.model_dump(mode="json")
            )
        for row in tables["scene_originality_checks"]:
            SceneOriginalityCheck.model_validate(
                {
                    **row,
                    "candidate_graph": _parse_json(row["candidate_graph_json"]),
                    "source_segment_ids": _parse_json(row["source_segment_ids_json"]),
                    "findings": findings_by_check.get(row["id"], []),
                    "status": (
                        "blocked"
                        if row["risk_level"] == "high"
                        else "review_required"
                        if row["risk_level"] == "medium" and row["acknowledged_at"] is None
                        else "passed"
                    ),
                    "legal_notice": "场景语义与情节图检测用于创作风控，不是抄袭认定或法律结论。",
                }
            )

        for row in tables["chapter_events"]:
            ChapterStatus(row["from_status"])
            ChapterStatus(row["to_status"])
        for row in tables["run_events"]:
            GenerationState(row["state"])
            if not isinstance(row["sequence"], int) or row["sequence"] < 1:
                raise InvalidProjectArchiveError("invalid_run_event_sequence")

        for row in tables["jobs"]:
            Job.model_validate(row)
            if not isinstance(_parse_json(row["input_json"]), dict):
                raise InvalidProjectArchiveError("invalid_job_input")
        for row in tables["job_chunks"]:
            JobChunk.model_validate(row)
            if not isinstance(_parse_json(row["input_json"]), dict):
                raise InvalidProjectArchiveError("invalid_job_chunk_input")
        for row in tables["job_attempts"]:
            JobAttempt.model_validate(row)
        for row in tables["job_artifacts"]:
            metadata = _parse_json(row["metadata_json"])
            if not isinstance(metadata, dict):
                raise InvalidProjectArchiveError("invalid_job_artifact_metadata")
            JobArtifact.model_validate({**row, "metadata": metadata})
            payload = row["payload"]
            if not isinstance(payload, str) or not compare_digest(
                hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                row["payload_sha256"],
            ):
                raise InvalidProjectArchiveError("invalid_job_artifact_hash")
        for row in tables["job_events"]:
            detail = _parse_json(row["detail_json"])
            if not isinstance(detail, dict):
                raise InvalidProjectArchiveError("invalid_job_event_detail")
            JobEvent.model_validate({**row, "detail": detail})

        _validate_craft_pattern_rows(tables)
        validate_writing_pattern_tables(tables)
        _validate_pattern_adaptation_rows(tables)
        _validate_m32_archive_rows(tables)
        _validate_m33_archive_rows(tables)

        for row in tables["comic_projects"]:
            source_ids = _parse_json(row["source_chapter_ids_json"])
            snapshot = _parse_json(row["source_snapshot_json"])
            if not isinstance(source_ids, list) or not isinstance(snapshot, list):
                raise InvalidProjectArchiveError("invalid_comic_source_snapshot")
            ComicProject.model_validate({**row, "source_chapter_ids": source_ids})
        for row in tables["comic_episodes"]:
            source_ids = _parse_json(row["source_chapter_ids_json"])
            if not isinstance(source_ids, list):
                raise InvalidProjectArchiveError("invalid_comic_episode_sources")
            ComicEpisode.model_validate({**row, "source_chapter_ids": source_ids})
        for row in tables["comic_versions"]:
            content = _parse_json(row["content_json"])
            if not isinstance(content, dict):
                raise InvalidProjectArchiveError("invalid_comic_version_content")
            ComicVersion.model_validate({**row, "content": content})
        for row in tables["comic_scenes"]:
            content = _parse_json(row["content_json"])
            source_ids = _parse_json(row["source_chapter_ids_json"])
            if not isinstance(content, dict) or not isinstance(source_ids, list):
                raise InvalidProjectArchiveError("invalid_comic_scene_content")
            ComicScene.model_validate({**row, "content": content, "source_chapter_ids": source_ids})

        for row in tables["review_findings"]:
            ReviewFinding.model_validate({**row, "evidence": _parse_json(row["evidence_json"])})
        text_changes_by_set: dict[str, list[dict[str, Any]]] = {}
        for row in tables["text_changes"]:
            TextChange.model_validate(
                {
                    **row,
                    "selected": (bool(row["selected"]) if row["selected"] is not None else None),
                }
            )
            text_changes_by_set.setdefault(row["change_set_id"], []).append(row)
        for row in tables["text_change_sets"]:
            TextChangeSet.model_validate({**row, "changes": text_changes_by_set.get(row["id"], [])})

        nullable_timestamps = {
            "lease_expires_at",
            "heartbeat_at",
            "started_at",
            "completed_at",
            "viewed_at",
            "acknowledged_at",
            "deleted_at",
            "undone_at",
            "reviewed_at",
            "decided_at",
            "adopted_at",
        }
        for table in ARCHIVE_TABLES:
            for row in tables[table.name]:
                for column in table.columns:
                    if column.endswith("_at"):
                        timestamp = row[column]
                        if timestamp is None and column in nullable_timestamps:
                            continue
                        if not isinstance(timestamp, str):
                            raise InvalidProjectArchiveError("invalid_timestamp")
                        datetime.fromisoformat(timestamp)
    except InvalidProjectArchiveError:
        raise
    except (TypeError, ValueError, ValidationError) as error:
        raise InvalidProjectArchiveError("invalid_business_values") from error


def _rebind_pattern_adaptation_rows(tables: dict[str, list[dict[str, Any]]]) -> None:
    """Rebind immutable lineage and invalidate pre-import execution decisions."""
    profiles = {str(row["id"]): row for row in tables["writing_pattern_profile_versions"]}
    recipes = {str(row["id"]): row for row in tables["writing_pattern_recipe_versions"]}
    topics = {str(row["id"]): row for row in tables["topic_decision_versions"]}
    jobs = {str(row["id"]): row for row in tables["jobs"]}
    blueprints = {str(row["id"]): row for row in tables["book_blueprints"]}
    proposals: dict[str, dict[str, Any]] = {}
    for row in tables["writing_pattern_adaptation_proposals"]:
        profile = profiles.get(str(row["profile_version_id"]))
        recipe = recipes.get(str(row["recipe_version_id"]))
        topic = topics.get(str(row["topic_decision_version_id"]))
        job = jobs.get(str(row["job_id"]))
        blueprint = (
            blueprints.get(str(row["base_blueprint_id"]))
            if row["base_blueprint_id"] is not None
            else None
        )
        if (
            profile is None
            or recipe is None
            or topic is None
            or job is None
            or profile["recipe_version_id"] != recipe["id"]
            or profile["project_id"] != row["project_id"]
            or topic["project_id"] != row["project_id"]
            or job["project_id"] != row["project_id"]
            or (blueprint is not None and blueprint["project_id"] != row["project_id"])
        ):
            raise InvalidProjectArchiveError("invalid_pattern_adaptation_proposal")
        row["profile_fingerprint_sha256"] = profile["profile_fingerprint_sha256"]
        row["recipe_content_sha256"] = recipe["content_sha256"]
        row["result_state"] = "stale"
        row["stale_reason"] = "restored_requires_resubmission"
        proposals[str(row["id"])] = row

    versions: dict[str, dict[str, Any]] = {}
    versions_by_candidate: dict[str, dict[int, dict[str, Any]]] = {}
    for row in tables["writing_pattern_adaptation_candidate_versions"]:
        try:
            candidate_blueprint = BookBlueprintContent.model_validate(
                _parse_json(row["blueprint_json"])
            )
            scenes = _parse_json(row["key_scene_sequence_json"])
            notes = _parse_json(row["transformation_notes_json"])
            if not isinstance(scenes, list) or not all(isinstance(item, str) for item in scenes):
                raise InvalidProjectArchiveError("invalid_pattern_candidate_version")
            if not isinstance(notes, list) or not all(isinstance(item, str) for item in notes):
                raise InvalidProjectArchiveError("invalid_pattern_candidate_version")
            row["content_sha256"] = candidate_content_sha256(
                candidate_blueprint, scenes, notes
            )
            revision = int(row["revision"])
        except (TypeError, ValueError, ValidationError) as error:
            raise InvalidProjectArchiveError("invalid_pattern_candidate_version") from error
        versions[str(row["id"])] = row
        by_revision = versions_by_candidate.setdefault(str(row["candidate_id"]), {})
        if revision in by_revision:
            raise InvalidProjectArchiveError("invalid_pattern_candidate_version")
        by_revision[revision] = row

    candidates: dict[str, dict[str, Any]] = {}
    for row in tables["writing_pattern_adaptation_candidates"]:
        proposal = proposals.get(str(row["proposal_id"]))
        current = versions_by_candidate.get(str(row["id"]), {}).get(int(row["current_revision"]))
        if proposal is None or current is None:
            raise InvalidProjectArchiveError("invalid_pattern_adaptation_candidate")
        row["current_content_sha256"] = current["content_sha256"]
        candidates[str(row["id"])] = row
    if set(versions_by_candidate) - set(candidates):
        raise InvalidProjectArchiveError("orphan_pattern_candidate_version")

    adoptions: dict[str, dict[str, Any]] = {}
    for row in tables["writing_pattern_adoptions"]:
        proposal = proposals.get(str(row["proposal_id"]))
        candidate = candidates.get(str(row["candidate_id"]))
        version = versions.get(str(row["candidate_version_id"]))
        blueprint = blueprints.get(str(row["blueprint_id"]))
        if (
            proposal is None
            or candidate is None
            or version is None
            or blueprint is None
            or candidate["proposal_id"] != proposal["id"]
            or version["candidate_id"] != candidate["id"]
            or proposal["project_id"] != row["project_id"]
            or blueprint["project_id"] != row["project_id"]
        ):
            raise InvalidProjectArchiveError("invalid_pattern_adoption")
        adopted_content = _parse_json(version["blueprint_json"])
        if not isinstance(adopted_content, dict) or not compare_digest(
            hashlib.sha256(canonical_json(adopted_content)).hexdigest(),
            str(row["blueprint_content_sha256"]),
        ):
            raise InvalidProjectArchiveError("invalid_pattern_adoption")
        row["profile_fingerprint_sha256"] = proposal["profile_fingerprint_sha256"]
        row["recipe_content_sha256"] = proposal["recipe_content_sha256"]
        adoptions[str(row["id"])] = row

    reports: dict[str, dict[str, Any]] = {}
    for row in tables["writing_pattern_originality_reports"]:
        adoption = adoptions.get(str(row["adoption_id"]))
        version = versions.get(str(row["candidate_version_id"]))
        blueprint = blueprints.get(str(row["blueprint_id"]))
        if (
            adoption is None
            or version is None
            or blueprint is None
            or adoption["project_id"] != row["project_id"]
            or adoption["candidate_version_id"] != version["id"]
            or adoption["blueprint_id"] != blueprint["id"]
        ):
            raise InvalidProjectArchiveError("invalid_pattern_originality_report")
        row["profile_fingerprint_sha256"] = adoption["profile_fingerprint_sha256"]
        row["recipe_content_sha256"] = adoption["recipe_content_sha256"]
        row["candidate_content_sha256"] = version["content_sha256"]
        reports[str(row["id"])] = row
    for row in tables["writing_pattern_originality_findings"]:
        if str(row["report_id"]) not in reports:
            raise InvalidProjectArchiveError("orphan_pattern_originality_finding")


def _insert_legacy_topic_decision(
    connection: sqlite3.Connection,
    project: dict[str, Any],
    blueprints: list[dict[str, Any]],
) -> None:
    blueprint = blueprints[0] if blueprints else None
    blueprint_content = _parse_json(blueprint["content_json"]) if blueprint is not None else {}
    if not isinstance(blueprint_content, dict):
        raise InvalidProjectArchiveError("invalid_legacy_topic_blueprint")

    def blueprint_text(field: str) -> str:
        value = blueprint_content.get(field, "")
        if not isinstance(value, str):
            raise InvalidProjectArchiveError("invalid_legacy_topic_blueprint")
        return value

    content = TopicDecisionContent(
        target_platform="",
        target_audience=blueprint_text("target_audience"),
        subgenre=topic_subgenre_label(Genre(str(project["genre"]))),
        premise=(str(blueprint["idea"]) if blueprint is not None else str(project["title"])),
        core_desire=blueprint_text("core_desire"),
        long_term_promise=blueprint_text("long_term_promise"),
        first_three_chapter_promise="",
        constraints=[],
        forbidden_elements=[],
        reference_purpose="",
        reality_anchor=f"{project['rebirth_year']} · {project['rebirth_location']}",
        first_ten_chapter_goal="",
    )
    timestamp = str(project["updated_at"])
    connection.execute(
        """
        INSERT INTO topic_decisions (
            id, project_id, content_json, locks_json, field_versions_json,
            rejection_reasons_json, source_template_id, source_job_id,
            source_candidate_ids_json, revision, confirmed_revision,
            plan_stale, onboarding_required, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, '{}', NULL, NULL, '[]', 0, NULL, 0, 0, ?, ?)
        """,
        (
            str(uuid4()),
            project["id"],
            content.model_dump_json(),
            json.dumps(
                {field.value: False for field in TopicDecisionField},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            json.dumps(
                {field.value: 1 for field in TopicDecisionField},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            timestamp,
            timestamp,
        ),
    )


class ProjectArchiveService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def export_project(
        self,
        project_id: str,
        *,
        include_reference_assets: bool = False,
    ) -> dict[str, Any]:
        with self.database.connect() as connection:
            project = connection.execute(
                "SELECT id, title FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if project is None:
                raise NotFoundError(project_id)
            tables: dict[str, list[dict[str, Any]]] = {}
            for table in ARCHIVE_TABLES:
                if (
                    table.name
                    in {
                        "reference_works",
                        "reference_segments",
                        "source_documents",
                        "research_sessions",
                        "research_sources",
                        "research_findings",
                    }
                    and not include_reference_assets
                ):
                    tables[table.name] = []
                    continue
                columns = ", ".join(table.columns)
                parameters = (
                    (project_id, project_id) if table.name == "source_documents" else (project_id,)
                )
                rows = connection.execute(
                    f"SELECT {columns} FROM {table.name} WHERE {table.scope} ORDER BY rowid",
                    parameters,
                ).fetchall()
                table_rows = [dict(row) for row in rows]
                if table.name == "reference_works":
                    for row in table_rows:
                        row["duplicate_of_id"] = None
                if table.name == "source_documents":
                    for row in table_rows:
                        row["duplicate_of_id"] = None
                if table.name == "source_cards" and not include_reference_assets:
                    for row in table_rows:
                        row["source_document_id"] = None
                if table.name == "craft_pattern_assets":
                    for row in table_rows:
                        source_job_id = row["source_job_id"]
                        if (
                            source_job_id is not None
                            and connection.execute(
                                "SELECT 1 FROM jobs WHERE id = ? AND project_id = ?",
                                (source_job_id, project_id),
                            ).fetchone()
                            is None
                        ):
                            # The immutable asset is global; a reused asset may
                            # have been produced by a different project's job.
                            row["source_job_id"] = None
                if table.name == "writing_pattern_recipes":
                    for row in table_rows:
                        created_from_project_id = row["created_from_project_id"]
                        if created_from_project_id != project_id:
                            # A globally reused recipe can outlive its origin project.
                            # The exported immutable versions remain complete without
                            # claiming that the restored project authored the series.
                            row["created_from_project_id"] = None
                tables[table.name] = table_rows

        payload: dict[str, Any] = {
            "format": ARCHIVE_FORMAT,
            "format_version": ARCHIVE_FORMAT_VERSION,
            "exported_at": datetime.now(UTC).isoformat(),
            "source_project_id": project["id"],
            "source_project_title": project["title"],
            "schema_version": CURRENT_SCHEMA_VERSION,
            "tables": tables,
        }
        payload["checksum_sha256"] = hashlib.sha256(canonical_json(payload)).hexdigest()
        return payload

    def import_project(self, raw_archive: bytes) -> str:
        if len(raw_archive) > MAX_ARCHIVE_BYTES:
            raise ProjectArchiveTooLargeError("archive_too_large")
        parsed_archive = _parse_json(raw_archive)
        source_archive_version = (
            parsed_archive.get("format_version") if isinstance(parsed_archive, dict) else None
        )
        archive = self._validate_archive(parsed_archive)
        assert isinstance(source_archive_version, int)
        tables = archive["tables"]
        assert isinstance(tables, dict)
        if source_archive_version >= 12 and not tables["topic_decisions"]:
            raise InvalidProjectArchiveError("missing_topic_decision")

        ids_by_table: dict[str, set[str]] = {}
        id_map: dict[str, str] = {}
        reused_craft_asset_ids: set[str] = set()
        has_raw_reference_assets = bool(tables["reference_works"] or tables["reference_segments"])
        with self.database.connect() as lookup:
            for table in ARCHIVE_TABLES:
                rows = tables[table.name]
                assert isinstance(rows, list)
                table_ids: set[str] = set()
                for row in rows:
                    assert isinstance(row, dict)
                    if table.identity_column is None:
                        continue
                    old_id = _valid_uuid(row[table.identity_column])
                    if old_id != row["id"] or old_id in id_map:
                        raise InvalidProjectArchiveError("duplicate_or_noncanonical_uuid")
                    table_ids.add(old_id)
                    existing_id: str | None = None
                    if table.name == "craft_pattern_assets" and not has_raw_reference_assets:
                        existing = lookup.execute(
                            "SELECT id FROM craft_pattern_assets WHERE content_sha256 = ?",
                            (row["content_sha256"],),
                        ).fetchone()
                        if existing is not None:
                            existing_id = str(existing["id"])
                            reused_craft_asset_ids.add(old_id)
                    id_map[old_id] = existing_id or str(uuid4())
                ids_by_table[table.name] = table_ids

        source_project_id = _valid_uuid(archive["source_project_id"])
        project_rows = tables["projects"]
        assert isinstance(project_rows, list)
        project_row = project_rows[0]
        assert isinstance(project_row, dict)
        if project_row["id"] != source_project_id:
            raise InvalidProjectArchiveError("source_project_mismatch")

        _validate_business_rows(tables, ids_by_table)

        remapped: dict[str, list[dict[str, Any]]] = {}
        comic_source_hash_map: dict[str, str] = {}
        imported_at = datetime.now(UTC).isoformat()
        for table in ARCHIVE_TABLES:
            source_rows = tables[table.name]
            assert isinstance(source_rows, list)
            remapped_rows: list[dict[str, Any]] = []
            for source_row in source_rows:
                assert isinstance(source_row, dict)
                row = dict(source_row)
                row_old_id: str | None = None
                if table.identity_column is not None:
                    row_old_id = row[table.identity_column]
                    assert isinstance(row_old_id, str)
                    row[table.identity_column] = id_map[row_old_id]
                for column, target_table, nullable in table.foreign_keys:
                    old_reference = row[column]
                    if old_reference is None and nullable:
                        continue
                    if not isinstance(old_reference, str):
                        raise InvalidProjectArchiveError("invalid_foreign_key")
                    if old_reference not in ids_by_table[target_table]:
                        raise InvalidProjectArchiveError("external_foreign_key")
                    row[column] = id_map[old_reference]
                for column in table.json_columns:
                    embedded = _parse_json(row[column]) if isinstance(row[column], str) else None
                    if embedded is None:
                        raise InvalidProjectArchiveError("invalid_embedded_json")
                    row[column] = json.dumps(
                        _remap_json(embedded, id_map),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                if table.name == "creative_plan_dependencies":
                    old_subject_id = row["subject_id"]
                    if not isinstance(old_subject_id, str) or old_subject_id not in id_map:
                        raise InvalidProjectArchiveError(
                            "external_creative_plan_subject"
                        )
                    row["subject_id"] = id_map[old_subject_id]
                    dependency = ContextDependencySnapshot.model_validate_json(
                        str(row["dependency_snapshot_json"])
                    )
                    old_fingerprint = row["dependency_fingerprint_sha256"]
                    new_fingerprint = _sha256_json(
                        dependency.model_dump(mode="json")
                    )
                    row["dependency_fingerprint_sha256"] = new_fingerprint
                    if isinstance(old_fingerprint, str):
                        id_map[old_fingerprint] = new_fingerprint
                if table.name == "plan_rebase_candidates":
                    if row["book_blueprint_json"] is not None:
                        blueprint = _parse_json(str(row["book_blueprint_json"]))
                        row["book_blueprint_json"] = json.dumps(
                            _remap_json(blueprint, id_map),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    impact = _parse_json(str(row["impact_json"]))
                    if not isinstance(impact, dict):
                        raise InvalidProjectArchiveError("invalid_plan_rebase_candidate")
                    dependency_value = impact.get("current_dependency")
                    if not isinstance(dependency_value, dict):
                        raise InvalidProjectArchiveError("invalid_plan_rebase_candidate")
                    target_fingerprint = _sha256_json(
                        ContextDependencySnapshot.model_validate(
                            dependency_value
                        ).model_dump(mode="json")
                    )
                    impact["current_dependency_fingerprint_sha256"] = target_fingerprint
                    row["impact_json"] = json.dumps(
                        impact,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    row["target_dependency_fingerprint_sha256"] = target_fingerprint
                    if row["state"] == PlanRebaseCandidateState.CANDIDATE.value:
                        row["state"] = PlanRebaseCandidateState.STALE.value
                        row["revision"] = int(row["revision"]) + 1
                        row["adoption_idempotency_key"] = None
                        row["updated_at"] = imported_at
                if table.name == "context_packets":
                    assert row_old_id is not None
                    _rebind_context_packet_row(
                        row,
                        old_id=row_old_id,
                        old_packet_sha256=source_row["packet_sha256"],
                        old_source_fingerprint_sha256=source_row[
                            "source_fingerprint_sha256"
                        ],
                        old_dependency_fingerprint_sha256=source_row[
                            "dependency_fingerprint_sha256"
                        ],
                        id_map=id_map,
                    )
                if table.name in {
                    "chapter_outline_candidate_versions",
                    "chapter_draft_candidate_versions",
                    "chapter_candidate_reviews",
                }:
                    for fingerprint_column in (
                        "context_packet_sha256",
                        "context_dependency_fingerprint_sha256",
                        "profile_fingerprint_sha256",
                    ):
                        old_fingerprint = row[fingerprint_column]
                        if (
                            isinstance(old_fingerprint, str)
                            and old_fingerprint in id_map
                        ):
                            row[fingerprint_column] = id_map[old_fingerprint]
                if table.name == "directory_events":
                    old_node_id = row["node_id"]
                    if not isinstance(old_node_id, str) or old_node_id not in id_map:
                        raise InvalidProjectArchiveError("external_directory_node")
                    row["node_id"] = id_map[old_node_id]
                if table.name == "context_directives":
                    old_source_id = row["source_id"]
                    if not isinstance(old_source_id, str) or old_source_id not in id_map:
                        raise InvalidProjectArchiveError("external_context_directive_source")
                    row["source_id"] = id_map[old_source_id]
                if table.name == "chapter_versions":
                    source_id = row["source_id"]
                    if isinstance(source_id, str) and source_id in id_map:
                        row["source_id"] = id_map[source_id]
                if table.name == "comic_versions":
                    old_target_id = row["target_id"]
                    if not isinstance(old_target_id, str) or old_target_id not in id_map:
                        raise InvalidProjectArchiveError("external_comic_version_target")
                    row["target_id"] = id_map[old_target_id]
                    old_snapshot_hash = row["source_snapshot_sha256"]
                    if (
                        isinstance(old_snapshot_hash, str)
                        and old_snapshot_hash in comic_source_hash_map
                    ):
                        row["source_snapshot_sha256"] = comic_source_hash_map[old_snapshot_hash]
                    content_json = row["content_json"]
                    if not isinstance(content_json, str):
                        raise InvalidProjectArchiveError("invalid_comic_version_content")
                    row["content_sha256"] = hashlib.sha256(content_json.encode("utf-8")).hexdigest()
                if table.name == "comic_projects":
                    old_snapshot_hash = row["source_snapshot_sha256"]
                    snapshot_json = row["source_snapshot_json"]
                    if not isinstance(old_snapshot_hash, str) or not isinstance(snapshot_json, str):
                        raise InvalidProjectArchiveError("invalid_comic_source_snapshot")
                    new_snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
                    comic_source_hash_map[old_snapshot_hash] = new_snapshot_hash
                    row["source_snapshot_sha256"] = new_snapshot_hash
                if table.name == "job_artifacts" and row["content_type"] == "application/json":
                    embedded_payload = (
                        _parse_json(row["payload"]) if isinstance(row["payload"], str) else None
                    )
                    if embedded_payload is None:
                        raise InvalidProjectArchiveError("invalid_job_artifact_json")
                    row["payload"] = json.dumps(
                        _remap_json(embedded_payload, id_map),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    row["payload_sha256"] = hashlib.sha256(
                        row["payload"].encode("utf-8")
                    ).hexdigest()
                if table.name == "jobs" and row["state"] in {
                    "queued",
                    "running",
                    "pause_requested",
                }:
                    row["state"] = "interrupted"
                    row["lease_owner"] = None
                    row["lease_expires_at"] = None
                    row["heartbeat_at"] = None
                    row["error_code"] = "restored_requires_resubmission"
                    row["error_message"] = "恢复的 AI 任务需要重新预检并提交"
                    row["updated_at"] = imported_at
                    row["completed_at"] = imported_at
                if (
                    table.name == "jobs"
                    and row["workflow"] in {"craft_pattern_analysis_v2", "craft_pattern_fusion_v2"}
                    and row["state"] != "succeeded"
                ):
                    # Imported craft jobs are historical records. Retrying must
                    # always start from a fresh preflight and fresh consent,
                    # including archives whose job was already failed/cancelled.
                    row["error_code"] = "restored_requires_resubmission"
                    row["error_message"] = "恢复的写作模式任务需要重新预检并提交"
                if (
                    table.name == "jobs"
                    and row["workflow"]
                    in {
                        "chapter_production_outline",
                        "chapter_production_draft",
                        "chapter_production_rewrite",
                        "chapter_production_review",
                    }
                    and row["state"] != "succeeded"
                ):
                    # Consent, cost approval and the frozen CreativeContext all
                    # belong to the source project. Restored work is history,
                    # never an executable continuation in the new project.
                    row["error_code"] = "restored_requires_resubmission"
                    row["error_message"] = "恢复的章节生产任务需要重新预检并提交"
                if table.name == "job_chunks" and row["state"] in {"queued", "running"}:
                    row["state"] = "interrupted"
                    row["error_code"] = "restored_requires_resubmission"
                    row["error_message"] = "恢复的任务块不会自动继续"
                    row["updated_at"] = imported_at
                if table.name == "job_attempts" and row["state"] == "running":
                    row["state"] = "interrupted"
                    row["error_code"] = "restored_requires_resubmission"
                    row["error_message"] = "恢复的调用不会自动继续"
                    row["completed_at"] = imported_at
                if (
                    table.name == "craft_pattern_assets"
                    and row_old_id in reused_craft_asset_ids
                ):
                    continue
                remapped_rows.append(row)
            remapped[table.name] = remapped_rows

        evidence_id_map: dict[str, str] = {}
        for row in remapped["craft_pattern_assets"]:
            craft_items = _parse_json(row["craft_items_json"])
            if not isinstance(craft_items, list):
                raise InvalidProjectArchiveError("invalid_craft_items")
            for item in craft_items:
                if not isinstance(item, dict) or not isinstance(item.get("evidence"), list):
                    raise InvalidProjectArchiveError("invalid_craft_items")
                for evidence in item["evidence"]:
                    if not isinstance(evidence, dict):
                        raise InvalidProjectArchiveError("invalid_craft_evidence")
                    old_evidence_id = _valid_uuid(evidence.get("id"))
                    identity = (
                        "mozhou-craft-evidence:"
                        f"{evidence.get('work_id')}:{evidence.get('segment_id')}:"
                        f"{evidence.get('absolute_start_char')}:"
                        f"{evidence.get('absolute_end_char')}:"
                        f"{evidence.get('evidence_sha256')}"
                    )
                    new_evidence_id = str(uuid5(NAMESPACE_URL, identity))
                    previous = evidence_id_map.setdefault(old_evidence_id, new_evidence_id)
                    if previous != new_evidence_id:
                        raise InvalidProjectArchiveError("inconsistent_craft_evidence_identity")
        for row in remapped["craft_pattern_assets"]:
            craft_items = _parse_json(row["craft_items_json"])
            row["craft_items_json"] = json.dumps(
                _remap_json(craft_items, evidence_id_map),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            row["series_id"] = _craft_asset_series_id(row)
            row["content_sha256"] = _craft_asset_content_hash(row)
            row["generation_fingerprint_sha256"] = hashlib.sha256(
                canonical_json(
                    {
                        "archive_import_asset_id": row["id"],
                        "content_sha256": row["content_sha256"],
                    }
                )
            ).hexdigest()

        # Validate the actual post-remap graph before opening the write
        # transaction. Abstract-only archives may reuse immutable global
        # versions; raw-inclusive archives remap the complete graph so that old
        # and new provenance identities are never mixed in one closure.
        validation_assets = list(remapped["craft_pattern_assets"])
        if reused_craft_asset_ids:
            reused_ids = sorted({id_map[old_id] for old_id in reused_craft_asset_ids})
            placeholders = ",".join("?" for _ in reused_ids)
            with self.database.connect() as lookup:
                rows = lookup.execute(
                    f"SELECT * FROM craft_pattern_assets WHERE id IN ({placeholders})",
                    reused_ids,
                ).fetchall()
            if len(rows) != len(reused_ids):
                raise InvalidProjectArchiveError("external_craft_parent")
            validation_assets.extend(dict(row) for row in rows)
        _validate_craft_pattern_rows(
            {
                "craft_pattern_assets": validation_assets,
                "project_craft_pattern_assets": remapped["project_craft_pattern_assets"],
                "craft_pattern_job_outputs": remapped["craft_pattern_job_outputs"],
            }
        )
        try:
            rebind_writing_pattern_rows(
                remapped,
                craft_asset_rows=validation_assets,
            )
            _rebind_pattern_adaptation_rows(remapped)
            validate_writing_pattern_tables(
                remapped,
                craft_asset_rows=validation_assets,
            )
        except InvalidWritingPatternArchiveError as error:
            raise InvalidProjectArchiveError(str(error)) from error
        _validate_m32_archive_rows(remapped)
        _validate_m33_archive_rows(remapped)

        restored_project = remapped["projects"][0]
        title = restored_project["title"]
        if not isinstance(title, str):
            raise InvalidProjectArchiveError("invalid_project_title")
        suffix = "（恢复副本）"
        restored_project["title"] = f"{title[: 120 - len(suffix)]}{suffix}"
        restored_project["updated_at"] = datetime.now(UTC).isoformat()

        try:
            with self.database.connect() as connection:
                for table in ARCHIVE_TABLES:
                    placeholders = ", ".join("?" for _ in table.columns)
                    columns = ", ".join(table.columns)
                    connection.executemany(
                        f"INSERT INTO {table.name} ({columns}) VALUES ({placeholders})",
                        [
                            tuple(row[column] for column in table.columns)
                            for row in remapped[table.name]
                        ],
                    )
                if source_archive_version < 12:
                    _insert_legacy_topic_decision(
                        connection,
                        restored_project,
                        remapped["book_blueprints"],
                    )
                connection.executemany(
                    """
                    INSERT INTO project_reference_works(project_id, reference_work_id, created_at)
                    VALUES (?, ?, ?)
                    """,
                    [
                        (
                            restored_project["id"],
                            row["id"],
                            restored_project["updated_at"],
                        )
                        for row in remapped["reference_works"]
                    ],
                )
        except sqlite3.Error as error:
            raise InvalidProjectArchiveError("invalid_table_values") from error
        project_id = restored_project["id"]
        assert isinstance(project_id, str)
        return project_id

    def create_recovery_point(self, project_id: str, label: str) -> RecoveryPointSummary:
        archive = self.export_project(project_id)
        raw_archive = canonical_json(archive)
        compressed = zlib.compress(raw_archive, level=9)
        recovery_id = str(uuid4())
        created_at = datetime.now(UTC).isoformat()
        archive_sha256 = hashlib.sha256(raw_archive).hexdigest()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO project_recovery_points (
                    id, project_id, label, kind, payload_zlib, archive_sha256,
                    uncompressed_bytes, compressed_bytes, created_at
                ) VALUES (?, ?, ?, 'manual', ?, ?, ?, ?, ?)
                """,
                (
                    recovery_id,
                    project_id,
                    label,
                    compressed,
                    archive_sha256,
                    len(raw_archive),
                    len(compressed),
                    created_at,
                ),
            )
        return RecoveryPointSummary(
            id=recovery_id,
            project_id=project_id,
            label=label,
            kind="manual",
            archive_sha256=archive_sha256,
            uncompressed_bytes=len(raw_archive),
            compressed_bytes=len(compressed),
            created_at=created_at,
        )

    def list_recovery_points(self, project_id: str) -> list[RecoveryPointSummary]:
        with self.database.connect() as connection:
            if (
                connection.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
                is None
            ):
                raise NotFoundError(project_id)
            rows = connection.execute(
                """
                SELECT id, project_id, label, kind, archive_sha256,
                       uncompressed_bytes, compressed_bytes, created_at
                FROM project_recovery_points
                WHERE project_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (project_id,),
            ).fetchall()
        return [RecoveryPointSummary(**dict(row)) for row in rows]

    def restore_recovery_point(self, recovery_point_id: str) -> str:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT payload_zlib, archive_sha256, uncompressed_bytes
                FROM project_recovery_points WHERE id = ?
                """,
                (recovery_point_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(recovery_point_id)
        compressed = row["payload_zlib"]
        if not isinstance(compressed, bytes):
            raise InvalidProjectArchiveError("invalid_recovery_payload")
        try:
            decompressor = zlib.decompressobj()
            raw_archive = decompressor.decompress(compressed, MAX_ARCHIVE_BYTES + 1)
            if (
                len(raw_archive) > MAX_ARCHIVE_BYTES
                or decompressor.unconsumed_tail
                or not decompressor.eof
            ):
                raise ProjectArchiveTooLargeError("recovery_archive_too_large")
        except zlib.error as error:
            raise InvalidProjectArchiveError("invalid_recovery_compression") from error
        if len(raw_archive) != row["uncompressed_bytes"]:
            raise InvalidProjectArchiveError("recovery_size_mismatch")
        if not compare_digest(hashlib.sha256(raw_archive).hexdigest(), row["archive_sha256"]):
            raise InvalidProjectArchiveError("recovery_checksum_mismatch")
        return self.import_project(raw_archive)

    def _validate_archive(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise InvalidProjectArchiveError("archive_not_object")
        expected_keys = {
            "format",
            "format_version",
            "exported_at",
            "source_project_id",
            "source_project_title",
            "schema_version",
            "tables",
            "checksum_sha256",
        }
        if set(value) != expected_keys:
            raise InvalidProjectArchiveError("invalid_archive_fields")
        if value["format"] != ARCHIVE_FORMAT or value["format_version"] not in {
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            11,
            12,
            13,
            14,
            15,
            16,
            17,
        }:
            raise InvalidProjectArchiveError("unsupported_archive_format")
        if not isinstance(value["schema_version"], int) or value["schema_version"] < 0:
            raise InvalidProjectArchiveError("invalid_schema_version")
        if not isinstance(value["exported_at"], str) or not value["exported_at"]:
            raise InvalidProjectArchiveError("invalid_export_time")
        if not isinstance(value["source_project_title"], str):
            raise InvalidProjectArchiveError("invalid_source_title")
        _valid_uuid(value["source_project_id"])

        checksum = value["checksum_sha256"]
        if not isinstance(checksum, str) or len(checksum) != 64:
            raise InvalidProjectArchiveError("invalid_checksum")
        unsigned = dict(value)
        unsigned.pop("checksum_sha256")
        expected_checksum = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        if not compare_digest(checksum, expected_checksum):
            raise InvalidProjectArchiveError("checksum_mismatch")

        if value["format_version"] == 1:
            value = self._upgrade_v1_archive(value)
        if value["format_version"] == 2:
            value = self._upgrade_v2_archive(value)
        if value["format_version"] == 3:
            value = self._upgrade_v3_archive(value)
        if value["format_version"] == 4:
            value = self._upgrade_v4_archive(value)
        if value["format_version"] == 5:
            value = self._upgrade_v5_archive(value)
        if value["format_version"] == 6:
            value = self._upgrade_v6_archive(value)
        if value["format_version"] == 7:
            value = self._upgrade_v7_archive(value)
        if value["format_version"] == 8:
            value = self._upgrade_v8_archive(value)
        if value["format_version"] == 9:
            value = self._upgrade_v9_archive(value)
        if value["format_version"] == 10:
            value = self._upgrade_v10_archive(value)
        if value["format_version"] == 11:
            value = self._upgrade_v11_archive(value)
        if value["format_version"] == 12:
            value = self._upgrade_v12_archive(value)
        if value["format_version"] == 13:
            value = self._upgrade_v13_archive(value)
        if value["format_version"] == 14:
            value = self._upgrade_v14_archive(value)
        if value["format_version"] == 15:
            value = self._upgrade_v15_archive(value)
        if value["format_version"] == 16:
            value = self._upgrade_v16_archive(value)

        tables = value["tables"]
        if not isinstance(tables, dict) or set(tables) != {table.name for table in ARCHIVE_TABLES}:
            raise InvalidProjectArchiveError("invalid_tables")
        for table in ARCHIVE_TABLES:
            rows = tables[table.name]
            if not isinstance(rows, list) or len(rows) > 100_000:
                raise InvalidProjectArchiveError("invalid_row_count")
            if table.name == "projects" and len(rows) != 1:
                raise InvalidProjectArchiveError("invalid_project_count")
            for row in rows:
                if not isinstance(row, dict) or set(row) != set(table.columns):
                    raise InvalidProjectArchiveError("invalid_columns")
        return cast(dict[str, Any], value)

    @staticmethod
    def _upgrade_v1_archive(value: dict[str, Any]) -> dict[str, Any]:
        tables = value.get("tables")
        if not isinstance(tables, dict):
            raise InvalidProjectArchiveError("invalid_tables")
        work_rows = tables.get("reference_works")
        segment_rows = tables.get("reference_segments")
        if not isinstance(work_rows, list) or not isinstance(segment_rows, list):
            raise InvalidProjectArchiveError("invalid_tables")
        contents_by_work: dict[str, str] = {}
        for segment in sorted(
            (row for row in segment_rows if isinstance(row, dict)),
            key=lambda row: (str(row.get("reference_work_id", "")), int(row.get("ordinal", 0))),
        ):
            work_id = segment.get("reference_work_id")
            content = segment.get("content")
            if not isinstance(work_id, str) or not isinstance(content, str):
                raise InvalidProjectArchiveError("invalid_reference_content")
            contents_by_work[work_id] = contents_by_work.get(work_id, "") + content
        upgraded_works: list[dict[str, Any]] = []
        legacy_columns = {
            "id",
            "project_id",
            "title",
            "source_filename",
            "source_format",
            "rights_basis",
            "total_characters",
            "segment_target_characters",
            "created_at",
        }
        for work in work_rows:
            if not isinstance(work, dict) or set(work) != legacy_columns:
                raise InvalidProjectArchiveError("invalid_columns")
            work_id = work["id"]
            created_at = work["created_at"]
            if not isinstance(work_id, str) or not isinstance(created_at, str):
                raise InvalidProjectArchiveError("invalid_business_values")
            upgraded_works.append(
                {key: item for key, item in work.items() if key != "project_id"}
                | {
                    "content_sha256": hashlib.sha256(
                        contents_by_work.get(work_id, "").encode("utf-8")
                    ).hexdigest(),
                    "source_sha256": hashlib.sha256(
                        contents_by_work.get(work_id, "").encode("utf-8")
                    ).hexdigest(),
                    "source_encoding": "utf-8",
                    "encoding_confidence": 1.0,
                    "import_state": "ready",
                    "source_spans_json": "[]",
                    "duplicate_of_id": None,
                    "updated_at": created_at,
                }
            )
        upgraded = dict(value)
        upgraded_tables = dict(tables)
        upgraded_tables["source_documents"] = []
        source_card_rows = upgraded_tables.get("source_cards")
        if not isinstance(source_card_rows, list) or any(
            not isinstance(row, dict) for row in source_card_rows
        ):
            raise InvalidProjectArchiveError("invalid_tables")
        upgraded_tables["source_cards"] = [
            {
                **row,
                "source_document_id": None,
                "source_date": None,
                "page_number_start": None,
                "page_number_end": None,
                "start_char": None,
                "end_char": None,
            }
            for row in source_card_rows
        ]
        upgraded_tables["reference_works"] = upgraded_works
        upgraded["tables"] = upgraded_tables
        upgraded["format_version"] = 2
        unsigned = dict(upgraded)
        unsigned.pop("checksum_sha256", None)
        upgraded["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        return upgraded

    @staticmethod
    def _upgrade_v2_archive(value: dict[str, Any]) -> dict[str, Any]:
        tables = value.get("tables")
        if not isinstance(tables, dict):
            raise InvalidProjectArchiveError("invalid_tables")
        application_rows = tables.get("reference_pattern_applications")
        card_rows = tables.get("reference_pattern_cards")
        if not isinstance(application_rows, list) or not isinstance(card_rows, list):
            raise InvalidProjectArchiveError("invalid_tables")
        proposals: dict[str, dict[str, Any]] = {}
        for card in card_rows:
            if not isinstance(card, dict):
                raise InvalidProjectArchiveError("invalid_columns")
            raw_proposal = card.get("proposal_json")
            if not isinstance(raw_proposal, (bytes, str)):
                raise InvalidProjectArchiveError("invalid_pattern_card_json")
            proposal = _parse_json(raw_proposal)
            if not isinstance(card.get("id"), str) or not isinstance(proposal, dict):
                raise InvalidProjectArchiveError("invalid_pattern_card_json")
            proposals[card["id"]] = proposal

        upgraded_applications: list[dict[str, Any]] = []
        versions: list[dict[str, Any]] = []
        expected_columns = {
            "id",
            "project_id",
            "pattern_card_id",
            "selected_dimensions_json",
            "dimensions_json",
            "relationship_recomposition",
            "application_note",
            "created_at",
        }
        for row in application_rows:
            if not isinstance(row, dict) or set(row) != expected_columns:
                raise InvalidProjectArchiveError("invalid_columns")
            selected = _parse_json(row["selected_dimensions_json"])
            dimensions = _parse_json(row["dimensions_json"])
            proposal = proposals.get(row["pattern_card_id"])
            if (
                not isinstance(selected, list)
                or not isinstance(dimensions, dict)
                or not isinstance(proposal, dict)
                or not all(
                    isinstance(name, str) and name in proposal and name in dimensions
                    for name in selected
                )
            ):
                raise InvalidProjectArchiveError("invalid_legacy_blueprint")
            blueprint = {
                "dimensions": {
                    name: {
                        "source": proposal[name],
                        "mode": "preserve",
                        "author_edits": row["application_note"],
                        "generated_variant": dimensions[name],
                        "version": 1,
                        "locked": False,
                        "named_entities": [],
                        "source_beats": [],
                        "key_beats": [],
                    }
                    for name in selected
                },
                "relationship": {
                    "source": proposal.get("relationship_recomposition", "人物关系待重组"),
                    "mode": "preserve",
                    "author_edits": row["application_note"],
                    "generated_variant": row["relationship_recomposition"],
                    "version": 1,
                    "locked": False,
                    "relationships": [],
                },
            }
            ReferenceBlueprintState.model_validate(blueprint)
            blueprint_json = json.dumps(blueprint, ensure_ascii=False, separators=(",", ":"))
            upgraded_applications.append(
                {
                    **row,
                    "blueprint_json": blueprint_json,
                    "originality_status": "needs_check",
                    "risk_level": None,
                    "latest_report_id": None,
                    "threshold_version": None,
                    "revision": 0,
                    "updated_at": row["created_at"],
                }
            )
            versions.append(
                {
                    "id": str(uuid4()),
                    "application_id": row["id"],
                    "blueprint_revision": 0,
                    "blueprint_json": blueprint_json,
                    "changed_dimensions_json": row["selected_dimensions_json"],
                    "relationship_changed": 1,
                    "created_at": row["created_at"],
                }
            )

        upgraded = dict(value)
        upgraded_tables = dict(tables)
        upgraded_tables["reference_pattern_applications"] = upgraded_applications
        upgraded_tables["reference_blueprint_versions"] = versions
        upgraded_tables["originality_reports"] = []
        upgraded["tables"] = upgraded_tables
        upgraded["format_version"] = 3
        unsigned = dict(upgraded)
        unsigned.pop("checksum_sha256", None)
        upgraded["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        return upgraded

    @staticmethod
    def _upgrade_v3_archive(value: dict[str, Any]) -> dict[str, Any]:
        tables = value.get("tables")
        if not isinstance(tables, dict):
            raise InvalidProjectArchiveError("invalid_tables")
        job_rows = tables.get("jobs")
        if not isinstance(job_rows, list):
            raise InvalidProjectArchiveError("invalid_tables")
        upgraded_jobs: list[dict[str, Any]] = []
        for row in job_rows:
            if not isinstance(row, dict) or "workflow" in row:
                raise InvalidProjectArchiveError("invalid_columns")
            upgraded_jobs.append({**row, "workflow": ""})
        upgraded = dict(value)
        upgraded_tables = dict(tables)
        upgraded_tables["jobs"] = upgraded_jobs
        upgraded_tables["book_blueprints"] = []
        upgraded_tables["volume_plans"] = []
        upgraded_tables["rolling_chapter_plans"] = []
        upgraded["tables"] = upgraded_tables
        upgraded["format_version"] = 4
        unsigned = dict(upgraded)
        unsigned.pop("checksum_sha256", None)
        upgraded["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        return upgraded

    @staticmethod
    def _upgrade_v4_archive(value: dict[str, Any]) -> dict[str, Any]:
        tables = value.get("tables")
        if not isinstance(tables, dict):
            raise InvalidProjectArchiveError("invalid_tables")
        chapter_rows = tables.get("chapters")
        if not isinstance(chapter_rows, list):
            raise InvalidProjectArchiveError("invalid_tables")
        versions: list[dict[str, Any]] = []
        for row in chapter_rows:
            if not isinstance(row, dict):
                raise InvalidProjectArchiveError("invalid_columns")
            content = row.get("content")
            chapter_id = row.get("id")
            revision = row.get("revision")
            updated_at = row.get("updated_at")
            if (
                not isinstance(content, str)
                or not isinstance(chapter_id, str)
                or not isinstance(revision, int)
                or not isinstance(updated_at, str)
            ):
                raise InvalidProjectArchiveError("invalid_chapter_version")
            versions.append(
                {
                    "id": str(uuid4()),
                    "chapter_id": chapter_id,
                    "version_number": 1,
                    "chapter_revision": revision,
                    "content": content,
                    "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "source": "initial",
                    "source_id": None,
                    "parent_version_id": None,
                    "is_candidate": 0,
                    "created_at": updated_at,
                }
            )
        upgraded = dict(value)
        upgraded_tables = dict(tables)
        upgraded_tables["chapter_versions"] = versions
        upgraded_tables["review_findings"] = []
        upgraded_tables["text_change_sets"] = []
        upgraded_tables["text_changes"] = []
        upgraded["tables"] = upgraded_tables
        upgraded["format_version"] = 5
        unsigned = dict(upgraded)
        unsigned.pop("checksum_sha256", None)
        upgraded["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        return upgraded

    @staticmethod
    def _upgrade_v5_archive(value: dict[str, Any]) -> dict[str, Any]:
        tables = value.get("tables")
        if not isinstance(tables, dict):
            raise InvalidProjectArchiveError("invalid_tables")
        chapter_rows = tables.get("chapters")
        project_rows = tables.get("projects")
        if (
            not isinstance(chapter_rows, list)
            or not isinstance(project_rows, list)
            or len(project_rows) != 1
        ):
            raise InvalidProjectArchiveError("invalid_tables")
        project_id = project_rows[0].get("id")
        created_at = project_rows[0].get("created_at")
        updated_at = project_rows[0].get("updated_at")
        if not all(isinstance(item, str) for item in (project_id, created_at, updated_at)):
            raise InvalidProjectArchiveError("invalid_project")
        volume_ids: dict[int, str] = {}
        volume_rows: list[dict[str, Any]] = []
        for ordinal, volume_number in enumerate(
            sorted({int(row["volume_number"]) for row in chapter_rows}),
            start=1,
        ):
            volume_id = str(uuid4())
            volume_ids[volume_number] = volume_id
            volume_rows.append(
                {
                    "id": volume_id,
                    "project_id": project_id,
                    "volume_number": volume_number,
                    "title": f"第{volume_number}卷",
                    "sort_key": ordinal * 1024,
                    "revision": 0,
                    "deleted_at": None,
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
        upgraded_chapters = [
            {
                **row,
                "volume_id": volume_ids[int(row["volume_number"])],
                "sort_key": (index + 1) * 1024,
                "deleted_at": None,
            }
            for index, row in enumerate(chapter_rows)
        ]
        upgraded = dict(value)
        upgraded_tables = dict(tables)
        upgraded_tables["manuscript_volumes"] = volume_rows
        upgraded_tables["chapters"] = upgraded_chapters
        upgraded_tables["manuscript_scenes"] = []
        upgraded_tables["directory_events"] = []
        upgraded_tables["serial_daily_goals"] = []
        upgraded["tables"] = upgraded_tables
        upgraded["format_version"] = 6
        unsigned = dict(upgraded)
        unsigned.pop("checksum_sha256", None)
        upgraded["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        return upgraded

    @staticmethod
    def _upgrade_v6_archive(value: dict[str, Any]) -> dict[str, Any]:
        tables = value.get("tables")
        if not isinstance(tables, dict):
            raise InvalidProjectArchiveError("invalid_tables")
        originality_rows = tables.get("originality_reports")
        if not isinstance(originality_rows, list):
            raise InvalidProjectArchiveError("invalid_tables")
        upgraded = dict(value)
        upgraded_tables = dict(tables)
        upgraded_tables["originality_reports"] = [
            {**row, "acknowledged_at": None} for row in originality_rows
        ]
        upgraded_tables["scene_originality_checks"] = []
        upgraded_tables["scene_originality_findings"] = []
        upgraded["tables"] = upgraded_tables
        upgraded["format_version"] = 7
        unsigned = dict(upgraded)
        unsigned.pop("checksum_sha256", None)
        upgraded["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        return upgraded

    @staticmethod
    def _upgrade_v7_archive(value: dict[str, Any]) -> dict[str, Any]:
        tables = value.get("tables")
        if not isinstance(tables, dict):
            raise InvalidProjectArchiveError("invalid_tables")
        upgraded = dict(value)
        upgraded_tables = dict(tables)
        upgraded_tables["research_sessions"] = []
        upgraded_tables["research_sources"] = []
        upgraded_tables["research_findings"] = []
        upgraded["tables"] = upgraded_tables
        upgraded["format_version"] = 8
        unsigned = dict(upgraded)
        unsigned.pop("checksum_sha256", None)
        upgraded["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        return upgraded

    @staticmethod
    def _upgrade_v8_archive(value: dict[str, Any]) -> dict[str, Any]:
        tables = value.get("tables")
        if not isinstance(tables, dict):
            raise InvalidProjectArchiveError("invalid_tables")
        upgraded = dict(value)
        upgraded_tables = dict(tables)
        upgraded_tables["author_ideas"] = []
        upgraded_tables["chapter_annotations"] = []
        upgraded_tables["story_relationships"] = []
        upgraded["tables"] = upgraded_tables
        upgraded["format_version"] = 9
        unsigned = dict(upgraded)
        unsigned.pop("checksum_sha256", None)
        upgraded["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        return upgraded

    @staticmethod
    def _upgrade_v9_archive(value: dict[str, Any]) -> dict[str, Any]:
        tables = value.get("tables")
        if not isinstance(tables, dict):
            raise InvalidProjectArchiveError("invalid_tables")
        upgraded = dict(value)
        upgraded_tables = dict(tables)
        upgraded_tables["comic_projects"] = []
        upgraded_tables["comic_episodes"] = []
        upgraded_tables["comic_versions"] = []
        upgraded_tables["comic_scenes"] = []
        upgraded["tables"] = upgraded_tables
        upgraded["format_version"] = 10
        unsigned = dict(upgraded)
        unsigned.pop("checksum_sha256", None)
        upgraded["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        return upgraded

    @staticmethod
    def _upgrade_v10_archive(value: dict[str, Any]) -> dict[str, Any]:
        tables = value.get("tables")
        if not isinstance(tables, dict):
            raise InvalidProjectArchiveError("invalid_tables")
        application_rows = tables.get("reference_pattern_applications")
        if not isinstance(application_rows, list):
            raise InvalidProjectArchiveError("invalid_tables")
        application_table = next(
            table for table in ARCHIVE_TABLES if table.name == "reference_pattern_applications"
        )
        legacy_columns = set(application_table.columns) - {
            "lifecycle_state",
            "lifecycle_revision",
        }
        upgraded_applications: list[dict[str, Any]] = []
        for row in application_rows:
            if not isinstance(row, dict) or set(row) != legacy_columns:
                raise InvalidProjectArchiveError("invalid_columns")
            upgraded_applications.append(
                {
                    **row,
                    "lifecycle_state": "active",
                    "lifecycle_revision": 0,
                }
            )
        upgraded = dict(value)
        upgraded_tables = dict(tables)
        upgraded_tables["reference_pattern_applications"] = upgraded_applications
        upgraded["tables"] = upgraded_tables
        upgraded["format_version"] = 11
        unsigned = dict(upgraded)
        unsigned.pop("checksum_sha256", None)
        upgraded["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        return upgraded

    @staticmethod
    def _upgrade_v11_archive(value: dict[str, Any]) -> dict[str, Any]:
        tables = value.get("tables")
        if not isinstance(tables, dict):
            raise InvalidProjectArchiveError("invalid_tables")
        upgraded = dict(value)
        upgraded_tables = dict(tables)
        upgraded_tables["topic_decisions"] = []
        upgraded_tables["topic_decision_versions"] = []
        upgraded_tables["topic_decision_candidate_sets"] = []
        upgraded_tables["topic_decision_candidates"] = []
        upgraded["tables"] = upgraded_tables
        upgraded["format_version"] = 12
        unsigned = dict(upgraded)
        unsigned.pop("checksum_sha256", None)
        upgraded["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        return upgraded

    @staticmethod
    def _upgrade_v12_archive(value: dict[str, Any]) -> dict[str, Any]:
        tables = value.get("tables")
        if not isinstance(tables, dict):
            raise InvalidProjectArchiveError("invalid_tables")
        upgraded = dict(value)
        upgraded_tables = dict(tables)
        upgraded_tables["craft_pattern_assets"] = []
        upgraded_tables["project_craft_pattern_assets"] = []
        upgraded_tables["craft_pattern_job_outputs"] = []
        upgraded["tables"] = upgraded_tables
        upgraded["format_version"] = 13
        unsigned = dict(upgraded)
        unsigned.pop("checksum_sha256", None)
        upgraded["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        return upgraded

    @staticmethod
    def _upgrade_v13_archive(value: dict[str, Any]) -> dict[str, Any]:
        tables = value.get("tables")
        if not isinstance(tables, dict):
            raise InvalidProjectArchiveError("invalid_tables")
        upgraded = dict(value)
        upgraded_tables = dict(tables)
        upgraded_tables["writing_pattern_recipes"] = []
        upgraded_tables["writing_pattern_recipe_versions"] = []
        upgraded_tables["writing_pattern_recipe_sources"] = []
        upgraded_tables["writing_pattern_profile_versions"] = []
        upgraded_tables["project_writing_pattern_profiles"] = []
        upgraded["tables"] = upgraded_tables
        upgraded["format_version"] = 14
        unsigned = dict(upgraded)
        unsigned.pop("checksum_sha256", None)
        upgraded["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        return upgraded

    @staticmethod
    def _upgrade_v14_archive(value: dict[str, Any]) -> dict[str, Any]:
        tables = value.get("tables")
        if not isinstance(tables, dict):
            raise InvalidProjectArchiveError("invalid_tables")
        upgraded = dict(value)
        upgraded_tables = dict(tables)
        for table_name in (
            "generation_runs",
            "fact_change_sets",
            "text_change_sets",
        ):
            rows = upgraded_tables.get(table_name, [])
            if isinstance(rows, list):
                upgraded_tables[table_name] = [
                    {**row, "creative_safety_json": row.get("creative_safety_json")}
                    if isinstance(row, dict)
                    else row
                    for row in rows
                ]
        upgraded_tables["writing_pattern_adaptation_proposals"] = []
        upgraded_tables["writing_pattern_adaptation_candidates"] = []
        upgraded_tables["writing_pattern_adaptation_candidate_versions"] = []
        upgraded_tables["writing_pattern_adoptions"] = []
        upgraded_tables["writing_pattern_originality_reports"] = []
        upgraded_tables["writing_pattern_originality_findings"] = []
        upgraded["tables"] = upgraded_tables
        upgraded["format_version"] = 15
        unsigned = dict(upgraded)
        unsigned.pop("checksum_sha256", None)
        upgraded["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        return upgraded

    @staticmethod
    def _upgrade_v15_archive(value: dict[str, Any]) -> dict[str, Any]:
        tables = value.get("tables")
        if not isinstance(tables, dict):
            raise InvalidProjectArchiveError("invalid_tables")
        upgraded = dict(value)
        upgraded_tables = dict(tables)
        upgraded_tables["context_packets"] = []
        upgraded_tables["creative_plan_dependencies"] = []
        upgraded_tables["plan_rebase_candidates"] = []
        upgraded["tables"] = upgraded_tables
        upgraded["format_version"] = 16
        unsigned = dict(upgraded)
        unsigned.pop("checksum_sha256", None)
        upgraded["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        return upgraded

    @staticmethod
    def _upgrade_v16_archive(value: dict[str, Any]) -> dict[str, Any]:
        tables = value.get("tables")
        if not isinstance(tables, dict):
            raise InvalidProjectArchiveError("invalid_tables")
        upgraded = dict(value)
        upgraded_tables = dict(tables)
        for table_name in (
            "chapter_productions",
            "chapter_production_events",
            "chapter_outline_candidates",
            "chapter_outline_candidate_versions",
            "chapter_preflight_checks",
            "chapter_draft_candidates",
            "chapter_draft_candidate_versions",
            "chapter_draft_candidate_locks",
            "chapter_candidate_reviews",
            "chapter_candidate_merge_sources",
            "chapter_writing_outcomes",
        ):
            upgraded_tables[table_name] = []
        upgraded["tables"] = upgraded_tables
        upgraded["format_version"] = 17
        unsigned = dict(upgraded)
        unsigned.pop("checksum_sha256", None)
        upgraded["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        return upgraded
