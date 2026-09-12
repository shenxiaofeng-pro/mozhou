from __future__ import annotations

import json
from datetime import UTC, datetime
from sqlite3 import Connection, Row
from typing import cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.database import Database
from app.models import BookBlueprint, BookBlueprintContent, BookBlueprintField
from app.pattern_adaptation.models import (
    PatternAdaptationCandidate,
    PatternAdaptationCandidateSource,
    PatternAdaptationCandidateVersion,
    PatternAdaptationDraftSet,
    PatternAdaptationPreflight,
    PatternAdaptationProposal,
    PatternAdaptationResultState,
)
from app.writing_patterns.compiler import canonical_sha256


class PatternAdaptationNotFoundError(LookupError):
    pass


class PatternAdaptationConflictError(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def candidate_content_sha256(
    blueprint: BookBlueprintContent,
    key_scene_sequence: list[str],
    transformation_notes: list[str],
) -> str:
    return canonical_sha256(
        {
            "schema_version": 1,
            "blueprint": blueprint.model_dump(mode="json"),
            "key_scene_sequence": key_scene_sequence,
            "transformation_notes": transformation_notes,
        }
    )


class PatternAdaptationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_pending_proposal(
        self,
        *,
        job_id: str,
        project_id: str,
        preview: PatternAdaptationPreflight,
        lock_snapshot: dict[BookBlueprintField, bool],
        prompt_version: str,
        input_rate: int | None,
        output_rate: int | None,
    ) -> PatternAdaptationProposal:
        proposal_id = str(uuid5(NAMESPACE_URL, f"mozhou:{job_id}:pattern-adaptation"))
        timestamp = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO writing_pattern_adaptation_proposals (
                    id, job_id, project_id, profile_version_id,
                    profile_fingerprint_sha256, recipe_version_id,
                    recipe_content_sha256, topic_decision_version_id,
                    topic_revision, topic_content_sha256, base_blueprint_id,
                    base_blueprint_revision, base_blueprint_content_sha256,
                    lock_snapshot_json, lock_snapshot_sha256,
                    dependency_fingerprint_sha256, safe_context_sha256,
                    provider, provider_profile_id, provider_profile_revision, model,
                    input_cost_microusd_per_million,
                    output_cost_microusd_per_million, prompt_version,
                    estimated_input_tokens, estimated_output_tokens,
                    estimated_cost_microusd, cost_status, result_state,
                    stale_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, ?, ?)
                ON CONFLICT(job_id) DO NOTHING
                """,
                (
                    proposal_id,
                    job_id,
                    project_id,
                    preview.profile_version_id,
                    preview.profile_fingerprint_sha256,
                    preview.recipe_version_id,
                    preview.recipe_content_sha256,
                    preview.topic_decision_version_id,
                    preview.topic_revision,
                    preview.topic_content_sha256,
                    preview.base_blueprint_id,
                    preview.base_blueprint_revision,
                    preview.base_blueprint_content_sha256,
                    _json({field.value: lock_snapshot[field] for field in BookBlueprintField}),
                    preview.lock_snapshot_sha256,
                    preview.dependency_fingerprint_sha256,
                    preview.safe_context_sha256,
                    preview.provider,
                    preview.provider_profile_id,
                    preview.provider_profile_revision,
                    preview.model,
                    input_rate,
                    output_rate,
                    prompt_version,
                    preview.estimated_input_tokens,
                    preview.estimated_output_tokens,
                    preview.estimated_cost_microusd,
                    preview.cost_status.value,
                    timestamp,
                    timestamp,
                ),
            )
        return self.get_by_job(job_id)

    def get_by_job(self, job_id: str) -> PatternAdaptationProposal:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM writing_pattern_adaptation_proposals WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise PatternAdaptationNotFoundError(job_id)
            candidates = self._candidate_rows(connection, str(row["id"]))
        return self._proposal(row, candidates)

    def get_proposal(self, project_id: str, proposal_id: str) -> PatternAdaptationProposal:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM writing_pattern_adaptation_proposals
                WHERE id = ? AND project_id = ?
                """,
                (proposal_id, project_id),
            ).fetchone()
            if row is None:
                raise PatternAdaptationNotFoundError(proposal_id)
            candidates = self._candidate_rows(connection, proposal_id)
        return self._proposal(row, candidates)

    def persist_candidates(
        self,
        proposal_id: str,
        drafts: PatternAdaptationDraftSet,
    ) -> PatternAdaptationProposal:
        timestamp = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            proposal = connection.execute(
                "SELECT * FROM writing_pattern_adaptation_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
            if proposal is None:
                raise PatternAdaptationNotFoundError(proposal_id)
            existing = connection.execute(
                """
                SELECT COUNT(*) FROM writing_pattern_adaptation_candidates
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()[0]
            if existing:
                if existing != 3:
                    raise PatternAdaptationConflictError("candidate_set_incomplete")
            else:
                for ordinal, draft in enumerate(drafts.candidates, start=1):
                    candidate_id = str(
                        uuid5(
                            NAMESPACE_URL,
                            f"mozhou:{proposal['job_id']}:pattern-candidate:{ordinal}",
                        )
                    )
                    digest = candidate_content_sha256(
                        draft.blueprint,
                        draft.key_scene_sequence,
                        draft.transformation_notes,
                    )
                    version_id = str(uuid5(NAMESPACE_URL, f"{candidate_id}:revision:0:{digest}"))
                    connection.execute(
                        """
                        INSERT INTO writing_pattern_adaptation_candidates (
                            id, proposal_id, ordinal, label, why_distinct,
                            distinct_axes_json, risk_hypotheses_json,
                            current_revision, current_content_sha256,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                        """,
                        (
                            candidate_id,
                            proposal_id,
                            ordinal,
                            draft.label,
                            draft.why_distinct,
                            _json([axis.value for axis in draft.distinct_axes]),
                            _json(draft.risk_hypotheses),
                            digest,
                            timestamp,
                            timestamp,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO writing_pattern_adaptation_candidate_versions (
                            id, candidate_id, revision, blueprint_json,
                            key_scene_sequence_json, transformation_notes_json,
                            content_sha256, changed_fields_json, source, created_at
                        ) VALUES (?, ?, 0, ?, ?, ?, ?, ?, 'model', ?)
                        """,
                        (
                            version_id,
                            candidate_id,
                            draft.blueprint.model_dump_json(),
                            _json(draft.key_scene_sequence),
                            _json(draft.transformation_notes),
                            digest,
                            _json([field.value for field in BookBlueprintField]),
                            timestamp,
                        ),
                    )
            connection.execute(
                """
                UPDATE writing_pattern_adaptation_proposals
                SET result_state = 'available', stale_reason = NULL, updated_at = ?
                WHERE id = ? AND result_state = 'pending'
                """,
                (timestamp, proposal_id),
            )
            updated = connection.execute(
                "SELECT * FROM writing_pattern_adaptation_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
            assert updated is not None
            candidates = self._candidate_rows(connection, proposal_id)
        return self._proposal(updated, candidates)

    def mark_stale(self, proposal_id: str, reason: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE writing_pattern_adaptation_proposals
                SET result_state = 'stale', stale_reason = ?, updated_at = ?
                WHERE id = ? AND result_state != 'invalid'
                """,
                (reason[:200], _now(), proposal_id),
            )

    def mark_invalid(self, proposal_id: str, reason: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE writing_pattern_adaptation_proposals
                SET result_state = 'invalid', stale_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (reason[:200], _now(), proposal_id),
            )

    def edit_candidate(
        self,
        *,
        project_id: str,
        candidate_id: str,
        blueprint: BookBlueprintContent,
        key_scene_sequence: list[str],
        transformation_notes: list[str],
        changed_fields: list[BookBlueprintField],
        expected_revision: int,
        expected_content_sha256: str,
    ) -> PatternAdaptationCandidate:
        digest = candidate_content_sha256(
            blueprint,
            key_scene_sequence,
            transformation_notes,
        )
        timestamp = _now()
        next_revision = expected_revision + 1
        version_id = str(uuid4())
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._candidate_join(connection, project_id, candidate_id)
            if row is None:
                raise PatternAdaptationNotFoundError(candidate_id)
            current = self._candidate_version(row)
            before = current.blueprint.model_dump(mode="json")
            after = blueprint.model_dump(mode="json")
            actual = [
                field for field in BookBlueprintField if before[field.value] != after[field.value]
            ]
            if set(actual) != set(changed_fields):
                raise PatternAdaptationConflictError("declared_fields_do_not_match")
            if (
                int(row["current_revision"]) != expected_revision
                or row["current_content_sha256"] != expected_content_sha256
            ):
                raise PatternAdaptationConflictError("candidate_changed")
            if digest == current.content_sha256:
                return self._candidate(row)
            locks = {
                BookBlueprintField(key): bool(value)
                for key, value in json.loads(str(row["lock_snapshot_json"])).items()
            }
            base = self._base_blueprint(connection, row)
            for field in BookBlueprintField:
                if locks[field] and (
                    base is None
                    or after[field.value] != base.content.model_dump(mode="json")[field.value]
                ):
                    raise PatternAdaptationConflictError("locked_field")
            connection.execute(
                """
                INSERT INTO writing_pattern_adaptation_candidate_versions (
                    id, candidate_id, revision, blueprint_json,
                    key_scene_sequence_json, transformation_notes_json,
                    content_sha256, changed_fields_json, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'author_edit', ?)
                """,
                (
                    version_id,
                    candidate_id,
                    next_revision,
                    blueprint.model_dump_json(),
                    _json(key_scene_sequence),
                    _json(transformation_notes),
                    digest,
                    _json([field.value for field in changed_fields]),
                    timestamp,
                ),
            )
            result = connection.execute(
                """
                UPDATE writing_pattern_adaptation_candidates
                SET current_revision = ?, current_content_sha256 = ?, updated_at = ?
                WHERE id = ? AND current_revision = ? AND current_content_sha256 = ?
                """,
                (
                    next_revision,
                    digest,
                    timestamp,
                    candidate_id,
                    expected_revision,
                    expected_content_sha256,
                ),
            )
            if result.rowcount != 1:
                raise PatternAdaptationConflictError("candidate_changed")
            updated = self._candidate_join(connection, project_id, candidate_id)
            assert updated is not None
        return self._candidate(updated)

    @staticmethod
    def _base_blueprint(connection: Connection, row: Row) -> BookBlueprint | None:
        from app.director.repository import DirectorRepository

        if row["base_blueprint_id"] is None:
            return None
        base = connection.execute(
            "SELECT * FROM book_blueprints WHERE id = ?",
            (row["base_blueprint_id"],),
        ).fetchone()
        return DirectorRepository.parse_book_blueprint(base) if base is not None else None

    @staticmethod
    def _candidate_rows(connection: Connection, proposal_id: str) -> list[Row]:
        return cast(
            list[Row],
            connection.execute(
                """
                SELECT c.*, p.project_id, p.result_state, p.lock_snapshot_json,
                       p.base_blueprint_id, p.base_blueprint_revision,
                       p.base_blueprint_content_sha256,
                       v.id AS version_id, v.blueprint_json,
                       v.key_scene_sequence_json, v.transformation_notes_json,
                       v.changed_fields_json, v.source, v.created_at AS version_created_at
                FROM writing_pattern_adaptation_candidates c
                JOIN writing_pattern_adaptation_proposals p ON p.id = c.proposal_id
                JOIN writing_pattern_adaptation_candidate_versions v
                  ON v.candidate_id = c.id AND v.revision = c.current_revision
                WHERE c.proposal_id = ? ORDER BY c.ordinal
                """,
                (proposal_id,),
            ).fetchall(),
        )

    @staticmethod
    def _candidate_join(
        connection: Connection,
        project_id: str,
        candidate_id: str,
    ) -> Row | None:
        return cast(
            Row | None,
            connection.execute(
                """
                SELECT c.*, p.project_id, p.result_state, p.lock_snapshot_json,
                       p.base_blueprint_id, p.base_blueprint_revision,
                       p.base_blueprint_content_sha256,
                       v.id AS version_id, v.blueprint_json,
                       v.key_scene_sequence_json, v.transformation_notes_json,
                       v.changed_fields_json, v.source, v.created_at AS version_created_at
                FROM writing_pattern_adaptation_candidates c
                JOIN writing_pattern_adaptation_proposals p ON p.id = c.proposal_id
                JOIN writing_pattern_adaptation_candidate_versions v
                  ON v.candidate_id = c.id AND v.revision = c.current_revision
                WHERE c.id = ? AND p.project_id = ?
                """,
                (candidate_id, project_id),
            ).fetchone(),
        )

    @staticmethod
    def _candidate_version(row: Row) -> PatternAdaptationCandidateVersion:
        return PatternAdaptationCandidateVersion(
            id=str(row["version_id"]),
            candidate_id=str(row["id"]),
            revision=int(row["current_revision"]),
            blueprint=BookBlueprintContent.model_validate_json(str(row["blueprint_json"])),
            key_scene_sequence=json.loads(str(row["key_scene_sequence_json"])),
            transformation_notes=json.loads(str(row["transformation_notes_json"])),
            content_sha256=str(row["current_content_sha256"]),
            changed_fields=[
                BookBlueprintField(value) for value in json.loads(str(row["changed_fields_json"]))
            ],
            source=PatternAdaptationCandidateSource(str(row["source"])),
            created_at=str(row["version_created_at"]),
        )

    @classmethod
    def _candidate(cls, row: Row) -> PatternAdaptationCandidate:
        return PatternAdaptationCandidate(
            id=str(row["id"]),
            proposal_id=str(row["proposal_id"]),
            ordinal=int(row["ordinal"]),
            label=str(row["label"]),
            why_distinct=str(row["why_distinct"]),
            distinct_axes=json.loads(str(row["distinct_axes_json"])),
            risk_hypotheses=json.loads(str(row["risk_hypotheses_json"])),
            current_version=cls._candidate_version(row),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @classmethod
    def _proposal(cls, row: Row, candidates: list[Row]) -> PatternAdaptationProposal:
        return PatternAdaptationProposal(
            id=str(row["id"]),
            job_id=str(row["job_id"]),
            project_id=str(row["project_id"]),
            profile_version_id=str(row["profile_version_id"]),
            profile_fingerprint_sha256=str(row["profile_fingerprint_sha256"]),
            recipe_version_id=str(row["recipe_version_id"]),
            recipe_content_sha256=str(row["recipe_content_sha256"]),
            topic_decision_version_id=str(row["topic_decision_version_id"]),
            topic_revision=int(row["topic_revision"]),
            topic_content_sha256=str(row["topic_content_sha256"]),
            base_blueprint_id=(
                str(row["base_blueprint_id"]) if row["base_blueprint_id"] is not None else None
            ),
            base_blueprint_revision=(
                int(row["base_blueprint_revision"])
                if row["base_blueprint_revision"] is not None
                else None
            ),
            base_blueprint_content_sha256=(
                str(row["base_blueprint_content_sha256"])
                if row["base_blueprint_content_sha256"] is not None
                else None
            ),
            dependency_fingerprint_sha256=str(row["dependency_fingerprint_sha256"]),
            safe_context_sha256=str(row["safe_context_sha256"]),
            lock_snapshot_sha256=str(row["lock_snapshot_sha256"]),
            provider=str(row["provider"]),
            provider_profile_id=(
                str(row["provider_profile_id"]) if row["provider_profile_id"] is not None else None
            ),
            provider_profile_revision=(
                int(row["provider_profile_revision"])
                if row["provider_profile_revision"] is not None
                else None
            ),
            model=str(row["model"]),
            input_cost_microusd_per_million=(
                int(row["input_cost_microusd_per_million"])
                if row["input_cost_microusd_per_million"] is not None
                else None
            ),
            output_cost_microusd_per_million=(
                int(row["output_cost_microusd_per_million"])
                if row["output_cost_microusd_per_million"] is not None
                else None
            ),
            result_state=PatternAdaptationResultState(str(row["result_state"])),
            stale_reason=(str(row["stale_reason"]) if row["stale_reason"] else None),
            candidates=[cls._candidate(item) for item in candidates],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
