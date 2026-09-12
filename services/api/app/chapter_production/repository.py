from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from sqlite3 import Connection, Row
from typing import cast
from uuid import uuid4

from app.context.models import CreativeContextPurpose
from app.database import Database
from app.models import ChapterStatus, ChapterVersionSource
from app.review.repository import ReviewRepository

from .models import (
    AdoptCandidateRequest,
    AdoptionMode,
    AppliedChapterVersion,
    CandidateLock,
    CandidateReview,
    CandidateReviewDraft,
    CandidateState,
    CandidateVersionOperation,
    ChapterOutline,
    ChapterProduction,
    ChapterProductionState,
    DraftCandidate,
    DraftCandidateVersion,
    EditableTextSelection,
    MergeCandidatesRequest,
    MergeSource,
    ModelTrace,
    OutlineCandidate,
    OutlineCandidateVersion,
    OutlineVersionOperation,
    PreflightCheck,
    ProductionEvent,
    ProductionSnapshot,
    RejectCandidateRequest,
    TextSelection,
    WritingDecision,
    WritingOutcome,
)


class ChapterProductionNotFoundError(LookupError):
    pass


class ChapterProductionConflictError(RuntimeError):
    pass


class LockedSelectionError(ChapterProductionConflictError):
    pass


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: object) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def text_sha256(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def outline_sha256(value: ChapterOutline) -> str:
    return canonical_sha256(value.model_dump(mode="json"))


class ChapterProductionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_production(
        self,
        *,
        project_id: str,
        chapter_id: str,
        expected_chapter_revision: int,
        expected_chapter_content_sha256: str,
    ) -> ChapterProduction:
        timestamp = now_iso()
        production_id = str(uuid4())
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            chapter = self._chapter_row(connection, project_id, chapter_id)
            self._require_chapter_guard(
                chapter,
                expected_chapter_revision,
                expected_chapter_content_sha256,
            )
            existing = connection.execute(
                """
                SELECT * FROM chapter_productions
                WHERE project_id = ? AND chapter_id = ?
                  AND base_chapter_revision = ? AND base_chapter_content_sha256 = ?
                  AND state NOT IN ('adopted', 'rejected')
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (
                    project_id,
                    chapter_id,
                    expected_chapter_revision,
                    expected_chapter_content_sha256,
                ),
            ).fetchone()
            if existing is not None:
                return self._parse_production(existing)
            connection.execute(
                """
                INSERT INTO chapter_productions (
                    id, project_id, chapter_id, base_chapter_revision,
                    base_chapter_content_sha256, state, revision,
                    current_outline_candidate_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'created', 0, NULL, ?, ?)
                """,
                (
                    production_id,
                    project_id,
                    chapter_id,
                    expected_chapter_revision,
                    expected_chapter_content_sha256,
                    timestamp,
                    timestamp,
                ),
            )
            self._append_event(
                connection,
                production_id=production_id,
                event_type="production_created",
                from_state=None,
                to_state=ChapterProductionState.CREATED,
                detail={
                    "chapter_revision": expected_chapter_revision,
                    "chapter_content_sha256": expected_chapter_content_sha256,
                },
                timestamp=timestamp,
            )
            row = self._production_row(connection, production_id)
        assert row is not None
        return self._parse_production(row)

    def get_current_production(self, project_id: str, chapter_id: str) -> ChapterProduction:
        """Return the latest open aggregate without repairing or materialising anything."""

        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM chapter_productions
                WHERE project_id = ? AND chapter_id = ?
                  AND state NOT IN ('adopted', 'rejected')
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (project_id, chapter_id),
            ).fetchone()
        if row is None:
            raise ChapterProductionNotFoundError(chapter_id)
        return self._parse_production(row)

    def get_production(self, production_id: str) -> ChapterProduction:
        with self.database.connect() as connection:
            row = self._production_row(connection, production_id)
        if row is None:
            raise ChapterProductionNotFoundError(production_id)
        return self._parse_production(row)

    def add_outline_candidate(
        self,
        *,
        production_id: str,
        outline: ChapterOutline,
        label: str,
        trace: ModelTrace,
        source_job_id: str | None = None,
    ) -> OutlineCandidate:
        if trace.purpose != CreativeContextPurpose.BRIEF:
            raise ValueError("outline_requires_brief_context")
        timestamp = now_iso()
        candidate_id = str(uuid4())
        version_id = str(uuid4())
        digest = outline_sha256(outline)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if source_job_id is not None:
                existing = self._outline_by_source_job(connection, source_job_id)
                if existing is not None:
                    if (
                        str(existing["production_id"]) != production_id
                        or str(existing["content_sha256"]) != digest
                    ):
                        raise ChapterProductionConflictError("job_result_changed")
                    return self._parse_outline(existing)
            production = self._require_mutable_production(connection, production_id)
            self._require_production_chapter_current(connection, production)
            ordinal = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(ordinal), 0) + 1
                    FROM chapter_outline_candidates WHERE production_id = ?
                    """,
                    (production_id,),
                ).fetchone()[0]
            )
            connection.execute(
                """
                INSERT INTO chapter_outline_candidates (
                    id, production_id, ordinal, label, state, current_revision,
                    current_content_sha256, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'available', 0, ?, ?, ?)
                """,
                (candidate_id, production_id, ordinal, label, digest, timestamp, timestamp),
            )
            connection.execute(
                """
                INSERT INTO chapter_outline_candidate_versions (
                    id, candidate_id, revision, content_json, content_sha256,
                    operation, parent_version_id, source_job_id,
                    context_purpose, context_packet_id, context_packet_sha256,
                    context_dependency_fingerprint_sha256, context_compiler_version,
                    profile_fingerprint_sha256, provider, model, prompt_version, created_at
                ) VALUES (?, ?, 0, ?, ?, 'model_draft', NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    candidate_id,
                    outline.model_dump_json(),
                    digest,
                    source_job_id,
                    trace.purpose.value,
                    trace.context_packet_id,
                    trace.context_packet_sha256,
                    trace.context_dependency_fingerprint_sha256,
                    trace.context_compiler_version,
                    trace.profile_fingerprint_sha256,
                    trace.provider,
                    trace.model,
                    trace.prompt_version,
                    timestamp,
                ),
            )
            connection.execute(
                """
                UPDATE chapter_productions SET current_outline_candidate_id = ?
                WHERE id = ?
                """,
                (candidate_id, production_id),
            )
            self._transition(
                connection,
                production,
                ChapterProductionState.OUTLINE_READY,
                "outline_candidate_created",
                {"outline_candidate_id": candidate_id, "outline_version_id": version_id},
                timestamp,
            )
            row = self._outline_row(connection, candidate_id)
        assert row is not None
        return self._parse_outline(row)

    def edit_outline_candidate(
        self,
        *,
        production_id: str,
        candidate_id: str,
        expected_outline_revision: int,
        expected_outline_content_sha256: str,
        outline: ChapterOutline,
    ) -> OutlineCandidate:
        timestamp = now_iso()
        digest = outline_sha256(outline)
        version_id = str(uuid4())
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            production = self._require_mutable_production(connection, production_id)
            self._require_production_chapter_current(connection, production)
            current = self._outline_row(connection, candidate_id, production_id)
            if current is None:
                raise ChapterProductionNotFoundError(candidate_id)
            self._require_outline_guard(
                current,
                expected_outline_revision,
                expected_outline_content_sha256,
            )
            next_revision = expected_outline_revision + 1
            connection.execute(
                """
                INSERT INTO chapter_outline_candidate_versions (
                    id, candidate_id, revision, content_json, content_sha256,
                    operation, parent_version_id, source_job_id,
                    context_purpose, context_packet_id, context_packet_sha256,
                    context_dependency_fingerprint_sha256, context_compiler_version,
                    profile_fingerprint_sha256, provider, model, prompt_version, created_at
                ) VALUES (?, ?, ?, ?, ?, 'author_edit', ?, NULL,
                          NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?)
                """,
                (
                    version_id,
                    candidate_id,
                    next_revision,
                    outline.model_dump_json(),
                    digest,
                    str(current["version_id"]),
                    timestamp,
                ),
            )
            updated = connection.execute(
                """
                UPDATE chapter_outline_candidates
                SET current_revision = ?, current_content_sha256 = ?, updated_at = ?
                WHERE id = ? AND state = 'available'
                  AND current_revision = ? AND current_content_sha256 = ?
                """,
                (
                    next_revision,
                    digest,
                    timestamp,
                    candidate_id,
                    expected_outline_revision,
                    expected_outline_content_sha256,
                ),
            )
            if updated.rowcount != 1:
                raise ChapterProductionConflictError("outline_candidate_changed")
            self._transition(
                connection,
                production,
                ChapterProductionState.OUTLINE_READY,
                "outline_candidate_edited",
                {"outline_candidate_id": candidate_id, "outline_version_id": version_id},
                timestamp,
            )
            row = self._outline_row(connection, candidate_id, production_id)
        assert row is not None
        return self._parse_outline(row)

    def get_outline_candidate(
        self,
        production_id: str,
        candidate_id: str,
    ) -> OutlineCandidate:
        with self.database.connect() as connection:
            row = self._outline_row(connection, candidate_id, production_id)
        if row is None:
            raise ChapterProductionNotFoundError(candidate_id)
        return self._parse_outline(row)

    def get_outline_job_result(self, production_id: str, job_id: str) -> OutlineCandidate:
        with self.database.connect() as connection:
            row = self._outline_by_source_job(connection, job_id)
        if row is None or str(row["production_id"]) != production_id:
            raise ChapterProductionNotFoundError(job_id)
        return self._parse_outline(row)

    def record_preflight(
        self,
        *,
        production_id: str,
        outline_candidate_id: str,
        expected_outline_revision: int,
        expected_outline_content_sha256: str,
        checks: dict[str, bool],
        missing_fields: list[str],
    ) -> PreflightCheck:
        timestamp = now_iso()
        check_id = str(uuid4())
        passed = not missing_fields
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            production = self._require_mutable_production(connection, production_id)
            self._require_production_chapter_current(connection, production)
            outline = self._outline_row(connection, outline_candidate_id, production_id)
            if outline is None:
                raise ChapterProductionNotFoundError(outline_candidate_id)
            self._require_outline_guard(
                outline,
                expected_outline_revision,
                expected_outline_content_sha256,
            )
            existing = connection.execute(
                """
                SELECT * FROM chapter_preflight_checks
                WHERE production_id = ? AND outline_version_id = ?
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (production_id, str(outline["version_id"])),
            ).fetchone()
            if existing is not None:
                return self._parse_preflight(existing)
            connection.execute(
                """
                INSERT INTO chapter_preflight_checks (
                    id, production_id, outline_candidate_id, outline_version_id,
                    outline_revision, outline_content_sha256, reader_promise,
                    opening_hook, state_change, emotional_payoff, ending_cliffhanger,
                    missing_fields_json, passed, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    check_id,
                    production_id,
                    outline_candidate_id,
                    str(outline["version_id"]),
                    expected_outline_revision,
                    expected_outline_content_sha256,
                    int(checks["reader_promise"]),
                    int(checks["opening_hook"]),
                    int(checks["state_change"]),
                    int(checks["emotional_payoff"]),
                    int(checks["ending_cliffhanger"]),
                    canonical_json(missing_fields),
                    int(passed),
                    timestamp,
                ),
            )
            next_state = (
                ChapterProductionState.DRAFT_READY
                if passed
                else ChapterProductionState.PREFLIGHT_BLOCKED
            )
            self._transition(
                connection,
                production,
                next_state,
                "preflight_passed" if passed else "preflight_blocked",
                {"check_id": check_id, "missing_fields": missing_fields},
                timestamp,
            )
            row = connection.execute(
                "SELECT * FROM chapter_preflight_checks WHERE id = ?", (check_id,)
            ).fetchone()
        assert row is not None
        return self._parse_preflight(row)

    def create_draft_candidate(
        self,
        *,
        production_id: str,
        outline_candidate_id: str,
        expected_outline_revision: int,
        expected_outline_content_sha256: str,
        content: str,
        label: str,
        trace: ModelTrace,
        source_job_id: str | None = None,
    ) -> DraftCandidate:
        if not content:
            raise ValueError("candidate_content_empty")
        if trace.purpose != CreativeContextPurpose.DRAFT:
            raise ValueError("draft_requires_draft_context")
        timestamp = now_iso()
        candidate_id = str(uuid4())
        version_id = str(uuid4())
        digest = text_sha256(content)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if source_job_id is not None:
                existing = self._candidate_by_source_job(connection, source_job_id)
                if existing is not None:
                    if (
                        str(existing["production_id"]) != production_id
                        or str(existing["content_sha256"]) != digest
                    ):
                        raise ChapterProductionConflictError("job_result_changed")
                    return self._parse_candidate(connection=connection, row=existing)
            production = self._require_mutable_production(connection, production_id)
            self._require_production_chapter_current(connection, production)
            outline = self._outline_row(connection, outline_candidate_id, production_id)
            if outline is None:
                raise ChapterProductionNotFoundError(outline_candidate_id)
            self._require_outline_guard(
                outline,
                expected_outline_revision,
                expected_outline_content_sha256,
            )
            passed = connection.execute(
                """
                SELECT 1 FROM chapter_preflight_checks
                WHERE production_id = ? AND outline_version_id = ? AND passed = 1
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (production_id, str(outline["version_id"])),
            ).fetchone()
            if passed is None:
                raise ChapterProductionConflictError("preflight_not_passed")
            connection.execute(
                """
                INSERT INTO chapter_draft_candidates (
                    id, production_id, label, state,
                    source_outline_candidate_id, source_outline_version_id,
                    source_outline_revision, source_outline_content_sha256, current_revision,
                    current_content_sha256, created_at, updated_at
                ) VALUES (?, ?, ?, 'available', ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    candidate_id,
                    production_id,
                    label,
                    outline_candidate_id,
                    str(outline["version_id"]),
                    expected_outline_revision,
                    expected_outline_content_sha256,
                    digest,
                    timestamp,
                    timestamp,
                ),
            )
            self._insert_candidate_version(
                connection,
                version_id=version_id,
                candidate_id=candidate_id,
                revision=0,
                content=content,
                operation=CandidateVersionOperation.MODEL_DRAFT,
                parent_version_id=None,
                restored_from_version_id=None,
                source_job_id=source_job_id,
                trace=trace,
                instruction="",
                timestamp=timestamp,
            )
            self._transition(
                connection,
                production,
                ChapterProductionState.CANDIDATE_READY,
                "draft_candidate_created",
                {"candidate_id": candidate_id, "candidate_version_id": version_id},
                timestamp,
            )
            row = self._candidate_row(connection, candidate_id, production_id)
        assert row is not None
        return self._parse_candidate(connection=None, row=row, locks=[])

    def get_candidate(self, production_id: str, candidate_id: str) -> DraftCandidate:
        with self.database.connect() as connection:
            row = self._candidate_row(connection, candidate_id, production_id)
            if row is None:
                raise ChapterProductionNotFoundError(candidate_id)
            locks = self._lock_rows(connection, candidate_id)
        return self._parse_candidate(connection=None, row=row, locks=locks)

    def get_candidate_job_result(self, production_id: str, job_id: str) -> DraftCandidate:
        with self.database.connect() as connection:
            row = self._candidate_by_source_job(connection, job_id)
            if row is None or str(row["production_id"]) != production_id:
                raise ChapterProductionNotFoundError(job_id)
            locks = self._lock_rows(connection, str(row["id"]))
        return self._parse_candidate(connection=None, row=row, locks=locks)

    def list_candidate_versions(
        self,
        production_id: str,
        candidate_id: str,
    ) -> list[DraftCandidateVersion]:
        with self.database.connect() as connection:
            if self._candidate_row(connection, candidate_id, production_id) is None:
                raise ChapterProductionNotFoundError(candidate_id)
            rows = connection.execute(
                """
                SELECT * FROM chapter_draft_candidate_versions
                WHERE candidate_id = ? ORDER BY revision
                """,
                (candidate_id,),
            ).fetchall()
        return [self._parse_candidate_version(row) for row in rows]

    def replace_candidate_selection(
        self,
        *,
        production_id: str,
        candidate_id: str,
        expected_candidate_revision: int,
        expected_candidate_content_sha256: str,
        selection: TextSelection | EditableTextSelection,
        replacement: str,
        operation: CandidateVersionOperation,
        instruction: str,
        trace: ModelTrace | None = None,
        source_job_id: str | None = None,
    ) -> DraftCandidate:
        if trace is not None and trace.purpose not in {
            CreativeContextPurpose.DRAFT,
            CreativeContextPurpose.CANDIDATE_REVIEW,
        }:
            raise ValueError("rewrite_requires_draft_context")
        if operation not in {
            CandidateVersionOperation.AUTHOR_EDIT,
            CandidateVersionOperation.LOCAL_REWRITE,
        }:
            raise ValueError("selection_operation_invalid")
        timestamp = now_iso()
        version_id = str(uuid4())
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if source_job_id is not None:
                existing = self._candidate_by_source_job(connection, source_job_id)
                if existing is not None:
                    if str(existing["production_id"]) != production_id:
                        raise ChapterProductionConflictError("job_result_changed")
                    return self._parse_candidate(connection=connection, row=existing)
            production = self._require_mutable_production(connection, production_id)
            self._require_production_chapter_current(connection, production)
            candidate = self._candidate_row(connection, candidate_id, production_id)
            if candidate is None:
                raise ChapterProductionNotFoundError(candidate_id)
            self._require_candidate_guard(
                candidate,
                expected_candidate_revision,
                expected_candidate_content_sha256,
            )
            current_content = str(candidate["content"])
            self._selected_text(current_content, selection)
            lock_rows = self._lock_rows(connection, candidate_id)
            self._require_unlocked(selection, lock_rows)
            next_content = (
                current_content[: selection.start_char]
                + replacement
                + current_content[selection.end_char :]
            )
            if not next_content:
                raise ChapterProductionConflictError("candidate_content_empty")
            next_revision = expected_candidate_revision + 1
            self._insert_candidate_version(
                connection,
                version_id=version_id,
                candidate_id=candidate_id,
                revision=next_revision,
                content=next_content,
                operation=operation,
                parent_version_id=str(candidate["version_id"]),
                restored_from_version_id=None,
                source_job_id=source_job_id,
                trace=trace,
                instruction=instruction,
                timestamp=timestamp,
            )
            result = connection.execute(
                """
                UPDATE chapter_draft_candidates
                SET current_revision = ?, current_content_sha256 = ?, updated_at = ?
                WHERE id = ? AND state = 'available'
                  AND current_revision = ? AND current_content_sha256 = ?
                """,
                (
                    next_revision,
                    text_sha256(next_content),
                    timestamp,
                    candidate_id,
                    expected_candidate_revision,
                    expected_candidate_content_sha256,
                ),
            )
            if result.rowcount != 1:
                raise ChapterProductionConflictError("candidate_changed")
            self._shift_locks(
                connection,
                lock_rows,
                selection,
                len(replacement) - (selection.end_char - selection.start_char),
            )
            self._transition(
                connection,
                production,
                ChapterProductionState.CANDIDATE_READY,
                operation.value,
                {
                    "candidate_id": candidate_id,
                    "candidate_version_id": version_id,
                    "start_char": selection.start_char,
                    "end_char": selection.end_char,
                },
                timestamp,
            )
            updated = self._candidate_row(connection, candidate_id, production_id)
            assert updated is not None
            updated_locks = self._lock_rows(connection, candidate_id)
        return self._parse_candidate(connection=None, row=updated, locks=updated_locks)

    def lock_selection(
        self,
        *,
        production_id: str,
        candidate_id: str,
        expected_candidate_revision: int,
        expected_candidate_content_sha256: str,
        selection: TextSelection,
    ) -> CandidateLock:
        timestamp = now_iso()
        lock_id = str(uuid4())
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            production = self._require_mutable_production(connection, production_id)
            self._require_production_chapter_current(connection, production)
            candidate = self._candidate_row(connection, candidate_id, production_id)
            if candidate is None:
                raise ChapterProductionNotFoundError(candidate_id)
            self._require_candidate_guard(
                candidate,
                expected_candidate_revision,
                expected_candidate_content_sha256,
            )
            selected_text = self._selected_text(str(candidate["content"]), selection)
            lock_rows = self._lock_rows(connection, candidate_id)
            self._require_unlocked(selection, lock_rows)
            connection.execute(
                """
                INSERT INTO chapter_draft_candidate_locks (
                    id, candidate_id, start_char, end_char, locked_text,
                    locked_text_sha256, created_from_version_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lock_id,
                    candidate_id,
                    selection.start_char,
                    selection.end_char,
                    selected_text,
                    selection.selected_text_sha256,
                    str(candidate["version_id"]),
                    timestamp,
                ),
            )
            self._transition(
                connection,
                production,
                ChapterProductionState(str(production["state"])),
                "candidate_range_locked",
                {
                    "candidate_id": candidate_id,
                    "lock_id": lock_id,
                    "start_char": selection.start_char,
                    "end_char": selection.end_char,
                },
                timestamp,
            )
            row = connection.execute(
                "SELECT * FROM chapter_draft_candidate_locks WHERE id = ?", (lock_id,)
            ).fetchone()
        assert row is not None
        return self._parse_lock(row)

    def unlock_selection(
        self,
        *,
        production_id: str,
        candidate_id: str,
        lock_id: str,
        expected_candidate_revision: int,
        expected_candidate_content_sha256: str,
    ) -> None:
        timestamp = now_iso()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            production = self._require_mutable_production(connection, production_id)
            self._require_production_chapter_current(connection, production)
            candidate = self._candidate_row(connection, candidate_id, production_id)
            if candidate is None:
                raise ChapterProductionNotFoundError(candidate_id)
            self._require_candidate_guard(
                candidate,
                expected_candidate_revision,
                expected_candidate_content_sha256,
            )
            deleted = connection.execute(
                "DELETE FROM chapter_draft_candidate_locks WHERE id = ? AND candidate_id = ?",
                (lock_id, candidate_id),
            )
            if deleted.rowcount != 1:
                raise ChapterProductionNotFoundError(lock_id)
            self._transition(
                connection,
                production,
                ChapterProductionState(str(production["state"])),
                "candidate_range_unlocked",
                {"candidate_id": candidate_id, "lock_id": lock_id},
                timestamp,
            )

    def undo_candidate(
        self,
        *,
        production_id: str,
        candidate_id: str,
        expected_candidate_revision: int,
        expected_candidate_content_sha256: str,
        target_version_id: str | None,
    ) -> DraftCandidate:
        timestamp = now_iso()
        new_version_id = str(uuid4())
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            production = self._require_mutable_production(connection, production_id)
            self._require_production_chapter_current(connection, production)
            candidate = self._candidate_row(connection, candidate_id, production_id)
            if candidate is None:
                raise ChapterProductionNotFoundError(candidate_id)
            self._require_candidate_guard(
                candidate,
                expected_candidate_revision,
                expected_candidate_content_sha256,
            )
            resolved_target_id = target_version_id or (
                str(candidate["parent_version_id"])
                if candidate["parent_version_id"] is not None
                else None
            )
            if resolved_target_id is None:
                raise ChapterProductionConflictError("candidate_has_no_undo_version")
            target = connection.execute(
                """
                SELECT * FROM chapter_draft_candidate_versions
                WHERE id = ? AND candidate_id = ? AND revision < ?
                """,
                (resolved_target_id, candidate_id, expected_candidate_revision),
            ).fetchone()
            if target is None:
                raise ChapterProductionConflictError("undo_version_invalid")
            target_content = str(target["content"])
            lock_rows = self._lock_rows(connection, candidate_id)
            relocated = self._relocated_locks(target_content, lock_rows)
            next_revision = expected_candidate_revision + 1
            self._insert_candidate_version(
                connection,
                version_id=new_version_id,
                candidate_id=candidate_id,
                revision=next_revision,
                content=target_content,
                operation=CandidateVersionOperation.UNDO,
                parent_version_id=str(candidate["version_id"]),
                restored_from_version_id=resolved_target_id,
                source_job_id=None,
                trace=None,
                instruction=f"undo:{resolved_target_id}",
                timestamp=timestamp,
            )
            result = connection.execute(
                """
                UPDATE chapter_draft_candidates
                SET current_revision = ?, current_content_sha256 = ?, updated_at = ?
                WHERE id = ? AND state = 'available'
                  AND current_revision = ? AND current_content_sha256 = ?
                """,
                (
                    next_revision,
                    text_sha256(target_content),
                    timestamp,
                    candidate_id,
                    expected_candidate_revision,
                    expected_candidate_content_sha256,
                ),
            )
            if result.rowcount != 1:
                raise ChapterProductionConflictError("candidate_changed")
            for lock_row, start_char, end_char in relocated:
                connection.execute(
                    """
                    UPDATE chapter_draft_candidate_locks
                    SET start_char = ?, end_char = ? WHERE id = ?
                    """,
                    (start_char, end_char, str(lock_row["id"])),
                )
            self._transition(
                connection,
                production,
                ChapterProductionState.CANDIDATE_READY,
                "candidate_undo",
                {
                    "candidate_id": candidate_id,
                    "candidate_version_id": new_version_id,
                    "restored_from_version_id": resolved_target_id,
                },
                timestamp,
            )
            updated = self._candidate_row(connection, candidate_id, production_id)
            assert updated is not None
            updated_locks = self._lock_rows(connection, candidate_id)
        return self._parse_candidate(connection=None, row=updated, locks=updated_locks)

    def merge_candidates(
        self,
        *,
        production_id: str,
        request: MergeCandidatesRequest,
    ) -> DraftCandidate:
        timestamp = now_iso()
        candidate_id = str(uuid4())
        version_id = str(uuid4())
        selected_parts: list[str] = []
        source_rows: list[tuple[MergeSource, Row]] = []
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            production = self._require_mutable_production(connection, production_id)
            self._require_production_chapter_current(connection, production)
            for source in request.sources:
                row = self._candidate_row(connection, source.candidate_id, production_id)
                if row is None:
                    raise ChapterProductionNotFoundError(source.candidate_id)
                self._require_candidate_guard(
                    row,
                    source.candidate_revision,
                    source.candidate_content_sha256,
                )
                if str(row["version_id"]) != source.candidate_version_id:
                    raise ChapterProductionConflictError("merge_source_changed")
                selected = self._selected_text(
                    str(row["content"]),
                    TextSelection(
                        start_char=source.start_char,
                        end_char=source.end_char,
                        selected_text_sha256=source.selected_text_sha256,
                    ),
                )
                selected_parts.append(selected)
                source_rows.append((source, row))
            content = request.separator.join(selected_parts)
            if not content:
                raise ChapterProductionConflictError("candidate_content_empty")
            connection.execute(
                """
                INSERT INTO chapter_draft_candidates (
                    id, production_id, label, state,
                    source_outline_candidate_id, source_outline_version_id,
                    source_outline_revision, source_outline_content_sha256, current_revision,
                    current_content_sha256, created_at, updated_at
                ) VALUES (?, ?, ?, 'available', NULL, NULL, NULL, NULL, 0, ?, ?, ?)
                """,
                (
                    candidate_id,
                    production_id,
                    request.label,
                    text_sha256(content),
                    timestamp,
                    timestamp,
                ),
            )
            self._insert_candidate_version(
                connection,
                version_id=version_id,
                candidate_id=candidate_id,
                revision=0,
                content=content,
                operation=CandidateVersionOperation.MERGE,
                parent_version_id=None,
                restored_from_version_id=None,
                source_job_id=None,
                trace=None,
                instruction="merge",
                timestamp=timestamp,
            )
            for ordinal, (source, _row) in enumerate(source_rows, start=1):
                connection.execute(
                    """
                    INSERT INTO chapter_candidate_merge_sources (
                        result_candidate_id, result_version_id, ordinal,
                        source_candidate_id, source_version_id, source_revision,
                        source_content_sha256, start_char, end_char,
                        selected_text_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate_id,
                        version_id,
                        ordinal,
                        source.candidate_id,
                        source.candidate_version_id,
                        source.candidate_revision,
                        source.candidate_content_sha256,
                        source.start_char,
                        source.end_char,
                        source.selected_text_sha256,
                    ),
                )
            self._transition(
                connection,
                production,
                ChapterProductionState.CANDIDATE_READY,
                "candidates_merged",
                {
                    "candidate_id": candidate_id,
                    "candidate_version_id": version_id,
                    "source_version_ids": [item.candidate_version_id for item in request.sources],
                },
                timestamp,
            )
            row = self._candidate_row(connection, candidate_id, production_id)
        assert row is not None
        return self._parse_candidate(connection=None, row=row, locks=[])

    def list_merge_sources(
        self,
        production_id: str,
        result_candidate_id: str,
    ) -> list[MergeSource]:
        with self.database.connect() as connection:
            if self._candidate_row(connection, result_candidate_id, production_id) is None:
                raise ChapterProductionNotFoundError(result_candidate_id)
            rows = connection.execute(
                """
                SELECT * FROM chapter_candidate_merge_sources
                WHERE result_candidate_id = ? ORDER BY ordinal
                """,
                (result_candidate_id,),
            ).fetchall()
        return [
            MergeSource(
                candidate_id=str(row["source_candidate_id"]),
                candidate_version_id=str(row["source_version_id"]),
                candidate_revision=int(row["source_revision"]),
                candidate_content_sha256=str(row["source_content_sha256"]),
                start_char=int(row["start_char"]),
                end_char=int(row["end_char"]),
                selected_text_sha256=str(row["selected_text_sha256"]),
            )
            for row in rows
        ]

    def save_candidate_review(
        self,
        *,
        production_id: str,
        candidate_id: str,
        expected_candidate_revision: int,
        expected_candidate_content_sha256: str,
        review: CandidateReviewDraft,
        trace: ModelTrace,
        source_job_id: str | None = None,
    ) -> CandidateReview:
        if trace.purpose != CreativeContextPurpose.CANDIDATE_REVIEW:
            raise ValueError("review_requires_candidate_review_context")
        timestamp = now_iso()
        review_id = str(uuid4())
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if source_job_id is not None:
                existing = connection.execute(
                    "SELECT * FROM chapter_candidate_reviews WHERE source_job_id = ?",
                    (source_job_id,),
                ).fetchone()
                if existing is not None:
                    if str(existing["candidate_id"]) != candidate_id:
                        raise ChapterProductionConflictError("job_result_changed")
                    return self._parse_review(existing)
            production = self._require_mutable_production(connection, production_id)
            self._require_production_chapter_current(connection, production)
            candidate = self._candidate_row(connection, candidate_id, production_id)
            if candidate is None:
                raise ChapterProductionNotFoundError(candidate_id)
            self._require_candidate_guard(
                candidate,
                expected_candidate_revision,
                expected_candidate_content_sha256,
            )
            existing = connection.execute(
                """
                SELECT * FROM chapter_candidate_reviews
                WHERE candidate_id = ? AND candidate_version_id = ?
                """,
                (candidate_id, str(candidate["version_id"])),
            ).fetchone()
            if existing is not None:
                return self._parse_review(existing)
            connection.execute(
                """
                INSERT INTO chapter_candidate_reviews (
                    id, candidate_id, candidate_version_id, candidate_revision,
                    candidate_content_sha256, source_job_id, context_purpose, context_packet_id,
                    context_packet_sha256, context_dependency_fingerprint_sha256,
                    context_compiler_version, profile_fingerprint_sha256,
                    provider, model, prompt_version, findings_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    candidate_id,
                    str(candidate["version_id"]),
                    expected_candidate_revision,
                    expected_candidate_content_sha256,
                    source_job_id,
                    trace.purpose.value,
                    trace.context_packet_id,
                    trace.context_packet_sha256,
                    trace.context_dependency_fingerprint_sha256,
                    trace.context_compiler_version,
                    trace.profile_fingerprint_sha256,
                    trace.provider,
                    trace.model,
                    trace.prompt_version,
                    canonical_json(review.model_dump(mode="json")["findings"]),
                    timestamp,
                ),
            )
            self._transition(
                connection,
                production,
                ChapterProductionState.REVIEWED,
                "candidate_reviewed",
                {
                    "candidate_id": candidate_id,
                    "candidate_version_id": str(candidate["version_id"]),
                    "review_id": review_id,
                },
                timestamp,
            )
            row = connection.execute(
                "SELECT * FROM chapter_candidate_reviews WHERE id = ?", (review_id,)
            ).fetchone()
        assert row is not None
        return self._parse_review(row)

    def get_review_for_current_candidate(
        self,
        production_id: str,
        candidate_id: str,
        expected_candidate_revision: int,
        expected_candidate_content_sha256: str,
    ) -> CandidateReview | None:
        with self.database.connect() as connection:
            candidate = self._candidate_row(connection, candidate_id, production_id)
            if candidate is None:
                raise ChapterProductionNotFoundError(candidate_id)
            self._require_candidate_guard(
                candidate,
                expected_candidate_revision,
                expected_candidate_content_sha256,
            )
            row = connection.execute(
                """
                SELECT * FROM chapter_candidate_reviews
                WHERE candidate_id = ? AND candidate_version_id = ?
                """,
                (candidate_id, str(candidate["version_id"])),
            ).fetchone()
        return self._parse_review(row) if row is not None else None

    def get_review_job_result(self, production_id: str, job_id: str) -> CandidateReview:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT cr.* FROM chapter_candidate_reviews cr
                JOIN chapter_draft_candidates dc ON dc.id = cr.candidate_id
                WHERE cr.source_job_id = ? AND dc.production_id = ?
                """,
                (job_id, production_id),
            ).fetchone()
        if row is None:
            raise ChapterProductionNotFoundError(job_id)
        return self._parse_review(row)

    def adopt_candidate(
        self,
        *,
        production_id: str,
        candidate_id: str,
        request: AdoptCandidateRequest,
    ) -> WritingOutcome:
        timestamp = now_iso()
        request_sha256 = canonical_sha256(
            {"candidate_id": candidate_id, "request": request.model_dump(mode="json")}
        )
        outcome_id = str(uuid4())
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._outcome_by_key(connection, production_id, request.idempotency_key)
            if replay is not None:
                self._require_idempotent_replay(replay, request_sha256)
                return self._parse_outcome(replay)
            production = self._require_mutable_production(connection, production_id)
            candidate = self._candidate_row(connection, candidate_id, production_id)
            if candidate is None:
                raise ChapterProductionNotFoundError(candidate_id)
            chapter = self._chapter_row(
                connection,
                str(production["project_id"]),
                str(production["chapter_id"]),
            )
            if chapter["status"] == ChapterStatus.APPROVED.value:
                raise ChapterProductionConflictError("approved_chapter_immutable")
            self._require_candidate_guard(
                candidate,
                request.expected_candidate_revision,
                request.expected_candidate_content_sha256,
            )
            self._require_chapter_guard(
                chapter,
                request.expected_chapter_revision,
                request.expected_chapter_content_sha256,
            )
            self._require_chapter_guard(
                chapter,
                int(production["base_chapter_revision"]),
                str(production["base_chapter_content_sha256"]),
            )
            candidate_content = str(candidate["content"])
            chapter_content = str(chapter["content"])
            if request.mode == AdoptionMode.WHOLE:
                final_content = candidate_content
            else:
                assert request.candidate_selection is not None
                assert request.chapter_selection is not None
                adopted_text = self._selected_text(candidate_content, request.candidate_selection)
                self._selected_text(chapter_content, request.chapter_selection)
                final_content = (
                    chapter_content[: request.chapter_selection.start_char]
                    + adopted_text
                    + chapter_content[request.chapter_selection.end_char :]
                )
            next_revision = request.expected_chapter_revision + 1
            final_digest = text_sha256(final_content)
            chapter_update = connection.execute(
                """
                UPDATE chapters
                SET content = ?, status = 'drafted', revision = ?, updated_at = ?
                WHERE id = ? AND revision = ? AND status != 'approved'
                """,
                (
                    final_content,
                    next_revision,
                    timestamp,
                    str(chapter["id"]),
                    request.expected_chapter_revision,
                ),
            )
            if chapter_update.rowcount != 1:
                raise ChapterProductionConflictError("chapter_changed")
            canonical_version = ReviewRepository.append_chapter_version(
                connection,
                chapter_id=str(chapter["id"]),
                chapter_revision=next_revision,
                content=final_content,
                source=ChapterVersionSource.GENERATION_APPLY,
                source_id=outcome_id,
                created_at=timestamp,
            )
            candidate_update = connection.execute(
                """
                UPDATE chapter_draft_candidates SET state = 'adopted', updated_at = ?
                WHERE id = ? AND state = 'available'
                  AND current_revision = ? AND current_content_sha256 = ?
                """,
                (
                    timestamp,
                    candidate_id,
                    request.expected_candidate_revision,
                    request.expected_candidate_content_sha256,
                ),
            )
            if candidate_update.rowcount != 1:
                raise ChapterProductionConflictError("candidate_changed")
            connection.execute(
                """
                INSERT INTO chapter_writing_outcomes (
                    id, production_id, candidate_id, candidate_version_id,
                    candidate_revision, candidate_content_sha256, decision,
                    source_outline_candidate_id, source_outline_version_id,
                    source_outline_revision, source_outline_content_sha256,
                    adoption_mode, base_chapter_revision, base_chapter_content_sha256,
                    final_chapter_revision, final_chapter_content_sha256,
                    final_chapter_status, chapter_version_id, adoption_detail_json, idempotency_key,
                    request_sha256, reason,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'adopted', ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          'drafted', ?, ?, ?, ?, '', ?)
                """,
                (
                    outcome_id,
                    production_id,
                    candidate_id,
                    str(candidate["version_id"]),
                    request.expected_candidate_revision,
                    request.expected_candidate_content_sha256,
                    candidate["source_outline_candidate_id"],
                    candidate["source_outline_version_id"],
                    candidate["source_outline_revision"],
                    candidate["source_outline_content_sha256"],
                    request.mode.value,
                    request.expected_chapter_revision,
                    request.expected_chapter_content_sha256,
                    next_revision,
                    final_digest,
                    canonical_version.id,
                    canonical_json(
                        {
                            "mode": request.mode.value,
                            "candidate_selection": (
                                request.candidate_selection.model_dump(mode="json")
                                if request.candidate_selection is not None
                                else None
                            ),
                            "chapter_selection": (
                                request.chapter_selection.model_dump(mode="json")
                                if request.chapter_selection is not None
                                else None
                            ),
                        }
                    ),
                    request.idempotency_key,
                    request_sha256,
                    timestamp,
                ),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (timestamp, str(production["project_id"])),
            )
            self._transition(
                connection,
                production,
                ChapterProductionState.ADOPTED,
                "candidate_adopted",
                {
                    "candidate_id": candidate_id,
                    "candidate_version_id": str(candidate["version_id"]),
                    "mode": request.mode.value,
                    "chapter_revision": next_revision,
                },
                timestamp,
            )
            row = connection.execute(
                "SELECT * FROM chapter_writing_outcomes WHERE id = ?", (outcome_id,)
            ).fetchone()
        assert row is not None
        return self._parse_outcome(row)

    def reject_candidate(
        self,
        *,
        production_id: str,
        candidate_id: str,
        request: RejectCandidateRequest,
    ) -> WritingOutcome:
        timestamp = now_iso()
        request_sha256 = canonical_sha256(
            {"candidate_id": candidate_id, "request": request.model_dump(mode="json")}
        )
        outcome_id = str(uuid4())
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._outcome_by_key(connection, production_id, request.idempotency_key)
            if replay is not None:
                self._require_idempotent_replay(replay, request_sha256)
                return self._parse_outcome(replay)
            production = self._require_mutable_production(connection, production_id)
            candidate = self._candidate_row(connection, candidate_id, production_id)
            if candidate is None:
                raise ChapterProductionNotFoundError(candidate_id)
            self._require_candidate_guard(
                candidate,
                request.expected_candidate_revision,
                request.expected_candidate_content_sha256,
            )
            chapter = self._chapter_row(
                connection,
                str(production["project_id"]),
                str(production["chapter_id"]),
            )
            result = connection.execute(
                """
                UPDATE chapter_draft_candidates SET state = 'rejected', updated_at = ?
                WHERE id = ? AND state = 'available'
                  AND current_revision = ? AND current_content_sha256 = ?
                """,
                (
                    timestamp,
                    candidate_id,
                    request.expected_candidate_revision,
                    request.expected_candidate_content_sha256,
                ),
            )
            if result.rowcount != 1:
                raise ChapterProductionConflictError("candidate_changed")
            connection.execute(
                """
                INSERT INTO chapter_writing_outcomes (
                    id, production_id, candidate_id, candidate_version_id,
                    candidate_revision, candidate_content_sha256, decision,
                    source_outline_candidate_id, source_outline_version_id,
                    source_outline_revision, source_outline_content_sha256,
                    adoption_mode, base_chapter_revision, base_chapter_content_sha256,
                    final_chapter_revision, final_chapter_content_sha256,
                    final_chapter_status, chapter_version_id, adoption_detail_json, idempotency_key,
                    request_sha256, reason,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'rejected', ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?,
                          NULL, '{}', ?, ?, ?, ?)
                """,
                (
                    outcome_id,
                    production_id,
                    candidate_id,
                    str(candidate["version_id"]),
                    request.expected_candidate_revision,
                    request.expected_candidate_content_sha256,
                    candidate["source_outline_candidate_id"],
                    candidate["source_outline_version_id"],
                    candidate["source_outline_revision"],
                    candidate["source_outline_content_sha256"],
                    int(production["base_chapter_revision"]),
                    str(production["base_chapter_content_sha256"]),
                    int(chapter["revision"]),
                    text_sha256(str(chapter["content"])),
                    str(chapter["status"]),
                    request.idempotency_key,
                    request_sha256,
                    request.reason,
                    timestamp,
                ),
            )
            remaining = connection.execute(
                """
                SELECT 1 FROM chapter_draft_candidates
                WHERE production_id = ? AND state = 'available' LIMIT 1
                """,
                (production_id,),
            ).fetchone()
            self._transition(
                connection,
                production,
                (
                    ChapterProductionState.CANDIDATE_READY
                    if remaining is not None
                    else ChapterProductionState.REJECTED
                ),
                "candidate_rejected",
                {"candidate_id": candidate_id, "reason": request.reason},
                timestamp,
            )
            row = connection.execute(
                "SELECT * FROM chapter_writing_outcomes WHERE id = ?", (outcome_id,)
            ).fetchone()
        assert row is not None
        return self._parse_outcome(row)

    def get_applied_version(self, outcome_id: str) -> AppliedChapterVersion:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT v.*, o.id AS outcome_id
                FROM chapter_writing_outcomes o
                JOIN chapter_versions v ON v.id = o.chapter_version_id
                WHERE o.id = ? AND o.decision = 'adopted'
                """,
                (outcome_id,),
            ).fetchone()
        if row is None:
            raise ChapterProductionNotFoundError(outcome_id)
        return AppliedChapterVersion(
            id=str(row["id"]),
            chapter_id=str(row["chapter_id"]),
            chapter_revision=int(row["chapter_revision"]),
            content=str(row["content"]),
            content_sha256=str(row["content_sha256"]),
            outcome_id=str(row["outcome_id"]),
            created_at=str(row["created_at"]),
        )

    def get_snapshot(self, production_id: str) -> ProductionSnapshot:
        """Pure read: it never repairs, materializes, or changes revisions."""

        with self.database.connect() as connection:
            production_row = self._production_row(connection, production_id)
            if production_row is None:
                raise ChapterProductionNotFoundError(production_id)
            outline_rows = connection.execute(
                """
                SELECT oc.*, ov.id AS version_id, ov.content_json,
                       ov.content_sha256, ov.operation, ov.parent_version_id,
                       ov.source_job_id,
                       ov.context_purpose, ov.context_packet_id,
                       ov.context_packet_sha256,
                       ov.context_dependency_fingerprint_sha256,
                       ov.context_compiler_version, ov.profile_fingerprint_sha256,
                       ov.provider, ov.model, ov.prompt_version,
                       ov.created_at AS version_created_at
                FROM chapter_outline_candidates oc
                JOIN chapter_outline_candidate_versions ov
                  ON ov.candidate_id = oc.id AND ov.revision = oc.current_revision
                WHERE oc.production_id = ? ORDER BY oc.ordinal
                """,
                (production_id,),
            ).fetchall()
            candidate_rows = connection.execute(
                self._CANDIDATE_SELECT
                + " WHERE dc.production_id = ? ORDER BY dc.created_at, dc.id",
                (production_id,),
            ).fetchall()
            all_lock_rows = connection.execute(
                """
                SELECT locks.* FROM chapter_draft_candidate_locks locks
                JOIN chapter_draft_candidates dc ON dc.id = locks.candidate_id
                WHERE dc.production_id = ? ORDER BY locks.start_char, locks.id
                """,
                (production_id,),
            ).fetchall()
            preflight_rows = connection.execute(
                """
                SELECT * FROM chapter_preflight_checks
                WHERE production_id = ? ORDER BY created_at, id
                """,
                (production_id,),
            ).fetchall()
            review_rows = connection.execute(
                """
                SELECT cr.* FROM chapter_candidate_reviews cr
                JOIN chapter_draft_candidates dc ON dc.id = cr.candidate_id
                WHERE dc.production_id = ? ORDER BY cr.created_at, cr.id
                """,
                (production_id,),
            ).fetchall()
            outcome_rows = connection.execute(
                """
                SELECT * FROM chapter_writing_outcomes
                WHERE production_id = ? ORDER BY created_at, id
                """,
                (production_id,),
            ).fetchall()
        locks_by_candidate: dict[str, list[Row]] = {}
        for lock_row in all_lock_rows:
            locks_by_candidate.setdefault(str(lock_row["candidate_id"]), []).append(lock_row)
        return ProductionSnapshot(
            production=self._parse_production(production_row),
            outlines=[self._parse_outline(row) for row in outline_rows],
            candidates=[
                self._parse_candidate(
                    connection=None,
                    row=row,
                    locks=locks_by_candidate.get(str(row["id"]), []),
                )
                for row in candidate_rows
            ],
            preflight_checks=[self._parse_preflight(row) for row in preflight_rows],
            reviews=[self._parse_review(row) for row in review_rows],
            outcomes=[self._parse_outcome(row) for row in outcome_rows],
        )

    def list_events(self, production_id: str) -> list[ProductionEvent]:
        with self.database.connect() as connection:
            if self._production_row(connection, production_id) is None:
                raise ChapterProductionNotFoundError(production_id)
            rows = connection.execute(
                """
                SELECT * FROM chapter_production_events
                WHERE production_id = ? ORDER BY sequence
                """,
                (production_id,),
            ).fetchall()
        return [self._parse_event(row) for row in rows]

    _CANDIDATE_SELECT = """
        SELECT dc.*, dv.id AS version_id, dv.content,
               dv.operation, dv.parent_version_id, dv.restored_from_version_id,
               dv.source_job_id,
               dv.context_purpose, dv.context_packet_id, dv.context_packet_sha256,
               dv.context_dependency_fingerprint_sha256,
               dv.context_compiler_version, dv.profile_fingerprint_sha256,
               dv.provider, dv.model, dv.prompt_version, dv.instruction,
               dv.created_at AS version_created_at
        FROM chapter_draft_candidates dc
        JOIN chapter_draft_candidate_versions dv
          ON dv.candidate_id = dc.id AND dv.revision = dc.current_revision
    """

    @staticmethod
    def _chapter_row(connection: Connection, project_id: str, chapter_id: str) -> Row:
        row = connection.execute(
            "SELECT * FROM chapters WHERE id = ? AND project_id = ?",
            (chapter_id, project_id),
        ).fetchone()
        if row is None:
            raise ChapterProductionNotFoundError(chapter_id)
        return cast(Row, row)

    @staticmethod
    def _production_row(connection: Connection, production_id: str) -> Row | None:
        return cast(
            Row | None,
            connection.execute(
                "SELECT * FROM chapter_productions WHERE id = ?", (production_id,)
            ).fetchone(),
        )

    def _require_mutable_production(
        self,
        connection: Connection,
        production_id: str,
    ) -> Row:
        row = self._production_row(connection, production_id)
        if row is None:
            raise ChapterProductionNotFoundError(production_id)
        if row["state"] in {
            ChapterProductionState.ADOPTED.value,
            ChapterProductionState.REJECTED.value,
        }:
            raise ChapterProductionConflictError("production_closed")
        return row

    @classmethod
    def _require_production_chapter_current(
        cls,
        connection: Connection,
        production: Row,
    ) -> Row:
        chapter = cls._chapter_row(
            connection,
            str(production["project_id"]),
            str(production["chapter_id"]),
        )
        if chapter["status"] == ChapterStatus.APPROVED.value:
            raise ChapterProductionConflictError("approved_chapter_immutable")
        cls._require_chapter_guard(
            chapter,
            int(production["base_chapter_revision"]),
            str(production["base_chapter_content_sha256"]),
        )
        return chapter

    @staticmethod
    def _require_chapter_guard(
        chapter: Row,
        expected_revision: int,
        expected_content_sha256: str,
    ) -> None:
        if (
            int(chapter["revision"]) != expected_revision
            or text_sha256(str(chapter["content"])) != expected_content_sha256
        ):
            raise ChapterProductionConflictError("chapter_changed")

    @staticmethod
    def _require_outline_guard(
        row: Row,
        expected_revision: int,
        expected_content_sha256: str,
    ) -> None:
        if (
            row["state"] != CandidateState.AVAILABLE.value
            or int(row["current_revision"]) != expected_revision
            or str(row["current_content_sha256"]) != expected_content_sha256
        ):
            raise ChapterProductionConflictError("outline_candidate_changed")

    @staticmethod
    def _require_candidate_guard(
        row: Row,
        expected_revision: int,
        expected_content_sha256: str,
    ) -> None:
        if (
            row["state"] != CandidateState.AVAILABLE.value
            or int(row["current_revision"]) != expected_revision
            or str(row["current_content_sha256"]) != expected_content_sha256
        ):
            raise ChapterProductionConflictError("candidate_changed")

    @staticmethod
    def _selected_text(
        content: str,
        selection: TextSelection | EditableTextSelection,
    ) -> str:
        if selection.end_char > len(content):
            raise ChapterProductionConflictError("selection_out_of_bounds")
        selected = content[selection.start_char : selection.end_char]
        if text_sha256(selected) != selection.selected_text_sha256:
            raise ChapterProductionConflictError("selection_changed")
        return selected

    @staticmethod
    def _require_unlocked(
        selection: TextSelection | EditableTextSelection,
        lock_rows: list[Row],
    ) -> None:
        for lock in lock_rows:
            if selection.start_char < int(lock["end_char"]) and selection.end_char > int(
                lock["start_char"]
            ):
                raise LockedSelectionError("selection_locked")

    @staticmethod
    def _shift_locks(
        connection: Connection,
        lock_rows: list[Row],
        selection: TextSelection | EditableTextSelection,
        delta: int,
    ) -> None:
        if delta == 0:
            return
        for lock in lock_rows:
            if selection.end_char <= int(lock["start_char"]):
                connection.execute(
                    """
                    UPDATE chapter_draft_candidate_locks
                    SET start_char = start_char + ?, end_char = end_char + ?
                    WHERE id = ?
                    """,
                    (delta, delta, str(lock["id"])),
                )

    @staticmethod
    def _relocated_locks(
        target_content: str,
        lock_rows: list[Row],
    ) -> list[tuple[Row, int, int]]:
        relocated: list[tuple[Row, int, int]] = []
        for lock in lock_rows:
            locked_text = str(lock["locked_text"])
            start = target_content.find(locked_text)
            if start < 0 or target_content.find(locked_text, start + 1) >= 0:
                raise LockedSelectionError("locked_text_cannot_be_relocated")
            if text_sha256(locked_text) != str(lock["locked_text_sha256"]):
                raise LockedSelectionError("locked_text_corrupted")
            relocated.append((lock, start, start + len(locked_text)))
        return relocated

    @staticmethod
    def _outcome_by_key(
        connection: Connection,
        production_id: str,
        idempotency_key: str,
    ) -> Row | None:
        return cast(
            Row | None,
            connection.execute(
                """
                SELECT * FROM chapter_writing_outcomes
                WHERE production_id = ? AND idempotency_key = ?
                """,
                (production_id, idempotency_key),
            ).fetchone(),
        )

    @staticmethod
    def _require_idempotent_replay(row: Row, request_sha256: str) -> None:
        if str(row["request_sha256"]) != request_sha256:
            raise ChapterProductionConflictError("idempotency_key_reused")

    @staticmethod
    def _outline_row(
        connection: Connection,
        candidate_id: str,
        production_id: str | None = None,
    ) -> Row | None:
        clause = "AND oc.production_id = ?" if production_id is not None else ""
        parameters: tuple[object, ...] = (
            (candidate_id, production_id) if production_id is not None else (candidate_id,)
        )
        return cast(
            Row | None,
            connection.execute(
                f"""
                SELECT oc.*, ov.id AS version_id, ov.content_json,
                       ov.content_sha256, ov.operation, ov.parent_version_id,
                       ov.source_job_id,
                       ov.context_purpose, ov.context_packet_id,
                       ov.context_packet_sha256,
                       ov.context_dependency_fingerprint_sha256,
                       ov.context_compiler_version, ov.profile_fingerprint_sha256,
                       ov.provider, ov.model, ov.prompt_version,
                       ov.created_at AS version_created_at
                FROM chapter_outline_candidates oc
                JOIN chapter_outline_candidate_versions ov
                  ON ov.candidate_id = oc.id AND ov.revision = oc.current_revision
                WHERE oc.id = ? {clause}
                """,
                parameters,
            ).fetchone(),
        )

    @classmethod
    def _outline_by_source_job(cls, connection: Connection, source_job_id: str) -> Row | None:
        row = connection.execute(
            "SELECT candidate_id FROM chapter_outline_candidate_versions WHERE source_job_id = ?",
            (source_job_id,),
        ).fetchone()
        return (
            cls._outline_row(connection, str(row["candidate_id"]))
            if row is not None
            else None
        )

    @classmethod
    def _candidate_row(
        cls,
        connection: Connection,
        candidate_id: str,
        production_id: str | None = None,
    ) -> Row | None:
        clause = "AND dc.production_id = ?" if production_id is not None else ""
        parameters: tuple[object, ...] = (
            (candidate_id, production_id) if production_id is not None else (candidate_id,)
        )
        return cast(
            Row | None,
            connection.execute(
                cls._CANDIDATE_SELECT + f" WHERE dc.id = ? {clause}", parameters
            ).fetchone(),
        )

    @classmethod
    def _candidate_by_source_job(cls, connection: Connection, source_job_id: str) -> Row | None:
        row = connection.execute(
            "SELECT candidate_id FROM chapter_draft_candidate_versions WHERE source_job_id = ?",
            (source_job_id,),
        ).fetchone()
        return (
            cls._candidate_row(connection, str(row["candidate_id"]))
            if row is not None
            else None
        )

    @staticmethod
    def _lock_rows(connection: Connection, candidate_id: str) -> list[Row]:
        return cast(
            list[Row],
            connection.execute(
                """
                SELECT * FROM chapter_draft_candidate_locks
                WHERE candidate_id = ? ORDER BY start_char, id
                """,
                (candidate_id,),
            ).fetchall(),
        )

    @staticmethod
    def _insert_candidate_version(
        connection: Connection,
        *,
        version_id: str,
        candidate_id: str,
        revision: int,
        content: str,
        operation: CandidateVersionOperation,
        parent_version_id: str | None,
        restored_from_version_id: str | None,
        source_job_id: str | None,
        trace: ModelTrace | None,
        instruction: str,
        timestamp: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO chapter_draft_candidate_versions (
                id, candidate_id, revision, content, content_sha256, operation,
                parent_version_id, restored_from_version_id, source_job_id, context_purpose,
                context_packet_id, context_packet_sha256,
                context_dependency_fingerprint_sha256, context_compiler_version,
                profile_fingerprint_sha256, provider, model, prompt_version,
                instruction, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                candidate_id,
                revision,
                content,
                text_sha256(content),
                operation.value,
                parent_version_id,
                restored_from_version_id,
                source_job_id,
                trace.purpose.value if trace is not None else None,
                trace.context_packet_id if trace is not None else None,
                trace.context_packet_sha256 if trace is not None else None,
                (trace.context_dependency_fingerprint_sha256 if trace is not None else None),
                trace.context_compiler_version if trace is not None else None,
                trace.profile_fingerprint_sha256 if trace is not None else None,
                trace.provider if trace is not None else None,
                trace.model if trace is not None else None,
                trace.prompt_version if trace is not None else None,
                instruction,
                timestamp,
            ),
        )

    @staticmethod
    def _append_event(
        connection: Connection,
        *,
        production_id: str,
        event_type: str,
        from_state: ChapterProductionState | None,
        to_state: ChapterProductionState,
        detail: dict[str, object],
        timestamp: str,
    ) -> None:
        sequence = int(
            connection.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) + 1
                FROM chapter_production_events WHERE production_id = ?
                """,
                (production_id,),
            ).fetchone()[0]
        )
        connection.execute(
            """
            INSERT INTO chapter_production_events (
                id, production_id, sequence, event_type, from_state,
                to_state, detail_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                production_id,
                sequence,
                event_type,
                from_state.value if from_state is not None else None,
                to_state.value,
                canonical_json(detail),
                timestamp,
            ),
        )

    @classmethod
    def _transition(
        cls,
        connection: Connection,
        production: Row,
        to_state: ChapterProductionState,
        event_type: str,
        detail: dict[str, object],
        timestamp: str,
    ) -> None:
        from_state = ChapterProductionState(str(production["state"]))
        if from_state == ChapterProductionState.ADOPTED and to_state != from_state:
            raise ChapterProductionConflictError("production_already_adopted")
        result = connection.execute(
            """
            UPDATE chapter_productions
            SET state = ?, revision = revision + 1, updated_at = ?
            WHERE id = ? AND revision = ? AND state = ?
            """,
            (
                to_state.value,
                timestamp,
                str(production["id"]),
                int(production["revision"]),
                from_state.value,
            ),
        )
        if result.rowcount != 1:
            raise ChapterProductionConflictError("production_changed")
        cls._append_event(
            connection,
            production_id=str(production["id"]),
            event_type=event_type,
            from_state=from_state,
            to_state=to_state,
            detail=detail,
            timestamp=timestamp,
        )

    @staticmethod
    def _parse_trace(row: Row) -> ModelTrace | None:
        purpose = row["context_purpose"]
        if purpose is None:
            return None
        return ModelTrace(
            purpose=CreativeContextPurpose(str(purpose)),
            context_packet_id=str(row["context_packet_id"]),
            context_packet_sha256=str(row["context_packet_sha256"]),
            context_dependency_fingerprint_sha256=str(row["context_dependency_fingerprint_sha256"]),
            context_compiler_version=str(row["context_compiler_version"]),
            profile_fingerprint_sha256=(
                str(row["profile_fingerprint_sha256"])
                if row["profile_fingerprint_sha256"] is not None
                else None
            ),
            provider=str(row["provider"]),
            model=str(row["model"]),
            prompt_version=str(row["prompt_version"]),
        )

    @staticmethod
    def _parse_production(row: Row) -> ChapterProduction:
        return ChapterProduction(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            chapter_id=str(row["chapter_id"]),
            base_chapter_revision=int(row["base_chapter_revision"]),
            base_chapter_content_sha256=str(row["base_chapter_content_sha256"]),
            state=ChapterProductionState(str(row["state"])),
            revision=int(row["revision"]),
            current_outline_candidate_id=(
                str(row["current_outline_candidate_id"])
                if row["current_outline_candidate_id"] is not None
                else None
            ),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @classmethod
    def _parse_outline(cls, row: Row) -> OutlineCandidate:
        trace = cls._parse_trace(row)
        return OutlineCandidate(
            id=str(row["id"]),
            production_id=str(row["production_id"]),
            ordinal=int(row["ordinal"]),
            label=str(row["label"]),
            state=CandidateState(str(row["state"])),
            current_version=OutlineCandidateVersion(
                id=str(row["version_id"]),
                candidate_id=str(row["id"]),
                revision=int(row["current_revision"]),
                content=ChapterOutline.model_validate_json(str(row["content_json"])),
                content_sha256=str(row["current_content_sha256"]),
                operation=OutlineVersionOperation(str(row["operation"])),
                parent_version_id=(
                    str(row["parent_version_id"])
                    if row["parent_version_id"] is not None
                    else None
                ),
                trace=trace,
                source_job_id=(
                    str(row["source_job_id"])
                    if row["source_job_id"] is not None
                    else None
                ),
                created_at=str(row["version_created_at"]),
            ),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @classmethod
    def _parse_candidate_version(cls, row: Row) -> DraftCandidateVersion:
        return DraftCandidateVersion(
            id=str(row["id"]),
            candidate_id=str(row["candidate_id"]),
            revision=int(row["revision"]),
            content=str(row["content"]),
            content_sha256=str(row["content_sha256"]),
            operation=CandidateVersionOperation(str(row["operation"])),
            parent_version_id=(
                str(row["parent_version_id"]) if row["parent_version_id"] is not None else None
            ),
            restored_from_version_id=(
                str(row["restored_from_version_id"])
                if row["restored_from_version_id"] is not None
                else None
            ),
            trace=cls._parse_trace(row),
            source_job_id=(
                str(row["source_job_id"]) if row["source_job_id"] is not None else None
            ),
            instruction=str(row["instruction"]),
            created_at=str(row["created_at"]),
        )

    @classmethod
    def _parse_candidate(
        cls,
        *,
        connection: Connection | None,
        row: Row,
        locks: list[Row] | None = None,
    ) -> DraftCandidate:
        lock_rows = locks
        if lock_rows is None:
            if connection is None:
                raise ValueError("candidate_locks_not_loaded")
            lock_rows = cls._lock_rows(connection, str(row["id"]))
        version = DraftCandidateVersion(
            id=str(row["version_id"]),
            candidate_id=str(row["id"]),
            revision=int(row["current_revision"]),
            content=str(row["content"]),
            content_sha256=str(row["current_content_sha256"]),
            operation=CandidateVersionOperation(str(row["operation"])),
            parent_version_id=(
                str(row["parent_version_id"]) if row["parent_version_id"] is not None else None
            ),
            restored_from_version_id=(
                str(row["restored_from_version_id"])
                if row["restored_from_version_id"] is not None
                else None
            ),
            trace=cls._parse_trace(row),
            source_job_id=(
                str(row["source_job_id"]) if row["source_job_id"] is not None else None
            ),
            instruction=str(row["instruction"]),
            created_at=str(row["version_created_at"]),
        )
        return DraftCandidate(
            id=str(row["id"]),
            production_id=str(row["production_id"]),
            label=str(row["label"]),
            state=CandidateState(str(row["state"])),
            source_outline_candidate_id=(
                str(row["source_outline_candidate_id"])
                if row["source_outline_candidate_id"] is not None
                else None
            ),
            source_outline_version_id=(
                str(row["source_outline_version_id"])
                if row["source_outline_version_id"] is not None
                else None
            ),
            source_outline_revision=(
                int(row["source_outline_revision"])
                if row["source_outline_revision"] is not None
                else None
            ),
            source_outline_content_sha256=(
                str(row["source_outline_content_sha256"])
                if row["source_outline_content_sha256"] is not None
                else None
            ),
            current_version=version,
            locks=[cls._parse_lock(lock) for lock in lock_rows],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _parse_preflight(row: Row) -> PreflightCheck:
        return PreflightCheck(
            id=str(row["id"]),
            production_id=str(row["production_id"]),
            outline_candidate_id=str(row["outline_candidate_id"]),
            outline_version_id=str(row["outline_version_id"]),
            outline_revision=int(row["outline_revision"]),
            outline_content_sha256=str(row["outline_content_sha256"]),
            reader_promise=bool(row["reader_promise"]),
            opening_hook=bool(row["opening_hook"]),
            state_change=bool(row["state_change"]),
            emotional_payoff=bool(row["emotional_payoff"]),
            ending_cliffhanger=bool(row["ending_cliffhanger"]),
            missing_fields=cast(list[str], json.loads(str(row["missing_fields_json"]))),
            passed=bool(row["passed"]),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _parse_lock(row: Row) -> CandidateLock:
        return CandidateLock(
            id=str(row["id"]),
            candidate_id=str(row["candidate_id"]),
            start_char=int(row["start_char"]),
            end_char=int(row["end_char"]),
            locked_text=str(row["locked_text"]),
            locked_text_sha256=str(row["locked_text_sha256"]),
            created_from_version_id=str(row["created_from_version_id"]),
            created_at=str(row["created_at"]),
        )

    @classmethod
    def _parse_review(cls, row: Row) -> CandidateReview:
        trace = cls._parse_trace(row)
        assert trace is not None
        draft = CandidateReviewDraft.model_validate(
            {"findings": json.loads(str(row["findings_json"]))}
        )
        return CandidateReview(
            id=str(row["id"]),
            candidate_id=str(row["candidate_id"]),
            candidate_version_id=str(row["candidate_version_id"]),
            candidate_revision=int(row["candidate_revision"]),
            candidate_content_sha256=str(row["candidate_content_sha256"]),
            trace=trace,
            source_job_id=(
                str(row["source_job_id"]) if row["source_job_id"] is not None else None
            ),
            findings=draft.findings,
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _parse_outcome(row: Row) -> WritingOutcome:
        return WritingOutcome(
            id=str(row["id"]),
            production_id=str(row["production_id"]),
            candidate_id=str(row["candidate_id"]),
            candidate_version_id=str(row["candidate_version_id"]),
            candidate_revision=int(row["candidate_revision"]),
            candidate_content_sha256=str(row["candidate_content_sha256"]),
            source_outline_candidate_id=(
                str(row["source_outline_candidate_id"])
                if row["source_outline_candidate_id"] is not None
                else None
            ),
            source_outline_version_id=(
                str(row["source_outline_version_id"])
                if row["source_outline_version_id"] is not None
                else None
            ),
            source_outline_revision=(
                int(row["source_outline_revision"])
                if row["source_outline_revision"] is not None
                else None
            ),
            source_outline_content_sha256=(
                str(row["source_outline_content_sha256"])
                if row["source_outline_content_sha256"] is not None
                else None
            ),
            decision=WritingDecision(str(row["decision"])),
            adoption_mode=(
                AdoptionMode(str(row["adoption_mode"]))
                if row["adoption_mode"] is not None
                else None
            ),
            base_chapter_revision=int(row["base_chapter_revision"]),
            base_chapter_content_sha256=str(row["base_chapter_content_sha256"]),
            final_chapter_revision=int(row["final_chapter_revision"]),
            final_chapter_content_sha256=str(row["final_chapter_content_sha256"]),
            final_chapter_status=ChapterStatus(str(row["final_chapter_status"])),
            chapter_version_id=(
                str(row["chapter_version_id"])
                if row["chapter_version_id"] is not None
                else None
            ),
            adoption_detail=cast(
                dict[str, object], json.loads(str(row["adoption_detail_json"]))
            ),
            idempotency_key=str(row["idempotency_key"]),
            reason=str(row["reason"]),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _parse_event(row: Row) -> ProductionEvent:
        return ProductionEvent(
            id=str(row["id"]),
            production_id=str(row["production_id"]),
            sequence=int(row["sequence"]),
            event_type=str(row["event_type"]),
            from_state=(
                ChapterProductionState(str(row["from_state"]))
                if row["from_state"] is not None
                else None
            ),
            to_state=ChapterProductionState(str(row["to_state"])),
            detail=cast(dict[str, object], json.loads(str(row["detail_json"]))),
            created_at=str(row["created_at"]),
        )
