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
    Chapter,
    ChapterStatus,
    FactChange,
    FactChangeSet,
    FutureKnowledge,
    GenerationRun,
    GenerationState,
    Project,
    RecoveryPointSummary,
    ReferencePatternApplication,
    ReferencePatternCard,
    ReferenceSegment,
    ReferenceWork,
    SourceCard,
    StoryEntity,
    StoryFact,
    StoryThread,
    TimelineEvent,
)
from app.repository import NotFoundError

ARCHIVE_FORMAT = "mozhou-project"
ARCHIVE_FORMAT_VERSION = 2
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
        "chapters",
        (
            "id",
            "project_id",
            "volume_number",
            "chapter_number",
            "title",
            "content",
            "reader_promise",
            "opening_hook",
            "state_change",
            "emotional_payoff",
            "ending_cliffhanger",
            "status",
            "revision",
            "updated_at",
        ),
        "project_id = ?",
        (("project_id", "projects", False),),
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
            "confirmed",
            "revision",
            "created_at",
            "updated_at",
        ),
        "project_id = ?",
        (("project_id", "projects", False),),
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
            "source_encoding",
            "encoding_confidence",
            "import_state",
            "duplicate_of_id",
            "created_at",
            "updated_at",
        ),
        "id IN (SELECT reference_work_id FROM project_reference_works WHERE project_id = ?)",
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
            "created_at",
        ),
        "project_id = ?",
        (
            ("project_id", "projects", False),
            ("pattern_card_id", "reference_pattern_cards", False),
        ),
        ("selected_dimensions_json", "dimensions_json"),
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
        for row in tables["chapters"]:
            Chapter.model_validate(row)
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
            ReferenceWork.model_validate({**row, "segments": segments_by_work.get(row["id"], [])})

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
            ReferencePatternApplication.model_validate(
                {
                    **row,
                    "selected_dimensions": selected_dimensions,
                    "dimensions": dimensions,
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

        nullable_timestamps = {
            "lease_expires_at",
            "heartbeat_at",
            "started_at",
            "completed_at",
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
                    table.name in {"reference_works", "reference_segments"}
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
                if table.name == "context_directives":
                    old_source_id = row["source_id"]
                    if not isinstance(old_source_id, str) or old_source_id not in id_map:
                        raise InvalidProjectArchiveError("external_context_directive_source")
                    row["source_id"] = id_map[old_source_id]
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
        if value["format"] != ARCHIVE_FORMAT or value["format_version"] not in {1, 2}:
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
                "source_encoding": "utf-8",
                "encoding_confidence": 1.0,
                "import_state": "ready",
                "duplicate_of_id": None,
                "updated_at": created_at,
            })
        upgraded = dict(value)
        upgraded_tables = dict(tables)
        upgraded_tables["reference_works"] = upgraded_works
        upgraded["tables"] = upgraded_tables
        upgraded["format_version"] = ARCHIVE_FORMAT_VERSION
        unsigned = dict(upgraded)
        unsigned.pop("checksum_sha256", None)
        upgraded["checksum_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        return upgraded
