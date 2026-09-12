from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, cast, runtime_checkable
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from app.ai import (
    AiGateway,
    AiGatewayManager,
    AiNotConfiguredError,
    AiProviderError,
    OpenAiGateway,
    consume_ai_call_metrics,
    require_compiled_context_gateway,
)
from app.context import (
    ContextPacket,
    ContextPacketNotFoundError,
    ContextRepository,
    CreativeContextBlockedError,
    CreativeContextChangedError,
    CreativeContextCompileRequest,
    CreativeContextPurpose,
    CreativeContextService,
    CreativeContextSubject,
    CreativeContextSubjectKind,
)
from app.creative_safety import CreativeSafetyProvenance
from app.jobs.models import AttemptState, ChunkState, Job, JobChunk, JobKind
from app.jobs.repository import JobRepository
from app.jobs.runtime import JobExecutionContext, JobExecutionError
from app.models import Chapter, ChapterStatus, ReviewDimension, Workspace
from app.providers import (
    AiErrorCategory,
    AiTaskType,
    ModelProfile,
    ModelProfileNotFoundError,
    ModelProfileRepository,
    ProviderCallError,
    ProviderCallMetrics,
)
from app.repository import NotFoundError, OriginalityGateBlockedError, ProjectRepository

from .models import (
    PREWRITE_FIELDS,
    AdapterOutlineResult,
    AdapterReviewResult,
    AdapterTextResult,
    CandidateGuard,
    CandidateReview,
    CandidateReviewDraft,
    CandidateReviewFinding,
    CandidateVersionOperation,
    ChapterOutline,
    ChapterProduction,
    ChapterProductionOutboundPreview,
    CreativeContextSnapshot,
    DraftCandidate,
    DraftGenerationInput,
    GenerateDraftRequest,
    GenerateOutlineRequest,
    ModelTrace,
    OutlineCandidate,
    OutlineGenerationInput,
    OutlineGuard,
    PreflightCheck,
    RegenerateSelectionRequest,
    ReviewCandidateRequest,
    ReviewGenerationInput,
    RewriteGenerationInput,
    RewriteIntent,
    SubmitDraftJobRequest,
    SubmitOutlineJobRequest,
    SubmitReviewJobRequest,
    SubmitRewriteJobRequest,
    TextSelection,
)
from .ports import ChapterProductionModelAdapter
from .repository import (
    ChapterProductionConflictError,
    ChapterProductionNotFoundError,
    ChapterProductionRepository,
    text_sha256,
)

OUTLINE_WORKFLOW = "chapter_production_outline"
DRAFT_WORKFLOW = "chapter_production_draft"
REWRITE_WORKFLOW = "chapter_production_rewrite"
REVIEW_WORKFLOW = "chapter_production_review"

OUTLINE_PROMPT_VERSION = "chapter-production-outline-v1"
DRAFT_PROMPT_VERSION = "chapter-production-draft-v1"
REWRITE_PROMPT_VERSION = "chapter-production-rewrite-v1"
REVIEW_PROMPT_VERSION = "chapter-production-review-v1"

_OUTPUT_TOKENS = {
    OUTLINE_WORKFLOW: 1_200,
    DRAFT_WORKFLOW: 12_000,
    REWRITE_WORKFLOW: 4_000,
    REVIEW_WORKFLOW: 1_200 * len(ReviewDimension),
}

_REWRITE_INSTRUCTIONS = """You are editing one selected passage in a Chinese web novel.
Return only the replacement passage. Obey the frozen creative context and the author's
instruction. Do not continue outside the selection, quote reference works, or add notes.
"""


class ChapterProductionRequestError(ChapterProductionConflictError):
    """A safe, author-actionable production precondition failed."""


class _JobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow: str
    production_id: str
    project_id: str
    chapter_id: str
    base_chapter_revision: int = Field(ge=0)
    base_chapter_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    context: CreativeContextSnapshot
    prompt_version: str
    creative_safety: CreativeSafetyProvenance | None = None
    author_intent: str = ""
    label: str = ""
    outline_candidate_id: str | None = None
    expected_outline_revision: int | None = Field(default=None, ge=0)
    expected_outline_content_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    candidate_id: str | None = None
    expected_candidate_revision: int | None = Field(default=None, ge=0)
    expected_candidate_content_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    selection: TextSelection | None = None
    rewrite_intent: str | None = None
    custom_instruction: str = ""


@dataclass(frozen=True)
class _Plan:
    production: ChapterProduction
    workspace: Workspace
    chapter: Chapter
    packet: ContextPacket
    profile: ModelProfile | None
    provider: str
    profile_id: str | None
    profile_name: str
    model: str
    estimated_cost_microusd: int | None


@runtime_checkable
class _SelectionRewriteGateway(Protocol):
    def rewrite_selection_from_context(
        self,
        context_text: str,
        selected_text: str,
        intent: str,
        instruction: str,
    ) -> str: ...


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ChapterProductionService:
    """Single application boundary for planning, drafting, review, and candidate work."""

    def __init__(
        self,
        projects: ProjectRepository,
        productions: ChapterProductionRepository,
        jobs: JobRepository,
        manager: AiGatewayManager,
        profiles: ModelProfileRepository,
        contexts: ContextRepository,
        creative_context: CreativeContextService,
        *,
        adapter: ChapterProductionModelAdapter | None = None,
    ) -> None:
        self.projects = projects
        self.productions = productions
        self.jobs = jobs
        self.manager = manager
        self.profiles = profiles
        self.contexts = contexts
        self.creative_context = creative_context
        self.adapter = adapter

    # ---- synchronous local use cases -------------------------------------------------

    def preflight(self, production_id: str, guard: OutlineGuard) -> PreflightCheck:
        production, _workspace, _chapter = self._load_current(production_id)
        outline = self.productions.get_outline_candidate(
            production.id, guard.outline_candidate_id
        )
        self._require_outline_guard(outline, guard)
        checks = {
            field: bool(cast(str, getattr(outline.current_version.content, field)).strip())
            for field in PREWRITE_FIELDS
        }
        missing = [field for field in PREWRITE_FIELDS if not checks[field]]
        return self.productions.record_preflight(
            production_id=production.id,
            outline_candidate_id=outline.id,
            expected_outline_revision=guard.expected_outline_revision,
            expected_outline_content_sha256=guard.expected_outline_content_sha256,
            checks=checks,
            missing_fields=missing,
        )

    def edit_candidate_selection(
        self,
        production_id: str,
        candidate_id: str,
        *,
        expected_candidate_revision: int,
        expected_candidate_content_sha256: str,
        selection: object,
        replacement: str,
    ) -> DraftCandidate:
        # EditableTextSelection is deliberately structural here so insertion and
        # replacement share one repository transaction without weakening AI ranges.
        return self.productions.replace_candidate_selection(
            production_id=production_id,
            candidate_id=candidate_id,
            expected_candidate_revision=expected_candidate_revision,
            expected_candidate_content_sha256=expected_candidate_content_sha256,
            selection=cast(TextSelection, selection),
            replacement=replacement,
            operation=CandidateVersionOperation.AUTHOR_EDIT,
            instruction="author_edit",
        )

    # ---- preview ---------------------------------------------------------------------

    def preview_outline(
        self, production_id: str, request: GenerateOutlineRequest
    ) -> ChapterProductionOutboundPreview:
        plan = self._plan(
            production_id,
            workflow=OUTLINE_WORKFLOW,
            token_budget=request.token_budget,
            author_intent=request.author_intent,
        )
        return self._preview(plan, OUTLINE_WORKFLOW)

    def preview_draft(
        self, production_id: str, request: GenerateDraftRequest
    ) -> ChapterProductionOutboundPreview:
        check = self.preflight(production_id, request)
        if not check.passed:
            raise ChapterProductionRequestError("preflight_not_passed")
        plan = self._plan(
            production_id,
            workflow=DRAFT_WORKFLOW,
            token_budget=request.token_budget,
            author_intent=request.author_intent,
            outline_guard=request,
        )
        return self._preview(plan, DRAFT_WORKFLOW)

    def preview_rewrite(
        self,
        production_id: str,
        candidate_id: str,
        request: RegenerateSelectionRequest,
    ) -> ChapterProductionOutboundPreview:
        candidate = self.productions.get_candidate(production_id, candidate_id)
        self._require_candidate_guard(candidate, request)
        self._validate_selection(candidate, request.selection, require_unlocked=True)
        plan = self._plan(
            production_id,
            workflow=REWRITE_WORKFLOW,
            token_budget=request.token_budget,
            author_intent=self._rewrite_author_intent(request),
            candidate=candidate,
        )
        return self._preview(plan, REWRITE_WORKFLOW)

    def preview_review(
        self,
        production_id: str,
        candidate_id: str,
        request: ReviewCandidateRequest,
    ) -> ChapterProductionOutboundPreview:
        candidate = self.productions.get_candidate(production_id, candidate_id)
        self._require_candidate_guard(candidate, request)
        plan = self._plan(
            production_id,
            workflow=REVIEW_WORKFLOW,
            token_budget=request.token_budget,
            author_intent="对本章候选稿执行七维审校",
            candidate=candidate,
        )
        return self._preview(plan, REVIEW_WORKFLOW)

    # ---- durable submission -----------------------------------------------------------

    def submit_outline(
        self, production_id: str, request: SubmitOutlineJobRequest
    ) -> Job:
        plan = self._plan(
            production_id,
            workflow=OUTLINE_WORKFLOW,
            token_budget=request.token_budget,
            author_intent=request.author_intent,
        )
        return self._submit(
            plan,
            workflow=OUTLINE_WORKFLOW,
            request=request,
            task=_JobInput(
                workflow=OUTLINE_WORKFLOW,
                production_id=plan.production.id,
                project_id=plan.production.project_id,
                chapter_id=plan.production.chapter_id,
                base_chapter_revision=plan.production.base_chapter_revision,
                base_chapter_content_sha256=plan.production.base_chapter_content_sha256,
                context=self._snapshot(plan.packet),
                prompt_version=OUTLINE_PROMPT_VERSION,
                creative_safety=self.projects.require_creative_safety(plan.production.project_id),
                author_intent=request.author_intent,
                label=request.label,
            ),
        )

    def submit_draft(
        self, production_id: str, request: SubmitDraftJobRequest
    ) -> Job:
        check = self.preflight(production_id, request)
        if not check.passed:
            raise ChapterProductionRequestError("preflight_not_passed")
        plan = self._plan(
            production_id,
            workflow=DRAFT_WORKFLOW,
            token_budget=request.token_budget,
            author_intent=request.author_intent,
            outline_guard=request,
        )
        return self._submit(
            plan,
            workflow=DRAFT_WORKFLOW,
            request=request,
            task=_JobInput(
                workflow=DRAFT_WORKFLOW,
                production_id=plan.production.id,
                project_id=plan.production.project_id,
                chapter_id=plan.production.chapter_id,
                base_chapter_revision=plan.production.base_chapter_revision,
                base_chapter_content_sha256=plan.production.base_chapter_content_sha256,
                context=self._snapshot(plan.packet),
                prompt_version=DRAFT_PROMPT_VERSION,
                creative_safety=self.projects.require_creative_safety(plan.production.project_id),
                author_intent=request.author_intent,
                label=request.label,
                outline_candidate_id=request.outline_candidate_id,
                expected_outline_revision=request.expected_outline_revision,
                expected_outline_content_sha256=request.expected_outline_content_sha256,
            ),
        )

    def submit_rewrite(
        self,
        production_id: str,
        candidate_id: str,
        request: SubmitRewriteJobRequest,
    ) -> Job:
        candidate = self.productions.get_candidate(production_id, candidate_id)
        self._require_candidate_guard(candidate, request)
        self._validate_selection(candidate, request.selection, require_unlocked=True)
        plan = self._plan(
            production_id,
            workflow=REWRITE_WORKFLOW,
            token_budget=request.token_budget,
            author_intent=self._rewrite_author_intent(request),
            candidate=candidate,
        )
        return self._submit(
            plan,
            workflow=REWRITE_WORKFLOW,
            request=request,
            task=_JobInput(
                workflow=REWRITE_WORKFLOW,
                production_id=plan.production.id,
                project_id=plan.production.project_id,
                chapter_id=plan.production.chapter_id,
                base_chapter_revision=plan.production.base_chapter_revision,
                base_chapter_content_sha256=plan.production.base_chapter_content_sha256,
                context=self._snapshot(plan.packet),
                prompt_version=REWRITE_PROMPT_VERSION,
                creative_safety=self.projects.require_creative_safety(plan.production.project_id),
                candidate_id=candidate_id,
                expected_candidate_revision=request.expected_candidate_revision,
                expected_candidate_content_sha256=request.expected_candidate_content_sha256,
                selection=request.selection,
                rewrite_intent=request.intent.value,
                custom_instruction=request.custom_instruction,
            ),
        )

    def submit_review(
        self,
        production_id: str,
        candidate_id: str,
        request: SubmitReviewJobRequest,
    ) -> Job:
        candidate = self.productions.get_candidate(production_id, candidate_id)
        self._require_candidate_guard(candidate, request)
        plan = self._plan(
            production_id,
            workflow=REVIEW_WORKFLOW,
            token_budget=request.token_budget,
            author_intent="对本章候选稿执行七维审校",
            candidate=candidate,
        )
        return self._submit(
            plan,
            workflow=REVIEW_WORKFLOW,
            request=request,
            task=_JobInput(
                workflow=REVIEW_WORKFLOW,
                production_id=plan.production.id,
                project_id=plan.production.project_id,
                chapter_id=plan.production.chapter_id,
                base_chapter_revision=plan.production.base_chapter_revision,
                base_chapter_content_sha256=plan.production.base_chapter_content_sha256,
                context=self._snapshot(plan.packet),
                prompt_version=REVIEW_PROMPT_VERSION,
                creative_safety=self.projects.require_creative_safety(plan.production.project_id),
                candidate_id=candidate_id,
                expected_candidate_revision=request.expected_candidate_revision,
                expected_candidate_content_sha256=request.expected_candidate_content_sha256,
            ),
        )

    # ---- worker routing ---------------------------------------------------------------

    def handles(self, job: Job) -> bool:
        return job.workflow in {
            OUTLINE_WORKFLOW,
            DRAFT_WORKFLOW,
            REWRITE_WORKFLOW,
            REVIEW_WORKFLOW,
        }

    def handle(self, context: JobExecutionContext, job: Job) -> None:
        task = _JobInput.model_validate(self.jobs.load_input(job.id))
        if not self.handles(job) or task.workflow != job.workflow:
            raise JobExecutionError("invalid_workflow", "单章生产任务路由无效")
        expected_kind = self._kind(job.workflow)
        if job.kind != expected_kind:
            raise JobExecutionError("invalid_job_kind", "单章生产任务类型无效")
        self._require_worker_current(task)
        packet = self._load_frozen_packet(job.id, task)
        self._require_packet_current(task, packet)
        self._ensure_context_artifact(job, packet, task.creative_safety)
        if job.workflow == REVIEW_WORKFLOW:
            self._handle_review(context, job, task, packet)
        else:
            self._handle_single(context, job, task, packet)

    def get_outline_result(self, production_id: str, job_id: str) -> OutlineCandidate:
        self._require_result_job(production_id, job_id, OUTLINE_WORKFLOW)
        return self.productions.get_outline_job_result(production_id, job_id)

    def get_candidate_result(
        self,
        production_id: str,
        job_id: str,
        workflow: str,
        *,
        candidate_id: str | None = None,
    ) -> DraftCandidate:
        self._require_result_job(production_id, job_id, workflow)
        candidate = self.productions.get_candidate_job_result(production_id, job_id)
        if candidate_id is not None and candidate.id != candidate_id:
            raise ChapterProductionNotFoundError(job_id)
        return candidate

    def get_review_result(
        self, production_id: str, candidate_id: str, job_id: str
    ) -> CandidateReview:
        self._require_result_job(production_id, job_id, REVIEW_WORKFLOW)
        review = self.productions.get_review_job_result(production_id, job_id)
        if review.candidate_id != candidate_id:
            raise ChapterProductionNotFoundError(job_id)
        return review

    # ---- planning internals -----------------------------------------------------------

    def _plan(
        self,
        production_id: str,
        *,
        workflow: str,
        token_budget: int,
        author_intent: str,
        outline_guard: OutlineGuard | None = None,
        candidate: DraftCandidate | None = None,
    ) -> _Plan:
        production, workspace, chapter = self._load_current(production_id)
        transient = chapter
        purpose = CreativeContextPurpose.BRIEF
        if workflow == DRAFT_WORKFLOW:
            if outline_guard is None:
                raise ChapterProductionRequestError("outline_guard_required")
            outline = self.productions.get_outline_candidate(
                production.id, outline_guard.outline_candidate_id
            )
            self._require_outline_guard(outline, outline_guard)
            content = outline.current_version.content
            transient = chapter.model_copy(
                update={
                    "title": content.title or chapter.title,
                    "content": "",
                    "reader_promise": content.reader_promise,
                    "opening_hook": content.opening_hook,
                    "state_change": content.state_change,
                    "emotional_payoff": content.emotional_payoff,
                    "ending_cliffhanger": content.ending_cliffhanger,
                }
            )
            purpose = CreativeContextPurpose.DRAFT
        elif workflow in {REWRITE_WORKFLOW, REVIEW_WORKFLOW}:
            if candidate is None:
                raise ChapterProductionRequestError("candidate_required")
            transient = chapter.model_copy(update={"content": candidate.current_version.content})
            purpose = CreativeContextPurpose.CANDIDATE_REVIEW
        transient_workspace = workspace.model_copy(
            update={
                "chapters": [
                    transient if item.id == chapter.id else item for item in workspace.chapters
                ]
            }
        )
        packet = self.creative_context.compile(
            transient_workspace,
            CreativeContextCompileRequest(
                purpose=purpose,
                subject=CreativeContextSubject(
                    kind=CreativeContextSubjectKind.CHAPTER,
                    id=chapter.id,
                    revision=chapter.revision,
                ),
                token_budget=token_budget,
                window_size=3,
                author_intent=author_intent,
            ),
        )
        self.creative_context.require_usable(packet)
        profile, provider, profile_id, profile_name, model = self._selected_model(workflow)
        input_rate = profile.input_cost_microusd_per_million if profile is not None else None
        output_rate = profile.output_cost_microusd_per_million if profile is not None else None
        if input_rate is not None and output_rate is not None:
            cost = (
                packet.used_tokens * input_rate
                + _OUTPUT_TOKENS[workflow] * output_rate
                + 999_999
            ) // 1_000_000
        elif self.adapter is not None or self._is_local(profile):
            cost = 0
        else:
            cost = None
        return _Plan(
            production=production,
            workspace=transient_workspace,
            chapter=transient,
            packet=packet,
            profile=profile,
            provider=provider,
            profile_id=profile_id,
            profile_name=profile_name,
            model=model,
            estimated_cost_microusd=cost,
        )

    def _preview(self, plan: _Plan, workflow: str) -> ChapterProductionOutboundPreview:
        included_kinds = sorted({item.kind.value for item in plan.packet.items if item.included})
        scope = {
            OUTLINE_WORKFLOW: "只生成本章章纲候选，不修改章节正文",
            DRAFT_WORKFLOW: "只生成完整正文候选，不自动采用",
            REWRITE_WORKFLOW: "只生成选区替换候选，不覆盖正文",
            REVIEW_WORKFLOW: "只审校当前候选 revision，不修改任何文本",
        }[workflow]
        return ChapterProductionOutboundPreview(
            purpose=plan.packet.purpose,
            profile_id=plan.profile_id,
            profile_name=plan.profile_name,
            provider=plan.provider,
            model=plan.model,
            data_types=included_kinds,
            content_scope=scope,
            character_count=len(plan.packet.rendered_context),
            estimated_input_tokens=plan.packet.used_tokens,
            estimated_output_tokens=_OUTPUT_TOKENS[workflow],
            estimated_cost_microusd=plan.estimated_cost_microusd,
            context_packet_id=plan.packet.id,
            context_packet_sha256=plan.packet.packet_sha256,
            context_dependency_fingerprint_sha256=(
                plan.packet.dependency_fingerprint_sha256
            ),
            context_compiler_version=plan.packet.compiler_version,
        )

    def _submit(
        self,
        plan: _Plan,
        *,
        workflow: str,
        request: SubmitOutlineJobRequest
        | SubmitDraftJobRequest
        | SubmitRewriteJobRequest
        | SubmitReviewJobRequest,
        task: _JobInput,
    ) -> Job:
        if (
            request.context_packet_id != plan.packet.id
            or request.context_packet_sha256 != plan.packet.packet_sha256
        ):
            raise ChapterProductionRequestError("preview_changed")
        if (
            self.adapter is None
            and not self._is_local(plan.profile)
            and not request.confirm_external_processing
        ):
            raise ChapterProductionRequestError("external_processing_not_confirmed")
        if plan.estimated_cost_microusd is None and not request.confirm_unknown_cost:
            raise ChapterProductionRequestError("unknown_cost_not_confirmed")
        if (
            plan.estimated_cost_microusd is not None
            and plan.estimated_cost_microusd > 0
            and request.max_estimated_cost_microusd is None
        ):
            raise ChapterProductionRequestError("cost_limit_required")
        if (
            request.max_estimated_cost_microusd is not None
            and plan.estimated_cost_microusd is not None
            and plan.estimated_cost_microusd > request.max_estimated_cost_microusd
        ):
            raise ChapterProductionRequestError("estimated_cost_exceeds_limit")
        payload = task.model_dump(mode="json")
        key = sha256(
            _canonical_json(
                {
                    "task": payload,
                    "kind": self._kind(workflow).value,
                    "provider": plan.provider,
                    "provider_profile_id": plan.profile_id,
                    "model": plan.model,
                }
            ).encode("utf-8")
        ).hexdigest()
        estimated_calls = len(ReviewDimension) if workflow == REVIEW_WORKFLOW else 1
        job, _created = self.jobs.create_job(
            project_id=plan.production.project_id,
            chapter_id=plan.production.chapter_id,
            kind=self._kind(workflow),
            workflow=workflow,
            idempotency_key=key,
            input_payload=payload,
            provider=plan.provider,
            provider_profile_id=plan.profile_id,
            model=plan.model,
            progress_total=estimated_calls,
            estimated_calls=estimated_calls,
        )
        self._ensure_context_artifact(job, plan.packet, task.creative_safety)
        if workflow == REVIEW_WORKFLOW:
            for ordinal, dimension in enumerate(ReviewDimension):
                self.jobs.ensure_chunk(
                    job.id,
                    kind=JobKind.REVIEW,
                    ordinal=ordinal,
                    idempotency_key=f"review:{dimension.value}",
                    input_payload={"dimension": dimension.value},
                )
        else:
            self.jobs.ensure_chunk(
                job.id,
                kind=self._kind(workflow),
                ordinal=0,
                idempotency_key="output",
                input_payload={"workflow": workflow},
            )
        return self.jobs.get_job(job.id)

    # ---- worker internals -------------------------------------------------------------

    def _handle_single(
        self,
        context: JobExecutionContext,
        job: Job,
        task: _JobInput,
        packet: ContextPacket,
    ) -> None:
        chunk = self._one_chunk(job)
        artifact_key = "output"
        artifact = self.jobs.find_artifact(job.id, artifact_key)
        if artifact is not None:
            self._complete_chunk(chunk)
            # Recovery may run long after the immutable provider artifact was
            # written. Never turn it into a candidate unless both the aggregate
            # and its frozen packet are still current at the write boundary.
            self._require_worker_current(task)
            self._require_packet_current(task, packet)
            self._materialize(job, task, artifact.payload)
            self.jobs.update_progress(job.id, current=1, total=1, step="已恢复候选结果")
            return
        if chunk.state == ChunkState.SUCCEEDED:
            raise JobExecutionError("missing_artifact", "已完成任务缺少不可变产物")
        context.checkpoint()
        if chunk.state != ChunkState.RUNNING:
            chunk = self.jobs.transition_chunk(chunk.id, ChunkState.RUNNING)
        self.jobs.update_progress(job.id, current=0, total=1, step="AI 正在生成候选")
        attempt = self.jobs.start_attempt(
            job.id,
            chunk_id=chunk.id,
            provider=job.provider,
            provider_profile_id=job.provider_profile_id,
            model=job.model,
        )
        try:
            payload, metrics = self._call_single(job, task, packet)
            # The author may edit while a paid call is in flight. Re-check before
            # persisting or materialising any model output.
            self._require_worker_current(task)
            self._require_packet_current(task, packet)
        except Exception as error:
            self._fail_attempt(attempt.id, chunk.id, error)
            raise self._execution_error(error) from error
        self.jobs.put_artifact(
            job.id,
            chunk_id=chunk.id,
            kind=job.workflow,
            artifact_key=artifact_key,
            payload=payload,
            content_type="application/json",
            metadata={"production_id": task.production_id, "prompt_version": task.prompt_version},
            provider=job.provider,
            provider_profile_id=job.provider_profile_id,
            model=job.model,
        )
        self._finish_attempt(attempt.id, metrics)
        self.jobs.transition_chunk(chunk.id, ChunkState.SUCCEEDED)
        # There is an intentional crash boundary between storing the immutable
        # provider artifact and materialising the editable candidate. Re-check
        # here as well so an intervening author edit leaves only a safely
        # recoverable artifact, never a stale candidate.
        self._require_worker_current(task)
        self._require_packet_current(task, packet)
        self._materialize(job, task, payload)
        self.jobs.update_progress(job.id, current=1, total=1, step="候选已生成")

    def _handle_review(
        self,
        context: JobExecutionContext,
        job: Job,
        task: _JobInput,
        packet: ContextPacket,
    ) -> None:
        candidate = self._task_candidate(task)
        findings: list[CandidateReviewFinding] = []
        chunks = self.jobs.list_chunks(job.id)
        if len(chunks) != len(ReviewDimension):
            raise JobExecutionError("invalid_plan", "候选审校任务计划不完整")
        for ordinal, dimension in enumerate(ReviewDimension):
            self._require_worker_current(task)
            self._require_packet_current(task, packet)
            chunk = chunks[ordinal]
            artifact_key = f"review:{dimension.value}"
            artifact = self.jobs.find_artifact(job.id, artifact_key)
            if artifact is None:
                if chunk.state == ChunkState.SUCCEEDED:
                    raise JobExecutionError("missing_artifact", "审校任务缺少不可变产物")
                context.checkpoint()
                if chunk.state != ChunkState.RUNNING:
                    chunk = self.jobs.transition_chunk(chunk.id, ChunkState.RUNNING)
                self.jobs.update_progress(
                    job.id,
                    current=ordinal,
                    total=len(chunks),
                    step=f"正在审校：{dimension.value}",
                )
                attempt = self.jobs.start_attempt(
                    job.id,
                    chunk_id=chunk.id,
                    provider=job.provider,
                    provider_profile_id=job.provider_profile_id,
                    model=job.model,
                )
                try:
                    result, metrics = self._call_review_dimension(
                        job, packet, candidate, dimension
                    )
                    self._require_worker_current(task)
                    self._require_packet_current(task, packet)
                except Exception as error:
                    self._fail_attempt(attempt.id, chunk.id, error)
                    raise self._execution_error(error) from error
                artifact, _created = self.jobs.put_artifact(
                    job.id,
                    chunk_id=chunk.id,
                    kind="candidate_review_dimension",
                    artifact_key=artifact_key,
                    payload=result.model_dump_json(),
                    content_type="application/json",
                    metadata={"dimension": dimension.value},
                    provider=job.provider,
                    provider_profile_id=job.provider_profile_id,
                    model=job.model,
                )
                self._finish_attempt(attempt.id, metrics)
                self.jobs.transition_chunk(chunk.id, ChunkState.SUCCEEDED)
            else:
                self._complete_chunk(chunk)
            parsed = CandidateReviewDraft.model_validate_json(artifact.payload)
            findings.extend(parsed.findings)
        self._require_worker_current(task)
        self._require_packet_current(task, packet)
        aggregate = AdapterReviewResult(
            review=CandidateReviewDraft(findings=findings),
            prompt_version=task.prompt_version,
        )
        self._materialize(job, task, aggregate.model_dump_json())
        self.jobs.update_progress(
            job.id,
            current=len(chunks),
            total=len(chunks),
            step="候选审校已完成",
        )

    def _call_single(
        self, job: Job, task: _JobInput, packet: ContextPacket
    ) -> tuple[str, ProviderCallMetrics | None]:
        if job.workflow == OUTLINE_WORKFLOW:
            if self.adapter is not None:
                outline_result = self.adapter.propose_outline(
                    OutlineGenerationInput(
                        context=self._snapshot(packet), author_intent=task.author_intent
                    )
                )
                return outline_result.model_dump_json(), None
            gateway = self._gateway_for_job(job)
            proposal = require_compiled_context_gateway(gateway).propose_brief_from_context(
                packet.rendered_context
            )
            outline_result = AdapterOutlineResult(
                outline=ChapterOutline(
                    title=proposal.title,
                    reader_promise=proposal.reader_promise,
                    opening_hook=proposal.opening_hook,
                    state_change=proposal.state_change,
                    emotional_payoff=proposal.emotional_payoff,
                    ending_cliffhanger=proposal.ending_cliffhanger,
                    scene_beats=[],
                ),
                prompt_version=task.prompt_version,
            )
            return outline_result.model_dump_json(), consume_ai_call_metrics(gateway)
        if job.workflow == DRAFT_WORKFLOW:
            outline = self._task_outline(task)
            if self.adapter is not None:
                draft_result = self.adapter.draft_chapter(
                    DraftGenerationInput(
                        context=self._snapshot(packet),
                        outline=outline.current_version.content,
                        author_intent=task.author_intent,
                    )
                )
                return draft_result.model_dump_json(), None
            gateway = self._gateway_for_job(job)
            content = require_compiled_context_gateway(gateway).draft_chapter_from_context(
                packet.rendered_context
            )
            return (
                AdapterTextResult(content=content, prompt_version=task.prompt_version).model_dump_json(),
                consume_ai_call_metrics(gateway),
            )
        if job.workflow != REWRITE_WORKFLOW:
            raise JobExecutionError("invalid_workflow", "未知单章生产工作流")
        candidate = self._task_candidate(task)
        assert task.selection is not None and task.rewrite_intent is not None
        selected = self._validate_selection(candidate, task.selection, require_unlocked=True)
        rewrite_input = RewriteGenerationInput(
            context=self._snapshot(packet),
            full_content=candidate.current_version.content,
            selected_text=selected,
            intent=RewriteIntent(task.rewrite_intent),
            custom_instruction=task.custom_instruction,
        )
        if self.adapter is not None:
            rewrite_result = self.adapter.rewrite_selection(rewrite_input)
            return rewrite_result.model_dump_json(), None
        gateway = self._gateway_for_job(job)
        content, metrics = self._rewrite_with_gateway(gateway, rewrite_input)
        return (
            AdapterTextResult(content=content, prompt_version=task.prompt_version).model_dump_json(),
            metrics,
        )

    def _call_review_dimension(
        self,
        job: Job,
        packet: ContextPacket,
        candidate: DraftCandidate,
        dimension: ReviewDimension,
    ) -> tuple[CandidateReviewDraft, ProviderCallMetrics | None]:
        if self.adapter is not None:
            # The demo adapter returns all seven dimensions in one deterministic call.
            complete = self.adapter.review_candidate(
                ReviewGenerationInput(
                    context=self._snapshot(packet),
                    candidate_content=candidate.current_version.content,
                )
            ).review
            return (
                CandidateReviewDraft(
                    findings=[item for item in complete.findings if item.dimension == dimension]
                ),
                None,
            )
        gateway = self._gateway_for_job(job)
        result = gateway.review_chapter(packet.rendered_context, dimension)
        findings = [
            CandidateReviewFinding(
                dimension=dimension,
                severity=item.severity,
                summary=f"{item.title}：{item.explanation}"[:1_200],
                suggestion=item.suggestion[:1_200],
            )
            for item in result.findings
        ]
        return CandidateReviewDraft(findings=findings), consume_ai_call_metrics(gateway)

    def _rewrite_with_gateway(
        self, gateway: AiGateway, request: RewriteGenerationInput
    ) -> tuple[str, ProviderCallMetrics | None]:
        if isinstance(gateway, _SelectionRewriteGateway):
            content = gateway.rewrite_selection_from_context(
                request.context.rendered_context,
                request.selected_text,
                request.intent.value,
                request.custom_instruction,
            ).strip()
            return content, consume_ai_call_metrics(gateway)
        if not isinstance(gateway, OpenAiGateway):
            raise AiProviderError(
                "当前模型线路不支持选区改写",
                category=AiErrorCategory.UNSUPPORTED_CAPABILITY,
                safe_message="当前模型线路不支持选区改写，模型未调用",
                retryable=False,
            )
        input_text = _canonical_json(
            {
                "creative_context": json.loads(request.context.rendered_context),
                "selection": request.selected_text,
                "intent": request.intent.value,
                "custom_instruction": request.custom_instruction,
            }
        )
        try:
            result = gateway.adapter.generate_text(
                instructions=_REWRITE_INSTRUCTIONS,
                input_text=input_text,
                max_output_tokens=4_000,
            )
        except ProviderCallError as error:
            raise AiProviderError(
                "AI 选区改写失败",
                category=error.category,
                safe_message=error.safe_message,
                retryable=error.retryable,
                duration_ms=error.duration_ms,
            ) from error
        content = result.output.strip()
        if not content:
            raise AiProviderError("AI 未返回可用改写")
        metrics = ProviderCallMetrics(
            usage=result.usage,
            duration_ms=result.duration_ms,
            estimated_cost_microusd=self._actual_cost(
                result.usage.input_tokens,
                result.usage.output_tokens,
                self._profile_for_job(gateway.status().profile_id),
            ),
        )
        return content, metrics

    def _materialize(self, job: Job, task: _JobInput, payload: str) -> object:
        trace = ModelTrace(
            purpose=task.context.purpose,
            context_packet_id=task.context.packet_id,
            context_packet_sha256=task.context.packet_sha256,
            context_dependency_fingerprint_sha256=(
                task.context.dependency_fingerprint_sha256
            ),
            context_compiler_version=task.context.compiler_version,
            profile_fingerprint_sha256=task.context.profile_fingerprint_sha256,
            provider=job.provider,
            model=job.model,
            prompt_version=task.prompt_version,
        )
        if job.workflow == OUTLINE_WORKFLOW:
            outline_result = AdapterOutlineResult.model_validate_json(payload)
            return self.productions.add_outline_candidate(
                production_id=task.production_id,
                outline=outline_result.outline,
                label=task.label,
                trace=trace,
                source_job_id=job.id,
            )
        if job.workflow == DRAFT_WORKFLOW:
            draft_result = AdapterTextResult.model_validate_json(payload)
            assert task.outline_candidate_id is not None
            assert task.expected_outline_revision is not None
            assert task.expected_outline_content_sha256 is not None
            return self.productions.create_draft_candidate(
                production_id=task.production_id,
                outline_candidate_id=task.outline_candidate_id,
                expected_outline_revision=task.expected_outline_revision,
                expected_outline_content_sha256=task.expected_outline_content_sha256,
                content=draft_result.content,
                label=task.label,
                trace=trace,
                source_job_id=job.id,
            )
        if job.workflow == REWRITE_WORKFLOW:
            rewrite_result = AdapterTextResult.model_validate_json(payload)
            assert task.candidate_id is not None
            assert task.expected_candidate_revision is not None
            assert task.expected_candidate_content_sha256 is not None
            assert task.selection is not None
            return self.productions.replace_candidate_selection(
                production_id=task.production_id,
                candidate_id=task.candidate_id,
                expected_candidate_revision=task.expected_candidate_revision,
                expected_candidate_content_sha256=task.expected_candidate_content_sha256,
                selection=task.selection,
                replacement=rewrite_result.content,
                operation=CandidateVersionOperation.LOCAL_REWRITE,
                instruction=(task.custom_instruction or cast(str, task.rewrite_intent)),
                trace=trace,
                source_job_id=job.id,
            )
        if job.workflow == REVIEW_WORKFLOW:
            review_result = AdapterReviewResult.model_validate_json(payload)
            assert task.candidate_id is not None
            assert task.expected_candidate_revision is not None
            assert task.expected_candidate_content_sha256 is not None
            return self.productions.save_candidate_review(
                production_id=task.production_id,
                candidate_id=task.candidate_id,
                expected_candidate_revision=task.expected_candidate_revision,
                expected_candidate_content_sha256=task.expected_candidate_content_sha256,
                review=review_result.review,
                trace=trace,
                source_job_id=job.id,
            )
        raise JobExecutionError("invalid_workflow", "未知单章生产工作流")

    # ---- guards and helpers -----------------------------------------------------------

    def _load_current(
        self, production_id: str
    ) -> tuple[ChapterProduction, Workspace, Chapter]:
        production = self.productions.get_production(production_id)
        if production.state.value in {"adopted", "rejected"}:
            raise ChapterProductionRequestError("production_closed")
        try:
            workspace = self.projects.get_workspace(production.project_id)
            chapter = next(item for item in workspace.chapters if item.id == production.chapter_id)
        except (NotFoundError, StopIteration) as error:
            raise ChapterProductionNotFoundError(production.chapter_id) from error
        if (
            chapter.revision != production.base_chapter_revision
            or text_sha256(chapter.content) != production.base_chapter_content_sha256
        ):
            raise ChapterProductionRequestError("chapter_changed")
        if chapter.status == ChapterStatus.APPROVED:
            raise ChapterProductionRequestError("approved_chapter_immutable")
        self.projects.require_creative_safety(production.project_id)
        return production, workspace, chapter

    def _require_worker_current(self, task: _JobInput) -> None:
        try:
            production, _workspace, _chapter = self._load_current(task.production_id)
            if (
                production.project_id != task.project_id
                or production.chapter_id != task.chapter_id
                or production.base_chapter_revision != task.base_chapter_revision
                or production.base_chapter_content_sha256
                != task.base_chapter_content_sha256
            ):
                raise ChapterProductionRequestError("production_changed")
            current_safety = self.projects.require_creative_safety(
                task.project_id, task.creative_safety
            )
            if (
                current_safety is not None
                and current_safety.mode == "pattern_adaptation"
                and task.creative_safety is None
            ):
                raise ChapterProductionRequestError("creative_safety_changed")
            if task.workflow == DRAFT_WORKFLOW:
                outline = self._task_outline(task)
                checks = [
                    bool(cast(str, getattr(outline.current_version.content, field)).strip())
                    for field in PREWRITE_FIELDS
                ]
                if not all(checks):
                    raise ChapterProductionRequestError("preflight_not_passed")
            elif task.workflow in {REWRITE_WORKFLOW, REVIEW_WORKFLOW}:
                candidate = self._task_candidate(task)
                if task.workflow == REWRITE_WORKFLOW:
                    assert task.selection is not None
                    self._validate_selection(candidate, task.selection, require_unlocked=True)
        except (ChapterProductionConflictError, OriginalityGateBlockedError) as error:
            raise JobExecutionError(
                str(error),
                "单章生产依赖已变化，请重新预览后提交；模型未调用",
            ) from error

    def _load_frozen_packet(self, job_id: str, task: _JobInput) -> ContextPacket:
        try:
            packet = self.contexts.get_packet(task.context.packet_id)
        except ContextPacketNotFoundError:
            artifact = self.jobs.find_artifact(job_id, "context_packet")
            if artifact is None:
                raise JobExecutionError(
                    "context_packet_missing", "任务冻结的创作上下文不存在"
                ) from None
            try:
                packet = ContextPacket.model_validate_json(artifact.payload)
            except ValueError as error:
                raise JobExecutionError(
                    "context_packet_invalid", "任务冻结的创作上下文损坏"
                ) from error
        if (
            packet.project_id != task.project_id
            or packet.chapter_id != task.chapter_id
            or packet.purpose != task.context.purpose
            or packet.packet_sha256 != task.context.packet_sha256
            or packet.dependency_fingerprint_sha256
            != task.context.dependency_fingerprint_sha256
            or packet.compiler_version != task.context.compiler_version
            or packet.profile_fingerprint_sha256 != task.context.profile_fingerprint_sha256
        ):
            raise JobExecutionError(
                "context_packet_mismatch", "任务上下文完整性校验失败，模型未调用"
            )
        return packet

    def _require_packet_current(self, task: _JobInput, packet: ContextPacket) -> None:
        try:
            self.creative_context.require_current(
                packet,
                preserve_frozen_subject=task.workflow != OUTLINE_WORKFLOW,
            )
        except (CreativeContextBlockedError, CreativeContextChangedError) as error:
            raise JobExecutionError(
                "creative_context_changed",
                "创作上下文已变化，请重新预览后提交；模型未调用",
            ) from error

    def _ensure_context_artifact(
        self,
        job: Job,
        packet: ContextPacket,
        creative_safety: CreativeSafetyProvenance | None,
    ) -> None:
        self.jobs.put_artifact(
            job.id,
            kind="context_packet",
            artifact_key="context_packet",
            payload=packet.model_dump_json(),
            content_type="application/json",
            metadata={
                "packet_sha256": packet.packet_sha256,
                "dependency_fingerprint_sha256": packet.dependency_fingerprint_sha256,
                "creative_safety": (
                    creative_safety.model_dump(mode="json")
                    if creative_safety is not None
                    else None
                ),
            },
            provider="local",
            model=packet.compiler_version,
        )

    def _selected_model(
        self, workflow: str
    ) -> tuple[ModelProfile | None, str, str | None, str, str]:
        if self.adapter is not None:
            return None, self.adapter.provider, None, "本地示范模型", self.adapter.model
        task_type = self._task_type(workflow)
        profile = self.profiles.get_task_profile(task_type)
        gateway = self.manager.gateway_for(profile.id) if profile is not None else self.manager.gateway()
        status = gateway.status()
        if not status.configured or (
            profile is not None
            and (status.profile_id != profile.id or status.model != profile.model)
        ):
            raise AiNotConfiguredError
        return (
            profile,
            status.provider.value,
            status.profile_id,
            status.profile_name or (profile.name if profile is not None else "当前会话线路"),
            status.model,
        )

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
                "provider_unavailable", "任务使用的模型配置当前不可用"
            )
        return gateway

    @staticmethod
    def _kind(workflow: str) -> JobKind:
        if workflow == OUTLINE_WORKFLOW:
            return JobKind.CHAPTER_BRIEF
        if workflow in {DRAFT_WORKFLOW, REWRITE_WORKFLOW}:
            return JobKind.CHAPTER_DRAFT
        if workflow == REVIEW_WORKFLOW:
            return JobKind.REVIEW
        raise ChapterProductionRequestError("invalid_workflow")

    @staticmethod
    def _task_type(workflow: str) -> AiTaskType:
        return {
            OUTLINE_WORKFLOW: AiTaskType.CHAPTER_BRIEF,
            DRAFT_WORKFLOW: AiTaskType.CHAPTER_DRAFT,
            REWRITE_WORKFLOW: AiTaskType.CHAPTER_DRAFT,
            REVIEW_WORKFLOW: AiTaskType.REVIEW,
        }[workflow]

    @staticmethod
    def _snapshot(packet: ContextPacket) -> CreativeContextSnapshot:
        return CreativeContextSnapshot(
            purpose=packet.purpose,
            packet_id=packet.id,
            packet_sha256=packet.packet_sha256,
            dependency_fingerprint_sha256=packet.dependency_fingerprint_sha256,
            compiler_version=packet.compiler_version,
            profile_fingerprint_sha256=packet.profile_fingerprint_sha256,
            rendered_context=packet.rendered_context,
        )

    @staticmethod
    def _require_outline_guard(candidate: OutlineCandidate, guard: OutlineGuard) -> None:
        if (
            candidate.current_version.revision != guard.expected_outline_revision
            or candidate.current_version.content_sha256
            != guard.expected_outline_content_sha256
        ):
            raise ChapterProductionRequestError("outline_candidate_changed")

    @staticmethod
    def _require_candidate_guard(
        candidate: DraftCandidate, guard: CandidateGuard
    ) -> None:
        if (
            candidate.current_version.revision != guard.expected_candidate_revision
            or candidate.current_version.content_sha256
            != guard.expected_candidate_content_sha256
        ):
            raise ChapterProductionRequestError("candidate_changed")

    @staticmethod
    def _validate_selection(
        candidate: DraftCandidate,
        selection: TextSelection,
        *,
        require_unlocked: bool,
    ) -> str:
        content = candidate.current_version.content
        if selection.end_char > len(content):
            raise ChapterProductionRequestError("selection_out_of_bounds")
        selected = content[selection.start_char : selection.end_char]
        if text_sha256(selected) != selection.selected_text_sha256:
            raise ChapterProductionRequestError("selection_changed")
        if require_unlocked and any(
            selection.start_char < lock.end_char and selection.end_char > lock.start_char
            for lock in candidate.locks
        ):
            raise ChapterProductionRequestError("selection_locked")
        return selected

    def _task_outline(self, task: _JobInput) -> OutlineCandidate:
        if (
            task.outline_candidate_id is None
            or task.expected_outline_revision is None
            or task.expected_outline_content_sha256 is None
        ):
            raise ChapterProductionRequestError("outline_guard_required")
        outline = self.productions.get_outline_candidate(
            task.production_id, task.outline_candidate_id
        )
        self._require_outline_guard(
            outline,
            OutlineGuard(
                outline_candidate_id=task.outline_candidate_id,
                expected_outline_revision=task.expected_outline_revision,
                expected_outline_content_sha256=task.expected_outline_content_sha256,
            ),
        )
        return outline

    def _task_candidate(self, task: _JobInput) -> DraftCandidate:
        if (
            task.candidate_id is None
            or task.expected_candidate_revision is None
            or task.expected_candidate_content_sha256 is None
        ):
            raise ChapterProductionRequestError("candidate_guard_required")
        candidate = self.productions.get_candidate(task.production_id, task.candidate_id)
        self._require_candidate_guard(
            candidate,
            CandidateGuard(
                expected_candidate_revision=task.expected_candidate_revision,
                expected_candidate_content_sha256=task.expected_candidate_content_sha256,
            ),
        )
        return candidate

    def _one_chunk(self, job: Job) -> JobChunk:
        chunks = self.jobs.list_chunks(job.id)
        if len(chunks) != 1:
            raise JobExecutionError("invalid_plan", "单章生产任务计划不完整")
        return chunks[0]

    def _complete_chunk(self, chunk: JobChunk) -> None:
        if chunk.state == ChunkState.SUCCEEDED:
            return
        if chunk.state != ChunkState.RUNNING:
            chunk = self.jobs.transition_chunk(chunk.id, ChunkState.RUNNING)
        self.jobs.transition_chunk(chunk.id, ChunkState.SUCCEEDED)

    def _finish_attempt(
        self, attempt_id: str, metrics: ProviderCallMetrics | None
    ) -> None:
        self.jobs.finish_attempt(
            attempt_id,
            AttemptState.SUCCEEDED,
            input_tokens=metrics.usage.input_tokens if metrics else None,
            output_tokens=metrics.usage.output_tokens if metrics else None,
            duration_ms=metrics.duration_ms if metrics else None,
            estimated_cost_microusd=metrics.estimated_cost_microusd if metrics else None,
        )

    def _fail_attempt(self, attempt_id: str, chunk_id: str, error: Exception) -> None:
        execution = self._execution_error(error)
        self.jobs.finish_attempt(
            attempt_id,
            AttemptState.FAILED,
            duration_ms=(
                error.duration_ms
                if isinstance(error, AiProviderError) and error.duration_ms is not None
                else None
            ),
            error_code=execution.code,
            error_message=execution.safe_message,
        )
        self.jobs.transition_chunk(
            chunk_id,
            ChunkState.FAILED,
            error_code=execution.code,
            error_message=execution.safe_message,
        )

    @staticmethod
    def _execution_error(error: Exception) -> JobExecutionError:
        if isinstance(error, JobExecutionError):
            return error
        if isinstance(error, AiProviderError):
            return JobExecutionError(error.category.value, error.safe_message)
        if isinstance(error, ProviderCallError):
            return JobExecutionError(error.category.value, error.safe_message)
        if isinstance(error, ChapterProductionConflictError):
            return JobExecutionError(str(error), "候选或章节已变化，模型结果未写入")
        return JobExecutionError("provider_error", "模型服务未完成本次单章任务")

    def _require_result_job(self, production_id: str, job_id: str, workflow: str) -> Job:
        job = self.jobs.get_job(job_id)
        production = self.productions.get_production(production_id)
        if (
            job.project_id != production.project_id
            or job.chapter_id != production.chapter_id
            or job.workflow != workflow
        ):
            raise ChapterProductionNotFoundError(job_id)
        return job

    @staticmethod
    def _rewrite_author_intent(request: RegenerateSelectionRequest) -> str:
        return f"选区改写意图：{request.intent.value}；{request.custom_instruction}".strip("；")

    @staticmethod
    def _is_local(profile: ModelProfile | None) -> bool:
        if profile is None:
            return False
        hostname = (urlparse(profile.base_url).hostname or "").casefold()
        return hostname in {"localhost", "127.0.0.1", "::1"}

    def _profile_for_job(self, profile_id: str | None) -> ModelProfile | None:
        if profile_id is None:
            return None
        try:
            return self.profiles.get_profile(profile_id)
        except ModelProfileNotFoundError:
            return None

    @staticmethod
    def _actual_cost(
        input_tokens: int | None,
        output_tokens: int | None,
        profile: ModelProfile | None,
    ) -> int | None:
        if (
            input_tokens is None
            or output_tokens is None
            or profile is None
            or profile.input_cost_microusd_per_million is None
            or profile.output_cost_microusd_per_million is None
        ):
            return None
        return (
            input_tokens * profile.input_cost_microusd_per_million
            + output_tokens * profile.output_cost_microusd_per_million
            + 999_999
        ) // 1_000_000
