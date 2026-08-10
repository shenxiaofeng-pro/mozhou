import hashlib
import json
import sqlite3
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from hmac import compare_digest
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.context import ContextDirective
from app.database import CURRENT_SCHEMA_VERSION, Database
from app.jobs.models import Job, JobArtifact, JobAttempt, JobChunk, JobEvent
from app.models import (
    BookBlueprint,
    Chapter,
    ChapterStatus,
    ChapterVersion,
    FactChange,
    FactChangeSet,
    FutureKnowledge,
    GenerationRun,
    GenerationState,
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
    SourceCard,
    SourceDocument,
    StoryEntity,
    StoryFact,
    StoryThread,
    TextChange,
    TextChangeSet,
    TimelineEvent,
    VolumePlan,
    VolumePlanContent,
)
from app.originality_guard import LEGAL_NOTICE
from app.repository import NotFoundError

ARCHIVE_FORMAT = "mozhou-project"
ARCHIVE_FORMAT_VERSION = 6
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class ArchiveTable:
    name: str
    columns: tuple[str, ...]
    scope: str
    foreign_keys: tuple[tuple[str, str, bool], ...] = ()
    json_columns: tuple[str, ...] = ()


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
            "created_at",
            "updated_at",
        ),
        "chapter_id IN (SELECT id FROM chapters WHERE project_id = ?)",
        (("chapter_id", "chapters", False),),
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
            "created_at",
            "updated_at",
        ),
        "chapter_id IN (SELECT id FROM chapters WHERE project_id = ?)",
        (("chapter_id", "chapters", False),),
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
            "created_at",
            "updated_at",
        ),
        "chapter_id IN (SELECT id FROM chapters WHERE project_id = ?)",
        (("chapter_id", "chapters", False),),
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
        "id IN (SELECT source_document_id FROM source_cards WHERE project_id = ? AND source_document_id IS NOT NULL)",
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
            BookBlueprint.model_validate({
                **row,
                "content": _parse_json(row["content_json"]),
                "locks": _parse_json(row["locks_json"]),
                "field_versions": _parse_json(row["field_versions_json"]),
                "stale_fields": _parse_json(row["stale_fields_json"]),
                "plan_stale": bool(row["plan_stale"]),
            })
        for row in tables["volume_plans"]:
            volume_content = VolumePlanContent.model_validate(
                _parse_json(row["content_json"])
            )
            VolumePlan.model_validate({
                **volume_content.model_dump(mode="json"),
                "id": row["id"],
                "project_id": row["project_id"],
                "revision": row["revision"],
                "locked": bool(row["locked"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            })
        for row in tables["rolling_chapter_plans"]:
            rolling_content = RollingChapterPlanContent.model_validate(
                _parse_json(row["content_json"])
            )
            RollingChapterPlan.model_validate({
                **rolling_content.model_dump(mode="json"),
                "id": row["id"],
                "project_id": row["project_id"],
                "volume_plan_id": row["volume_plan_id"],
                "revision": row["revision"],
                "locked": bool(row["locked"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            })
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
            version = ChapterVersion.model_validate(
                {**row, "is_candidate": bool(row["is_candidate"])}
            )
            if not compare_digest(
                hashlib.sha256(version.content.encode("utf-8")).hexdigest(),
                version.content_sha256,
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
            if (
                target_table is None
                or directive.source_id not in ids_by_table[target_table]
            ):
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
            SourceDocument.model_validate({
                **row,
                "source_spans": spans,
                "total_characters": len(content),
            })

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
            ReferenceWork.model_validate({
                **row,
                "source_spans": spans,
                "segments": segments_by_work.get(row["id"], []),
            })

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
                or not set(changed_dimensions) <= {
                    dimension.value for dimension in state.dimensions
                }
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

        for row in tables["review_findings"]:
            ReviewFinding.model_validate(
                {**row, "evidence": _parse_json(row["evidence_json"])}
            )
        text_changes_by_set: dict[str, list[dict[str, Any]]] = {}
        for row in tables["text_changes"]:
            TextChange.model_validate(
                {
                    **row,
                    "selected": (
                        bool(row["selected"])
                        if row["selected"] is not None
                        else None
                    ),
                }
            )
            text_changes_by_set.setdefault(row["change_set_id"], []).append(row)
        for row in tables["text_change_sets"]:
            TextChangeSet.model_validate(
                {**row, "changes": text_changes_by_set.get(row["id"], [])}
            )

        nullable_timestamps = {
            "lease_expires_at",
            "heartbeat_at",
            "started_at",
            "completed_at",
            "viewed_at",
            "deleted_at",
            "undone_at",
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
                    table.name in {"reference_works", "reference_segments", "source_documents"}
                    and not include_reference_assets
                ):
                    tables[table.name] = []
                    continue
                columns = ", ".join(table.columns)
                rows = connection.execute(
                    f"SELECT {columns} FROM {table.name} WHERE {table.scope} ORDER BY rowid",
                    (project_id,),
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
        archive = self._validate_archive(_parse_json(raw_archive))
        tables = archive["tables"]
        assert isinstance(tables, dict)

        ids_by_table: dict[str, set[str]] = {}
        id_map: dict[str, str] = {}
        for table in ARCHIVE_TABLES:
            rows = tables[table.name]
            assert isinstance(rows, list)
            table_ids: set[str] = set()
            for row in rows:
                assert isinstance(row, dict)
                old_id = _valid_uuid(row["id"])
                if old_id != row["id"] or old_id in id_map:
                    raise InvalidProjectArchiveError("duplicate_or_noncanonical_uuid")
                table_ids.add(old_id)
                id_map[old_id] = str(uuid4())
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
        for table in ARCHIVE_TABLES:
            source_rows = tables[table.name]
            assert isinstance(source_rows, list)
            remapped_rows: list[dict[str, Any]] = []
            for source_row in source_rows:
                assert isinstance(source_row, dict)
                row = dict(source_row)
                old_id = row["id"]
                assert isinstance(old_id, str)
                row["id"] = id_map[old_id]
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
                if table.name == "job_artifacts" and row["content_type"] == "application/json":
                    embedded_payload = (
                        _parse_json(row["payload"])
                        if isinstance(row["payload"], str)
                        else None
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
                remapped_rows.append(row)
            remapped[table.name] = remapped_rows

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
                        [tuple(row[column] for column in table.columns) for row in remapped[table.name]],
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
            if connection.execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)
            ).fetchone() is None:
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
        if value["format"] != ARCHIVE_FORMAT or value["format_version"] not in {1, 2, 3, 4, 5, 6}:
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
            "id", "project_id", "title", "source_filename", "source_format",
            "rights_basis", "total_characters", "segment_target_characters", "created_at",
        }
        for work in work_rows:
            if not isinstance(work, dict) or set(work) != legacy_columns:
                raise InvalidProjectArchiveError("invalid_columns")
            work_id = work["id"]
            created_at = work["created_at"]
            if not isinstance(work_id, str) or not isinstance(created_at, str):
                raise InvalidProjectArchiveError("invalid_business_values")
            upgraded_works.append({
                key: item for key, item in work.items() if key != "project_id"
            } | {
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
            })
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
            "id", "project_id", "pattern_card_id", "selected_dimensions_json",
            "dimensions_json", "relationship_recomposition", "application_note",
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
                    isinstance(name, str)
                    and name in proposal
                    and name in dimensions
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
            blueprint_json = json.dumps(
                blueprint, ensure_ascii=False, separators=(",", ":")
            )
            upgraded_applications.append({
                **row,
                "blueprint_json": blueprint_json,
                "originality_status": "needs_check",
                "risk_level": None,
                "latest_report_id": None,
                "threshold_version": None,
                "revision": 0,
                "updated_at": row["created_at"],
            })
            versions.append({
                "id": str(uuid4()),
                "application_id": row["id"],
                "blueprint_revision": 0,
                "blueprint_json": blueprint_json,
                "changed_dimensions_json": row["selected_dimensions_json"],
                "relationship_changed": 1,
                "created_at": row["created_at"],
            })

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
            volume_rows.append({
                "id": volume_id,
                "project_id": project_id,
                "volume_number": volume_number,
                "title": f"第{volume_number}卷",
                "sort_key": ordinal * 1024,
                "revision": 0,
                "deleted_at": None,
                "created_at": created_at,
                "updated_at": updated_at,
            })
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
        upgraded["format_version"] = ARCHIVE_FORMAT_VERSION
        unsigned = dict(upgraded)
        unsigned.pop("checksum_sha256", None)
        upgraded["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        return upgraded
