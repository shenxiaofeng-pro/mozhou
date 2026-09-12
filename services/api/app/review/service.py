import json
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from hashlib import sha256

from pydantic import BaseModel, Field

from app.ai import (
    AiGateway,
    AiGatewayManager,
    AiNotConfiguredError,
    AiProviderError,
    consume_ai_call_metrics,
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
from app.context.compiler import estimate_tokens
from app.creative_safety import CreativeSafetyProvenance
from app.jobs.models import AttemptState, ChunkState, Job, JobAttempt, JobChunk, JobKind
from app.jobs.repository import JobRepository
from app.jobs.runtime import JobExecutionContext, JobExecutionError
from app.models import (
    Chapter,
    ReviewChapterRequest,
    ReviewDimension,
    ReviewDimensionOutcome,
    ReviewDimensionState,
    ReviewEvidence,
    ReviewEvidenceKind,
    ReviewFinding,
    ReviewFindingDraftSet,
    ReviewJobResult,
    ReviewOutboundPreview,
    Workspace,
)
from app.providers import (
    AiTaskType,
    ModelProfile,
    ModelProfileNotFoundError,
    ModelProfileRepository,
    ProviderCallMetrics,
)
from app.repository import (
    NotFoundError,
    OriginalityGateBlockedError,
    ProjectRepository,
    StaleRevisionError,
)
from app.review.repository import ReviewRepository
from app.review.rules import (
    EXTERNAL_REVIEW_DIMENSIONS,
    LOCAL_REVIEW_DIMENSIONS,
    build_local_findings,
    make_finding,
)

REVIEW_WORKFLOW = "chapter_review"
REVIEW_PROMPT_VERSION = "chapter-review-v1"


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _estimated_cost(
    input_tokens: int,
    output_tokens: int,
    input_rate: int | None,
    output_rate: int | None,
) -> int | None:
    if input_rate is None or output_rate is None:
        return None
    return (
        input_tokens * input_rate + output_tokens * output_rate + 999_999
    ) // 1_000_000


class ReviewJobInput(BaseModel):
    chapter_id: str
    chapter_revision: int = Field(ge=0)
    window_size: int = Field(ge=1, le=10)
    dimensions: list[ReviewDimension] = Field(min_length=1, max_length=7)
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_packet_id: str = Field(min_length=36, max_length=36)
    context_compiler_version: str = Field(min_length=1, max_length=80)
    context_dependency_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_version: str
    creative_safety: CreativeSafetyProvenance | None = None


class ReviewDimensionArtifact(BaseModel):
    dimension: ReviewDimension
    findings: list[ReviewFinding] = Field(default_factory=list, max_length=20)


class ReviewService:
    def __init__(
        self,
        repository: ProjectRepository,
        reviews: ReviewRepository,
        jobs: JobRepository,
        manager: AiGatewayManager,
        profiles: ModelProfileRepository | None = None,
        contexts: ContextRepository | None = None,
        creative_context: CreativeContextService | None = None,
    ) -> None:
        self.repository = repository
        self.reviews = reviews
        self.jobs = jobs
        self.manager = manager
        self.profiles = profiles
        self.contexts = contexts or ContextRepository(repository.database)
        self.creative_context = creative_context or CreativeContextService(
            repository,
            self.contexts,
        )

    def preview(
        self,
        chapter_id: str,
        request: ReviewChapterRequest,
    ) -> ReviewOutboundPreview:
        _workspace, target, review_window, packet = self._snapshot(
            chapter_id,
            request.expected_revision,
            request.window_size,
            request.dimensions,
        )
        context_text = packet.rendered_context
        external = [
            dimension
            for dimension in request.dimensions
            if dimension in EXTERNAL_REVIEW_DIMENSIONS
        ]
        local = [
            dimension
            for dimension in request.dimensions
            if dimension in LOCAL_REVIEW_DIMENSIONS
        ]
        profile, profile_name, provider, model = self._preview_profile(bool(external))
        base_tokens = estimate_tokens(context_text)
        input_tokens = base_tokens * len(external)
        output_tokens = 1_200 * len(external)
        return ReviewOutboundPreview(
            profile_id=profile.id if profile is not None else None,
            profile_name=profile_name,
            provider=provider,
            model=model,
            dimensions=request.dimensions,
            local_dimensions=local,
            external_dimensions=external,
            data_types=[
                "目标章节正文",
                f"最近 {len(review_window)} 章正文",
                "正式事实、人物、伏笔与双时间线",
                "已确认现实资料与整书计划",
            ],
            content_scope=(
                f"第 {target.chapter_number} 章 · {len(review_window)} 章窗口 · "
                f"{len(local)} 个本地维度 / {len(external)} 个模型维度"
            ),
            character_count=len(context_text),
            estimated_input_tokens=input_tokens,
            estimated_output_tokens=output_tokens,
            estimated_calls=len(external),
            estimated_cost_microusd=_estimated_cost(
                input_tokens,
                output_tokens,
                (
                    profile.input_cost_microusd_per_million
                    if profile is not None
                    else None
                ),
                (
                    profile.output_cost_microusd_per_million
                    if profile is not None
                    else None
                ),
            ),
            context_sha256=sha256(context_text.encode("utf-8")).hexdigest(),
            context_packet=packet.model_dump(mode="json"),
        )

    def submit(self, chapter_id: str, request: ReviewChapterRequest) -> Job:
        preview = self.preview(chapter_id, request)
        if preview.external_dimensions and not request.confirm_external_processing:
            raise ValueError("external_processing_not_confirmed")
        if (
            request.max_estimated_cost_microusd is not None
            and preview.estimated_cost_microusd is not None
            and preview.estimated_cost_microusd > request.max_estimated_cost_microusd
        ):
            raise ValueError("estimated_cost_exceeds_limit")
        workspace, target, _review_window, packet = self._snapshot(
            chapter_id,
            request.expected_revision,
            request.window_size,
            request.dimensions,
        )
        self.creative_context.require_usable(packet)
        creative_safety = self.repository.require_creative_safety(workspace.project.id)
        if preview.context_sha256 != sha256(packet.rendered_context.encode("utf-8")).hexdigest():
            raise StaleRevisionError(str(target.revision))
        if request.parent_job_id is not None:
            parent = self.jobs.get_job(request.parent_job_id)
            if (
                parent.workflow != REVIEW_WORKFLOW
                or parent.chapter_id != chapter_id
                or parent.project_id != workspace.project.id
            ):
                raise ValueError("review_parent_mismatch")
        task_input = ReviewJobInput(
            chapter_id=chapter_id,
            chapter_revision=target.revision,
            window_size=request.window_size,
            dimensions=request.dimensions,
            context_sha256=preview.context_sha256,
            context_packet_id=packet.id,
            context_compiler_version=packet.compiler_version,
            context_dependency_fingerprint_sha256=packet.dependency_fingerprint_sha256,
            prompt_version=REVIEW_PROMPT_VERSION,
            creative_safety=creative_safety,
        )
        input_payload = task_input.model_dump(mode="json")
        idempotency_key = sha256(
            _canonical_json(
                {
                    **input_payload,
                    "profile_id": preview.profile_id,
                    "model": preview.model,
                    "parent_job_id": request.parent_job_id,
                }
            ).encode("utf-8")
        ).hexdigest()
        job, _created = self.jobs.create_job(
            project_id=workspace.project.id,
            chapter_id=chapter_id,
            parent_job_id=request.parent_job_id,
            kind=JobKind.REVIEW,
            workflow=REVIEW_WORKFLOW,
            idempotency_key=idempotency_key,
            input_payload=input_payload,
            provider=preview.provider,
            provider_profile_id=preview.profile_id,
            model=preview.model,
            progress_total=len(request.dimensions),
            estimated_calls=preview.estimated_calls,
        )
        self._put_context_artifact(job.id, packet, task_input)
        self._ensure_chunks(job.id, task_input)
        return self.jobs.get_job(job.id)

    def handle(self, context: JobExecutionContext, job: Job) -> None:
        if job.kind != JobKind.REVIEW or job.workflow != REVIEW_WORKFLOW:
            raise JobExecutionError("invalid_workflow", "章节审校任务类型无效")
        task_input = ReviewJobInput.model_validate(self.jobs.load_input(job.id))
        try:
            current_safety = self.repository.require_creative_safety(
                job.project_id, task_input.creative_safety
            )
        except OriginalityGateBlockedError as error:
            raise JobExecutionError(
                "creative_safety_changed",
                "创作安全依赖已变化，请重新预览后提交；模型未调用",
            ) from error
        if (
            current_safety is not None
            and current_safety.mode == "pattern_adaptation"
            and task_input.creative_safety is None
        ):
            raise JobExecutionError(
                "creative_safety_changed",
                "旧任务缺少创作安全快照，请重新预览后提交；模型未调用",
            )
        workspace = self.repository.get_workspace_for_chapter(task_input.chapter_id)
        try:
            target = next(
                chapter for chapter in workspace.chapters if chapter.id == task_input.chapter_id
            )
        except StopIteration as error:
            raise JobExecutionError("review_context_changed", "审校章节已不存在") from error
        if target.revision != task_input.chapter_revision:
            raise JobExecutionError(
                "review_context_changed",
                "审校章节已有新版本，请重新预览后提交",
            )
        eligible = [
            chapter
            for chapter in workspace.chapters
            if chapter.chapter_number <= target.chapter_number
        ]
        review_window = eligible[-task_input.window_size :]
        packet = self._load_frozen_context_packet(job.id, task_input)
        if (
            packet.project_id != job.project_id
            or packet.chapter_id != task_input.chapter_id
            or packet.chapter_revision != task_input.chapter_revision
            or packet.purpose != CreativeContextPurpose.CANDIDATE_REVIEW
            or packet.compiler_version != task_input.context_compiler_version
            or packet.dependency_fingerprint_sha256
            != task_input.context_dependency_fingerprint_sha256
            or sha256(packet.rendered_context.encode("utf-8")).hexdigest()
            != task_input.context_sha256
        ):
            raise JobExecutionError(
                "review_context_invalid",
                "冻结的审校上下文完整性校验失败，未调用模型",
            )
        try:
            self.creative_context.require_current(packet)
        except (CreativeContextBlockedError, CreativeContextChangedError) as error:
            raise JobExecutionError(
                "creative_context_changed",
                "创作上下文依赖已变化或超出预算，请重新预览后提交；模型未调用",
            ) from error
        rebuilt_context = packet.rendered_context
        artifact = self.jobs.find_artifact(job.id, "review_context")
        if artifact is None:
            self._put_context_artifact(job.id, packet, task_input)
        chunks = self._ensure_chunks(job.id, task_input)
        chunks_by_dimension = {
            ReviewDimension(self.jobs.load_chunk_input(chunk.id)["dimension"]): chunk
            for chunk in chunks
        }
        completed = 0
        failed = 0
        pending_external: dict[
            ReviewDimension,
            tuple[JobChunk, JobAttempt],
        ] = {}
        gateway: AiGateway | None = None
        if any(
            dimension in EXTERNAL_REVIEW_DIMENSIONS
            for dimension in task_input.dimensions
        ):
            gateway = self._gateway_for_job(job)

        for dimension in task_input.dimensions:
            context.checkpoint()
            chunk = chunks_by_dimension[dimension]
            existing = self.jobs.find_artifact(job.id, f"review:{dimension.value}")
            if existing is not None:
                parsed = ReviewDimensionArtifact.model_validate_json(existing.payload)
                self.reviews.save_findings(parsed.findings)
                if chunk.state != ChunkState.SUCCEEDED:
                    if chunk.state != ChunkState.RUNNING:
                        chunk = self.jobs.transition_chunk(chunk.id, ChunkState.RUNNING)
                    self.jobs.transition_chunk(chunk.id, ChunkState.SUCCEEDED)
                completed += 1
                continue
            if dimension in LOCAL_REVIEW_DIMENSIONS:
                if chunk.state != ChunkState.RUNNING:
                    chunk = self.jobs.transition_chunk(chunk.id, ChunkState.RUNNING)
                findings = build_local_findings(
                    workspace,
                    target,
                    review_window,
                    dimension,
                    job.id,
                )
                self._save_dimension_artifact(job, chunk.id, dimension, findings, "local", "review-rules-v1")
                self.jobs.transition_chunk(chunk.id, ChunkState.SUCCEEDED)
                completed += 1
                self.jobs.update_progress(
                    job.id,
                    current=completed,
                    total=len(task_input.dimensions),
                    step=f"{dimension.value} 本地审校完成",
                )
                continue
            if gateway is None:
                raise JobExecutionError("provider_unavailable", "审校模型配置当前不可用")
            if chunk.state != ChunkState.RUNNING:
                chunk = self.jobs.transition_chunk(chunk.id, ChunkState.RUNNING)
            attempt = self.jobs.start_attempt(
                job.id,
                chunk_id=chunk.id,
                provider=job.provider,
                provider_profile_id=job.provider_profile_id,
                model=job.model,
            )
            pending_external[dimension] = (chunk, attempt)

        if pending_external and gateway is not None:
            with ThreadPoolExecutor(
                max_workers=min(4, len(pending_external)),
                thread_name_prefix="mozhou-review",
            ) as pool:
                futures: dict[
                    Future[tuple[ReviewFindingDraftSet, ProviderCallMetrics | None]],
                    ReviewDimension,
                ] = {
                    pool.submit(
                        self._call_dimension,
                        gateway,
                        rebuilt_context,
                        dimension,
                    ): dimension
                    for dimension in pending_external
                }
                for future in as_completed(futures):
                    dimension = futures[future]
                    chunk, attempt = pending_external[dimension]
                    try:
                        proposal, metrics = future.result()
                        findings = self._materialize_external_findings(
                            proposal,
                            workspace,
                            target,
                            dimension,
                            job.id,
                        )
                        self._save_dimension_artifact(
                            job,
                            chunk.id,
                            dimension,
                            findings,
                            job.provider,
                            job.model,
                        )
                        self.jobs.finish_attempt(
                            attempt.id,
                            AttemptState.SUCCEEDED,
                            input_tokens=metrics.usage.input_tokens if metrics else None,
                            output_tokens=metrics.usage.output_tokens if metrics else None,
                            duration_ms=metrics.duration_ms if metrics else None,
                            estimated_cost_microusd=(
                                metrics.estimated_cost_microusd if metrics else None
                            ),
                        )
                        self.jobs.transition_chunk(chunk.id, ChunkState.SUCCEEDED)
                    except AiProviderError as error:
                        self.jobs.finish_attempt(
                            attempt.id,
                            AttemptState.FAILED,
                            duration_ms=error.duration_ms,
                            error_code=error.category.value,
                            error_message=error.safe_message,
                        )
                        self.jobs.transition_chunk(
                            chunk.id,
                            ChunkState.FAILED,
                            error_code=error.category.value,
                            error_message=error.safe_message,
                        )
                        failed += 1
                    except Exception:  # noqa: BLE001 - dimension boundary stores safe failure
                        self.jobs.finish_attempt(
                            attempt.id,
                            AttemptState.FAILED,
                            error_code="invalid_review_result",
                            error_message="该维度未返回可验证的审校结果",
                        )
                        self.jobs.transition_chunk(
                            chunk.id,
                            ChunkState.FAILED,
                            error_code="invalid_review_result",
                            error_message="该维度未返回可验证的审校结果",
                        )
                        failed += 1
                    completed += 1
                    self.jobs.update_progress(
                        job.id,
                        current=completed,
                        total=len(task_input.dimensions),
                        step=f"已完成 {completed}/{len(task_input.dimensions)} 个审校维度",
                    )
        if failed == len(task_input.dimensions):
            raise JobExecutionError("all_review_dimensions_failed", "全部审校维度失败，可安全重试")

    def get_result(self, job_id: str) -> ReviewJobResult:
        job = self.jobs.get_job(job_id)
        if job.kind != JobKind.REVIEW or job.workflow != REVIEW_WORKFLOW:
            raise ValueError("review_result_unavailable")
        task_input = ReviewJobInput.model_validate(self.jobs.load_input(job_id))
        chunks = self.jobs.list_chunks(job_id)
        chunks_by_dimension = {
            ReviewDimension(self.jobs.load_chunk_input(chunk.id)["dimension"]): chunk
            for chunk in chunks
        }
        outcomes: list[ReviewDimensionOutcome] = []
        for dimension in task_input.dimensions:
            chunk = chunks_by_dimension.get(dimension)
            artifact = self.jobs.find_artifact(job_id, f"review:{dimension.value}")
            if artifact is not None:
                finding_count = len(
                    ReviewDimensionArtifact.model_validate_json(artifact.payload).findings
                )
                outcomes.append(
                    ReviewDimensionOutcome(
                        dimension=dimension,
                        state=ReviewDimensionState.SUCCEEDED,
                        finding_count=finding_count,
                    )
                )
            else:
                outcomes.append(
                    ReviewDimensionOutcome(
                        dimension=dimension,
                        state=ReviewDimensionState.FAILED,
                        finding_count=0,
                        error_code=chunk.error_code if chunk is not None else "pending",
                        error_message=(
                            chunk.error_message if chunk is not None else "审校维度尚未完成"
                        ),
                    )
                )
        return ReviewJobResult(
            job_id=job.id,
            project_id=job.project_id,
            chapter_id=task_input.chapter_id,
            chapter_revision=task_input.chapter_revision,
            window_size=task_input.window_size,
            outcomes=outcomes,
            findings=self.reviews.list_findings_for_job(job.id),
        )

    def _snapshot(
        self,
        chapter_id: str,
        expected_revision: int,
        window_size: int,
        dimensions: list[ReviewDimension],
    ) -> tuple[Workspace, Chapter, list[Chapter], ContextPacket]:
        workspace = self.repository.get_workspace_for_chapter(chapter_id)
        self.repository.require_creative_safety(workspace.project.id)
        try:
            target = next(chapter for chapter in workspace.chapters if chapter.id == chapter_id)
        except StopIteration as error:
            raise NotFoundError(chapter_id) from error
        if target.revision != expected_revision:
            raise StaleRevisionError(str(target.revision))
        eligible = [
            chapter
            for chapter in workspace.chapters
            if chapter.chapter_number <= target.chapter_number
        ]
        review_window = eligible[-window_size:]
        packet = self.creative_context.compile(
            workspace,
            CreativeContextCompileRequest(
                purpose=CreativeContextPurpose.CANDIDATE_REVIEW,
                subject=CreativeContextSubject(
                    kind=CreativeContextSubjectKind.CHAPTER,
                    id=target.id,
                    revision=target.revision,
                ),
                token_budget=24_000,
                window_size=window_size,
                review_dimensions=dimensions,
            ),
        )
        return workspace, target, review_window, packet

    def _preview_profile(
        self,
        needs_external: bool,
    ) -> tuple[ModelProfile | None, str, str, str]:
        if not needs_external:
            return None, "本地规则", "local", "review-rules-v1"
        profile = (
            self.profiles.get_task_profile(AiTaskType.REVIEW)
            if self.profiles is not None
            else None
        )
        if profile is not None:
            gateway = self.manager.gateway_for(profile.id)
            status = gateway.status()
            if not status.configured:
                raise AiNotConfiguredError
            return profile, profile.name, profile.provider.value, profile.model
        status = self.manager.status()
        if not status.configured:
            raise AiNotConfiguredError
        active_profile: ModelProfile | None = None
        if self.profiles is not None and status.profile_id is not None:
            try:
                active_profile = self.profiles.get_profile(status.profile_id)
            except ModelProfileNotFoundError:
                active_profile = None
        return (
            active_profile,
            status.profile_name or "当前会话线路",
            status.provider.value,
            status.model,
        )

    def _gateway_for_job(self, job: Job) -> AiGateway:
        gateway = self.manager.gateway_for(job.provider_profile_id)
        status = gateway.status()
        if (
            not status.configured
            or status.provider.value != job.provider
            or status.model != job.model
            or status.profile_id != job.provider_profile_id
        ):
            raise JobExecutionError(
                "provider_unavailable",
                "任务使用的审校模型配置当前不可用，请恢复配置后重试",
            )
        return gateway

    def _put_context_artifact(
        self,
        job_id: str,
        packet: ContextPacket,
        task_input: ReviewJobInput,
    ) -> None:
        self.jobs.put_artifact(
            job_id,
            kind="review_context",
            artifact_key="review_context",
            payload=packet.model_dump_json(),
            content_type="application/json",
            provider="local",
            model=REVIEW_PROMPT_VERSION,
            metadata={
                "chapter_id": task_input.chapter_id,
                "chapter_revision": task_input.chapter_revision,
                "creative_safety": (
                    task_input.creative_safety.model_dump(mode="json")
                    if task_input.creative_safety is not None
                    else None
                ),
                "window_size": task_input.window_size,
                "context_sha256": task_input.context_sha256,
                "context_packet_id": task_input.context_packet_id,
                "context_dependency_fingerprint_sha256": (
                    task_input.context_dependency_fingerprint_sha256
                ),
            },
        )

    def _load_frozen_context_packet(
        self,
        job_id: str,
        task_input: ReviewJobInput,
    ) -> ContextPacket:
        try:
            packet = self.contexts.get_packet(task_input.context_packet_id)
        except ContextPacketNotFoundError:
            artifact = self.jobs.find_artifact(job_id, "review_context")
            if artifact is None:
                raise JobExecutionError(
                    "review_context_missing",
                    "任务冻结的审校上下文不存在，无法安全重放",
                ) from None
            try:
                packet = ContextPacket.model_validate_json(artifact.payload)
            except ValueError as error:
                raise JobExecutionError(
                    "review_context_invalid",
                    "任务冻结的审校上下文无法解析，未调用模型",
                ) from error
        if packet.id != task_input.context_packet_id:
            raise JobExecutionError(
                "review_context_invalid",
                "任务冻结的审校上下文标识不匹配，未调用模型",
            )
        return packet

    def _ensure_chunks(self, job_id: str, task_input: ReviewJobInput) -> list[JobChunk]:
        chunks: list[JobChunk] = []
        for ordinal, dimension in enumerate(task_input.dimensions):
            chunk, _created = self.jobs.ensure_chunk(
                job_id,
                kind=JobKind.REVIEW,
                ordinal=ordinal,
                idempotency_key=f"review:{dimension.value}",
                input_payload={
                    "dimension": dimension.value,
                    "chapter_id": task_input.chapter_id,
                    "chapter_revision": task_input.chapter_revision,
                    "context_sha256": task_input.context_sha256,
                },
            )
            chunks.append(chunk)
        return chunks

    @staticmethod
    def _call_dimension(
        gateway: AiGateway,
        context_text: str,
        dimension: ReviewDimension,
    ) -> tuple[ReviewFindingDraftSet, ProviderCallMetrics | None]:
        proposal = gateway.review_chapter(context_text, dimension)
        return proposal, consume_ai_call_metrics(gateway)

    @staticmethod
    def _materialize_external_findings(
        proposal: ReviewFindingDraftSet,
        workspace: Workspace,
        target: Chapter,
        dimension: ReviewDimension,
        job_id: str,
    ) -> list[ReviewFinding]:
        findings: list[ReviewFinding] = []
        for draft in proposal.findings:
            start = target.content.find(draft.evidence_text)
            if start < 0:
                continue
            evidence = ReviewEvidence(
                kind=ReviewEvidenceKind.BODY,
                chapter_id=target.id,
                start_char=start,
                end_char=start + len(draft.evidence_text),
                excerpt=draft.evidence_text,
                label=f"第 {target.chapter_number} 章正文",
            )
            replacement = draft.suggested_replacement
            if replacement == draft.evidence_text:
                replacement = None
            findings.append(
                make_finding(
                    job_id=job_id,
                    project_id=workspace.project.id,
                    chapter_id=target.id,
                    chapter_revision=target.revision,
                    dimension=dimension,
                    severity=draft.severity,
                    code=draft.code,
                    title=draft.title,
                    evidence=[evidence],
                    explanation=draft.explanation,
                    suggestion=draft.suggestion,
                    suggested_replacement=replacement,
                    confidence=draft.confidence,
                )
            )
        unique: dict[str, ReviewFinding] = {}
        for finding in findings:
            unique.setdefault(finding.dedupe_key, finding)
        return list(unique.values())

    def _save_dimension_artifact(
        self,
        job: Job,
        chunk_id: str,
        dimension: ReviewDimension,
        findings: list[ReviewFinding],
        provider: str,
        model: str,
    ) -> None:
        artifact = ReviewDimensionArtifact(dimension=dimension, findings=findings)
        self.jobs.put_artifact(
            job.id,
            chunk_id=chunk_id,
            kind="review_findings",
            artifact_key=f"review:{dimension.value}",
            payload=artifact.model_dump_json(),
            content_type="application/json",
            provider=provider,
            provider_profile_id=(
                job.provider_profile_id if provider != "local" else None
            ),
            model=model,
            metadata={
                "dimension": dimension.value,
                "finding_count": len(findings),
                "prompt_version": REVIEW_PROMPT_VERSION,
            },
        )
        self.reviews.save_findings(findings)
