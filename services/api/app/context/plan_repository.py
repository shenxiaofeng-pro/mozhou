from __future__ import annotations

import json
from datetime import UTC, datetime
from sqlite3 import Connection, Row
from typing import Literal
from uuid import uuid4

from app.context.models import ContextDependencyRef, ContextDependencySnapshot
from app.context.plan_models import (
    AdoptPlanRebaseCandidateRequest,
    AdoptPlanRebaseCandidateResult,
    CreatePlanRebaseCandidateRequest,
    CreativePlanDependencyState,
    CreativePlanImpactPreview,
    CreativePlanImpactTarget,
    CreativePlanSubjectKind,
    PlanRebaseBlueprintDraft,
    PlanRebaseCandidate,
    PlanRebaseCandidateState,
    PlanRebaseRollingDraft,
    PlanRebaseVolumeDraft,
    UpdatePlanRebaseCandidateRequest,
)
from app.creative_safety import CreativeSafetyGate
from app.database import Database
from app.director.repository import DirectorRepository
from app.models import (
    BookBlueprintField,
    ChapterStatus,
    RollingChapterPlanContent,
    VolumePlanContent,
)
from app.writing_patterns.compiler import canonical_sha256

PLAN_REBASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS creative_plan_dependencies (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    subject_kind TEXT NOT NULL CHECK(subject_kind IN (
        'book_blueprint', 'volume_plan', 'rolling_plan'
    )),
    subject_id TEXT NOT NULL,
    subject_revision INTEGER NOT NULL CHECK(subject_revision >= 0),
    dependency_snapshot_json TEXT NOT NULL CHECK(json_valid(dependency_snapshot_json)),
    dependency_fingerprint_sha256 TEXT NOT NULL
        CHECK(length(dependency_fingerprint_sha256) = 64),
    baseline_state TEXT NOT NULL CHECK(baseline_state IN ('current', 'legacy')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(project_id, subject_kind, subject_id)
);

CREATE INDEX IF NOT EXISTS idx_creative_plan_dependencies_project
ON creative_plan_dependencies(project_id, subject_kind, subject_id);

CREATE TABLE IF NOT EXISTS plan_rebase_candidates (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    state TEXT NOT NULL CHECK(state IN ('candidate', 'adopted', 'stale', 'rejected')),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    based_on_dependency_fingerprint_sha256 TEXT NOT NULL
        CHECK(length(based_on_dependency_fingerprint_sha256) = 64),
    target_dependency_fingerprint_sha256 TEXT NOT NULL
        CHECK(length(target_dependency_fingerprint_sha256) = 64),
    impact_json TEXT NOT NULL CHECK(json_valid(impact_json)),
    book_blueprint_json TEXT CHECK(book_blueprint_json IS NULL OR json_valid(book_blueprint_json)),
    volume_plans_json TEXT NOT NULL CHECK(json_valid(volume_plans_json)),
    rolling_chapter_plans_json TEXT NOT NULL CHECK(json_valid(rolling_chapter_plans_json)),
    adoption_idempotency_key TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    adopted_at TEXT,
    CHECK((state = 'adopted') = (adopted_at IS NOT NULL)),
    CHECK(adoption_idempotency_key IS NULL OR length(adoption_idempotency_key) BETWEEN 1 AND 200)
);

CREATE INDEX IF NOT EXISTS idx_plan_rebase_candidates_project_updated
ON plan_rebase_candidates(project_id, updated_at DESC, id);
"""


class PlanRebaseNotFoundError(LookupError):
    pass


class PlanRebaseConflictError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class PlanRebaseRepository:
    """Versioned plan dependency and author-controlled rebase boundary."""

    def __init__(
        self,
        database: Database,
        creative_safety_gate: CreativeSafetyGate | None = None,
    ) -> None:
        self.database = database
        self.director = DirectorRepository(database)
        self._creative_safety_gate = creative_safety_gate
        self.ensure_schema()

    def set_creative_safety_gate(self, gate: CreativeSafetyGate) -> None:
        self._creative_safety_gate = gate

    def ensure_schema(self) -> None:
        with self.database.connect() as connection:
            connection.executescript(PLAN_REBASE_SCHEMA)

    def get_impact(self, project_id: str) -> CreativePlanImpactPreview:
        safety_gate_allows = self._safety_gate_allows(project_id)
        with self.database.connect() as connection:
            return self._impact_in_connection(
                connection,
                project_id,
                safety_gate_allows=safety_gate_allows,
            )

    def _impact_in_connection(
        self,
        connection: Connection,
        project_id: str,
        *,
        safety_gate_allows: bool,
    ) -> CreativePlanImpactPreview:
        dependency, fingerprint = self._current_dependency(connection, project_id)
        targets = self._planning_targets(connection, project_id)
        result: list[CreativePlanImpactTarget] = []
        all_reasons: set[str] = set()
        for target in targets:
            row = connection.execute(
                """
                SELECT * FROM creative_plan_dependencies
                WHERE project_id = ? AND subject_kind = ? AND subject_id = ?
                """,
                (project_id, target.kind.value, target.id),
            ).fetchone()
            if row is None:
                state = CreativePlanDependencyState.LEGACY
                reasons = ["legacy_dependency_snapshot"]
            else:
                state, reasons = self._dependency_state(row, dependency, fingerprint)
            all_reasons.update(reasons)
            result.append(
                target.model_copy(update={"state": state, "stale_reasons": reasons})
            )

        blueprint_row = connection.execute(
            "SELECT locks_json FROM book_blueprints WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        blueprint_locks = (
            json.loads(str(blueprint_row["locks_json"]))
            if blueprint_row is not None
            else {}
        )
        locked_fields = [
            field for field in BookBlueprintField if blueprint_locks.get(field.value)
        ]
        reasons = self._ordered_reasons(all_reasons)
        if not safety_gate_allows or not self._local_context_is_usable(
            connection,
            project_id,
            dependency,
        ):
            reasons = self._ordered_reasons({*reasons, "context_blocked"})
        approved_count = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM chapters
                WHERE project_id = ? AND status = ? AND deleted_at IS NULL
                """,
                (project_id, ChapterStatus.APPROVED.value),
            ).fetchone()[0]
        )
        return CreativePlanImpactPreview(
            project_id=project_id,
            current_dependency=dependency,
            current_dependency_fingerprint_sha256=fingerprint,
            reasons=reasons,
            affected_blueprint_fields=(list(BookBlueprintField) if reasons else []),
            locked_blueprint_fields=locked_fields,
            targets=result,
            approved_chapter_count=approved_count,
            can_rebase=(
                blueprint_row is not None
                and dependency.topic is not None
                and bool(result)
                and bool(reasons)
                and "context_blocked" not in reasons
            ),
        )

    def create_candidate(
        self,
        project_id: str,
        request: CreatePlanRebaseCandidateRequest,
    ) -> PlanRebaseCandidate:
        timestamp = _now_iso()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            impact = self._impact_in_connection(
                connection,
                project_id,
                safety_gate_allows=self._safety_gate_allows(project_id),
            )
            if (
                impact.current_dependency_fingerprint_sha256
                != request.expected_dependency_fingerprint_sha256
            ):
                raise PlanRebaseConflictError("creative_context_dependency_changed")
            if "context_blocked" in impact.reasons:
                raise PlanRebaseConflictError("context_blocked")
            if not impact.can_rebase:
                raise PlanRebaseConflictError("plan_rebase_not_required")

            blueprint_row = connection.execute(
                "SELECT * FROM book_blueprints WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            if blueprint_row is None:
                raise PlanRebaseConflictError("plan_rebase_unavailable")
            blueprint = DirectorRepository.parse_book_blueprint(blueprint_row)
            volume_plans = [
                DirectorRepository.parse_volume_plan(row)
                for row in connection.execute(
                    """
                    SELECT * FROM volume_plans
                    WHERE project_id = ? ORDER BY volume_number, id
                    """,
                    (project_id,),
                ).fetchall()
            ]
            rolling_plans = [
                DirectorRepository.parse_rolling_plan(row)
                for row in connection.execute(
                    """
                    SELECT * FROM rolling_chapter_plans
                    WHERE project_id = ? ORDER BY chapter_number, id
                    """,
                    (project_id,),
                ).fetchall()
            ]
            candidate = PlanRebaseCandidate(
                id=str(uuid4()),
                project_id=project_id,
                state=PlanRebaseCandidateState.CANDIDATE,
                revision=0,
                based_on_dependency_fingerprint_sha256=(
                    self._based_on_fingerprint(connection, project_id, impact)
                ),
                target_dependency_fingerprint_sha256=(
                    impact.current_dependency_fingerprint_sha256
                ),
                impact=impact,
                book_blueprint=PlanRebaseBlueprintDraft(
                    id=blueprint.id,
                    expected_revision=blueprint.revision,
                    content=blueprint.content,
                    locks=blueprint.locks,
                ),
                volume_plans=[
                    PlanRebaseVolumeDraft(
                        id=plan.id,
                        expected_revision=plan.revision,
                        locked=plan.locked,
                        content=VolumePlanContent.model_validate(
                            plan.model_dump(
                                include=set(VolumePlanContent.model_fields)
                            )
                        ),
                    )
                    for plan in volume_plans
                ],
                rolling_chapter_plans=[
                    PlanRebaseRollingDraft(
                        id=plan.id,
                        expected_revision=plan.revision,
                        locked=plan.locked,
                        content=RollingChapterPlanContent.model_validate(
                            plan.model_dump(
                                include=set(RollingChapterPlanContent.model_fields)
                            )
                        ),
                    )
                    for plan in rolling_plans
                ],
                created_at=timestamp,
                updated_at=timestamp,
            )
            connection.execute(
                """
                INSERT INTO plan_rebase_candidates (
                    id, project_id, state, revision,
                    based_on_dependency_fingerprint_sha256,
                    target_dependency_fingerprint_sha256, impact_json,
                    book_blueprint_json, volume_plans_json,
                    rolling_chapter_plans_json, adoption_idempotency_key,
                    created_at, updated_at, adopted_at
                ) VALUES (?, ?, 'candidate', 0, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL)
                """,
                (
                    candidate.id,
                    project_id,
                    candidate.based_on_dependency_fingerprint_sha256,
                    candidate.target_dependency_fingerprint_sha256,
                    candidate.impact.model_dump_json(),
                    (
                        candidate.book_blueprint.model_dump_json()
                        if candidate.book_blueprint is not None
                        else None
                    ),
                    _json(
                        [item.model_dump(mode="json") for item in candidate.volume_plans]
                    ),
                    _json(
                        [
                            item.model_dump(mode="json")
                            for item in candidate.rolling_chapter_plans
                        ]
                    ),
                    timestamp,
                    timestamp,
                ),
            )
        return candidate

    def get_candidate(self, project_id: str, candidate_id: str) -> PlanRebaseCandidate:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM plan_rebase_candidates WHERE id = ? AND project_id = ?",
                (candidate_id, project_id),
            ).fetchone()
            if row is None:
                raise PlanRebaseNotFoundError(candidate_id)
            candidate = self._candidate(row)
            if candidate.state == PlanRebaseCandidateState.CANDIDATE:
                _dependency, current_fingerprint = self._current_dependency(
                    connection,
                    project_id,
                )
                if current_fingerprint != candidate.target_dependency_fingerprint_sha256:
                    candidate = candidate.model_copy(
                        update={"state": PlanRebaseCandidateState.STALE}
                    )
        return candidate

    def update_candidate(
        self,
        project_id: str,
        candidate_id: str,
        request: UpdatePlanRebaseCandidateRequest,
    ) -> PlanRebaseCandidate:
        timestamp = _now_iso()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_context_usable_in_connection(connection, project_id)
            row = connection.execute(
                "SELECT * FROM plan_rebase_candidates WHERE id = ? AND project_id = ?",
                (candidate_id, project_id),
            ).fetchone()
            if row is None:
                raise PlanRebaseNotFoundError(candidate_id)
            candidate = self._candidate(row)
            if candidate.state != PlanRebaseCandidateState.CANDIDATE:
                raise PlanRebaseConflictError("rebase_candidate_not_editable")
            if candidate.revision != request.expected_revision:
                raise PlanRebaseConflictError("rebase_candidate_changed")
            self._require_candidate_provenance(connection, candidate)
            _dependency, current_fingerprint = self._current_dependency(
                connection,
                project_id,
            )
            if current_fingerprint != candidate.target_dependency_fingerprint_sha256:
                raise PlanRebaseConflictError("creative_context_dependency_changed")

            blueprint = candidate.book_blueprint
            if blueprint is not None:
                next_blueprint_content = request.book_blueprint_content or blueprint.content
                before = blueprint.content.model_dump(mode="json")
                after = next_blueprint_content.model_dump(mode="json")
                for field in BookBlueprintField:
                    if blueprint.locks[field] and before[field.value] != after[field.value]:
                        raise PlanRebaseConflictError("locked_blueprint_field")
                next_blueprint = blueprint.model_copy(
                    update={"content": next_blueprint_content}
                )
            elif request.book_blueprint_content is not None:
                raise PlanRebaseConflictError("rebase_candidate_changed")
            else:
                next_blueprint = None

            volume_edits = self._unique_edits(request.volume_plans)
            rolling_edits = self._unique_edits(request.rolling_chapter_plans)
            if set(volume_edits) != {item.id for item in candidate.volume_plans}:
                raise PlanRebaseConflictError("rebase_candidate_changed")
            if set(rolling_edits) != {
                item.id for item in candidate.rolling_chapter_plans
            }:
                raise PlanRebaseConflictError("rebase_candidate_changed")

            next_volumes: list[PlanRebaseVolumeDraft] = []
            for current_volume in candidate.volume_plans:
                volume_content = volume_edits[current_volume.id].content
                if current_volume.locked and volume_content.model_dump(
                    mode="json"
                ) != current_volume.content.model_dump(mode="json"):
                    raise PlanRebaseConflictError("locked_volume_plan")
                next_volumes.append(
                    current_volume.model_copy(update={"content": volume_content})
                )
            if len({item.content.volume_number for item in next_volumes}) != len(
                next_volumes
            ):
                raise PlanRebaseConflictError("rebase_candidate_changed")

            next_rolling: list[PlanRebaseRollingDraft] = []
            for current_rolling in candidate.rolling_chapter_plans:
                rolling_content = rolling_edits[current_rolling.id].content
                if current_rolling.locked and rolling_content.model_dump(
                    mode="json"
                ) != current_rolling.content.model_dump(mode="json"):
                    raise PlanRebaseConflictError("locked_rolling_plan")
                next_rolling.append(
                    current_rolling.model_copy(update={"content": rolling_content})
                )
            if len({item.content.chapter_number for item in next_rolling}) != len(
                next_rolling
            ):
                raise PlanRebaseConflictError("rebase_candidate_changed")

            result = connection.execute(
                """
                UPDATE plan_rebase_candidates
                SET revision = revision + 1, book_blueprint_json = ?,
                    volume_plans_json = ?, rolling_chapter_plans_json = ?, updated_at = ?
                WHERE id = ? AND project_id = ? AND state = 'candidate' AND revision = ?
                """,
                (
                    next_blueprint.model_dump_json() if next_blueprint is not None else None,
                    _json([item.model_dump(mode="json") for item in next_volumes]),
                    _json([item.model_dump(mode="json") for item in next_rolling]),
                    timestamp,
                    candidate_id,
                    project_id,
                    request.expected_revision,
                ),
            )
            if result.rowcount != 1:
                raise PlanRebaseConflictError("rebase_candidate_changed")
            updated = connection.execute(
                "SELECT * FROM plan_rebase_candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
        if updated is None:
            raise PlanRebaseNotFoundError(candidate_id)
        return self._candidate(updated)

    def adopt_candidate(
        self,
        project_id: str,
        candidate_id: str,
        request: AdoptPlanRebaseCandidateRequest,
    ) -> AdoptPlanRebaseCandidateResult:
        timestamp = _now_iso()
        adopted_candidate: PlanRebaseCandidate | None = None
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_context_usable_in_connection(connection, project_id)
            row = connection.execute(
                "SELECT * FROM plan_rebase_candidates WHERE id = ? AND project_id = ?",
                (candidate_id, project_id),
            ).fetchone()
            if row is None:
                raise PlanRebaseNotFoundError(candidate_id)
            candidate = self._candidate(row)
            if candidate.state == PlanRebaseCandidateState.ADOPTED:
                if row["adoption_idempotency_key"] != request.idempotency_key:
                    raise PlanRebaseConflictError("rebase_candidate_not_editable")
                adopted_candidate = candidate
            else:
                if candidate.state != PlanRebaseCandidateState.CANDIDATE:
                    raise PlanRebaseConflictError("rebase_candidate_not_editable")
                if candidate.revision != request.expected_revision:
                    raise PlanRebaseConflictError("rebase_candidate_changed")
                self._require_candidate_provenance(connection, candidate)
                _dependency, current_fingerprint = self._current_dependency(
                    connection,
                    project_id,
                )
                if (
                    request.expected_dependency_fingerprint_sha256 != current_fingerprint
                    or candidate.target_dependency_fingerprint_sha256 != current_fingerprint
                ):
                    raise PlanRebaseConflictError("creative_context_dependency_changed")

                blueprint_row, volume_rows, rolling_rows = self._require_live_targets(
                    connection,
                    candidate,
                )
                self._apply_blueprint(connection, candidate, blueprint_row, timestamp)
                self._apply_volume_plans(connection, candidate, volume_rows, timestamp)
                self._apply_rolling_plans(connection, candidate, rolling_rows, timestamp)
                connection.execute(
                    "UPDATE topic_decisions SET plan_stale = 0, updated_at = ? "
                    "WHERE project_id = ?",
                    (timestamp, project_id),
                )

                final_dependency, final_fingerprint = self._current_dependency(
                    connection,
                    project_id,
                )
                self._bind_current_in_connection(
                    connection,
                    project_id,
                    final_dependency,
                    final_fingerprint,
                    timestamp,
                )
                result = connection.execute(
                    """
                    UPDATE plan_rebase_candidates
                    SET state = 'adopted', revision = revision + 1,
                        adoption_idempotency_key = ?, updated_at = ?, adopted_at = ?
                    WHERE id = ? AND project_id = ? AND state = 'candidate' AND revision = ?
                    """,
                    (
                        request.idempotency_key,
                        timestamp,
                        timestamp,
                        candidate_id,
                        project_id,
                        request.expected_revision,
                    ),
                )
                if result.rowcount != 1:
                    raise PlanRebaseConflictError("rebase_candidate_changed")
                adopted_row = connection.execute(
                    "SELECT * FROM plan_rebase_candidates WHERE id = ?",
                    (candidate_id,),
                ).fetchone()
                if adopted_row is None:
                    raise PlanRebaseNotFoundError(candidate_id)
                adopted_candidate = self._candidate(adopted_row)
        if adopted_candidate is None:
            raise PlanRebaseNotFoundError(candidate_id)
        return AdoptPlanRebaseCandidateResult(
            candidate=adopted_candidate,
            planning=self.director.get_snapshot(project_id),
        )

    def bind_current_planning(self, project_id: str) -> CreativePlanImpactPreview:
        """Mark the current planning snapshot as authored against current dependencies."""
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_context_usable_in_connection(connection, project_id)
            dependency, fingerprint = self._current_dependency(connection, project_id)
            timestamp = _now_iso()
            self._bind_current_in_connection(
                connection,
                project_id,
                dependency,
                fingerprint,
                timestamp,
            )
        return self.get_impact(project_id)

    def _bind_current_in_connection(
        self,
        connection: Connection,
        project_id: str,
        dependency: ContextDependencySnapshot,
        fingerprint: str,
        timestamp: str,
    ) -> None:
        current_targets = self._planning_targets(connection, project_id)
        current_keys = {(item.kind.value, item.id) for item in current_targets}
        for target in current_targets:
            connection.execute(
                """
                INSERT INTO creative_plan_dependencies (
                    project_id, subject_kind, subject_id, subject_revision,
                    dependency_snapshot_json, dependency_fingerprint_sha256,
                    baseline_state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'current', ?, ?)
                ON CONFLICT(project_id, subject_kind, subject_id) DO UPDATE SET
                    subject_revision = excluded.subject_revision,
                    dependency_snapshot_json = excluded.dependency_snapshot_json,
                    dependency_fingerprint_sha256 = excluded.dependency_fingerprint_sha256,
                    baseline_state = 'current', updated_at = excluded.updated_at
                """,
                (
                    project_id,
                    target.kind.value,
                    target.id,
                    target.revision,
                    _json(dependency.model_dump(mode="json")),
                    fingerprint,
                    timestamp,
                    timestamp,
                ),
            )
        for row in connection.execute(
            """
            SELECT subject_kind, subject_id FROM creative_plan_dependencies
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchall():
            key = (str(row["subject_kind"]), str(row["subject_id"]))
            if key not in current_keys:
                connection.execute(
                    """
                    DELETE FROM creative_plan_dependencies
                    WHERE project_id = ? AND subject_kind = ? AND subject_id = ?
                    """,
                    (project_id, *key),
                )

    def _based_on_fingerprint(
        self,
        connection: Connection,
        project_id: str,
        impact: CreativePlanImpactPreview,
    ) -> str:
        rows = connection.execute(
            """
            SELECT subject_kind, subject_id, dependency_fingerprint_sha256
            FROM creative_plan_dependencies WHERE project_id = ?
            ORDER BY subject_kind, subject_id
            """,
            (project_id,),
        ).fetchall()
        row_fingerprints = {
            (str(row["subject_kind"]), str(row["subject_id"])): str(
                row["dependency_fingerprint_sha256"]
            )
            for row in rows
        }
        if not impact.targets:
            return impact.current_dependency_fingerprint_sha256
        fingerprints = {
            row_fingerprints.get(
                (target.kind.value, target.id),
                impact.current_dependency_fingerprint_sha256,
            )
            for target in impact.targets
        }
        if len(fingerprints) == 1:
            return next(iter(fingerprints))
        return canonical_sha256(
            [
                {
                    "kind": target.kind.value,
                    "id": target.id,
                    "dependency_fingerprint_sha256": row_fingerprints.get(
                        (target.kind.value, target.id),
                        impact.current_dependency_fingerprint_sha256,
                    ),
                }
                for target in impact.targets
            ]
        )

    def _require_candidate_provenance(
        self,
        connection: Connection,
        candidate: PlanRebaseCandidate,
    ) -> None:
        impact = candidate.impact
        if (
            impact.project_id != candidate.project_id
            or impact.current_dependency_fingerprint_sha256
            != candidate.target_dependency_fingerprint_sha256
            or canonical_sha256(impact.current_dependency.model_dump(mode="json"))
            != candidate.target_dependency_fingerprint_sha256
            or self._based_on_fingerprint(
                connection,
                candidate.project_id,
                impact,
            )
            != candidate.based_on_dependency_fingerprint_sha256
        ):
            raise PlanRebaseConflictError("rebase_candidate_changed")

        frozen_targets = {(item.kind, item.id): item for item in impact.targets}
        if len(frozen_targets) != len(impact.targets):
            raise PlanRebaseConflictError("rebase_candidate_changed")
        draft_targets: dict[
            tuple[CreativePlanSubjectKind, str],
            tuple[int, bool],
        ] = {}
        if candidate.book_blueprint is not None:
            draft_targets[
                (CreativePlanSubjectKind.BOOK_BLUEPRINT, candidate.book_blueprint.id)
            ] = (
                candidate.book_blueprint.expected_revision,
                all(candidate.book_blueprint.locks.values()),
            )
        draft_targets.update(
            {
                (CreativePlanSubjectKind.VOLUME_PLAN, item.id): (
                    item.expected_revision,
                    item.locked,
                )
                for item in candidate.volume_plans
            }
        )
        draft_targets.update(
            {
                (CreativePlanSubjectKind.ROLLING_PLAN, item.id): (
                    item.expected_revision,
                    item.locked,
                )
                for item in candidate.rolling_chapter_plans
            }
        )
        if set(frozen_targets) != set(draft_targets):
            raise PlanRebaseConflictError("rebase_candidate_changed")
        for key, target in frozen_targets.items():
            if (target.revision, target.locked) != draft_targets[key]:
                raise PlanRebaseConflictError("rebase_candidate_changed")

    @staticmethod
    def _require_live_targets(
        connection: Connection,
        candidate: PlanRebaseCandidate,
    ) -> tuple[Row, dict[str, Row], dict[str, Row]]:
        blueprint = connection.execute(
            "SELECT * FROM book_blueprints WHERE project_id = ?",
            (candidate.project_id,),
        ).fetchone()
        if blueprint is None or candidate.book_blueprint is None:
            raise PlanRebaseConflictError("rebase_candidate_changed")
        if (
            str(blueprint["id"]) != candidate.book_blueprint.id
            or int(blueprint["revision"]) != candidate.book_blueprint.expected_revision
        ):
            raise PlanRebaseConflictError("rebase_candidate_changed")

        volume_rows = {
            str(row["id"]): row
            for row in connection.execute(
                "SELECT * FROM volume_plans WHERE project_id = ?",
                (candidate.project_id,),
            ).fetchall()
        }
        rolling_rows = {
            str(row["id"]): row
            for row in connection.execute(
                "SELECT * FROM rolling_chapter_plans WHERE project_id = ?",
                (candidate.project_id,),
            ).fetchall()
        }
        if set(volume_rows) != {item.id for item in candidate.volume_plans} or set(
            rolling_rows
        ) != {item.id for item in candidate.rolling_chapter_plans}:
            raise PlanRebaseConflictError("rebase_candidate_changed")
        for volume_item in candidate.volume_plans:
            row = volume_rows[volume_item.id]
            if (
                int(row["revision"]) != volume_item.expected_revision
                or bool(row["locked"]) != volume_item.locked
            ):
                raise PlanRebaseConflictError("rebase_candidate_changed")
        for rolling_item in candidate.rolling_chapter_plans:
            row = rolling_rows[rolling_item.id]
            if (
                int(row["revision"]) != rolling_item.expected_revision
                or bool(row["locked"]) != rolling_item.locked
            ):
                raise PlanRebaseConflictError("rebase_candidate_changed")
        return blueprint, volume_rows, rolling_rows

    @staticmethod
    def _apply_blueprint(
        connection: Connection,
        candidate: PlanRebaseCandidate,
        row: Row,
        timestamp: str,
    ) -> None:
        draft = candidate.book_blueprint
        if draft is None:
            raise PlanRebaseConflictError("rebase_candidate_changed")
        live = DirectorRepository.parse_book_blueprint(row)
        if live.locks != draft.locks:
            raise PlanRebaseConflictError("rebase_candidate_changed")
        before = live.content.model_dump(mode="json")
        after = draft.content.model_dump(mode="json")
        changed = [
            field for field in BookBlueprintField if before[field.value] != after[field.value]
        ]
        for field in changed:
            if live.locks[field]:
                raise PlanRebaseConflictError("locked_blueprint_field")
        versions = dict(live.field_versions)
        for field in changed:
            versions[field] += 1
        next_revision = live.revision + (1 if changed else 0)
        result = connection.execute(
            """
            UPDATE book_blueprints
            SET content_json = ?, field_versions_json = ?, stale_fields_json = '[]',
                plan_stale = 0, revision = ?, updated_at = ?
            WHERE id = ? AND project_id = ? AND revision = ?
            """,
            (
                draft.content.model_dump_json(),
                _json({field.value: value for field, value in versions.items()}),
                next_revision,
                timestamp,
                live.id,
                live.project_id,
                draft.expected_revision,
            ),
        )
        if result.rowcount != 1:
            raise PlanRebaseConflictError("rebase_candidate_changed")
        connection.execute(
            """
            UPDATE projects
            SET title = ?, genre = ?, rebirth_year = ?, rebirth_location = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                draft.content.title,
                draft.content.genre.value,
                draft.content.rebirth_year,
                draft.content.rebirth_location,
                timestamp,
                candidate.project_id,
            ),
        )

    @staticmethod
    def _apply_volume_plans(
        connection: Connection,
        candidate: PlanRebaseCandidate,
        rows: dict[str, Row],
        timestamp: str,
    ) -> None:
        for volume_draft in candidate.volume_plans:
            row = rows[volume_draft.id]
            previous = DirectorRepository.parse_volume_plan(row)
            previous_content = VolumePlanContent.model_validate(
                previous.model_dump(include=set(VolumePlanContent.model_fields))
            )
            if volume_draft.content.volume_number != previous.volume_number:
                raise PlanRebaseConflictError("rebase_candidate_changed")
            if previous.locked and volume_draft.content.model_dump(
                mode="json"
            ) != previous_content.model_dump(mode="json"):
                raise PlanRebaseConflictError("locked_volume_plan")
            if volume_draft.content.model_dump(mode="json") == previous_content.model_dump(
                mode="json"
            ):
                continue
            result = connection.execute(
                """
                UPDATE volume_plans
                SET content_json = ?, revision = revision + 1, updated_at = ?
                WHERE id = ? AND project_id = ? AND revision = ? AND locked = 0
                """,
                (
                    volume_draft.content.model_dump_json(),
                    timestamp,
                    volume_draft.id,
                    candidate.project_id,
                    volume_draft.expected_revision,
                ),
            )
            if result.rowcount != 1:
                raise PlanRebaseConflictError("rebase_candidate_changed")

    @staticmethod
    def _apply_rolling_plans(
        connection: Connection,
        candidate: PlanRebaseCandidate,
        rows: dict[str, Row],
        timestamp: str,
    ) -> None:
        for rolling_draft in candidate.rolling_chapter_plans:
            row = rows[rolling_draft.id]
            previous = DirectorRepository.parse_rolling_plan(row)
            previous_content = RollingChapterPlanContent.model_validate(
                previous.model_dump(
                    include=set(RollingChapterPlanContent.model_fields)
                )
            )
            if rolling_draft.content.chapter_number != previous.chapter_number:
                raise PlanRebaseConflictError("rebase_candidate_changed")
            if previous.locked and rolling_draft.content.model_dump(
                mode="json"
            ) != previous_content.model_dump(mode="json"):
                raise PlanRebaseConflictError("locked_rolling_plan")
            if rolling_draft.content.model_dump(
                mode="json"
            ) == previous_content.model_dump(
                mode="json"
            ):
                continue
            result = connection.execute(
                """
                UPDATE rolling_chapter_plans
                SET content_json = ?, revision = revision + 1, updated_at = ?
                WHERE id = ? AND project_id = ? AND revision = ? AND locked = 0
                """,
                (
                    rolling_draft.content.model_dump_json(),
                    timestamp,
                    rolling_draft.id,
                    candidate.project_id,
                    rolling_draft.expected_revision,
                ),
            )
            if result.rowcount != 1:
                raise PlanRebaseConflictError("rebase_candidate_changed")

    @staticmethod
    def _unique_edits[Edit](edits: list[Edit]) -> dict[str, Edit]:
        result: dict[str, Edit] = {}
        for edit in edits:
            edit_id = getattr(edit, "id", None)
            if not isinstance(edit_id, str) or edit_id in result:
                raise PlanRebaseConflictError("rebase_candidate_changed")
            result[edit_id] = edit
        return result

    def _current_dependency(
        self,
        connection: Connection,
        project_id: str,
    ) -> tuple[ContextDependencySnapshot, str]:
        project = connection.execute(
            "SELECT * FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if project is None:
            raise PlanRebaseNotFoundError(project_id)
        topic = connection.execute(
            """
            SELECT v.id, v.revision, v.content_sha256
            FROM topic_decisions d
            JOIN topic_decision_versions v
              ON v.topic_decision_id = d.id AND v.revision = d.confirmed_revision
            WHERE d.project_id = ? AND d.confirmed_revision = d.revision
            """,
            (project_id,),
        ).fetchone()
        profile = connection.execute(
            """
            SELECT p.id, p.recipe_version_id, p.profile_fingerprint_sha256,
                   p.safety_basis, l.lifecycle_revision
            FROM project_writing_pattern_profiles l
            JOIN writing_pattern_profile_versions p ON p.id = l.profile_version_id
            WHERE l.project_id = ? AND l.lifecycle_state = 'active'
            ORDER BY l.updated_at DESC, l.id LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        blueprint = connection.execute(
            "SELECT * FROM book_blueprints WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        blueprint_digest: str | None = None
        blueprint_ref: ContextDependencyRef | None = None
        if blueprint is not None:
            blueprint_digest = canonical_sha256(
                {
                    "content": json.loads(str(blueprint["content_json"])),
                    "locks": json.loads(str(blueprint["locks_json"])),
                }
            )
            blueprint_ref = ContextDependencyRef(
                id=str(blueprint["id"]),
                revision=int(blueprint["revision"]),
                content_sha256=blueprint_digest,
            )
        subject_sha256 = blueprint_digest or canonical_sha256(
            {
                "title": str(project["title"]),
                "genre": str(project["genre"]),
                "rebirth_year": int(project["rebirth_year"]),
                "rebirth_location": str(project["rebirth_location"]),
                "chapter_target_words": int(project["chapter_target_words"]),
                "safety_buffer_chapters": int(project["safety_buffer_chapters"]),
            }
        )
        source_availability = self._profile_source_availability(connection, profile)
        dependency = ContextDependencySnapshot(
            topic=(
                ContextDependencyRef(
                    id=str(topic["id"]),
                    revision=int(topic["revision"]),
                    content_sha256=str(topic["content_sha256"]),
                )
                if topic is not None
                else None
            ),
            writing_pattern_profile=(
                ContextDependencyRef(
                    id=str(profile["id"]),
                    revision=int(profile["lifecycle_revision"]),
                    content_sha256=str(profile["profile_fingerprint_sha256"]),
                )
                if profile is not None
                else None
            ),
            writing_pattern_source_availability=source_availability,
            base_blueprint=blueprint_ref,
            subject_sha256=subject_sha256,
        )
        return dependency, canonical_sha256(dependency.model_dump(mode="json"))

    def _require_context_usable_in_connection(
        self,
        connection: Connection,
        project_id: str,
    ) -> None:
        if not self._safety_gate_allows(project_id):
            raise PlanRebaseConflictError("context_blocked")
        dependency, _fingerprint = self._current_dependency(connection, project_id)
        if not self._local_context_is_usable(connection, project_id, dependency):
            raise PlanRebaseConflictError("context_blocked")

    def _safety_gate_allows(self, project_id: str) -> bool:
        if self._creative_safety_gate is None:
            return True
        try:
            self._creative_safety_gate.require_creative_safety(project_id)
        except (LookupError, ValueError):
            return False
        return True

    def _local_context_is_usable(
        self,
        connection: Connection,
        project_id: str,
        dependency: ContextDependencySnapshot,
    ) -> bool:
        if dependency.topic is None:
            return False
        if dependency.base_blueprint is None:
            return False
        profile = connection.execute(
            """
            SELECT p.topic_revision, p.topic_content_sha256,
                   p.recipe_content_sha256,
                   rv.content_sha256 AS current_recipe_content_sha256
            FROM project_writing_pattern_profiles l
            JOIN writing_pattern_profile_versions p ON p.id = l.profile_version_id
            JOIN writing_pattern_recipe_versions rv ON rv.id = p.recipe_version_id
            WHERE l.project_id = ? AND l.lifecycle_state = 'active'
            ORDER BY l.updated_at DESC, l.id LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        if profile is None:
            return True
        if self._creative_safety_gate is None:
            return False
        return (
            int(profile["topic_revision"]) == dependency.topic.revision
            and str(profile["topic_content_sha256"])
            == dependency.topic.content_sha256
            and str(profile["recipe_content_sha256"])
            == str(profile["current_recipe_content_sha256"])
        )

    @staticmethod
    def _profile_source_availability(
        connection: Connection,
        profile: Row | None,
    ) -> Literal["source_verified", "abstract_only"] | None:
        if profile is None:
            return None
        source_rows = connection.execute(
            """
            SELECT source_work_fingerprints_json
            FROM writing_pattern_recipe_sources
            WHERE recipe_version_id = ? ORDER BY ordinal
            """,
            (profile["recipe_version_id"],),
        ).fetchall()
        fingerprints: set[tuple[str, str]] = set()
        for source_row in source_rows:
            values = json.loads(str(source_row["source_work_fingerprints_json"]))
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, dict):
                    continue
                basis = value.get("basis")
                identity = value.get("identity_sha256")
                if isinstance(basis, str) and isinstance(identity, str):
                    fingerprints.add((basis, identity))
        if not fingerprints or any(basis == "abstract_lineage" for basis, _ in fingerprints):
            return "abstract_only"
        content_hashes = {identity for _basis, identity in fingerprints}
        placeholders = ",".join("?" for _ in content_hashes)
        available = {
            str(row[0])
            for row in connection.execute(
                f"""
                SELECT DISTINCT content_sha256 FROM reference_works
                WHERE content_sha256 IN ({placeholders})
                """,
                sorted(content_hashes),
            ).fetchall()
        }
        return "source_verified" if available == content_hashes else "abstract_only"

    @staticmethod
    def _planning_targets(
        connection: Connection,
        project_id: str,
    ) -> list[CreativePlanImpactTarget]:
        targets: list[CreativePlanImpactTarget] = []
        blueprint = connection.execute(
            "SELECT id, revision, locks_json FROM book_blueprints WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if blueprint is not None:
            locks = json.loads(str(blueprint["locks_json"]))
            targets.append(
                CreativePlanImpactTarget(
                    kind=CreativePlanSubjectKind.BOOK_BLUEPRINT,
                    id=str(blueprint["id"]),
                    revision=int(blueprint["revision"]),
                    locked=bool(locks) and all(bool(value) for value in locks.values()),
                    state=CreativePlanDependencyState.CURRENT,
                    stale_reasons=[],
                )
            )
        for row in connection.execute(
            """
            SELECT id, revision, locked FROM volume_plans
            WHERE project_id = ? ORDER BY volume_number, id
            """,
            (project_id,),
        ).fetchall():
            targets.append(
                CreativePlanImpactTarget(
                    kind=CreativePlanSubjectKind.VOLUME_PLAN,
                    id=str(row["id"]),
                    revision=int(row["revision"]),
                    locked=bool(row["locked"]),
                    state=CreativePlanDependencyState.CURRENT,
                    stale_reasons=[],
                )
            )
        for row in connection.execute(
            """
            SELECT id, revision, locked FROM rolling_chapter_plans
            WHERE project_id = ? ORDER BY chapter_number, id
            """,
            (project_id,),
        ).fetchall():
            targets.append(
                CreativePlanImpactTarget(
                    kind=CreativePlanSubjectKind.ROLLING_PLAN,
                    id=str(row["id"]),
                    revision=int(row["revision"]),
                    locked=bool(row["locked"]),
                    state=CreativePlanDependencyState.CURRENT,
                    stale_reasons=[],
                )
            )
        return targets

    @staticmethod
    def _dependency_state(
        row: Row,
        current: ContextDependencySnapshot,
        current_fingerprint: str,
    ) -> tuple[CreativePlanDependencyState, list[str]]:
        if row["baseline_state"] == CreativePlanDependencyState.LEGACY.value:
            return CreativePlanDependencyState.LEGACY, ["legacy_dependency_snapshot"]
        if row["dependency_fingerprint_sha256"] == current_fingerprint:
            return CreativePlanDependencyState.CURRENT, []
        previous = ContextDependencySnapshot.model_validate_json(
            str(row["dependency_snapshot_json"])
        )
        reasons: set[str] = set()
        if previous.topic != current.topic:
            reasons.add("topic_dependency_changed")
        if (
            previous.writing_pattern_profile != current.writing_pattern_profile
            or previous.writing_pattern_source_availability
            != current.writing_pattern_source_availability
        ):
            reasons.add("writing_pattern_profile_dependency_changed")
        if previous.base_blueprint != current.base_blueprint:
            reasons.add("base_blueprint_dependency_changed")
        if not reasons:
            reasons.add("creative_context_dependency_changed")
        return CreativePlanDependencyState.STALE, PlanRebaseRepository._ordered_reasons(reasons)

    @staticmethod
    def _ordered_reasons(reasons: set[str]) -> list[str]:
        order = {
            "context_blocked": 0,
            "legacy_dependency_snapshot": 1,
            "topic_dependency_changed": 2,
            "writing_pattern_profile_dependency_changed": 3,
            "base_blueprint_dependency_changed": 4,
            "creative_context_dependency_changed": 5,
        }
        return sorted(reasons, key=lambda item: (order.get(item, 99), item))

    @staticmethod
    def _candidate(row: Row) -> PlanRebaseCandidate:
        return PlanRebaseCandidate(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            state=PlanRebaseCandidateState(str(row["state"])),
            revision=int(row["revision"]),
            based_on_dependency_fingerprint_sha256=str(
                row["based_on_dependency_fingerprint_sha256"]
            ),
            target_dependency_fingerprint_sha256=str(
                row["target_dependency_fingerprint_sha256"]
            ),
            impact=CreativePlanImpactPreview.model_validate_json(str(row["impact_json"])),
            book_blueprint=(
                PlanRebaseBlueprintDraft.model_validate_json(
                    str(row["book_blueprint_json"])
                )
                if row["book_blueprint_json"] is not None
                else None
            ),
            volume_plans=[
                PlanRebaseVolumeDraft.model_validate(item)
                for item in json.loads(str(row["volume_plans_json"]))
            ],
            rolling_chapter_plans=[
                PlanRebaseRollingDraft.model_validate(item)
                for item in json.loads(str(row["rolling_chapter_plans_json"]))
            ],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            adopted_at=(str(row["adopted_at"]) if row["adopted_at"] is not None else None),
        )
