from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from itertools import combinations
from sqlite3 import Connection, Row
from typing import Literal, Protocol, cast
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import BaseModel

from app.ai import (
    AiGateway,
    AiGatewayManager,
    AiNotConfiguredError,
    AiProviderError,
    consume_ai_call_metrics,
)
from app.context.compiler import estimate_tokens
from app.creative_safety import CreativeSafetyProvenance
from app.database import Database
from app.director.repository import DirectorRepository
from app.jobs.models import AttemptState, Job, JobKind
from app.jobs.repository import JobRepository
from app.jobs.runtime import JobExecutionContext, JobExecutionError
from app.models import (
    AiStatus,
    BookBlueprint,
    BookBlueprintContent,
    BookBlueprintField,
    OriginalityRiskLevel,
    OriginalityStatus,
)
from app.pattern_adaptation.context import (
    build_safe_adaptation_context,
    source_sensitive_terms,
)
from app.pattern_adaptation.models import (
    AdoptPatternAdaptationCandidateRequest,
    AdoptPatternAdaptationResult,
    EditPatternAdaptationCandidateRequest,
    PatternAdaptationAdoption,
    PatternAdaptationCandidate,
    PatternAdaptationCostStatus,
    PatternAdaptationDraft,
    PatternAdaptationDraftSet,
    PatternAdaptationPreflight,
    PatternAdaptationPreflightRequest,
    PatternAdaptationProposal,
    PatternAdaptationResultState,
    PatternDistinctAxis,
    PatternOriginalityFindingRecord,
    PatternOriginalityGateState,
    PatternOriginalityReport,
    RunPatternOriginalityGuardRequest,
    SubmitPatternAdaptationRequest,
)
from app.pattern_adaptation.originality import (
    THRESHOLD_VERSION,
    PatternOriginalityAssessment,
    assess_pattern_adaptation_originality,
)
from app.pattern_adaptation.repository import (
    PatternAdaptationConflictError,
    PatternAdaptationNotFoundError,
    PatternAdaptationRepository,
    candidate_content_sha256,
)
from app.providers import AiTaskType, ModelProfile, ModelProfileRepository
from app.repository import now_iso
from app.topic_decisions import (
    TopicDecisionNotConfirmedError,
    TopicDecisionNotFoundError,
    TopicDecisionService,
)
from app.writing_patterns.compiler import canonical_sha256
from app.writing_patterns.models import (
    WritingPatternLifecycleState,
    WritingPatternProfileVersion,
    WritingPatternSafetyBasis,
)
from app.writing_patterns.repository import (
    WritingPatternError,
    WritingPatternNotFoundError,
    WritingPatternRepository,
)

PATTERN_ADAPTATION_PROMPT_VERSION = "pattern-adaptation-v1"
PATTERN_ADAPTATION_WORKFLOW = "pattern_adaptation"
PATTERN_ADAPTATION_OUTPUT_TOKENS = 12_000


class PatternAdaptationGateway(Protocol):
    def propose_pattern_adaptations(self, context_text: str) -> PatternAdaptationDraftSet: ...


class PatternOriginalityGateError(ValueError):
    pass


class _PatternAdaptationJobInput(BaseModel):
    project_id: str
    dependency_fingerprint_sha256: str
    safe_context_sha256: str
    preview_sha256: str
    source_availability: WritingPatternSafetyBasis
    prompt_version: str


@dataclass(frozen=True)
class _PlannedAdaptation:
    preview: PatternAdaptationPreflight
    context_text: str
    profile: WritingPatternProfileVersion
    input_rate: int | None
    output_rate: int | None
    is_local: bool
    protected_titles: list[str]


def _local_endpoint(profile: ModelProfile | None, gateway: AiGateway) -> bool:
    if bool(getattr(gateway, "is_local", False)):
        return True
    if profile is None:
        return False
    hostname = (urlparse(profile.base_url).hostname or "").casefold()
    return hostname in {"localhost", "127.0.0.1", "::1"}


class PatternAdaptationService:
    def __init__(
        self,
        database: Database,
        jobs: JobRepository,
        manager: AiGatewayManager,
        profiles: ModelProfileRepository,
        topic_decisions: TopicDecisionService,
    ) -> None:
        self.database = database
        self.jobs = jobs
        self.manager = manager
        self.profiles = profiles
        self.topic_decisions = topic_decisions
        self.patterns = WritingPatternRepository(database)
        self.director = DirectorRepository(database)
        self.repository = PatternAdaptationRepository(database)

    def preview(
        self,
        project_id: str,
        request: PatternAdaptationPreflightRequest,
    ) -> PatternAdaptationPreflight:
        return self._plan(project_id, request).preview

    def submit(self, project_id: str, request: SubmitPatternAdaptationRequest) -> Job:
        planned = self._plan(
            project_id,
            PatternAdaptationPreflightRequest.model_validate(
                request.model_dump(
                    exclude={
                        "expected_preview_sha256",
                        "confirm_external_processing",
                        "max_estimated_cost_microusd",
                    }
                )
            ),
        )
        preview = planned.preview
        if preview.preview_sha256 != request.expected_preview_sha256:
            raise PatternAdaptationConflictError("preview_changed")
        if preview.cost_status == PatternAdaptationCostStatus.UNAVAILABLE:
            raise PatternAdaptationConflictError("cost_unavailable")
        if not planned.is_local:
            if not request.confirm_external_processing:
                raise PatternAdaptationConflictError("external_processing_not_confirmed")
            if request.max_estimated_cost_microusd is None:
                raise PatternAdaptationConflictError("cost_limit_required")
        if (
            request.max_estimated_cost_microusd is not None
            and preview.estimated_cost_microusd is not None
            and preview.estimated_cost_microusd > request.max_estimated_cost_microusd
        ):
            raise PatternAdaptationConflictError("estimated_cost_exceeds_limit")

        idempotency_key = canonical_sha256(
            {
                "workflow": PATTERN_ADAPTATION_WORKFLOW,
                "project_id": project_id,
                "preview_sha256": preview.preview_sha256,
            }
        )
        task = _PatternAdaptationJobInput(
            project_id=project_id,
            dependency_fingerprint_sha256=preview.dependency_fingerprint_sha256,
            safe_context_sha256=preview.safe_context_sha256,
            preview_sha256=preview.preview_sha256,
            source_availability=preview.source_availability,
            prompt_version=PATTERN_ADAPTATION_PROMPT_VERSION,
        )
        # The proposal UUID is deterministic from the resulting job UUID, so the job
        # input deliberately does not carry author text or any source identity.
        job, _created = self.jobs.create_job(
            project_id=project_id,
            kind=JobKind.PATTERN_ADAPTATION,
            workflow=PATTERN_ADAPTATION_WORKFLOW,
            idempotency_key=idempotency_key,
            input_payload=task.model_dump(mode="json"),
            provider=preview.provider,
            provider_profile_id=preview.provider_profile_id,
            model=preview.model,
            progress_total=1,
            estimated_calls=1,
        )
        self.repository.create_pending_proposal(
            job_id=job.id,
            project_id=project_id,
            preview=preview,
            lock_snapshot=self._locks_for_project(project_id),
            prompt_version=PATTERN_ADAPTATION_PROMPT_VERSION,
            input_rate=planned.input_rate,
            output_rate=planned.output_rate,
        )
        self.jobs.put_artifact(
            job.id,
            kind="pattern_adaptation_context",
            artifact_key="pattern-adaptation-context",
            payload=planned.context_text,
            content_type="application/json",
            provider="local",
            model=PATTERN_ADAPTATION_PROMPT_VERSION,
            metadata={
                "dependency_fingerprint_sha256": preview.dependency_fingerprint_sha256,
                "safe_context_sha256": preview.safe_context_sha256,
                "profile_fingerprint_sha256": preview.profile_fingerprint_sha256,
                "recipe_content_sha256": preview.recipe_content_sha256,
                "topic_revision": preview.topic_revision,
                "base_blueprint_revision": preview.base_blueprint_revision,
            },
        )
        return self.jobs.get_job(job.id)

    def handle(self, context: JobExecutionContext, job: Job) -> None:
        if job.kind != JobKind.PATTERN_ADAPTATION or job.workflow != PATTERN_ADAPTATION_WORKFLOW:
            raise JobExecutionError("invalid_workflow", "原创迁移任务类型无效")
        task = _PatternAdaptationJobInput.model_validate(self.jobs.load_input(job.id))
        if (
            task.project_id != job.project_id
            or task.prompt_version != PATTERN_ADAPTATION_PROMPT_VERSION
        ):
            raise JobExecutionError("invalid_input", "原创迁移任务输入无效")
        proposal = self.repository.get_by_job(job.id)
        if len(proposal.candidates) == 3:
            self.jobs.update_progress(job.id, current=1, total=1, step="3 套原创迁移方案已恢复")
            return
        self._require_job_dependencies(proposal, task, job)
        context_artifact = self.jobs.find_artifact(job.id, "pattern-adaptation-context")
        if (
            context_artifact is None
            or sha256(context_artifact.payload.encode()).hexdigest() != proposal.safe_context_sha256
            or proposal.safe_context_sha256 != task.safe_context_sha256
        ):
            raise JobExecutionError("context_invalid", "原创迁移冻结上下文无效")
        context.checkpoint()
        gateway = self._gateway_for_job(job)
        if not hasattr(gateway, "propose_pattern_adaptations"):
            raise JobExecutionError("unsupported_capability", "当前模型线路不支持原创迁移")
        attempt = self.jobs.start_attempt(
            job.id,
            provider=job.provider,
            provider_profile_id=job.provider_profile_id,
            model=job.model,
        )
        try:
            drafts = cast(PatternAdaptationGateway, gateway).propose_pattern_adaptations(
                context_artifact.payload
            )
            normalized = self._normalize_and_validate_drafts(proposal, drafts)
            metrics = consume_ai_call_metrics(gateway)
            self.jobs.finish_attempt(
                attempt.id,
                AttemptState.SUCCEEDED,
                input_tokens=metrics.usage.input_tokens if metrics else None,
                output_tokens=metrics.usage.output_tokens if metrics else None,
                duration_ms=metrics.duration_ms if metrics else None,
                estimated_cost_microusd=(metrics.estimated_cost_microusd if metrics else None),
            )
        except AiProviderError as error:
            self.jobs.finish_attempt(
                attempt.id,
                AttemptState.FAILED,
                duration_ms=error.duration_ms,
                error_code=error.category.value,
                error_message=error.safe_message,
            )
            raise JobExecutionError(error.category.value, error.safe_message) from error
        except (PatternAdaptationConflictError, ValueError) as error:
            self.jobs.finish_attempt(
                attempt.id,
                AttemptState.FAILED,
                error_code="invalid_response",
                error_message="AI 返回的原创迁移方案未通过结构校验",
            )
            self.repository.mark_invalid(proposal.id, str(error))
            raise JobExecutionError(
                "invalid_response",
                "AI 返回的原创迁移方案未通过结构校验",
            ) from error

        self.jobs.put_artifact(
            job.id,
            kind="pattern_adaptation_drafts",
            artifact_key="pattern-adaptation-drafts",
            payload=normalized.model_dump_json(),
            content_type="application/json",
            provider=job.provider,
            provider_profile_id=job.provider_profile_id,
            model=job.model,
            metadata={
                "candidate_count": 3,
                "dependency_fingerprint_sha256": proposal.dependency_fingerprint_sha256,
                "profile_fingerprint_sha256": proposal.profile_fingerprint_sha256,
                "recipe_content_sha256": proposal.recipe_content_sha256,
            },
        )
        persisted = self.repository.persist_candidates(proposal.id, normalized)
        try:
            self._require_job_dependencies(persisted, task, job)
        except JobExecutionError as error:
            self.repository.mark_stale(proposal.id, error.code)
            raise
        self.jobs.update_progress(job.id, current=1, total=1, step="3 套原创迁移方案已生成")

    def get_result(self, project_id: str, job_id: str) -> PatternAdaptationProposal:
        job = self.jobs.get_job(job_id)
        if (
            job.project_id != project_id
            or job.kind != JobKind.PATTERN_ADAPTATION
            or job.workflow != PATTERN_ADAPTATION_WORKFLOW
        ):
            raise PatternAdaptationNotFoundError(job_id)
        proposal = self.repository.get_by_job(job_id)
        if proposal.result_state == PatternAdaptationResultState.AVAILABLE:
            task = _PatternAdaptationJobInput.model_validate(self.jobs.load_input(job_id))
            try:
                self._require_job_dependencies(proposal, task, job)
            except JobExecutionError as error:
                return proposal.model_copy(
                    update={
                        "result_state": PatternAdaptationResultState.STALE,
                        "stale_reason": error.code,
                    }
                )
        return proposal

    def edit_candidate(
        self,
        project_id: str,
        candidate_id: str,
        request: EditPatternAdaptationCandidateRequest,
    ) -> PatternAdaptationCandidate:
        proposal = self._proposal_for_candidate(project_id, candidate_id)
        job = self.jobs.get_job(proposal.job_id)
        task = _PatternAdaptationJobInput.model_validate(self.jobs.load_input(proposal.job_id))
        try:
            self._require_job_dependencies(proposal, task, job)
        except JobExecutionError as error:
            raise PatternAdaptationConflictError("proposal_stale") from error
        current = next(item for item in proposal.candidates if item.id == candidate_id)
        locks, base = self._proposal_lock_context(proposal)
        before = current.current_version.blueprint.model_dump(mode="json")
        after = request.blueprint.model_dump(mode="json")
        for field in BookBlueprintField:
            if locks[field] and (base is None or after[field.value] != base[field.value]):
                raise PatternAdaptationConflictError("locked_field")
        if (
            base is not None
            and not locks[BookBlueprintField.RELATIONSHIP_DESIGN]
            and after[BookBlueprintField.RELATIONSHIP_DESIGN.value]
            == base[BookBlueprintField.RELATIONSHIP_DESIGN.value]
        ):
            raise PatternAdaptationConflictError("relationships_must_be_rebuilt")
        actual = {
            field for field in BookBlueprintField if before[field.value] != after[field.value]
        }
        if actual != set(request.changed_fields):
            raise PatternAdaptationConflictError("declared_fields_do_not_match")
        return self.repository.edit_candidate(
            project_id=project_id,
            candidate_id=candidate_id,
            blueprint=request.blueprint,
            key_scene_sequence=request.key_scene_sequence,
            transformation_notes=request.transformation_notes,
            changed_fields=request.changed_fields,
            expected_revision=request.expected_revision,
            expected_content_sha256=request.expected_content_sha256,
        )

    def adopt_candidate(
        self,
        project_id: str,
        candidate_id: str,
        request: AdoptPatternAdaptationCandidateRequest,
    ) -> AdoptPatternAdaptationResult:
        proposal = self._proposal_for_candidate(project_id, candidate_id)
        if (
            self.get_result(project_id, proposal.job_id).result_state
            != PatternAdaptationResultState.AVAILABLE
        ):
            raise PatternAdaptationConflictError("proposal_stale")
        candidate = next(item for item in proposal.candidates if item.id == candidate_id)
        version = candidate.current_version
        self._validate_adoption_request(proposal, version.revision, version.content_sha256, request)
        timestamp = now_iso()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = connection.execute(
                """
                SELECT * FROM writing_pattern_adoptions
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, request.idempotency_key),
            ).fetchone()
            if replay is not None:
                if (
                    replay["candidate_id"] != candidate_id
                    or replay["candidate_version_id"] != version.id
                ):
                    raise PatternAdaptationConflictError("idempotency_conflict")
                blueprint_row = connection.execute(
                    "SELECT * FROM book_blueprints WHERE id = ?",
                    (replay["blueprint_id"],),
                ).fetchone()
                if blueprint_row is None:
                    raise PatternAdaptationNotFoundError("adopted_blueprint_missing")
                return AdoptPatternAdaptationResult(
                    adoption=self._adoption(replay),
                    blueprint=DirectorRepository.parse_book_blueprint(blueprint_row),
                )
            self._assert_atomic_dependencies(connection, proposal, request)
            current_row = connection.execute(
                "SELECT * FROM book_blueprints WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            content = version.blueprint
            content_hash = canonical_sha256(content.model_dump(mode="json"))
            if current_row is None:
                if proposal.base_blueprint_id is not None:
                    raise PatternAdaptationConflictError("base_blueprint_changed")
                blueprint_id = str(uuid4())
                revision = 0
                field_versions = {field: 1 for field in BookBlueprintField}
                connection.execute(
                    """
                    INSERT INTO book_blueprints (
                        id, project_id, idea, content_json, locks_json,
                        field_versions_json, stale_fields_json, plan_stale,
                        source_candidate_id, revision, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, '[]', 1, ?, 0, ?, ?)
                    """,
                    (
                        blueprint_id,
                        project_id,
                        self._topic_premise(connection, project_id),
                        content.model_dump_json(),
                        json.dumps(
                            {field.value: False for field in BookBlueprintField},
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        json.dumps(
                            {field.value: 1 for field in BookBlueprintField},
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        candidate_id,
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                current = DirectorRepository.parse_book_blueprint(current_row)
                if (
                    proposal.base_blueprint_id != current.id
                    or proposal.base_blueprint_revision != current.revision
                    or proposal.base_blueprint_content_sha256
                    != canonical_sha256(current.content.model_dump(mode="json"))
                ):
                    raise PatternAdaptationConflictError("base_blueprint_changed")
                before = current.content.model_dump(mode="json")
                after = content.model_dump(mode="json")
                for field in BookBlueprintField:
                    if current.locks[field] and before[field.value] != after[field.value]:
                        raise PatternAdaptationConflictError("locked_field")
                field_versions = dict(current.field_versions)
                changed = [
                    field
                    for field in BookBlueprintField
                    if before[field.value] != after[field.value]
                ]
                for field in changed:
                    field_versions[field] += 1
                blueprint_id = current.id
                revision = current.revision + 1
                result = connection.execute(
                    """
                    UPDATE book_blueprints
                    SET content_json = ?, field_versions_json = ?,
                        stale_fields_json = ?, plan_stale = 1,
                        source_candidate_id = ?, revision = ?, updated_at = ?
                    WHERE id = ? AND revision = ?
                    """,
                    (
                        content.model_dump_json(),
                        json.dumps(
                            {field.value: field_versions[field] for field in BookBlueprintField},
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        json.dumps(
                            [field.value for field in changed],
                            separators=(",", ":"),
                        ),
                        candidate_id,
                        revision,
                        timestamp,
                        blueprint_id,
                        current.revision,
                    ),
                )
                if result.rowcount != 1:
                    raise PatternAdaptationConflictError("base_blueprint_changed")
            DirectorRepository._sync_project(connection, project_id, content, timestamp)
            adoption_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO writing_pattern_adoptions (
                    id, project_id, proposal_id, candidate_id,
                    candidate_version_id, blueprint_id, blueprint_revision,
                    blueprint_content_sha256, profile_fingerprint_sha256,
                    recipe_content_sha256, idempotency_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    adoption_id,
                    project_id,
                    proposal.id,
                    candidate_id,
                    version.id,
                    blueprint_id,
                    revision,
                    content_hash,
                    proposal.profile_fingerprint_sha256,
                    proposal.recipe_content_sha256,
                    request.idempotency_key,
                    timestamp,
                ),
            )
            adoption_row = connection.execute(
                "SELECT * FROM writing_pattern_adoptions WHERE id = ?",
                (adoption_id,),
            ).fetchone()
            blueprint_row = connection.execute(
                "SELECT * FROM book_blueprints WHERE id = ?",
                (blueprint_id,),
            ).fetchone()
        assert adoption_row is not None and blueprint_row is not None
        return AdoptPatternAdaptationResult(
            adoption=self._adoption(adoption_row),
            blueprint=DirectorRepository.parse_book_blueprint(blueprint_row),
        )

    def run_originality_guard(
        self,
        project_id: str,
        request: RunPatternOriginalityGuardRequest,
    ) -> PatternOriginalityReport:
        adoption, candidate, profile, blueprint = self._current_adoption_inputs(project_id)
        blueprint_hash = canonical_sha256(blueprint.content.model_dump(mode="json"))
        if (
            blueprint.revision != request.expected_blueprint_revision
            or blueprint_hash != request.expected_blueprint_content_sha256
            or adoption.profile_fingerprint_sha256 != request.expected_profile_fingerprint_sha256
            or adoption.recipe_content_sha256 != request.expected_recipe_content_sha256
        ):
            raise PatternOriginalityGateError("guard_dependencies_changed")
        recipe = self.patterns.get_recipe_version(profile.recipe_version_id)
        source_availability = self.patterns.verify_recipe_sources(
            project_id,
            recipe.sources,
            require_project_link=False,
        )
        work_fingerprints = sorted(
            {
                fingerprint.identity_sha256
                for source in recipe.sources
                for fingerprint in source.source_work_fingerprints
            }
        )
        assessment = assess_pattern_adaptation_originality(
            profile.model_safe_profile,
            blueprint.content,
            candidate.current_version.key_scene_sequence,
            source_work_fingerprints=work_fingerprints,
        )
        if source_availability == WritingPatternSafetyBasis.ABSTRACT_ONLY:
            assessment = assessment.model_copy(
                update={
                    "risk_level": max(
                        assessment.risk_level,
                        OriginalityRiskLevel.MEDIUM,
                        key=lambda value: {
                            OriginalityRiskLevel.LOW: 0,
                            OriginalityRiskLevel.MEDIUM: 1,
                            OriginalityRiskLevel.HIGH: 2,
                        }[value],
                    ),
                    "score": max(assessment.score, 45),
                }
            )
        assessment = assessment.model_copy(
            update={
                "input_sha256": canonical_sha256(
                    {
                        "assessment_input_sha256": assessment.input_sha256,
                        "source_availability": source_availability.value,
                    }
                )
            }
        )
        return self._persist_originality_report(
            adoption,
            candidate,
            blueprint,
            assessment,
            source_availability,
        )

    def get_originality_report(self, report_id: str) -> PatternOriginalityReport:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM writing_pattern_originality_reports WHERE id = ?",
                (report_id,),
            ).fetchone()
            if row is None:
                raise PatternAdaptationNotFoundError(report_id)
            findings = connection.execute(
                """
                SELECT * FROM writing_pattern_originality_findings
                WHERE report_id = ? ORDER BY ordinal
                """,
                (report_id,),
            ).fetchall()
        return self._report(row, findings)

    def view_originality_report(self, report_id: str) -> PatternOriginalityReport:
        with self.database.connect() as connection:
            result = connection.execute(
                """
                UPDATE writing_pattern_originality_reports
                SET viewed_at = COALESCE(viewed_at, ?)
                WHERE id = ?
                """,
                (now_iso(), report_id),
            )
            if result.rowcount != 1:
                raise PatternAdaptationNotFoundError(report_id)
        return self.get_originality_report(report_id)

    def acknowledge_originality_report(self, report_id: str) -> PatternOriginalityReport:
        report = self.get_originality_report(report_id)
        gate_state = self.get_current_gate_state(report.project_id)
        if (
            gate_state.latest_report is None
            or gate_state.latest_report.id != report_id
            or not gate_state.report_is_current
        ):
            raise PatternOriginalityGateError("stale_originality_report")
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM writing_pattern_originality_reports WHERE id = ?",
                (report_id,),
            ).fetchone()
            if row is None:
                raise PatternAdaptationNotFoundError(report_id)
            if row["risk_level"] == OriginalityRiskLevel.HIGH.value:
                raise PatternOriginalityGateError("high_risk_cannot_be_acknowledged")
            if row["status"] == OriginalityStatus.PASSED.value:
                return self.get_originality_report(report_id)
            if row["viewed_at"] is None:
                raise PatternOriginalityGateError("report_must_be_viewed")
            connection.execute(
                """
                UPDATE writing_pattern_originality_reports
                SET status = 'passed', acknowledged_at = ? WHERE id = ?
                """,
                (now_iso(), report_id),
            )
        return self.get_originality_report(report_id)

    def require_current_originality_passed(self, project_id: str) -> None:
        self.require_creative_safety(project_id)

    def require_creative_safety(
        self,
        project_id: str,
        expected: CreativeSafetyProvenance | None = None,
    ) -> CreativeSafetyProvenance:
        with self.database.connect() as connection:
            adoption_exists = connection.execute(
                "SELECT 1 FROM writing_pattern_adoptions WHERE project_id = ? LIMIT 1",
                (project_id,),
            ).fetchone()
        if adoption_exists is None:
            try:
                self.patterns.get_active_profile(project_id)
            except WritingPatternNotFoundError:
                provenance = CreativeSafetyProvenance(
                    project_id=project_id,
                    mode="legacy",
                    fingerprint_sha256=canonical_sha256(
                        {
                            "schema_version": 1,
                            "project_id": project_id,
                            "mode": "legacy",
                        }
                    ),
                )
                if expected is not None and expected != provenance:
                    raise PatternOriginalityGateError("creative_safety_changed")
                return provenance
            raise PatternOriginalityGateError("adaptation_not_adopted")
        adoption, candidate, profile, blueprint = self._current_adoption_inputs(project_id)
        proposal = self._proposal_for_candidate(project_id, candidate.id)
        digest = canonical_sha256(blueprint.content.model_dump(mode="json"))
        recipe = self.patterns.get_recipe_version(profile.recipe_version_id)
        availability = self.patterns.verify_recipe_sources(
            project_id, recipe.sources, require_project_link=False
        )
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM writing_pattern_originality_reports
                WHERE adoption_id = ? ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (adoption.id,),
            ).fetchone()
        if (
            row is None
            or row["status"] != OriginalityStatus.PASSED.value
            or int(row["blueprint_revision"]) != blueprint.revision
            or row["blueprint_content_sha256"] != digest
            or row["profile_fingerprint_sha256"] != profile.profile_fingerprint_sha256
            or row["recipe_content_sha256"] != profile.recipe_content_sha256
            or row["threshold_version"] != THRESHOLD_VERSION
            or row["source_availability"] != availability.value
        ):
            raise PatternOriginalityGateError("originality_check_required")
        payload = {
            "schema_version": 1,
            "project_id": project_id,
            "mode": "pattern_adaptation",
            "adoption_id": adoption.id,
            "topic_decision_version_id": proposal.topic_decision_version_id,
            "topic_revision": proposal.topic_revision,
            "topic_content_sha256": proposal.topic_content_sha256,
            "profile_version_id": proposal.profile_version_id,
            "profile_fingerprint_sha256": profile.profile_fingerprint_sha256,
            "recipe_version_id": proposal.recipe_version_id,
            "recipe_content_sha256": profile.recipe_content_sha256,
            "blueprint_id": blueprint.id,
            "blueprint_revision": blueprint.revision,
            "blueprint_content_sha256": digest,
            "originality_report_id": str(row["id"]),
            "originality_input_sha256": str(row["input_sha256"]),
            "originality_threshold_version": str(row["threshold_version"]),
            "source_availability": availability.value,
        }
        provenance = CreativeSafetyProvenance(
            project_id=project_id,
            mode="pattern_adaptation",
            fingerprint_sha256=canonical_sha256(payload),
            adoption_id=adoption.id,
            topic_decision_version_id=proposal.topic_decision_version_id,
            topic_revision=proposal.topic_revision,
            topic_content_sha256=proposal.topic_content_sha256,
            profile_version_id=proposal.profile_version_id,
            profile_fingerprint_sha256=profile.profile_fingerprint_sha256,
            recipe_version_id=proposal.recipe_version_id,
            recipe_content_sha256=profile.recipe_content_sha256,
            blueprint_id=blueprint.id,
            blueprint_revision=blueprint.revision,
            blueprint_content_sha256=digest,
            originality_report_id=str(row["id"]),
            originality_input_sha256=str(row["input_sha256"]),
            originality_threshold_version=str(row["threshold_version"]),
            source_availability=availability.value,
        )
        if expected is not None and expected != provenance:
            raise PatternOriginalityGateError("creative_safety_changed")
        return provenance

    @staticmethod
    def _gate_state(
        *,
        project_id: str,
        state: Literal[
            "legacy",
            "needs_adaptation",
            "needs_check",
            "review_required",
            "blocked",
            "passed",
            "stale",
        ],
        requires_check: bool,
        adoption: PatternAdaptationAdoption | None,
        blueprint: BookBlueprint | None,
        blueprint_hash: str | None,
        reason: str | None = None,
        latest_report: PatternOriginalityReport | None = None,
        report_is_current: bool = False,
    ) -> PatternOriginalityGateState:
        return PatternOriginalityGateState(
            project_id=project_id,
            state=state,
            reason=reason,
            requires_check=requires_check,
            adoption=adoption,
            blueprint_id=(
                blueprint.id
                if blueprint is not None
                else adoption.blueprint_id
                if adoption is not None
                else None
            ),
            blueprint_revision=blueprint.revision if blueprint is not None else None,
            blueprint_content_sha256=blueprint_hash,
            latest_report=latest_report,
            report_is_current=report_is_current,
        )

    def get_current_gate_state(self, project_id: str) -> PatternOriginalityGateState:
        blueprint = self.director.get_book_blueprint(project_id)
        blueprint_hash = (
            canonical_sha256(blueprint.content.model_dump(mode="json"))
            if blueprint is not None
            else None
        )
        with self.database.connect() as connection:
            if (
                connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
                is None
            ):
                raise PatternAdaptationNotFoundError(project_id)
            adoption_row = connection.execute(
                """
                SELECT * FROM writing_pattern_adoptions
                WHERE project_id = ? ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (project_id,),
            ).fetchone()
        if adoption_row is None:
            try:
                self.patterns.get_active_profile(project_id)
            except WritingPatternNotFoundError:
                return self._gate_state(
                    project_id=project_id,
                    state="legacy",
                    requires_check=False,
                    adoption=None,
                    blueprint=blueprint,
                    blueprint_hash=blueprint_hash,
                )
            return self._gate_state(
                project_id=project_id,
                state="needs_adaptation",
                reason="adaptation_not_adopted",
                requires_check=True,
                adoption=None,
                blueprint=blueprint,
                blueprint_hash=blueprint_hash,
            )

        adoption = self._adoption(adoption_row)
        with self.database.connect() as connection:
            report_row = connection.execute(
                """
                SELECT * FROM writing_pattern_originality_reports
                WHERE adoption_id = ? ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (adoption.id,),
            ).fetchone()
            findings = (
                connection.execute(
                    """
                    SELECT * FROM writing_pattern_originality_findings
                    WHERE report_id = ? ORDER BY ordinal
                    """,
                    (str(report_row["id"]),),
                ).fetchall()
                if report_row is not None
                else []
            )
        report = self._report(report_row, findings) if report_row is not None else None
        if blueprint is None:
            return self._gate_state(
                project_id=project_id,
                state="stale",
                reason="adopted_blueprint_missing",
                requires_check=True,
                adoption=adoption,
                blueprint=None,
                blueprint_hash=None,
                latest_report=report,
                report_is_current=False,
            )
        if report is None:
            return self._gate_state(
                project_id=project_id,
                state="needs_check",
                reason="originality_check_required",
                requires_check=True,
                adoption=adoption,
                blueprint=blueprint,
                blueprint_hash=blueprint_hash,
            )
        try:
            _adoption, _candidate, profile, current_blueprint = self._current_adoption_inputs(
                project_id
            )
            recipe = self.patterns.get_recipe_version(profile.recipe_version_id)
            availability = self.patterns.verify_recipe_sources(
                project_id, recipe.sources, require_project_link=False
            )
            current_hash = canonical_sha256(current_blueprint.content.model_dump(mode="json"))
            report_is_current = (
                report.blueprint_id == current_blueprint.id
                and report.blueprint_revision == current_blueprint.revision
                and report.blueprint_content_sha256 == current_hash
                and report.profile_fingerprint_sha256 == adoption.profile_fingerprint_sha256
                and report.recipe_content_sha256 == adoption.recipe_content_sha256
                and report.threshold_version == THRESHOLD_VERSION
                and report.source_availability == availability
            )
            stale_reason = "originality_check_required"
        except (LookupError, ValueError) as error:
            report_is_current = False
            stale_reason = str(error) or "originality_check_required"
        if not report_is_current:
            return self._gate_state(
                project_id=project_id,
                state="stale",
                reason=stale_reason,
                requires_check=True,
                adoption=adoption,
                blueprint=blueprint,
                blueprint_hash=blueprint_hash,
                latest_report=report,
                report_is_current=False,
            )
        if report.status == OriginalityStatus.PASSED:
            return self._gate_state(
                project_id=project_id,
                state="passed",
                requires_check=False,
                adoption=adoption,
                blueprint=blueprint,
                blueprint_hash=blueprint_hash,
                latest_report=report,
                report_is_current=True,
            )
        if report.risk_level == OriginalityRiskLevel.HIGH:
            return self._gate_state(
                project_id=project_id,
                state="blocked",
                reason="high_risk_blocked",
                requires_check=True,
                adoption=adoption,
                blueprint=blueprint,
                blueprint_hash=blueprint_hash,
                latest_report=report,
                report_is_current=True,
            )
        return self._gate_state(
            project_id=project_id,
            state="review_required",
            reason="originality_acknowledgement_required",
            requires_check=True,
            adoption=adoption,
            blueprint=blueprint,
            blueprint_hash=blueprint_hash,
            latest_report=report,
            report_is_current=True,
        )

    def _plan(
        self,
        project_id: str,
        request: PatternAdaptationPreflightRequest,
    ) -> _PlannedAdaptation:
        try:
            topic = self.topic_decisions.get_confirmed_version(project_id)
        except (TopicDecisionNotFoundError, TopicDecisionNotConfirmedError) as error:
            raise PatternAdaptationConflictError("topic_not_confirmed") from error
        if (
            topic.revision != request.expected_topic_revision
            or topic.content_sha256 != request.expected_topic_content_sha256
        ):
            raise PatternAdaptationConflictError("topic_changed")
        try:
            profile = self.patterns.get_profile(project_id, request.profile_version_id)
        except (WritingPatternNotFoundError, WritingPatternError) as error:
            raise PatternAdaptationConflictError("profile_unavailable") from error
        if (
            profile.lifecycle_state != WritingPatternLifecycleState.ACTIVE
            or not profile.is_current
            or profile.profile_fingerprint_sha256 != request.expected_profile_fingerprint_sha256
            or profile.topic_revision != topic.revision
            or profile.topic_content_sha256 != topic.content_sha256
        ):
            raise PatternAdaptationConflictError("profile_changed")
        recipe = self.patterns.get_recipe_version(profile.recipe_version_id)
        if recipe.content_sha256 != profile.recipe_content_sha256:
            raise PatternAdaptationConflictError("recipe_changed")
        source_availability = self.patterns.verify_recipe_sources(
            project_id,
            recipe.sources,
            require_project_link=False,
        )
        blueprint = self.director.get_book_blueprint(project_id)
        blueprint_hash = (
            canonical_sha256(blueprint.content.model_dump(mode="json"))
            if blueprint is not None
            else None
        )
        if blueprint is None:
            if request.expected_base_blueprint_revision is not None:
                raise PatternAdaptationConflictError("base_blueprint_changed")
            locks = {field: False for field in BookBlueprintField}
            field_versions = {field: 0 for field in BookBlueprintField}
        else:
            if (
                request.expected_base_blueprint_revision != blueprint.revision
                or request.expected_base_blueprint_content_sha256 != blueprint_hash
            ):
                raise PatternAdaptationConflictError("base_blueprint_changed")
            locks = blueprint.locks
            field_versions = blueprint.field_versions
        protected_titles = self._protected_titles(recipe.id)
        context_text, context_hash = build_safe_adaptation_context(
            topic=topic.content,
            profile=profile.model_safe_profile,
            author_intent=request.author_intent,
            current_blueprint=blueprint.content if blueprint else None,
            locks=locks,
            protected_titles=protected_titles,
            current_safety_basis=source_availability,
        )
        gateway, provider_profile, status = self._selected_gateway(request.provider_profile_id)
        input_rate = (
            provider_profile.input_cost_microusd_per_million
            if provider_profile is not None
            else getattr(gateway, "input_cost_microusd_per_million", None)
        )
        output_rate = (
            provider_profile.output_cost_microusd_per_million
            if provider_profile is not None
            else getattr(gateway, "output_cost_microusd_per_million", None)
        )
        is_local = _local_endpoint(provider_profile, gateway)
        input_tokens = estimate_tokens(context_text)
        output_tokens = PATTERN_ADAPTATION_OUTPUT_TOKENS
        if input_rate is not None and output_rate is not None:
            estimated_cost = (
                input_tokens * input_rate + output_tokens * output_rate + 999_999
            ) // 1_000_000
            cost_status = PatternAdaptationCostStatus.KNOWN
        elif is_local:
            estimated_cost = 0
            cost_status = PatternAdaptationCostStatus.FREE
        else:
            estimated_cost = None
            cost_status = PatternAdaptationCostStatus.UNAVAILABLE
        lock_hash = canonical_sha256(
            {
                "locks": {field.value: locks[field] for field in BookBlueprintField},
                "field_versions": {
                    field.value: field_versions[field] for field in BookBlueprintField
                },
            }
        )
        dependency_hash = canonical_sha256(
            {
                "schema_version": 1,
                "topic_decision_version_id": topic.id,
                "topic_revision": topic.revision,
                "topic_content_sha256": topic.content_sha256,
                "profile_version_id": profile.id,
                "profile_fingerprint_sha256": profile.profile_fingerprint_sha256,
                "recipe_version_id": profile.recipe_version_id,
                "recipe_content_sha256": profile.recipe_content_sha256,
                "compiler_version": profile.compiler_version,
                "source_availability": source_availability.value,
                "base_blueprint_id": blueprint.id if blueprint else None,
                "base_blueprint_revision": blueprint.revision if blueprint else None,
                "base_blueprint_content_sha256": blueprint_hash,
                "lock_snapshot_sha256": lock_hash,
                "prompt_version": PATTERN_ADAPTATION_PROMPT_VERSION,
                "provider_profile_id": status.profile_id,
                "provider_profile_revision": (
                    provider_profile.revision if provider_profile else None
                ),
                "provider": status.provider.value,
                "model": status.model,
                "input_rate": input_rate,
                "output_rate": output_rate,
                "author_intent_sha256": canonical_sha256(json.loads(context_text)["author_intent"]),
            }
        )
        data_types = ["已确认选题", "抽象写作模式", "当前蓝图", "作者意图", "字段锁"]
        content_scope = "生成 3 套隔离的整书蓝图候选，不自动采用"
        preview_payload = {
            "dependency_fingerprint_sha256": dependency_hash,
            "safe_context_sha256": context_hash,
            "estimated_input_tokens": input_tokens,
            "estimated_output_tokens": output_tokens,
            "estimated_cost_microusd": estimated_cost,
            "cost_status": cost_status.value,
            "data_types": data_types,
            "content_scope": content_scope,
        }
        preview = PatternAdaptationPreflight(
            profile_version_id=profile.id,
            profile_fingerprint_sha256=profile.profile_fingerprint_sha256,
            recipe_version_id=profile.recipe_version_id,
            recipe_content_sha256=profile.recipe_content_sha256,
            source_availability=source_availability,
            topic_decision_version_id=topic.id,
            topic_revision=topic.revision,
            topic_content_sha256=topic.content_sha256,
            base_blueprint_id=blueprint.id if blueprint else None,
            base_blueprint_revision=blueprint.revision if blueprint else None,
            base_blueprint_content_sha256=blueprint_hash,
            dependency_fingerprint_sha256=dependency_hash,
            safe_context_sha256=context_hash,
            lock_snapshot_sha256=lock_hash,
            provider=status.provider.value,
            provider_profile_id=status.profile_id,
            provider_profile_name=status.profile_name or "当前会话线路",
            provider_profile_revision=provider_profile.revision if provider_profile else None,
            model=status.model,
            estimated_input_tokens=input_tokens,
            estimated_output_tokens=output_tokens,
            estimated_cost_microusd=estimated_cost,
            cost_status=cost_status,
            data_types=data_types,
            content_scope=content_scope,
            locked_fields=[field for field in BookBlueprintField if locks[field]],
            preview_sha256=canonical_sha256(preview_payload),
        )
        return _PlannedAdaptation(
            preview=preview,
            context_text=context_text,
            profile=profile,
            input_rate=input_rate,
            output_rate=output_rate,
            is_local=is_local,
            protected_titles=protected_titles,
        )

    def _selected_gateway(
        self,
        requested_profile_id: str | None,
    ) -> tuple[AiGateway, ModelProfile | None, AiStatus]:
        profile = None
        if requested_profile_id is not None:
            profile = self.profiles.get_profile(requested_profile_id)
        else:
            profile = self.profiles.get_task_profile(AiTaskType.PATTERN_ADAPTATION)
        gateway = self.manager.gateway_for(profile.id) if profile else self.manager.gateway()
        status = gateway.status()
        if not status.configured or (profile is not None and status.profile_id != profile.id):
            raise AiNotConfiguredError
        return gateway, profile, status

    def _gateway_for_job(self, job: Job) -> AiGateway:
        gateway = self.manager.gateway_for(job.provider_profile_id)
        status = gateway.status()
        if (
            not status.configured
            or status.provider.value != job.provider
            or status.profile_id != job.provider_profile_id
            or status.model != job.model
        ):
            raise JobExecutionError(
                "provider_unavailable",
                "任务使用的模型配置当前不可用，请恢复后重试",
            )
        return gateway

    def _require_job_dependencies(
        self,
        proposal: PatternAdaptationProposal,
        task: _PatternAdaptationJobInput,
        job: Job,
    ) -> None:
        if task.dependency_fingerprint_sha256 != proposal.dependency_fingerprint_sha256:
            raise JobExecutionError("dependency_changed", "原创迁移依赖已变化，请重新预览")
        try:
            topic = self.topic_decisions.get_confirmed_version(proposal.project_id)
            profile = self.patterns.get_profile(proposal.project_id, proposal.profile_version_id)
            recipe = self.patterns.get_recipe_version(proposal.recipe_version_id)
            availability = self.patterns.verify_recipe_sources(
                proposal.project_id, recipe.sources, require_project_link=False
            )
        except (LookupError, ValueError) as error:
            raise JobExecutionError(
                "dependency_changed", "原创迁移依赖已变化，请重新预览"
            ) from error
        if (
            topic.id != proposal.topic_decision_version_id
            or topic.revision != proposal.topic_revision
            or topic.content_sha256 != proposal.topic_content_sha256
            or profile.lifecycle_state != WritingPatternLifecycleState.ACTIVE
            or not profile.is_current
            or profile.profile_fingerprint_sha256 != proposal.profile_fingerprint_sha256
            or recipe.content_sha256 != proposal.recipe_content_sha256
            or availability != task.source_availability
        ):
            raise JobExecutionError("dependency_changed", "原创迁移依赖已变化，请重新预览")
        blueprint = self.director.get_book_blueprint(proposal.project_id)
        if blueprint is None:
            if proposal.base_blueprint_id is not None:
                raise JobExecutionError("blueprint_changed", "整书蓝图已变化，请重新预览")
        elif (
            blueprint.id != proposal.base_blueprint_id
            or blueprint.revision != proposal.base_blueprint_revision
            or canonical_sha256(blueprint.content.model_dump(mode="json"))
            != proposal.base_blueprint_content_sha256
            or self._lock_snapshot_sha256(blueprint) != proposal.lock_snapshot_sha256
        ):
            raise JobExecutionError("blueprint_changed", "整书蓝图已变化，请重新预览")
        gateway = self._gateway_for_job(job)
        if proposal.provider_profile_id is not None:
            try:
                provider_profile = self.profiles.get_profile(proposal.provider_profile_id)
            except LookupError as error:
                raise JobExecutionError("provider_changed", "模型配置已变化，请重新预览") from error
            if (
                provider_profile.revision != proposal.provider_profile_revision
                or provider_profile.model != proposal.model
                or provider_profile.input_cost_microusd_per_million
                != proposal.input_cost_microusd_per_million
                or provider_profile.output_cost_microusd_per_million
                != proposal.output_cost_microusd_per_million
            ):
                raise JobExecutionError("provider_changed", "模型配置已变化，请重新预览")
        del gateway

    def _normalize_and_validate_drafts(
        self,
        proposal: PatternAdaptationProposal,
        drafts: PatternAdaptationDraftSet,
    ) -> PatternAdaptationDraftSet:
        if len(drafts.candidates) != 3:
            raise PatternAdaptationConflictError("exactly_three_candidates_required")
        profile = self.patterns.get_profile(proposal.project_id, proposal.profile_version_id)
        recipe = self.patterns.get_recipe_version(proposal.recipe_version_id)
        protected_titles = self._protected_titles(recipe.id)
        sensitive_terms = source_sensitive_terms(profile.model_safe_profile, protected_titles)
        raw_output = drafts.model_dump_json()
        if any(term in raw_output for term in sensitive_terms):
            raise PatternAdaptationConflictError("source_term_in_output")
        locks, base = self._proposal_lock_context(proposal)
        normalized: list[PatternAdaptationDraft] = []
        for draft in drafts.candidates:
            payload = draft.blueprint.model_dump(mode="json")
            if base is not None:
                for field in BookBlueprintField:
                    if locks[field]:
                        payload[field.value] = base[field.value]
                if (
                    not locks[BookBlueprintField.RELATIONSHIP_DESIGN]
                    and payload[BookBlueprintField.RELATIONSHIP_DESIGN.value]
                    == base[BookBlueprintField.RELATIONSHIP_DESIGN.value]
                ):
                    raise PatternAdaptationConflictError("relationships_must_be_rebuilt")
            normalized.append(
                draft.model_copy(update={"blueprint": BookBlueprintContent.model_validate(payload)})
            )
        result = PatternAdaptationDraftSet(candidates=normalized)
        self._validate_structural_distinctness(result)
        return result

    @staticmethod
    def _actual_axes(
        left: PatternAdaptationDraft,
        right: PatternAdaptationDraft,
    ) -> set[PatternDistinctAxis]:
        axes: set[PatternDistinctAxis] = set()
        left_payload = left.blueprint.model_dump(mode="json")
        right_payload = right.blueprint.model_dump(mode="json")
        if any(
            left_payload[field] != right_payload[field]
            for field in ("core_desire", "divergence_point", "long_term_promise")
        ):
            axes.add(PatternDistinctAxis.CORE_CONFLICT)
        if left.blueprint.relationship_design != right.blueprint.relationship_design:
            axes.add(PatternDistinctAxis.CHARACTER_RELATIONSHIPS)
        if (
            left.blueprint.resource_growth != right.blueprint.resource_growth
            or left.blueprint.core_selling_points != right.blueprint.core_selling_points
        ):
            axes.add(PatternDistinctAxis.RESOURCE_PROGRESSION)
        if left.key_scene_sequence != right.key_scene_sequence:
            axes.add(PatternDistinctAxis.SCENE_ORGANIZATION)
        if left.blueprint.ending_direction != right.blueprint.ending_direction:
            axes.add(PatternDistinctAxis.ENDING)
        return axes

    @classmethod
    def _validate_structural_distinctness(cls, drafts: PatternAdaptationDraftSet) -> None:
        if (
            len(
                {
                    candidate_content_sha256(
                        item.blueprint,
                        item.key_scene_sequence,
                        item.transformation_notes,
                    )
                    for item in drafts.candidates
                }
            )
            != 3
        ):
            raise PatternAdaptationConflictError("duplicate_candidates")
        major = {
            PatternDistinctAxis.CORE_CONFLICT,
            PatternDistinctAxis.CHARACTER_RELATIONSHIPS,
            PatternDistinctAxis.SCENE_ORGANIZATION,
        }
        for left, right in combinations(drafts.candidates, 2):
            actual = cls._actual_axes(left, right)
            if len(actual) < 2 or not actual & major:
                raise PatternAdaptationConflictError("candidates_not_structurally_distinct")
            if not set(left.distinct_axes) & actual or not set(right.distinct_axes) & actual:
                raise PatternAdaptationConflictError("declared_axes_not_supported")

    def _proposal_for_candidate(
        self, project_id: str, candidate_id: str
    ) -> PatternAdaptationProposal:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT p.id FROM writing_pattern_adaptation_proposals p
                JOIN writing_pattern_adaptation_candidates c ON c.proposal_id = p.id
                WHERE c.id = ? AND p.project_id = ?
                """,
                (candidate_id, project_id),
            ).fetchone()
        if row is None:
            raise PatternAdaptationNotFoundError(candidate_id)
        return self.repository.get_proposal(project_id, str(row["id"]))

    def _proposal_lock_context(
        self, proposal: PatternAdaptationProposal
    ) -> tuple[dict[BookBlueprintField, bool], dict[str, object] | None]:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT lock_snapshot_json, job_id
                FROM writing_pattern_adaptation_proposals WHERE id = ?
                """,
                (proposal.id,),
            ).fetchone()
        if row is None:
            raise PatternAdaptationNotFoundError(proposal.id)
        locks = {
            BookBlueprintField(key): bool(value)
            for key, value in json.loads(str(row["lock_snapshot_json"])).items()
        }
        artifact = self.jobs.find_artifact(str(row["job_id"]), "pattern-adaptation-context")
        if artifact is None:
            raise PatternAdaptationConflictError("context_invalid")
        base = json.loads(artifact.payload).get("current_blueprint")
        return locks, cast(dict[str, object] | None, base)

    def _validate_adoption_request(
        self,
        proposal: PatternAdaptationProposal,
        candidate_revision: int,
        candidate_hash: str,
        request: AdoptPatternAdaptationCandidateRequest,
    ) -> None:
        if (
            candidate_revision != request.expected_candidate_revision
            or candidate_hash != request.expected_candidate_content_sha256
        ):
            raise PatternAdaptationConflictError("candidate_changed")
        if (
            proposal.profile_fingerprint_sha256 != request.expected_profile_fingerprint_sha256
            or proposal.recipe_content_sha256 != request.expected_recipe_content_sha256
            or proposal.topic_revision != request.expected_topic_revision
            or proposal.topic_content_sha256 != request.expected_topic_content_sha256
            or proposal.base_blueprint_revision != request.expected_base_blueprint_revision
            or proposal.base_blueprint_content_sha256
            != request.expected_base_blueprint_content_sha256
        ):
            raise PatternAdaptationConflictError("adoption_dependencies_changed")

    def _assert_atomic_dependencies(
        self,
        connection: Connection,
        proposal: PatternAdaptationProposal,
        request: AdoptPatternAdaptationCandidateRequest,
    ) -> None:
        topic = connection.execute(
            """
            SELECT d.revision, d.confirmed_revision, v.id AS version_id,
                   v.content_sha256
            FROM topic_decisions d
            LEFT JOIN topic_decision_versions v
              ON v.topic_decision_id = d.id AND v.revision = d.confirmed_revision
            WHERE d.project_id = ?
            """,
            (proposal.project_id,),
        ).fetchone()
        profile = connection.execute(
            """
            SELECT p.profile_fingerprint_sha256, p.recipe_content_sha256,
                   l.lifecycle_state
            FROM writing_pattern_profile_versions p
            JOIN project_writing_pattern_profiles l ON l.profile_version_id = p.id
            WHERE p.id = ? AND p.project_id = ?
            """,
            (proposal.profile_version_id, proposal.project_id),
        ).fetchone()
        if (
            topic is None
            or topic["confirmed_revision"] is None
            or int(topic["revision"]) != int(topic["confirmed_revision"])
            or int(topic["revision"]) != request.expected_topic_revision
            or topic["version_id"] != proposal.topic_decision_version_id
            or topic["content_sha256"] != request.expected_topic_content_sha256
            or profile is None
            or profile["lifecycle_state"] != "active"
            or profile["profile_fingerprint_sha256"] != request.expected_profile_fingerprint_sha256
            or profile["recipe_content_sha256"] != request.expected_recipe_content_sha256
        ):
            raise PatternAdaptationConflictError("adoption_dependencies_changed")

    @staticmethod
    def _topic_premise(connection: Connection, project_id: str) -> str:
        row = connection.execute(
            "SELECT content_json FROM topic_decisions WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            raise PatternAdaptationNotFoundError(project_id)
        premise = json.loads(str(row["content_json"])).get("premise")
        if not isinstance(premise, str) or not premise:
            raise PatternAdaptationConflictError("topic_invalid")
        return premise

    def _current_adoption_inputs(
        self, project_id: str
    ) -> tuple[
        PatternAdaptationAdoption,
        PatternAdaptationCandidate,
        WritingPatternProfileVersion,
        BookBlueprint,
    ]:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM writing_pattern_adoptions
                WHERE project_id = ? ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (project_id,),
            ).fetchone()
        if row is None:
            raise PatternOriginalityGateError("adaptation_not_adopted")
        adoption = self._adoption(row)
        proposal = self._proposal_for_candidate(project_id, adoption.candidate_id)
        try:
            topic = self.topic_decisions.get_confirmed_version(project_id)
        except (TopicDecisionNotFoundError, TopicDecisionNotConfirmedError) as error:
            raise PatternOriginalityGateError("topic_changed") from error
        if (
            topic.id != proposal.topic_decision_version_id
            or topic.revision != proposal.topic_revision
            or topic.content_sha256 != proposal.topic_content_sha256
        ):
            raise PatternOriginalityGateError("topic_changed")
        profile = self.patterns.get_profile(project_id, proposal.profile_version_id)
        try:
            active_profile = self.patterns.get_active_profile(project_id)
        except WritingPatternNotFoundError as error:
            raise PatternOriginalityGateError(
                "writing_pattern_profile_inactive"
            ) from error
        if (
            active_profile.id != proposal.profile_version_id
            or active_profile.profile_fingerprint_sha256
            != adoption.profile_fingerprint_sha256
        ):
            raise PatternOriginalityGateError("writing_pattern_profile_changed")
        candidate = next(item for item in proposal.candidates if item.id == adoption.candidate_id)
        if candidate.current_version.id != adoption.candidate_version_id:
            with self.database.connect() as connection:
                version_row = connection.execute(
                    """
                    SELECT v.*, c.proposal_id, c.ordinal, c.label, c.why_distinct,
                           c.distinct_axes_json, c.risk_hypotheses_json,
                           c.created_at, c.updated_at,
                           v.revision AS current_revision,
                           v.content_sha256 AS current_content_sha256,
                           v.id AS version_id, v.created_at AS version_created_at
                    FROM writing_pattern_adaptation_candidate_versions v
                    JOIN writing_pattern_adaptation_candidates c ON c.id = v.candidate_id
                    WHERE v.id = ?
                    """,
                    (adoption.candidate_version_id,),
                ).fetchone()
            if version_row is None:
                raise PatternOriginalityGateError("adopted_candidate_missing")
            candidate = PatternAdaptationRepository._candidate(version_row)
        blueprint = self.director.require_book_blueprint(project_id)
        if (
            blueprint.id != adoption.blueprint_id
            or profile.profile_fingerprint_sha256 != adoption.profile_fingerprint_sha256
            or profile.recipe_content_sha256 != adoption.recipe_content_sha256
        ):
            raise PatternOriginalityGateError("guard_dependencies_changed")
        return adoption, candidate, profile, blueprint

    def _persist_originality_report(
        self,
        adoption: PatternAdaptationAdoption,
        candidate: PatternAdaptationCandidate,
        blueprint: BookBlueprint,
        assessment: PatternOriginalityAssessment,
        source_availability: WritingPatternSafetyBasis,
    ) -> PatternOriginalityReport:
        status = (
            OriginalityStatus.BLOCKED
            if assessment.risk_level == OriginalityRiskLevel.HIGH
            else OriginalityStatus.REVIEW_REQUIRED
            if assessment.risk_level == OriginalityRiskLevel.MEDIUM
            else OriginalityStatus.PASSED
        )
        report_id = str(uuid4())
        timestamp = now_iso()
        source_seed = canonical_sha256(
            {
                "profile": adoption.profile_fingerprint_sha256,
                "recipe": adoption.recipe_content_sha256,
            }
        )
        with self.database.connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM writing_pattern_originality_reports
                WHERE adoption_id = ? AND threshold_version = ? AND input_sha256 = ?
                """,
                (adoption.id, assessment.threshold_version, assessment.input_sha256),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO writing_pattern_originality_reports (
                        id, project_id, adoption_id, profile_fingerprint_sha256,
                        recipe_content_sha256, blueprint_id, blueprint_revision,
                        blueprint_content_sha256, candidate_version_id,
                        candidate_content_sha256, risk_level, status, score,
                        threshold_version, input_sha256, source_availability,
                        viewed_at, acknowledged_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
                    """,
                    (
                        report_id,
                        adoption.project_id,
                        adoption.id,
                        adoption.profile_fingerprint_sha256,
                        adoption.recipe_content_sha256,
                        blueprint.id,
                        blueprint.revision,
                        canonical_sha256(blueprint.content.model_dump(mode="json")),
                        candidate.current_version.id,
                        candidate.current_version.content_sha256,
                        assessment.risk_level.value,
                        status.value,
                        assessment.score,
                        assessment.threshold_version,
                        assessment.input_sha256,
                        source_availability.value,
                        timestamp,
                    ),
                )
                for ordinal, finding in enumerate(assessment.findings):
                    connection.execute(
                        """
                        INSERT INTO writing_pattern_originality_findings (
                            id, report_id, ordinal, signal, score, summary,
                            source_fingerprint_sha256, evidence_sha256
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid4()),
                            report_id,
                            ordinal,
                            finding.signal.value,
                            finding.score,
                            finding.summary,
                            sha256(f"{source_seed}:{finding.signal.value}".encode()).hexdigest(),
                            finding.evidence_sha256,
                        ),
                    )
            else:
                report_id = str(existing["id"])
        return self.get_originality_report(report_id)

    def _protected_titles(self, recipe_version_id: str) -> list[str]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT rw.title
                FROM writing_pattern_recipe_sources source
                JOIN craft_pattern_assets asset ON asset.id = source.asset_version_id
                JOIN json_each(asset.source_work_ids_json) work_id
                JOIN reference_works rw ON rw.id = work_id.value
                WHERE source.recipe_version_id = ?
                ORDER BY rw.title
                """,
                (recipe_version_id,),
            ).fetchall()
        return [str(row["title"]) for row in rows]

    def _locks_for_project(self, project_id: str) -> dict[BookBlueprintField, bool]:
        blueprint = self.director.get_book_blueprint(project_id)
        return (
            blueprint.locks
            if blueprint is not None
            else {field: False for field in BookBlueprintField}
        )

    @staticmethod
    def _lock_snapshot_sha256(blueprint: BookBlueprint) -> str:
        return canonical_sha256(
            {
                "locks": {field.value: blueprint.locks[field] for field in BookBlueprintField},
                "field_versions": {
                    field.value: blueprint.field_versions[field] for field in BookBlueprintField
                },
            }
        )

    @staticmethod
    def _adoption(row: Row) -> PatternAdaptationAdoption:
        return PatternAdaptationAdoption(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            proposal_id=str(row["proposal_id"]),
            candidate_id=str(row["candidate_id"]),
            candidate_version_id=str(row["candidate_version_id"]),
            blueprint_id=str(row["blueprint_id"]),
            blueprint_revision=int(row["blueprint_revision"]),
            blueprint_content_sha256=str(row["blueprint_content_sha256"]),
            profile_fingerprint_sha256=str(row["profile_fingerprint_sha256"]),
            recipe_content_sha256=str(row["recipe_content_sha256"]),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _report(row: Row, findings: list[Row]) -> PatternOriginalityReport:
        return PatternOriginalityReport(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            adoption_id=str(row["adoption_id"]),
            profile_fingerprint_sha256=str(row["profile_fingerprint_sha256"]),
            recipe_content_sha256=str(row["recipe_content_sha256"]),
            blueprint_id=str(row["blueprint_id"]),
            blueprint_revision=int(row["blueprint_revision"]),
            blueprint_content_sha256=str(row["blueprint_content_sha256"]),
            candidate_version_id=str(row["candidate_version_id"]),
            candidate_content_sha256=str(row["candidate_content_sha256"]),
            risk_level=OriginalityRiskLevel(str(row["risk_level"])),
            status=OriginalityStatus(str(row["status"])),
            score=int(row["score"]),
            threshold_version=str(row["threshold_version"]),
            input_sha256=str(row["input_sha256"]),
            source_availability=WritingPatternSafetyBasis(str(row["source_availability"])),
            findings=[
                PatternOriginalityFindingRecord(
                    id=str(item["id"]),
                    ordinal=int(item["ordinal"]),
                    signal=str(item["signal"]),
                    score=int(item["score"]),
                    summary=str(item["summary"]),
                    source_fingerprint_sha256=str(item["source_fingerprint_sha256"]),
                    evidence_sha256=str(item["evidence_sha256"]),
                )
                for item in findings
            ],
            viewed_at=str(row["viewed_at"]) if row["viewed_at"] else None,
            acknowledged_at=(str(row["acknowledged_at"]) if row["acknowledged_at"] else None),
            created_at=str(row["created_at"]),
        )
