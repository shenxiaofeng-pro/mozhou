from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from sqlite3 import Connection, Row
from typing import cast
from uuid import uuid4

from app.canon_reconciliation.models import (
    CANON_PAYLOAD_MODELS,
    AdoptRollingPlanReplenishmentRequest,
    ApprovalTransactionResult,
    AuthorPreference,
    AuthorPreferenceCandidate,
    AuthorPreferenceCandidateDraft,
    AuthorPreferenceDimension,
    AuthorPreferenceState,
    CandidateDecisionAction,
    CanonCandidateState,
    CanonConflict,
    CanonDecisionBatchRequest,
    CanonDecisionBatchResult,
    CanonDeltaCandidate,
    CanonDeltaCandidateDraft,
    CanonEvidence,
    CanonKind,
    CanonPayload,
    CanonReconciliation,
    CanonReconciliationSnapshot,
    CanonReconciliationState,
    CanonRecord,
    ChapterApproval,
    CharacterStatePayload,
    FutureKnowledgePayload,
    PreferenceCandidateState,
    PreferenceScopeKind,
    ReconciliationAnalysis,
    RejectRollingPlanReplenishmentRequest,
    RelationshipPayload,
    ResourceStatePayload,
    RollingPlanReplenishment,
    RollingPlanReplenishmentDraft,
    RollingPlanReplenishmentState,
    StoryThreadPayload,
    TimelineEventPayload,
)
from app.database import Database
from app.models import ChapterStatus, ChapterVersionSource
from app.review.repository import ReviewRepository

CANON_RECONCILIATION_WORKFLOW = "canon_reconciliation_v1"
CANON_RECONCILIATION_MODEL = "typed-reconciliation-v1"


class CanonReconciliationNotFoundError(LookupError):
    pass


class CanonReconciliationConflictError(RuntimeError):
    pass


class CanonReconciliationStaleError(CanonReconciliationConflictError):
    pass


class CanonReconciliationSourceChangedError(CanonReconciliationStaleError):
    """The approved chapter snapshot changed, so every remaining candidate is unsafe."""


class CanonEvidenceError(ValueError):
    pass


class CanonDecisionIdempotencyError(CanonReconciliationConflictError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def text_sha256(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def canonical_sha256(value: object) -> str:
    return text_sha256(canonical_json(value))


def _load_json_object(value: str) -> dict[str, object]:
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise TypeError("持久化的 JSON 不是对象")
    return cast(dict[str, object], loaded)


def _load_json_list(value: str) -> list[object]:
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        raise TypeError("持久化的 JSON 不是列表")
    return cast(list[object], loaded)


class CanonReconciliationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def approve_chapter_and_enqueue(
        self,
        *,
        project_id: str,
        chapter_id: str,
        expected_revision: int,
        expected_content_sha256: str,
        source_writing_outcome_id: str | None = None,
    ) -> ApprovalTransactionResult:
        """Approve final author text and enqueue its local reconciliation atomically."""

        timestamp = _now()
        approval_id = str(uuid4())
        job_id = str(uuid4())
        reconciliation_id = str(uuid4())
        new_revision = expected_revision + 1
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            chapter = connection.execute(
                "SELECT * FROM chapters WHERE id = ? AND project_id = ?",
                (chapter_id, project_id),
            ).fetchone()
            if chapter is None:
                raise CanonReconciliationNotFoundError(chapter_id)
            if int(chapter["revision"]) != expected_revision:
                raise CanonReconciliationStaleError(str(chapter["revision"]))
            content = str(chapter["content"])
            content_digest = text_sha256(content)
            if content_digest != expected_content_sha256:
                raise CanonReconciliationStaleError("chapter_content_changed")
            if chapter["status"] != ChapterStatus.REVIEWING.value:
                raise CanonReconciliationConflictError(
                    f"invalid_chapter_state:{chapter['status']}"
                )
            if not content.strip():
                raise CanonReconciliationConflictError("empty_content")
            if not all(
                str(chapter[field]).strip()
                for field in ("opening_hook", "state_change", "ending_cliffhanger")
            ):
                raise CanonReconciliationConflictError("incomplete_brief")

            outcome_id = self._resolve_writing_outcome(
                connection,
                chapter_id=chapter_id,
                source_writing_outcome_id=source_writing_outcome_id,
            )
            updated = connection.execute(
                """
                UPDATE chapters
                SET status = ?, revision = ?, updated_at = ?
                WHERE id = ? AND project_id = ? AND revision = ? AND status = ?
                """,
                (
                    ChapterStatus.APPROVED.value,
                    new_revision,
                    timestamp,
                    chapter_id,
                    project_id,
                    expected_revision,
                    ChapterStatus.REVIEWING.value,
                ),
            )
            if updated.rowcount != 1:
                raise CanonReconciliationStaleError("chapter_changed_during_approval")
            connection.execute(
                """
                INSERT INTO chapter_events (
                    id, chapter_id, from_status, to_status, revision, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    chapter_id,
                    ChapterStatus.REVIEWING.value,
                    ChapterStatus.APPROVED.value,
                    new_revision,
                    timestamp,
                ),
            )
            version = ReviewRepository.append_chapter_version(
                connection,
                chapter_id=chapter_id,
                chapter_revision=new_revision,
                content=content,
                source=ChapterVersionSource.APPROVAL,
                source_id=approval_id,
                created_at=timestamp,
            )
            connection.execute(
                """
                INSERT INTO chapter_approvals (
                    id, project_id, chapter_id, chapter_revision,
                    chapter_content_sha256, chapter_version_id,
                    source_writing_outcome_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval_id,
                    project_id,
                    chapter_id,
                    new_revision,
                    content_digest,
                    version.id,
                    outcome_id,
                    timestamp,
                ),
            )
            input_payload = {
                "schema_version": 1,
                "approval_id": approval_id,
                "chapter_version_id": version.id,
                "chapter_revision": new_revision,
                "chapter_content_sha256": content_digest,
            }
            job_idempotency_key = (
                f"canon-reconciliation:{chapter_id}:{new_revision}:{content_digest}"
            )
            connection.execute(
                """
                INSERT INTO jobs (
                    id, project_id, chapter_id, parent_job_id, kind, workflow,
                    state, idempotency_key, input_json, progress_total,
                    estimated_calls, provider, provider_profile_id, model,
                    created_at, updated_at
                ) VALUES (?, ?, ?, NULL, 'review', ?, 'queued', ?, ?, 1, 0,
                          'local', NULL, ?, ?, ?)
                """,
                (
                    job_id,
                    project_id,
                    chapter_id,
                    CANON_RECONCILIATION_WORKFLOW,
                    job_idempotency_key,
                    canonical_json(input_payload),
                    CANON_RECONCILIATION_MODEL,
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO job_events (
                    id, job_id, sequence, event_type, from_state, to_state,
                    detail_json, created_at
                ) VALUES (?, ?, 1, 'created', NULL, 'queued', '{}', ?)
                """,
                (str(uuid4()), job_id, timestamp),
            )
            connection.execute(
                """
                INSERT INTO canon_reconciliations (
                    id, approval_id, project_id, chapter_id, job_id, state,
                    revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)
                """,
                (
                    reconciliation_id,
                    approval_id,
                    project_id,
                    chapter_id,
                    job_id,
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (timestamp, project_id),
            )
            approval_row = connection.execute(
                "SELECT * FROM chapter_approvals WHERE id = ?", (approval_id,)
            ).fetchone()
            reconciliation_row = connection.execute(
                "SELECT * FROM canon_reconciliations WHERE id = ?",
                (reconciliation_id,),
            ).fetchone()
            assert approval_row is not None and reconciliation_row is not None
            return ApprovalTransactionResult(
                approval=self._approval(approval_row),
                reconciliation=self._reconciliation(reconciliation_row),
                job_id=job_id,
                chapter_revision=new_revision,
                chapter_content_sha256=content_digest,
            )

    @staticmethod
    def _resolve_writing_outcome(
        connection: Connection,
        *,
        chapter_id: str,
        source_writing_outcome_id: str | None,
    ) -> str | None:
        if source_writing_outcome_id is None:
            row = connection.execute(
                """
                SELECT outcome.id
                FROM chapter_writing_outcomes outcome
                JOIN chapter_productions production
                  ON production.id = outcome.production_id
                WHERE production.chapter_id = ? AND outcome.decision = 'adopted'
                ORDER BY outcome.created_at DESC, outcome.id DESC LIMIT 1
                """,
                (chapter_id,),
            ).fetchone()
            return str(row["id"]) if row is not None else None
        row = connection.execute(
            """
            SELECT outcome.id
            FROM chapter_writing_outcomes outcome
            JOIN chapter_productions production
              ON production.id = outcome.production_id
            WHERE outcome.id = ? AND production.chapter_id = ?
              AND outcome.decision = 'adopted'
            """,
            (source_writing_outcome_id, chapter_id),
        ).fetchone()
        if row is None:
            raise CanonReconciliationConflictError("invalid_writing_outcome")
        return str(row["id"])

    def get_approval(self, approval_id: str) -> ChapterApproval:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM chapter_approvals WHERE id = ?", (approval_id,)
            ).fetchone()
        if row is None:
            raise CanonReconciliationNotFoundError(approval_id)
        return self._approval(row)

    def get_reconciliation(self, reconciliation_id: str) -> CanonReconciliation:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM canon_reconciliations WHERE id = ?",
                (reconciliation_id,),
            ).fetchone()
        if row is None:
            raise CanonReconciliationNotFoundError(reconciliation_id)
        return self._reconciliation(row)

    def get_reconciliation_by_job(self, job_id: str) -> CanonReconciliation:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM canon_reconciliations WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise CanonReconciliationNotFoundError(job_id)
        return self._reconciliation(row)

    def get_latest_snapshot(
        self,
        *,
        project_id: str,
        chapter_id: str,
    ) -> CanonReconciliationSnapshot:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM canon_reconciliations
                WHERE project_id = ? AND chapter_id = ?
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (project_id, chapter_id),
            ).fetchone()
            if row is None:
                raise CanonReconciliationNotFoundError(chapter_id)
            return self._snapshot(connection, row)

    def persist_analysis(
        self,
        reconciliation_id: str,
        analysis: ReconciliationAnalysis,
    ) -> CanonReconciliationSnapshot:
        timestamp = _now()
        analysis_digest = canonical_sha256(analysis.model_dump(mode="json"))
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            reconciliation = connection.execute(
                "SELECT * FROM canon_reconciliations WHERE id = ?",
                (reconciliation_id,),
            ).fetchone()
            if reconciliation is None:
                raise CanonReconciliationNotFoundError(reconciliation_id)
            if reconciliation["state"] != CanonReconciliationState.PENDING.value:
                if reconciliation["analysis_sha256"] == analysis_digest:
                    return self._snapshot(connection, reconciliation)
                raise CanonReconciliationConflictError("reconciliation_already_materialized")
            approval = connection.execute(
                """
                SELECT approval.*, version.content AS approved_content
                FROM chapter_approvals approval
                JOIN chapter_versions version ON version.id = approval.chapter_version_id
                WHERE approval.id = ?
                """,
                (reconciliation["approval_id"],),
            ).fetchone()
            if approval is None:
                raise CanonReconciliationNotFoundError(str(reconciliation["approval_id"]))
            self._validate_candidate_set(
                connection,
                approval=approval,
                project_id=str(reconciliation["project_id"]),
                candidates=analysis.canon_candidates,
            )
            for preference_candidate in analysis.preference_candidates:
                self._validate_preference_scope(
                    connection,
                    project_id=str(reconciliation["project_id"]),
                    scope_kind=preference_candidate.scope_kind,
                    scope_value=preference_candidate.scope_value,
                )
                self._validate_preference_source(
                    connection, approval, preference_candidate
                )

            for ordinal, candidate in enumerate(analysis.canon_candidates, start=1):
                self._insert_canon_candidate(
                    connection,
                    reconciliation_id=reconciliation_id,
                    project_id=str(reconciliation["project_id"]),
                    ordinal=ordinal,
                    candidate=candidate,
                    timestamp=timestamp,
                )
            for ordinal, preference_candidate in enumerate(
                analysis.preference_candidates, start=1
            ):
                self._insert_preference_candidate(
                    connection,
                    reconciliation_id=reconciliation_id,
                    project_id=str(reconciliation["project_id"]),
                    ordinal=ordinal,
                    candidate=preference_candidate,
                    timestamp=timestamp,
                )
            has_candidates = bool(
                analysis.canon_candidates or analysis.preference_candidates
            )
            target_state = (
                CanonReconciliationState.READY
                if has_candidates
                else CanonReconciliationState.DECIDED
            )
            connection.execute(
                """
                UPDATE canon_reconciliations
                SET state = ?, revision = revision + 1,
                    context_packet_id = ?, context_packet_sha256 = ?,
                    context_dependency_fingerprint_sha256 = ?, analysis_sha256 = ?,
                    preference_skip_reason = ?, error_message = NULL,
                    updated_at = ?, completed_at = ?
                WHERE id = ? AND state = 'pending'
                """,
                (
                    target_state.value,
                    analysis.context_packet_id,
                    analysis.context_packet_sha256,
                    analysis.context_dependency_fingerprint_sha256,
                    analysis_digest,
                    analysis.preference_skip_reason,
                    timestamp,
                    None if has_candidates else timestamp,
                    reconciliation_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM canon_reconciliations WHERE id = ?",
                (reconciliation_id,),
            ).fetchone()
            assert updated is not None
            return self._snapshot(connection, updated)

    @staticmethod
    def _validate_candidate_set(
        connection: Connection,
        *,
        approval: Row,
        project_id: str,
        candidates: list[CanonDeltaCandidateDraft],
    ) -> None:
        identities = [(item.kind.value, item.subject_key.casefold()) for item in candidates]
        if len(set(identities)) != len(identities):
            raise CanonReconciliationConflictError("duplicate_canon_candidate")
        for candidate in candidates:
            CanonReconciliationRepository._validate_evidence(approval, candidate.evidence)
            for conflict in candidate.conflicts:
                if conflict.existing_record_id is None:
                    continue
                found = connection.execute(
                    "SELECT 1 FROM canon_records WHERE id = ? AND project_id = ?",
                    (conflict.existing_record_id, project_id),
                ).fetchone()
                if found is None:
                    raise CanonReconciliationConflictError("cross_project_canon_conflict")

    @staticmethod
    def _validate_evidence(approval: Row, evidence: CanonEvidence) -> None:
        if (
            evidence.approval_version_id != approval["chapter_version_id"]
            or evidence.chapter_id != approval["chapter_id"]
            or evidence.chapter_revision != approval["chapter_revision"]
            or evidence.chapter_content_sha256 != approval["chapter_content_sha256"]
        ):
            raise CanonEvidenceError("候选证据不属于当前定稿")
        content = str(approval["approved_content"])
        if text_sha256(content) != approval["chapter_content_sha256"]:
            raise CanonEvidenceError("定稿版本指纹无效")
        if evidence.end_char > len(content):
            raise CanonEvidenceError("候选证据超出定稿范围")
        if content[evidence.start_char : evidence.end_char] != evidence.excerpt:
            raise CanonEvidenceError("候选证据与定稿原文不一致")
        if text_sha256(evidence.excerpt) != evidence.excerpt_sha256:
            raise CanonEvidenceError("候选证据摘录指纹无效")

    @staticmethod
    def _validate_preference_source(
        connection: Connection,
        approval: Row,
        candidate: AuthorPreferenceCandidateDraft,
    ) -> None:
        if candidate.final_content_sha256 != approval["chapter_content_sha256"]:
            raise CanonEvidenceError("偏好候选的定稿指纹不一致")
        source = connection.execute(
            """
            SELECT outcome.*, production.chapter_id,
                   version.content_sha256 AS source_version_content_sha256
            FROM chapter_writing_outcomes outcome
            JOIN chapter_productions production ON production.id = outcome.production_id
            JOIN chapter_draft_candidate_versions version
              ON version.id = outcome.candidate_version_id
            WHERE outcome.id = ? AND outcome.candidate_version_id = ?
            """,
            (
                candidate.source_writing_outcome_id,
                candidate.source_candidate_version_id,
            ),
        ).fetchone()
        if source is None:
            raise CanonReconciliationConflictError("preference_source_not_found")
        if (
            source["chapter_id"] != approval["chapter_id"]
            or source["decision"] != "adopted"
            or source["adoption_mode"] != "whole"
            or source["candidate_content_sha256"] != candidate.candidate_content_sha256
            or source["source_version_content_sha256"]
            != candidate.candidate_content_sha256
        ):
            raise CanonReconciliationConflictError("preference_source_not_eligible")
        ancestry = connection.execute(
            """
            WITH RECURSIVE ancestry(id, parent_version_id) AS (
                SELECT id, parent_version_id FROM chapter_versions WHERE id = ?
                UNION ALL
                SELECT version.id, version.parent_version_id
                FROM chapter_versions version
                JOIN ancestry ON version.id = ancestry.parent_version_id
            )
            SELECT 1 FROM ancestry WHERE id = ? LIMIT 1
            """,
            (approval["chapter_version_id"], source["chapter_version_id"]),
        ).fetchone()
        if ancestry is None:
            raise CanonReconciliationConflictError("preference_source_not_in_ancestry")

    @staticmethod
    def _insert_canon_candidate(
        connection: Connection,
        *,
        reconciliation_id: str,
        project_id: str,
        ordinal: int,
        candidate: CanonDeltaCandidateDraft,
        timestamp: str,
    ) -> None:
        payload = candidate.payload.model_dump(mode="json")
        evidence = candidate.evidence.model_dump(mode="json")
        connection.execute(
            """
            INSERT INTO canon_delta_candidates (
                id, reconciliation_id, project_id, ordinal, kind,
                subject_key, summary, payload_json, payload_sha256,
                evidence_json, evidence_sha256, conflicts_json,
                state, revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'candidate', 0, ?, ?)
            """,
            (
                str(uuid4()),
                reconciliation_id,
                project_id,
                ordinal,
                candidate.kind.value,
                candidate.subject_key,
                candidate.summary,
                canonical_json(payload),
                canonical_sha256(payload),
                canonical_json(evidence),
                canonical_sha256(evidence),
                canonical_json(
                    [item.model_dump(mode="json") for item in candidate.conflicts]
                ),
                timestamp,
                timestamp,
            ),
        )

    @staticmethod
    def _insert_preference_candidate(
        connection: Connection,
        *,
        reconciliation_id: str,
        project_id: str,
        ordinal: int,
        candidate: AuthorPreferenceCandidateDraft,
        timestamp: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO author_preference_candidates (
                id, reconciliation_id, project_id, ordinal,
                scope_kind, scope_value, dimension, compact_rule,
                rule_sha256, confidence, comparison_metrics_json,
                source_writing_outcome_id, source_candidate_version_id,
                candidate_content_sha256, final_content_sha256,
                state, revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      'candidate', 0, ?, ?)
            """,
            (
                str(uuid4()),
                reconciliation_id,
                project_id,
                ordinal,
                candidate.scope_kind.value,
                candidate.scope_value,
                candidate.dimension.value,
                candidate.compact_rule,
                text_sha256(candidate.compact_rule),
                candidate.confidence,
                canonical_json(candidate.comparison_metrics),
                candidate.source_writing_outcome_id,
                candidate.source_candidate_version_id,
                candidate.candidate_content_sha256,
                candidate.final_content_sha256,
                timestamp,
                timestamp,
            ),
        )

    def decide_batch(
        self,
        *,
        project_id: str,
        request: CanonDecisionBatchRequest,
    ) -> CanonDecisionBatchResult:
        """Apply edits, rejections and accepted ledger changes in one transaction."""

        timestamp = _now()
        request_payload = request.model_dump(mode="json")
        request_digest = canonical_sha256(request_payload)
        batch_id = str(uuid4())
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = connection.execute(
                """
                SELECT * FROM canon_decision_batches
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, request.idempotency_key),
            ).fetchone()
            if replay is not None:
                if replay["request_sha256"] != request_digest:
                    raise CanonDecisionIdempotencyError(
                        "same_idempotency_key_different_request"
                    )
                result = CanonDecisionBatchResult.model_validate_json(
                    str(replay["response_json"])
                )
                return result.model_copy(update={"replayed": True})

            reconciliation = connection.execute(
                """
                SELECT * FROM canon_reconciliations
                WHERE id = ? AND project_id = ?
                """,
                (request.reconciliation_id, project_id),
            ).fetchone()
            if reconciliation is None:
                raise CanonReconciliationNotFoundError(request.reconciliation_id)
            if reconciliation["state"] != CanonReconciliationState.READY.value:
                raise CanonReconciliationConflictError(
                    f"invalid_reconciliation_state:{reconciliation['state']}"
                )
            if int(reconciliation["revision"]) != request.expected_reconciliation_revision:
                raise CanonReconciliationStaleError(str(reconciliation["revision"]))
            approval = connection.execute(
                "SELECT * FROM chapter_approvals WHERE id = ?",
                (reconciliation["approval_id"],),
            ).fetchone()
            assert approval is not None
            chapter = connection.execute(
                """
                SELECT status, revision, content FROM chapters
                WHERE id = ? AND project_id = ? AND deleted_at IS NULL
                """,
                (approval["chapter_id"], project_id),
            ).fetchone()
            if (
                chapter is None
                or chapter["status"] != ChapterStatus.APPROVED.value
                or int(chapter["revision"]) != int(approval["chapter_revision"])
                or text_sha256(str(chapter["content"]))
                != approval["chapter_content_sha256"]
            ):
                raise CanonReconciliationSourceChangedError(
                    "chapter_changed_after_reconciliation"
                )

            accepted_record_ids: list[str] = []
            confirmed_preference_ids: list[str] = []
            rejected_candidate_ids: list[str] = []
            for decision in request.canon_decisions:
                record_id, rejected = self._apply_canon_decision(
                    connection,
                    project_id=project_id,
                    reconciliation_id=request.reconciliation_id,
                    source_chapter_id=str(approval["chapter_id"]),
                    candidate_id=decision.candidate_id,
                    expected_revision=decision.expected_revision,
                    action=decision.action,
                    edited_subject_key=decision.edited_subject_key,
                    edited_summary=decision.edited_summary,
                    edited_payload=decision.edited_payload,
                    rejection_reason=decision.rejection_reason,
                    timestamp=timestamp,
                )
                if record_id is not None and record_id not in accepted_record_ids:
                    accepted_record_ids.append(record_id)
                if rejected:
                    rejected_candidate_ids.append(decision.candidate_id)
            for preference_decision in request.preference_decisions:
                preference_id, rejected = self._apply_preference_decision(
                    connection,
                    project_id=project_id,
                    reconciliation_id=request.reconciliation_id,
                    approval_id=str(approval["id"]),
                    candidate_id=preference_decision.candidate_id,
                    expected_revision=preference_decision.expected_revision,
                    action=preference_decision.action,
                    edited_scope_kind=preference_decision.edited_scope_kind,
                    edited_scope_value=preference_decision.edited_scope_value,
                    edited_dimension=preference_decision.edited_dimension,
                    edited_compact_rule=preference_decision.edited_compact_rule,
                    edited_confidence=preference_decision.edited_confidence,
                    rejection_reason=preference_decision.rejection_reason,
                    timestamp=timestamp,
                )
                if preference_id is not None and preference_id not in confirmed_preference_ids:
                    confirmed_preference_ids.append(preference_id)
                if rejected:
                    rejected_candidate_ids.append(preference_decision.candidate_id)

            remaining = int(
                connection.execute(
                    """
                    SELECT (
                        SELECT COUNT(*) FROM canon_delta_candidates
                        WHERE reconciliation_id = ? AND state = 'candidate'
                    ) + (
                        SELECT COUNT(*) FROM author_preference_candidates
                        WHERE reconciliation_id = ? AND state = 'candidate'
                    )
                    """,
                    (request.reconciliation_id, request.reconciliation_id),
                ).fetchone()[0]
            )
            target_state = (
                CanonReconciliationState.READY
                if remaining
                else CanonReconciliationState.DECIDED
            )
            analysis_digest = self._current_analysis_sha256(connection, reconciliation)
            next_revision = request.expected_reconciliation_revision + 1
            updated = connection.execute(
                """
                UPDATE canon_reconciliations
                SET state = ?, revision = ?, analysis_sha256 = ?,
                    updated_at = ?, completed_at = ?
                WHERE id = ? AND project_id = ? AND revision = ? AND state = 'ready'
                """,
                (
                    target_state.value,
                    next_revision,
                    analysis_digest,
                    timestamp,
                    timestamp if target_state == CanonReconciliationState.DECIDED else None,
                    request.reconciliation_id,
                    project_id,
                    request.expected_reconciliation_revision,
                ),
            )
            if updated.rowcount != 1:
                raise CanonReconciliationStaleError("reconciliation_changed")
            rolling = connection.execute(
                """
                SELECT id FROM rolling_plan_replenishments
                WHERE reconciliation_id = ?
                """,
                (request.reconciliation_id,),
            ).fetchone()
            result = CanonDecisionBatchResult(
                batch_id=batch_id,
                reconciliation_id=request.reconciliation_id,
                reconciliation_revision=next_revision,
                accepted_canon_record_ids=accepted_record_ids,
                confirmed_preference_ids=confirmed_preference_ids,
                rejected_candidate_ids=rejected_candidate_ids,
                rolling_plan_replenishment_id=(
                    str(rolling["id"]) if rolling is not None else None
                ),
            )
            connection.execute(
                """
                INSERT INTO canon_decision_batches (
                    id, project_id, reconciliation_id, idempotency_key,
                    request_sha256, response_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    project_id,
                    request.reconciliation_id,
                    request.idempotency_key,
                    request_digest,
                    result.model_dump_json(),
                    timestamp,
                ),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (timestamp, project_id),
            )
            return result

    def list_accepted_canon_record_ids(
        self,
        *,
        project_id: str,
        reconciliation_id: str,
    ) -> list[str]:
        """Return every Canon record accepted across all decision batches."""

        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT accepted_record_id
                FROM canon_delta_candidates
                WHERE project_id = ? AND reconciliation_id = ?
                  AND state = 'accepted' AND accepted_record_id IS NOT NULL
                ORDER BY ordinal ASC, id ASC
                """,
                (project_id, reconciliation_id),
            ).fetchall()
        return [str(row["accepted_record_id"]) for row in rows]

    def _apply_canon_decision(
        self,
        connection: Connection,
        *,
        project_id: str,
        reconciliation_id: str,
        source_chapter_id: str,
        candidate_id: str,
        expected_revision: int,
        action: CandidateDecisionAction,
        edited_subject_key: str | None,
        edited_summary: str | None,
        edited_payload: CanonPayload | None,
        rejection_reason: str | None,
        timestamp: str,
    ) -> tuple[str | None, bool]:
        row = connection.execute(
            """
            SELECT * FROM canon_delta_candidates
            WHERE id = ? AND reconciliation_id = ? AND project_id = ?
            """,
            (candidate_id, reconciliation_id, project_id),
        ).fetchone()
        if row is None:
            raise CanonReconciliationNotFoundError(candidate_id)
        if row["state"] != CanonCandidateState.CANDIDATE.value:
            raise CanonReconciliationConflictError("canon_candidate_already_decided")
        if int(row["revision"]) != expected_revision:
            raise CanonReconciliationStaleError(str(row["revision"]))
        kind = CanonKind(row["kind"])
        if action == CandidateDecisionAction.EDIT:
            assert edited_subject_key is not None
            assert edited_summary is not None
            assert edited_payload is not None
            if not isinstance(edited_payload, CANON_PAYLOAD_MODELS[kind]):
                raise CanonReconciliationConflictError("edited_payload_kind_mismatch")
            subject_key = edited_subject_key
            summary = edited_summary
            payload = edited_payload
        else:
            subject_key = str(row["subject_key"])
            summary = str(row["summary"])
            payload = self._payload(kind, str(row["payload_json"]))
        if action == CandidateDecisionAction.REJECT:
            assert rejection_reason is not None
            connection.execute(
                """
                UPDATE canon_delta_candidates
                SET state = 'rejected', revision = revision + 1,
                    rejection_reason = ?, updated_at = ?, decided_at = ?
                WHERE id = ? AND revision = ? AND state = 'candidate'
                """,
                (
                    rejection_reason,
                    timestamp,
                    timestamp,
                    candidate_id,
                    expected_revision,
                ),
            )
            return None, True
        self._require_current_canon_record_snapshot(
            connection,
            project_id=project_id,
            kind=kind,
            original_subject_key=str(row["subject_key"]),
            target_subject_key=subject_key,
            conflicts=[
                CanonConflict.model_validate(item)
                for item in _load_json_list(str(row["conflicts_json"]))
            ],
        )
        record_id = self._materialize_canon_record(
            connection,
            project_id=project_id,
            source_chapter_id=source_chapter_id,
            candidate_id=candidate_id,
            kind=kind,
            subject_key=subject_key,
            payload=payload,
            timestamp=timestamp,
        )
        connection.execute(
            """
            UPDATE canon_delta_candidates
            SET subject_key = ?, summary = ?, payload_json = ?,
                payload_sha256 = ?, state = 'accepted', revision = revision + 1,
                accepted_record_id = ?, updated_at = ?, decided_at = ?
            WHERE id = ? AND revision = ? AND state = 'candidate'
            """,
            (
                subject_key,
                summary,
                canonical_json(payload.model_dump(mode="json")),
                canonical_sha256(payload.model_dump(mode="json")),
                record_id,
                timestamp,
                timestamp,
                candidate_id,
                expected_revision,
            ),
        )
        return record_id, False

    @staticmethod
    def _require_current_canon_record_snapshot(
        connection: Connection,
        *,
        project_id: str,
        kind: CanonKind,
        original_subject_key: str,
        target_subject_key: str,
        conflicts: list[CanonConflict],
    ) -> None:
        """Reject a decision when its target Canon changed after extraction.

        SQLite's write lock serialises decisions but cannot by itself detect that
        an older READY reconciliation observed an earlier Canon revision.  New
        candidates carry that revision and payload hash in their existing JSON
        conflict envelope.  Legacy candidates remain readable; when they lack a
        trustworthy snapshot they may only create an identity that is still absent.
        """

        active_rows = connection.execute(
            """
            SELECT id, subject_key, payload_sha256, revision
            FROM canon_records
            WHERE project_id = ? AND kind = ? AND state = 'active'
            """,
            (project_id, kind.value),
        ).fetchall()
        target_key = target_subject_key.casefold()
        current = [
            row
            for row in active_rows
            if str(row["subject_key"]).casefold() == target_key
        ]
        same_identity = original_subject_key.casefold() == target_key
        expected = (
            [item for item in conflicts if item.existing_record_id is not None]
            if same_identity
            else []
        )
        if not expected:
            if current:
                raise CanonReconciliationStaleError(
                    "canon_record_changed_after_reconciliation"
                )
            return
        if len(expected) != 1:
            raise CanonReconciliationStaleError("ambiguous_canon_record_snapshot")
        snapshot = expected[0]
        if (
            snapshot.existing_record_revision is None
            or snapshot.existing_record_payload_sha256 is None
            or len(current) != 1
            or str(current[0]["id"]) != snapshot.existing_record_id
            or int(current[0]["revision"]) != snapshot.existing_record_revision
            or str(current[0]["payload_sha256"])
            != snapshot.existing_record_payload_sha256
        ):
            raise CanonReconciliationStaleError(
                "canon_record_changed_after_reconciliation"
            )

    def _materialize_canon_record(
        self,
        connection: Connection,
        *,
        project_id: str,
        source_chapter_id: str,
        candidate_id: str,
        kind: CanonKind,
        subject_key: str,
        payload: CanonPayload,
        timestamp: str,
    ) -> str:
        payload_value = payload.model_dump(mode="json")
        payload_json = canonical_json(payload_value)
        payload_digest = canonical_sha256(payload_value)
        active_rows = connection.execute(
            """
            SELECT * FROM canon_records
            WHERE project_id = ? AND kind = ? AND state = 'active'
            """,
            (project_id, kind.value),
        ).fetchall()
        matching = [
            row
            for row in active_rows
            if str(row["subject_key"]).casefold() == subject_key.casefold()
        ]
        if len(matching) > 1:
            raise CanonReconciliationStaleError("ambiguous_canon_record_identity")
        existing = matching[0] if matching else None
        if existing is None:
            record_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO canon_records (
                    id, project_id, kind, subject_key, payload_json,
                    payload_sha256, revision, state, source_candidate_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 'active', ?, ?, ?)
                """,
                (
                    record_id,
                    project_id,
                    kind.value,
                    subject_key,
                    payload_json,
                    payload_digest,
                    candidate_id,
                    timestamp,
                    timestamp,
                ),
            )
        else:
            record_id = str(existing["id"])
            connection.execute(
                """
                UPDATE canon_records
                SET payload_json = ?, payload_sha256 = ?, revision = revision + 1,
                    source_candidate_id = ?, updated_at = ?
                WHERE id = ? AND state = 'active'
                """,
                (payload_json, payload_digest, candidate_id, timestamp, record_id),
            )
        self._project_canon_record(
            connection,
            project_id=project_id,
            source_chapter_id=source_chapter_id,
            kind=kind,
            payload=payload,
            timestamp=timestamp,
        )
        return record_id

    def _project_canon_record(
        self,
        connection: Connection,
        *,
        project_id: str,
        source_chapter_id: str,
        kind: CanonKind,
        payload: CanonPayload,
        timestamp: str,
    ) -> None:
        if kind == CanonKind.CHARACTER_STATE:
            assert isinstance(payload, CharacterStatePayload)
            entity_id = self._ensure_story_entity(
                connection,
                project_id=project_id,
                entity_kind="character",
                name=payload.character_name,
                timestamp=timestamp,
            )
            connection.execute(
                """
                UPDATE story_entities
                SET current_state = ?, relationship_notes = ?,
                    revision = revision + 1, updated_at = ?
                WHERE id = ? AND project_id = ?
                """,
                (payload.state, payload.change, timestamp, entity_id, project_id),
            )
            return
        if kind == CanonKind.RESOURCE_STATE:
            assert isinstance(payload, ResourceStatePayload)
            entity_id = self._ensure_story_entity(
                connection,
                project_id=project_id,
                entity_kind="resource",
                name=payload.resource_name,
                timestamp=timestamp,
            )
            notes = "；".join(
                item
                for item in (
                    f"归属：{payload.owner_name}" if payload.owner_name else "",
                    f"变化：{payload.delta}",
                )
                if item
            )
            connection.execute(
                """
                UPDATE story_entities
                SET current_state = ?, relationship_notes = ?,
                    revision = revision + 1, updated_at = ?
                WHERE id = ? AND project_id = ?
                """,
                (payload.state, notes[:1_000], timestamp, entity_id, project_id),
            )
            return
        if kind == CanonKind.RELATIONSHIP:
            assert isinstance(payload, RelationshipPayload)
            source_id = self._ensure_story_entity(
                connection,
                project_id=project_id,
                entity_kind="character",
                name=payload.source_name,
                timestamp=timestamp,
            )
            target_id = self._ensure_story_entity(
                connection,
                project_id=project_id,
                entity_kind="character",
                name=payload.target_name,
                timestamp=timestamp,
            )
            existing = connection.execute(
                """
                SELECT id FROM story_relationships
                WHERE project_id = ? AND source_entity_id = ?
                  AND target_entity_id = ? AND relation_type = ? AND status = 'active'
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (project_id, source_id, target_id, payload.relation_type),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO story_relationships (
                        id, project_id, source_entity_id, target_entity_id,
                        relation_type, summary, status, source_chapter_id,
                        revision, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, 0, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        project_id,
                        source_id,
                        target_id,
                        payload.relation_type,
                        payload.summary,
                        source_chapter_id,
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE story_relationships
                    SET summary = ?, source_chapter_id = ?, revision = revision + 1,
                        updated_at = ? WHERE id = ? AND project_id = ?
                    """,
                    (
                        payload.summary,
                        source_chapter_id,
                        timestamp,
                        existing["id"],
                        project_id,
                    ),
                )
            return
        if kind == CanonKind.FUTURE_KNOWLEDGE:
            assert isinstance(payload, FutureKnowledgePayload)
            if payload.event_year is None:
                return
            existing = connection.execute(
                """
                SELECT id FROM future_knowledge
                WHERE project_id = ? AND future_year = ? AND content = ?
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (project_id, payload.event_year, payload.knowledge),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO future_knowledge (
                        id, project_id, future_year, content, source_note,
                        confidence, status, divergence_event_id, revision,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'valid', NULL, 0, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        project_id,
                        payload.event_year,
                        payload.knowledge,
                        payload.holder_name,
                        payload.confidence,
                        timestamp,
                        timestamp,
                    ),
                )
            return
        if kind == CanonKind.STORY_THREAD:
            assert isinstance(payload, StoryThreadPayload)
            chapter = connection.execute(
                "SELECT chapter_number FROM chapters WHERE id = ? AND project_id = ?",
                (source_chapter_id, project_id),
            ).fetchone()
            assert chapter is not None
            existing = connection.execute(
                """
                SELECT id FROM story_threads
                WHERE project_id = ? AND source_chapter_id = ? AND title = ?
                """,
                (project_id, source_chapter_id, payload.title),
            ).fetchone()
            resolved_chapter_id = (
                source_chapter_id if payload.status == "resolved" else None
            )
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO story_threads (
                        id, project_id, source_chapter_id, title, summary,
                        status, planted_chapter_number, resolved_chapter_id,
                        revision, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        project_id,
                        source_chapter_id,
                        payload.title,
                        payload.summary,
                        payload.status,
                        chapter["chapter_number"],
                        resolved_chapter_id,
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE story_threads
                    SET summary = ?, status = ?, resolved_chapter_id = ?,
                        revision = revision + 1, updated_at = ?
                    WHERE id = ? AND project_id = ?
                    """,
                    (
                        payload.summary,
                        payload.status,
                        resolved_chapter_id,
                        timestamp,
                        existing["id"],
                        project_id,
                    ),
                )
            return
        if kind == CanonKind.TIMELINE_EVENT:
            assert isinstance(payload, TimelineEventPayload)
            if payload.event_year is None:
                return
            existing = connection.execute(
                """
                SELECT id FROM timeline_events
                WHERE project_id = ? AND layer = ? AND event_year = ?
                  AND title = ? AND source_chapter_id = ?
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (
                    project_id,
                    payload.layer.value,
                    payload.event_year,
                    payload.title,
                    source_chapter_id,
                ),
            ).fetchone()
            if existing is None:
                event_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO timeline_events (
                        id, project_id, layer, event_year, title, summary,
                        source_chapter_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        project_id,
                        payload.layer.value,
                        payload.event_year,
                        payload.title,
                        payload.summary,
                        source_chapter_id,
                        timestamp,
                    ),
                )
            else:
                event_id = str(existing["id"])
                connection.execute(
                    "UPDATE timeline_events SET summary = ? WHERE id = ?",
                    (payload.summary, event_id),
                )
            if payload.layer.value == "novel":
                connection.execute(
                    """
                    UPDATE future_knowledge
                    SET status = 'candidate_invalid', divergence_event_id = ?,
                        revision = revision + 1, updated_at = ?
                    WHERE project_id = ? AND future_year >= ? AND status = 'valid'
                    """,
                    (event_id, timestamp, project_id, payload.event_year),
                )

    @staticmethod
    def _ensure_story_entity(
        connection: Connection,
        *,
        project_id: str,
        entity_kind: str,
        name: str,
        timestamp: str,
    ) -> str:
        rows = connection.execute(
            """
            SELECT id, name FROM story_entities
            WHERE project_id = ? AND kind = ?
            ORDER BY created_at, id
            """,
            (project_id, entity_kind),
        ).fetchall()
        matching = [
            row for row in rows if str(row["name"]).casefold() == name.casefold()
        ]
        if len(matching) > 1:
            raise CanonReconciliationStaleError("ambiguous_story_entity_identity")
        if matching:
            return str(matching[0]["id"])
        entity_id = str(uuid4())
        connection.execute(
            """
            INSERT INTO story_entities (
                id, project_id, kind, name, role, goal, current_state,
                relationship_notes, revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, '', '', '', '', 0, ?, ?)
            """,
            (entity_id, project_id, entity_kind, name, timestamp, timestamp),
        )
        return entity_id

    def get_author_preference(
        self,
        *,
        project_id: str,
        preference_id: str,
    ) -> AuthorPreference:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM author_preferences
                WHERE id = ? AND project_id = ?
                """,
                (preference_id, project_id),
            ).fetchone()
        if row is None:
            raise CanonReconciliationNotFoundError(preference_id)
        return self._author_preference(row)

    def delete_author_preference(
        self,
        *,
        project_id: str,
        preference_id: str,
        expected_revision: int,
    ) -> AuthorPreference:
        timestamp = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM author_preferences
                WHERE id = ? AND project_id = ?
                """,
                (preference_id, project_id),
            ).fetchone()
            if row is None:
                raise CanonReconciliationNotFoundError(preference_id)
            if row["state"] != AuthorPreferenceState.ACTIVE.value:
                raise CanonReconciliationConflictError("preference_already_deleted")
            if int(row["revision"]) != expected_revision:
                raise CanonReconciliationStaleError(str(row["revision"]))
            updated = connection.execute(
                """
                UPDATE author_preferences
                SET state = 'deleted', revision = revision + 1, updated_at = ?
                WHERE id = ? AND project_id = ? AND revision = ? AND state = 'active'
                """,
                (timestamp, preference_id, project_id, expected_revision),
            )
            if updated.rowcount != 1:
                raise CanonReconciliationStaleError("preference_changed")
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (timestamp, project_id),
            )
            result = connection.execute(
                "SELECT * FROM author_preferences WHERE id = ?", (preference_id,)
            ).fetchone()
            assert result is not None
            return self._author_preference(result)

    def create_rolling_plan_replenishment(
        self,
        *,
        project_id: str,
        reconciliation_id: str,
        draft: RollingPlanReplenishmentDraft,
    ) -> RollingPlanReplenishment:
        timestamp = _now()
        plan_values = [plan.model_dump(mode="json") for plan in draft.plans]
        plans_digest = canonical_sha256(plan_values)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            reconciliation = connection.execute(
                """
                SELECT * FROM canon_reconciliations
                WHERE id = ? AND project_id = ?
                """,
                (reconciliation_id, project_id),
            ).fetchone()
            if reconciliation is None:
                raise CanonReconciliationNotFoundError(reconciliation_id)
            existing = connection.execute(
                """
                SELECT * FROM rolling_plan_replenishments
                WHERE reconciliation_id = ?
                """,
                (reconciliation_id,),
            ).fetchone()
            if existing is not None:
                parsed = self._rolling_plan(existing)
                if (
                    parsed.plans_sha256 != plans_digest
                    or parsed.source_chapter_id != draft.source_chapter_id
                    or parsed.source_canon_record_ids
                    != draft.source_canon_record_ids
                ):
                    raise CanonReconciliationConflictError(
                        "rolling_replenishment_already_exists"
                    )
                return parsed
            if draft.source_chapter_id != reconciliation["chapter_id"]:
                raise CanonReconciliationConflictError("rolling_source_chapter_mismatch")
            if not draft.source_canon_record_ids:
                raise CanonReconciliationConflictError("rolling_source_canon_required")
            if not self._rolling_source_canon_is_current(
                connection,
                project_id=project_id,
                reconciliation_id=reconciliation_id,
                record_ids=draft.source_canon_record_ids,
            ):
                raise CanonReconciliationConflictError("rolling_source_canon_invalid")
            if draft.source_decision_batch_id is not None:
                batch = connection.execute(
                    """
                    SELECT 1 FROM canon_decision_batches
                    WHERE id = ? AND project_id = ? AND reconciliation_id = ?
                    """,
                    (draft.source_decision_batch_id, project_id, reconciliation_id),
                ).fetchone()
                if batch is None:
                    raise CanonReconciliationConflictError("rolling_source_batch_invalid")
            self._validate_rolling_dependencies(connection, project_id, draft)
            chapter_numbers = [plan.chapter_number for plan in draft.plans]
            if len(set(chapter_numbers)) != len(chapter_numbers):
                raise CanonReconciliationConflictError("duplicate_rolling_chapter_number")
            protected = set(draft.protected_chapter_numbers)
            if any(number in protected for number in chapter_numbers):
                raise CanonReconciliationConflictError("rolling_target_is_protected")
            for chapter_number in chapter_numbers:
                conflict = connection.execute(
                    """
                    SELECT 1 FROM rolling_chapter_plans
                    WHERE project_id = ? AND chapter_number = ?
                    UNION ALL
                    SELECT 1 FROM chapters
                    WHERE project_id = ? AND chapter_number = ?
                    LIMIT 1
                    """,
                    (project_id, chapter_number, project_id, chapter_number),
                ).fetchone()
                if conflict is not None:
                    raise CanonReconciliationConflictError(
                        f"rolling_target_exists:{chapter_number}"
                    )
            state = (
                RollingPlanReplenishmentState.CANDIDATE
                if draft.plans
                else RollingPlanReplenishmentState.NOT_NEEDED
            )
            replenishment_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO rolling_plan_replenishments (
                    id, project_id, reconciliation_id, source_decision_batch_id,
                    source_chapter_id, source_canon_record_ids_json, state,
                    revision, volume_plan_id, base_blueprint_id,
                    base_blueprint_revision, base_blueprint_content_sha256,
                    protected_chapter_numbers_json, plans_json, plans_sha256,
                    blocked_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    replenishment_id,
                    project_id,
                    reconciliation_id,
                    draft.source_decision_batch_id,
                    draft.source_chapter_id,
                    canonical_json(draft.source_canon_record_ids),
                    state.value,
                    draft.volume_plan_id,
                    draft.base_blueprint_id,
                    draft.base_blueprint_revision,
                    draft.base_blueprint_content_sha256,
                    canonical_json(draft.protected_chapter_numbers),
                    canonical_json(plan_values),
                    plans_digest,
                    draft.blocked_reason,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                "SELECT * FROM rolling_plan_replenishments WHERE id = ?",
                (replenishment_id,),
            ).fetchone()
            assert row is not None
            return self._rolling_plan(row)

    @staticmethod
    def _validate_rolling_dependencies(
        connection: Connection,
        project_id: str,
        draft: RollingPlanReplenishmentDraft,
    ) -> None:
        if draft.volume_plan_id is not None:
            volume = connection.execute(
                "SELECT 1 FROM volume_plans WHERE id = ? AND project_id = ?",
                (draft.volume_plan_id, project_id),
            ).fetchone()
            if volume is None:
                raise CanonReconciliationConflictError("rolling_volume_plan_invalid")
        if draft.base_blueprint_id is None:
            return
        blueprint = connection.execute(
            """
            SELECT content_json, revision FROM book_blueprints
            WHERE id = ? AND project_id = ?
            """,
            (draft.base_blueprint_id, project_id),
        ).fetchone()
        if blueprint is None:
            raise CanonReconciliationConflictError("rolling_blueprint_invalid")
        content_digest = canonical_sha256(json.loads(str(blueprint["content_json"])))
        if (
            int(blueprint["revision"]) != draft.base_blueprint_revision
            or content_digest != draft.base_blueprint_content_sha256
        ):
            raise CanonReconciliationStaleError("rolling_blueprint_changed")

    @staticmethod
    def _rolling_source_canon_is_current(
        connection: Connection,
        *,
        project_id: str,
        reconciliation_id: str,
        record_ids: list[str],
    ) -> bool:
        if not record_ids:
            return False
        placeholders = ",".join("?" for _ in record_ids)
        matched = int(
            connection.execute(
                f"""
                SELECT COUNT(DISTINCT record.id)
                FROM canon_records record
                JOIN canon_delta_candidates candidate
                  ON candidate.accepted_record_id = record.id
                WHERE record.project_id = ? AND record.state = 'active'
                  AND candidate.project_id = ?
                  AND candidate.reconciliation_id = ?
                  AND candidate.state = 'accepted'
                  AND record.id IN ({placeholders})
                  AND record.source_candidate_id = candidate.id
                  AND record.kind = candidate.kind
                  AND record.subject_key = candidate.subject_key
                  AND record.payload_sha256 = candidate.payload_sha256
                """,
                (project_id, project_id, reconciliation_id, *record_ids),
            ).fetchone()[0]
        )
        return matched == len(record_ids)

    def get_rolling_plan_replenishment(
        self,
        *,
        project_id: str,
        replenishment_id: str,
    ) -> RollingPlanReplenishment:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM rolling_plan_replenishments
                WHERE id = ? AND project_id = ?
                """,
                (replenishment_id, project_id),
            ).fetchone()
        if row is None:
            raise CanonReconciliationNotFoundError(replenishment_id)
        return self._rolling_plan(row)

    def reject_rolling_plan_replenishment(
        self,
        *,
        project_id: str,
        replenishment_id: str,
        request: RejectRollingPlanReplenishmentRequest,
    ) -> RollingPlanReplenishment:
        timestamp = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM rolling_plan_replenishments
                WHERE id = ? AND project_id = ?
                """,
                (replenishment_id, project_id),
            ).fetchone()
            if row is None:
                raise CanonReconciliationNotFoundError(replenishment_id)
            if row["state"] != RollingPlanReplenishmentState.CANDIDATE.value:
                raise CanonReconciliationConflictError("rolling_plan_not_candidate")
            if int(row["revision"]) != request.expected_revision:
                raise CanonReconciliationStaleError(str(row["revision"]))
            connection.execute(
                """
                UPDATE rolling_plan_replenishments
                SET state = 'rejected', revision = revision + 1,
                    updated_at = ?, decided_at = ?
                WHERE id = ? AND project_id = ? AND revision = ? AND state = 'candidate'
                """,
                (
                    timestamp,
                    timestamp,
                    replenishment_id,
                    project_id,
                    request.expected_revision,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM rolling_plan_replenishments WHERE id = ?",
                (replenishment_id,),
            ).fetchone()
            assert updated is not None
            return self._rolling_plan(updated)

    def adopt_rolling_plan_replenishment(
        self,
        *,
        project_id: str,
        replenishment_id: str,
        request: AdoptRollingPlanReplenishmentRequest,
    ) -> RollingPlanReplenishment:
        timestamp = _now()
        stale_reason: str | None = None
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM rolling_plan_replenishments
                WHERE id = ? AND project_id = ?
                """,
                (replenishment_id, project_id),
            ).fetchone()
            if row is None:
                raise CanonReconciliationNotFoundError(replenishment_id)
            if (
                row["state"] == RollingPlanReplenishmentState.ADOPTED.value
                and row["adoption_idempotency_key"] == request.idempotency_key
                and row["plans_sha256"] == request.expected_plans_sha256
            ):
                return self._rolling_plan(row)
            if row["state"] != RollingPlanReplenishmentState.CANDIDATE.value:
                raise CanonReconciliationConflictError("rolling_plan_not_candidate")
            if int(row["revision"]) != request.expected_revision:
                raise CanonReconciliationStaleError(str(row["revision"]))
            if row["plans_sha256"] != request.expected_plans_sha256:
                raise CanonReconciliationStaleError("rolling_plan_content_changed")
            replenishment = self._rolling_plan(row)
            plans = replenishment.plans
            if not self._rolling_source_canon_is_current(
                connection,
                project_id=project_id,
                reconciliation_id=str(row["reconciliation_id"]),
                record_ids=replenishment.source_canon_record_ids,
            ):
                stale_reason = "rolling_canon_changed"
            if row["base_blueprint_id"] is not None:
                blueprint = connection.execute(
                    """
                    SELECT content_json, revision FROM book_blueprints
                    WHERE id = ? AND project_id = ?
                    """,
                    (row["base_blueprint_id"], project_id),
                ).fetchone()
                if blueprint is None or (
                    int(blueprint["revision"]) != int(row["base_blueprint_revision"])
                    or canonical_sha256(json.loads(str(blueprint["content_json"])))
                    != row["base_blueprint_content_sha256"]
                ):
                    stale_reason = "rolling_blueprint_changed"
            volume = connection.execute(
                """
                SELECT id, volume_number FROM volume_plans
                WHERE id = ? AND project_id = ?
                """,
                (row["volume_plan_id"], project_id),
            ).fetchone()
            manuscript_volume = None
            if volume is not None:
                manuscript_volume = connection.execute(
                    """
                    SELECT id FROM manuscript_volumes
                    WHERE project_id = ? AND volume_number = ? AND deleted_at IS NULL
                    """,
                    (project_id, volume["volume_number"]),
                ).fetchone()
            if volume is None or manuscript_volume is None:
                stale_reason = stale_reason or "rolling_volume_plan_changed"
            if stale_reason is None:
                for plan in plans:
                    conflict = connection.execute(
                        """
                        SELECT 1 FROM rolling_chapter_plans
                        WHERE project_id = ? AND chapter_number = ?
                        UNION ALL
                        SELECT 1 FROM chapters
                        WHERE project_id = ? AND chapter_number = ?
                        LIMIT 1
                        """,
                        (
                            project_id,
                            plan.chapter_number,
                            project_id,
                            plan.chapter_number,
                        ),
                    ).fetchone()
                    if conflict is not None:
                        stale_reason = f"rolling_target_exists:{plan.chapter_number}"
                        break
            if stale_reason is not None:
                connection.execute(
                    """
                    UPDATE rolling_plan_replenishments
                    SET state = 'stale', revision = revision + 1,
                        blocked_reason = ?, updated_at = ?
                    WHERE id = ? AND project_id = ? AND state = 'candidate'
                    """,
                    (stale_reason, timestamp, replenishment_id, project_id),
                )
            else:
                assert volume is not None and manuscript_volume is not None
                for plan in plans:
                    connection.execute(
                        """
                        INSERT INTO rolling_chapter_plans (
                            id, project_id, volume_plan_id, chapter_number,
                            content_json, locked, revision, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)
                        """,
                        (
                            str(uuid4()),
                            project_id,
                            volume["id"],
                            plan.chapter_number,
                            plan.model_dump_json(),
                            timestamp,
                            timestamp,
                        ),
                    )
                    chapter_id = str(uuid4())
                    connection.execute(
                        """
                        INSERT INTO chapters (
                            id, project_id, volume_id, volume_number,
                            chapter_number, sort_key, title, content,
                            reader_promise, opening_hook, state_change,
                            emotional_payoff, ending_cliffhanger, status,
                            revision, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?,
                                  'planned', 0, ?)
                        """,
                        (
                            chapter_id,
                            project_id,
                            manuscript_volume["id"],
                            volume["volume_number"],
                            plan.chapter_number,
                            plan.chapter_number * 1_024,
                            plan.title,
                            plan.reader_promise,
                            plan.opening_hook,
                            plan.state_change,
                            plan.emotional_payoff,
                            plan.ending_cliffhanger,
                            timestamp,
                        ),
                    )
                    ReviewRepository.append_chapter_version(
                        connection,
                        chapter_id=chapter_id,
                        chapter_revision=0,
                        content="",
                        source=ChapterVersionSource.INITIAL,
                        created_at=timestamp,
                    )
                connection.execute(
                    """
                    UPDATE rolling_plan_replenishments
                    SET state = 'adopted', revision = revision + 1,
                        adoption_idempotency_key = ?, updated_at = ?, decided_at = ?
                    WHERE id = ? AND project_id = ? AND revision = ? AND state = 'candidate'
                    """,
                    (
                        request.idempotency_key,
                        timestamp,
                        timestamp,
                        replenishment_id,
                        project_id,
                        request.expected_revision,
                    ),
                )
                connection.execute(
                    "UPDATE projects SET updated_at = ? WHERE id = ?",
                    (timestamp, project_id),
                )
            updated = connection.execute(
                "SELECT * FROM rolling_plan_replenishments WHERE id = ?",
                (replenishment_id,),
            ).fetchone()
            assert updated is not None
            result = self._rolling_plan(updated)
        if stale_reason is not None:
            raise CanonReconciliationStaleError(stale_reason)
        return result

    def _apply_preference_decision(
        self,
        connection: Connection,
        *,
        project_id: str,
        reconciliation_id: str,
        approval_id: str,
        candidate_id: str,
        expected_revision: int,
        action: CandidateDecisionAction,
        edited_scope_kind: PreferenceScopeKind | None,
        edited_scope_value: str | None,
        edited_dimension: AuthorPreferenceDimension | None,
        edited_compact_rule: str | None,
        edited_confidence: float | None,
        rejection_reason: str | None,
        timestamp: str,
    ) -> tuple[str | None, bool]:
        row = connection.execute(
            """
            SELECT * FROM author_preference_candidates
            WHERE id = ? AND reconciliation_id = ? AND project_id = ?
            """,
            (candidate_id, reconciliation_id, project_id),
        ).fetchone()
        if row is None:
            raise CanonReconciliationNotFoundError(candidate_id)
        if row["state"] != PreferenceCandidateState.CANDIDATE.value:
            raise CanonReconciliationConflictError("preference_candidate_already_decided")
        if int(row["revision"]) != expected_revision:
            raise CanonReconciliationStaleError(str(row["revision"]))
        if action == CandidateDecisionAction.REJECT:
            assert rejection_reason is not None
            connection.execute(
                """
                UPDATE author_preference_candidates
                SET state = 'rejected', revision = revision + 1,
                    rejection_reason = ?, updated_at = ?, decided_at = ?
                WHERE id = ? AND revision = ? AND state = 'candidate'
                """,
                (
                    rejection_reason,
                    timestamp,
                    timestamp,
                    candidate_id,
                    expected_revision,
                ),
            )
            return None, True
        if action == CandidateDecisionAction.EDIT:
            assert edited_scope_kind is not None
            assert edited_scope_value is not None
            assert edited_dimension is not None
            assert edited_compact_rule is not None
            assert edited_confidence is not None
            scope_kind = edited_scope_kind
            scope_value = edited_scope_value
            dimension = edited_dimension
            compact_rule = edited_compact_rule
            confidence = edited_confidence
        else:
            scope_kind = PreferenceScopeKind(row["scope_kind"])
            scope_value = str(row["scope_value"])
            dimension = AuthorPreferenceDimension(row["dimension"])
            compact_rule = str(row["compact_rule"])
            confidence = float(row["confidence"])
        self._validate_preference_scope(
            connection,
            project_id=project_id,
            scope_kind=scope_kind,
            scope_value=scope_value,
        )
        fingerprint = canonical_sha256(
            {
                "schema_version": 1,
                "scope_kind": scope_kind.value,
                "scope_value": scope_value,
                "dimension": dimension.value,
                "compact_rule": compact_rule,
            }
        )
        preference = connection.execute(
            """
            SELECT * FROM author_preferences
            WHERE project_id = ? AND fingerprint_sha256 = ? AND state = 'active'
            """,
            (project_id, fingerprint),
        ).fetchone()
        if preference is None:
            preference_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO author_preferences (
                    id, project_id, scope_kind, scope_value, dimension,
                    compact_rule, rule_sha256, fingerprint_sha256, confidence,
                    occurrence_count, state, revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'active', 0, ?, ?)
                """,
                (
                    preference_id,
                    project_id,
                    scope_kind.value,
                    scope_value,
                    dimension.value,
                    compact_rule,
                    text_sha256(compact_rule),
                    fingerprint,
                    confidence,
                    timestamp,
                    timestamp,
                ),
            )
        else:
            preference_id = str(preference["id"])
            old_count = int(preference["occurrence_count"])
            combined_confidence = (
                float(preference["confidence"]) * old_count + confidence
            ) / (old_count + 1)
            connection.execute(
                """
                UPDATE author_preferences
                SET confidence = ?, occurrence_count = occurrence_count + 1,
                    revision = revision + 1, updated_at = ?
                WHERE id = ? AND project_id = ? AND state = 'active'
                """,
                (combined_confidence, timestamp, preference_id, project_id),
            )
        connection.execute(
            """
            INSERT INTO author_preference_sources (
                preference_id, candidate_id, source_writing_outcome_id,
                source_candidate_version_id, approval_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                preference_id,
                candidate_id,
                row["source_writing_outcome_id"],
                row["source_candidate_version_id"],
                approval_id,
                timestamp,
            ),
        )
        connection.execute(
            """
            UPDATE author_preference_candidates
            SET scope_kind = ?, scope_value = ?, dimension = ?,
                compact_rule = ?, rule_sha256 = ?, confidence = ?,
                state = 'confirmed', revision = revision + 1,
                confirmed_preference_id = ?, updated_at = ?, decided_at = ?
            WHERE id = ? AND revision = ? AND state = 'candidate'
            """,
            (
                scope_kind.value,
                scope_value,
                dimension.value,
                compact_rule,
                text_sha256(compact_rule),
                confidence,
                preference_id,
                timestamp,
                timestamp,
                candidate_id,
                expected_revision,
            ),
        )
        return preference_id, False

    def mark_failed(self, reconciliation_id: str, error_message: str) -> CanonReconciliation:
        return self._mark_terminal(
            reconciliation_id,
            state=CanonReconciliationState.FAILED,
            error_message=error_message,
        )

    def mark_stale(self, reconciliation_id: str, reason: str) -> CanonReconciliation:
        return self._mark_terminal(
            reconciliation_id,
            state=CanonReconciliationState.STALE,
            error_message=reason,
        )

    def _mark_terminal(
        self,
        reconciliation_id: str,
        *,
        state: CanonReconciliationState,
        error_message: str,
    ) -> CanonReconciliation:
        if state not in {
            CanonReconciliationState.FAILED,
            CanonReconciliationState.STALE,
        }:
            raise ValueError("invalid terminal reconciliation state")
        timestamp = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM canon_reconciliations WHERE id = ?",
                (reconciliation_id,),
            ).fetchone()
            if row is None:
                raise CanonReconciliationNotFoundError(reconciliation_id)
            if row["state"] == CanonReconciliationState.DECIDED.value:
                raise CanonReconciliationConflictError("reconciliation_already_decided")
            connection.execute(
                """
                UPDATE canon_reconciliations
                SET state = ?, revision = revision + 1, error_message = ?,
                    updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (state.value, error_message[:1_000], timestamp, timestamp, reconciliation_id),
            )
            connection.execute(
                """
                UPDATE canon_delta_candidates
                SET state = 'stale', revision = revision + 1, updated_at = ?
                WHERE reconciliation_id = ? AND state = 'candidate'
                """,
                (timestamp, reconciliation_id),
            )
            connection.execute(
                """
                UPDATE author_preference_candidates
                SET state = 'stale', revision = revision + 1, updated_at = ?
                WHERE reconciliation_id = ? AND state = 'candidate'
                """,
                (timestamp, reconciliation_id),
            )
            updated = connection.execute(
                "SELECT * FROM canon_reconciliations WHERE id = ?",
                (reconciliation_id,),
            ).fetchone()
            assert updated is not None
            return self._reconciliation(updated)

    def list_canon_records(self, project_id: str) -> list[CanonRecord]:
        with self.database.connect() as connection:
            self._require_project(connection, project_id)
            rows = connection.execute(
                """
                SELECT * FROM canon_records
                WHERE project_id = ? AND state = 'active'
                ORDER BY kind, subject_key, id
                """,
                (project_id,),
            ).fetchall()
        return [self._canon_record(row) for row in rows]

    def list_author_preferences(self, project_id: str) -> list[AuthorPreference]:
        with self.database.connect() as connection:
            self._require_project(connection, project_id)
            rows = connection.execute(
                """
                SELECT * FROM author_preferences
                WHERE project_id = ? AND state = 'active'
                ORDER BY scope_kind, dimension, created_at, id
                """,
                (project_id,),
            ).fetchall()
        return [self._author_preference(row) for row in rows]

    @staticmethod
    def _require_project(connection: Connection, project_id: str) -> None:
        if connection.execute(
            "SELECT 1 FROM projects WHERE id = ?", (project_id,)
        ).fetchone() is None:
            raise CanonReconciliationNotFoundError(project_id)

    @staticmethod
    def _validate_preference_scope(
        connection: Connection,
        *,
        project_id: str,
        scope_kind: PreferenceScopeKind,
        scope_value: str,
    ) -> None:
        if scope_kind == PreferenceScopeKind.PROJECT:
            if scope_value != project_id:
                raise CanonReconciliationConflictError("preference_scope_project_mismatch")
            CanonReconciliationRepository._require_project(connection, project_id)
            return
        if scope_kind == PreferenceScopeKind.GENRE:
            project = connection.execute(
                "SELECT genre FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise CanonReconciliationNotFoundError(project_id)
            if scope_value != project["genre"]:
                raise CanonReconciliationConflictError("preference_scope_genre_mismatch")
            return
        chapter = connection.execute(
            "SELECT 1 FROM chapters WHERE id = ? AND project_id = ?",
            (scope_value, project_id),
        ).fetchone()
        if chapter is None:
            raise CanonReconciliationConflictError("preference_scope_chapter_mismatch")

    @staticmethod
    def _approval(row: Row) -> ChapterApproval:
        return ChapterApproval.model_validate(dict(row))

    @staticmethod
    def _reconciliation(row: Row) -> CanonReconciliation:
        return CanonReconciliation.model_validate(dict(row))

    @staticmethod
    def _payload(kind: CanonKind, payload_json: str) -> CanonPayload:
        model = CANON_PAYLOAD_MODELS[kind]
        return cast(CanonPayload, model.model_validate(_load_json_object(payload_json)))

    @classmethod
    def _canon_candidate(cls, row: Row) -> CanonDeltaCandidate:
        kind = CanonKind(row["kind"])
        values = dict(row)
        for name in ("payload_json", "evidence_json", "conflicts_json"):
            values.pop(name, None)
        return CanonDeltaCandidate.model_validate(
            {
                **values,
                "kind": kind,
                "payload": cls._payload(kind, str(row["payload_json"])),
                "evidence": _load_json_object(str(row["evidence_json"])),
                "conflicts": _load_json_list(str(row["conflicts_json"])),
            }
        )

    @staticmethod
    def _preference_candidate(row: Row) -> AuthorPreferenceCandidate:
        values = dict(row)
        values.pop("comparison_metrics_json", None)
        return AuthorPreferenceCandidate.model_validate(
            {
                **values,
                "comparison_metrics": _load_json_object(
                    str(row["comparison_metrics_json"])
                ),
            }
        )

    @classmethod
    def _canon_record(cls, row: Row) -> CanonRecord:
        kind = CanonKind(row["kind"])
        return CanonRecord.model_validate(
            {
                **dict(row),
                "kind": kind,
                "payload": cls._payload(kind, str(row["payload_json"])),
            }
        )

    @staticmethod
    def _author_preference(row: Row) -> AuthorPreference:
        return AuthorPreference.model_validate(dict(row))

    @staticmethod
    def _rolling_plan(row: Row) -> RollingPlanReplenishment:
        return RollingPlanReplenishment.model_validate(
            {
                **dict(row),
                "source_canon_record_ids": _load_json_list(
                    str(row["source_canon_record_ids_json"])
                ),
                "protected_chapter_numbers": _load_json_list(
                    str(row["protected_chapter_numbers_json"])
                ),
                "plans": _load_json_list(str(row["plans_json"])),
            }
        )

    @classmethod
    def _current_analysis_sha256(cls, connection: Connection, row: Row) -> str:
        snapshot = cls._snapshot(connection, row)
        analysis = ReconciliationAnalysis(
            context_packet_id=str(row["context_packet_id"]),
            context_packet_sha256=str(row["context_packet_sha256"]),
            context_dependency_fingerprint_sha256=str(
                row["context_dependency_fingerprint_sha256"]
            ),
            canon_candidates=[
                CanonDeltaCandidateDraft.model_validate(
                    candidate.model_dump(
                        include=set(CanonDeltaCandidateDraft.model_fields)
                    )
                )
                for candidate in snapshot.canon_candidates
            ],
            preference_candidates=[
                AuthorPreferenceCandidateDraft.model_validate(
                    candidate.model_dump(
                        include=set(AuthorPreferenceCandidateDraft.model_fields)
                    )
                )
                for candidate in snapshot.preference_candidates
            ],
            preference_skip_reason=snapshot.reconciliation.preference_skip_reason,
        )
        return canonical_sha256(analysis.model_dump(mode="json"))

    @classmethod
    def _snapshot(cls, connection: Connection, row: Row) -> CanonReconciliationSnapshot:
        approval = connection.execute(
            "SELECT * FROM chapter_approvals WHERE id = ?", (row["approval_id"],)
        ).fetchone()
        assert approval is not None
        canon_rows = connection.execute(
            """
            SELECT * FROM canon_delta_candidates
            WHERE reconciliation_id = ? ORDER BY ordinal, id
            """,
            (row["id"],),
        ).fetchall()
        preference_rows = connection.execute(
            """
            SELECT * FROM author_preference_candidates
            WHERE reconciliation_id = ? ORDER BY ordinal, id
            """,
            (row["id"],),
        ).fetchall()
        rolling_row = connection.execute(
            "SELECT * FROM rolling_plan_replenishments WHERE reconciliation_id = ?",
            (row["id"],),
        ).fetchone()
        return CanonReconciliationSnapshot(
            approval=cls._approval(approval),
            reconciliation=cls._reconciliation(row),
            canon_candidates=[cls._canon_candidate(item) for item in canon_rows],
            preference_candidates=[
                cls._preference_candidate(item) for item in preference_rows
            ],
            rolling_plan_replenishment=(
                cls._rolling_plan(rolling_row) if rolling_row is not None else None
            ),
        )
