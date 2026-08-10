import json
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, Field

from app.ai import (
    AiGateway,
    AiGatewayManager,
    AiNotConfiguredError,
    AiProviderError,
    CompiledContextGateway,
    StreamingCompiledContextGateway,
    StreamingDraftGateway,
    consume_ai_call_metrics,
)
from app.context import (
    ContextCompiler,
    ContextPacket,
    ContextPacketNotFoundError,
    ContextRepository,
    ContextTaskType,
    InvalidContextPacketError,
)
from app.jobs.models import AttemptState, ChunkState, Job, JobKind
from app.jobs.repository import JobRepository
from app.jobs.runtime import JobCancellationRequested, JobExecutionContext, JobExecutionError
from app.models import (
    AiChapterBriefProposal,
    AiChapterBriefRequest,
    AiDraftRequest,
    AiStatus,
    Chapter,
    ChapterStatus,
    GenerationRun,
    OriginalityStatus,
    Workspace,
)
from app.providers import (
    AiErrorCategory,
    AiOutboundPreview,
    AiTaskType,
    ModelProfile,
    ModelProfileNotFoundError,
    ModelProfileRepository,
    ProviderCallError,
    ProviderKind,
)
from app.repository import (
    InvalidChapterStateError,
    NotFoundError,
    OriginalityGateBlockedError,
    ProjectRepository,
    StaleRevisionError,
)

CHAPTER_JOB_PROMPT_VERSION = "chapter-writing-v2"


def _estimated_cost(
    input_tokens: int,
    output_tokens: int,
    input_rate: int | None,
    output_rate: int | None,
) -> int | None:
    if input_rate is None or output_rate is None:
        return None
    return (
        input_tokens * input_rate
        + output_tokens * output_rate
        + 999_999
    ) // 1_000_000


def _chapter_data_types(workspace: Workspace, chapter: Chapter) -> list[str]:
    data_types = ["项目设定", "本章章纲", "作者创作意图"]
    if any(
        item.chapter_number < chapter.chapter_number and item.content.strip()
        for item in workspace.chapters
    ):
        data_types.append("最近章节正文摘录")
    if workspace.story_facts:
        data_types.append("正式事实")
    if workspace.story_entities:
        data_types.append("人物与资源状态")
    if any(thread.status.value == "open" for thread in workspace.story_threads):
        data_types.append("开放伏笔")
    if workspace.timeline_events or workspace.future_knowledge:
        data_types.append("时间线与未来知识")
    if any(card.confirmed for card in workspace.source_cards):
        data_types.append("已确认现实资料")
    if any(
        application.originality_status == OriginalityStatus.PASSED
        for application in workspace.reference_pattern_applications
    ):
        data_types.append("已应用拆书蓝图")
    return data_types


class ChapterJobInput(BaseModel):
    chapter_id: str
    expected_revision: int = Field(ge=0)
    author_intent: str = Field(default="", max_length=1000)
    context_packet_id: str = Field(min_length=36, max_length=36)
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_compiler_version: str = Field(min_length=1, max_length=80)
    prompt_version: str


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ChapterJobService:
    def __init__(
        self,
        repository: ProjectRepository,
        jobs: JobRepository,
        manager: AiGatewayManager,
        profiles: ModelProfileRepository | None = None,
        contexts: ContextRepository | None = None,
        compiler: ContextCompiler | None = None,
    ) -> None:
        self.repository = repository
        self.jobs = jobs
        self.manager = manager
        self.profiles = profiles
        self.contexts = contexts or ContextRepository(repository.database)
        self.compiler = compiler or ContextCompiler()

    def submit_brief(self, chapter_id: str, request: AiChapterBriefRequest) -> Job:
        return self._submit(JobKind.CHAPTER_BRIEF, chapter_id, request)

    def submit_draft(self, chapter_id: str, request: AiDraftRequest) -> Job:
        return self._submit(JobKind.CHAPTER_DRAFT, chapter_id, request)

    def preview_brief(
        self,
        chapter_id: str,
        request: AiChapterBriefRequest,
    ) -> AiOutboundPreview:
        return self._preview(JobKind.CHAPTER_BRIEF, chapter_id, request)

    def preview_draft(
        self,
        chapter_id: str,
        request: AiDraftRequest,
    ) -> AiOutboundPreview:
        return self._preview(JobKind.CHAPTER_DRAFT, chapter_id, request)

    def handle_brief(self, context: JobExecutionContext, job: Job) -> None:
        self._handle(context, job, JobKind.CHAPTER_BRIEF)

    def handle_draft(self, context: JobExecutionContext, job: Job) -> None:
        self._handle(context, job, JobKind.CHAPTER_DRAFT)

    def get_brief_result(self, job_id: str) -> AiChapterBriefProposal:
        job = self.jobs.get_job(job_id)
        if job.kind != JobKind.CHAPTER_BRIEF:
            raise ValueError("任务类型不是章纲")
        artifact = self.jobs.find_artifact(job_id, "brief")
        if artifact is None:
            raise ValueError("章纲任务尚无可用结果")
        return AiChapterBriefProposal.model_validate_json(artifact.payload)

    def get_draft_result(self, job_id: str) -> GenerationRun:
        job = self.jobs.get_job(job_id)
        if job.kind != JobKind.CHAPTER_DRAFT:
            raise ValueError("任务类型不是正文")
        artifact = self.jobs.find_artifact(job_id, "draft")
        if artifact is None:
            raise ValueError("正文任务尚无可用结果")
        run_id = artifact.metadata.get("generation_run_id")
        if not isinstance(run_id, str):
            raise TypeError("正文候选缺少采用标识")
        return self.repository.get_generation_run(run_id)

    def _submit(
        self,
        kind: JobKind,
        chapter_id: str,
        request: AiChapterBriefRequest,
    ) -> Job:
        _gateway, status = self._selected_gateway(kind)
        if not status.configured:
            raise AiNotConfiguredError
        workspace, chapter = self._load_chapter(
            chapter_id,
            request.expected_revision,
            require_brief=kind == JobKind.CHAPTER_DRAFT,
        )
        packet = self._resolve_context_packet(kind, workspace, chapter, request)
        input_payload = ChapterJobInput(
            chapter_id=chapter_id,
            expected_revision=request.expected_revision,
            author_intent=request.author_intent,
            context_packet_id=packet.id,
            context_sha256=packet.packet_sha256,
            context_compiler_version=packet.compiler_version,
            prompt_version=CHAPTER_JOB_PROMPT_VERSION,
        ).model_dump(mode="json")
        idempotency_key = sha256(_canonical_json({
            **input_payload,
            "provider": status.provider.value,
            "provider_profile_id": status.profile_id,
            "model": status.model,
            "kind": kind.value,
        }).encode("utf-8")).hexdigest()
        job, _created = self.jobs.create_job(
            project_id=chapter.project_id,
            chapter_id=chapter.id,
            kind=kind,
            idempotency_key=idempotency_key,
            input_payload=input_payload,
            provider=status.provider.value,
            provider_profile_id=status.profile_id,
            model=status.model,
            progress_total=1,
            estimated_calls=1,
        )
        self._ensure_context_artifact(job.id, packet)
        artifact_key = "brief" if kind == JobKind.CHAPTER_BRIEF else "draft"
        self.jobs.ensure_chunk(
            job.id,
            kind=kind,
            ordinal=0,
            idempotency_key=artifact_key,
            input_payload={
                "chapter_id": chapter.id,
                "expected_revision": request.expected_revision,
                "context_packet_id": packet.id,
                "context_sha256": packet.packet_sha256,
            },
        )
        return self.jobs.get_job(job.id)

    def _preview(
        self,
        kind: JobKind,
        chapter_id: str,
        request: AiChapterBriefRequest,
    ) -> AiOutboundPreview:
        workspace, chapter = self._load_chapter(
            chapter_id,
            request.expected_revision,
            require_brief=kind == JobKind.CHAPTER_DRAFT,
        )
        packet = self._compile_context_packet(kind, workspace, chapter, request)
        packet = self.contexts.put_packet(packet)
        profile = self._task_profile(kind)
        profile_id: str | None
        if profile is not None:
            profile_id = profile.id
            profile_name = profile.name
            provider = profile.provider
            model = profile.model
            input_rate = profile.input_cost_microusd_per_million
            output_rate = profile.output_cost_microusd_per_million
        else:
            status = self.manager.status()
            if not status.configured:
                raise AiNotConfiguredError
            profile_id = status.profile_id
            profile_name = status.profile_name or "当前会话线路"
            provider = ProviderKind(status.provider.value)
            model = status.model
            active_profile: ModelProfile | None = None
            if self.profiles is not None and profile_id is not None:
                try:
                    active_profile = self.profiles.get_profile(profile_id)
                except ModelProfileNotFoundError:
                    active_profile = None
            input_rate = (
                active_profile.input_cost_microusd_per_million
                if active_profile is not None
                else None
            )
            output_rate = (
                active_profile.output_cost_microusd_per_million
                if active_profile is not None
                else None
            )
        input_tokens = packet.used_tokens
        output_tokens = (
            1_200
            if kind == JobKind.CHAPTER_BRIEF
            else min(12_000, max(1_000, (workspace.project.chapter_target_words * 12 + 9) // 10))
        )
        return AiOutboundPreview(
            task_type=AiTaskType(kind.value),
            profile_id=profile_id,
            profile_name=profile_name,
            provider=provider,
            model=model,
            data_types=_chapter_data_types(workspace, chapter),
            content_scope=(
                f"第 {chapter.chapter_number} 章 · 编译器 {packet.compiler_version} · "
                f"入选 {sum(1 for item in packet.items if item.included)} 项 / "
                f"排除 {sum(1 for item in packet.items if not item.included)} 项"
            ),
            character_count=len(packet.rendered_context),
            estimated_input_tokens=input_tokens,
            estimated_output_tokens=output_tokens,
            estimated_cost_microusd=_estimated_cost(
                input_tokens,
                output_tokens,
                input_rate,
                output_rate,
            ),
            context_packet=packet,
        )

    def _compile_context_packet(
        self,
        kind: JobKind,
        workspace: Workspace,
        chapter: Chapter,
        request: AiChapterBriefRequest,
    ) -> ContextPacket:
        return self.compiler.compile(
            workspace,
            chapter,
            author_intent=request.author_intent,
            task_type=ContextTaskType(kind.value),
            token_budget=request.context_token_budget,
            directives=self.contexts.list_directives(chapter.id),
        )

    def _resolve_context_packet(
        self,
        kind: JobKind,
        workspace: Workspace,
        chapter: Chapter,
        request: AiChapterBriefRequest,
    ) -> ContextPacket:
        compiled = self._compile_context_packet(kind, workspace, chapter, request)
        if request.context_packet_id is None:
            return self.contexts.put_packet(compiled)
        try:
            previewed = self.contexts.get_packet(request.context_packet_id)
        except ContextPacketNotFoundError as error:
            raise InvalidContextPacketError("context_packet_not_found") from error
        if (
            previewed.project_id != workspace.project.id
            or previewed.chapter_id != chapter.id
            or previewed.chapter_revision != chapter.revision
            or previewed.task_type != ContextTaskType(kind.value)
            or previewed.id != compiled.id
            or previewed.packet_sha256 != compiled.packet_sha256
        ):
            raise InvalidContextPacketError("context_packet_changed")
        return previewed

    def _task_profile(self, kind: JobKind) -> ModelProfile | None:
        if self.profiles is None:
            return None
        return self.profiles.get_task_profile(AiTaskType(kind.value))

    def _selected_gateway(self, kind: JobKind) -> tuple[AiGateway, AiStatus]:
        profile = self._task_profile(kind)
        gateway = (
            self.manager.gateway_for(profile.id)
            if profile is not None
            else self.manager.gateway()
        )
        status = gateway.status()
        if (
            not status.configured
            or (profile is not None and (
                status.profile_id != profile.id or status.model != profile.model
            ))
        ):
            raise AiNotConfiguredError
        return gateway, status

    def _handle(
        self,
        context: JobExecutionContext,
        job: Job,
        expected_kind: JobKind,
    ) -> None:
        if job.kind != expected_kind:
            raise JobExecutionError("invalid_job_kind", "章节任务类型无效")
        task_input = ChapterJobInput.model_validate(self.jobs.load_input(job.id))
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
                "任务使用的模型配置当前不可用，请恢复配置后重试",
            )
        try:
            workspace, chapter = self._load_chapter(
                task_input.chapter_id,
                task_input.expected_revision,
                require_brief=expected_kind == JobKind.CHAPTER_DRAFT,
            )
        except StaleRevisionError as error:
            raise JobExecutionError(
                "stale_revision",
                "章节已有新版本，请基于当前版本重新提交 AI 任务",
            ) from error
        except InvalidChapterStateError as error:
            raise JobExecutionError(
                "invalid_chapter_state",
                "当前章节状态或章纲不允许执行该 AI 任务",
            ) from error
        packet = self._load_frozen_context_packet(job.id, task_input)
        if (
            packet.project_id != workspace.project.id
            or packet.chapter_id != chapter.id
            or packet.chapter_revision != task_input.expected_revision
            or packet.task_type != ContextTaskType(expected_kind.value)
            or packet.packet_sha256 != task_input.context_sha256
            or packet.compiler_version != task_input.context_compiler_version
        ):
            raise JobExecutionError(
                "context_packet_mismatch",
                "任务上下文来源校验失败，未调用模型",
            )

        artifact_key = "brief" if expected_kind == JobKind.CHAPTER_BRIEF else "draft"
        self._ensure_context_artifact(job.id, packet)
        planned_chunk, _created = self.jobs.ensure_chunk(
            job.id,
            kind=expected_kind,
            ordinal=0,
            idempotency_key=artifact_key,
            input_payload={
                "chapter_id": chapter.id,
                "expected_revision": task_input.expected_revision,
                "context_packet_id": packet.id,
                "context_sha256": packet.packet_sha256,
            },
        )
        chunks = self.jobs.list_chunks(job.id)
        if len(chunks) != 1 or chunks[0].id != planned_chunk.id:
            raise JobExecutionError("invalid_plan", "章节任务计划不完整")
        chunk = chunks[0]
        artifact = self.jobs.find_artifact(job.id, artifact_key)
        if artifact is not None:
            if chunk.state != ChunkState.SUCCEEDED:
                if chunk.state != ChunkState.RUNNING:
                    chunk = self.jobs.transition_chunk(chunk.id, ChunkState.RUNNING)
                self.jobs.transition_chunk(chunk.id, ChunkState.SUCCEEDED)
            self.jobs.update_progress(
                job.id,
                current=1,
                total=1,
                step="复用已完成的章节候选",
            )
            if expected_kind == JobKind.CHAPTER_DRAFT:
                self._materialize_draft(job, task_input, artifact.payload)
            return
        if chunk.state == ChunkState.SUCCEEDED:
            raise JobExecutionError("missing_artifact", "已完成章节任务缺少产物")

        context.checkpoint()
        if chunk.state != ChunkState.RUNNING:
            chunk = self.jobs.transition_chunk(chunk.id, ChunkState.RUNNING)
        step = "AI 正在设计本章章纲" if expected_kind == JobKind.CHAPTER_BRIEF else "AI 正在写完整章节候选"
        self.jobs.update_progress(job.id, current=0, total=1, step=step)
        attempt = self.jobs.start_attempt(
            job.id,
            chunk_id=chunk.id,
            provider=job.provider,
            provider_profile_id=job.provider_profile_id,
            model=job.model,
        )
        try:
            payload, metadata = self._call_gateway(
                gateway,
                context,
                expected_kind,
                workspace,
                chapter,
                task_input,
                packet,
                job,
            )
        except AiProviderError as error:
            metrics = consume_ai_call_metrics(gateway)
            self.jobs.finish_attempt(
                attempt.id,
                AttemptState.FAILED,
                duration_ms=error.duration_ms or (metrics.duration_ms if metrics else None),
                input_tokens=metrics.usage.input_tokens if metrics else None,
                output_tokens=metrics.usage.output_tokens if metrics else None,
                estimated_cost_microusd=(
                    metrics.estimated_cost_microusd if metrics else None
                ),
                error_code=error.category.value,
                error_message=error.safe_message,
            )
            self.jobs.transition_chunk(
                chunk.id,
                ChunkState.FAILED,
                error_code=error.category.value,
                error_message=error.safe_message,
            )
            raise JobExecutionError(
                error.category.value,
                error.safe_message,
            ) from error
        except Exception as error:
            self.jobs.finish_attempt(
                attempt.id,
                AttemptState.FAILED,
                error_code="provider_error",
                error_message="模型服务未完成当前章节任务",
            )
            self.jobs.transition_chunk(
                chunk.id,
                ChunkState.FAILED,
                error_code="provider_error",
                error_message="模型服务未完成当前章节任务",
            )
            raise JobExecutionError(
                "provider_error",
                "模型服务未完成当前章节任务，可安全重试",
            ) from error
        self.jobs.put_artifact(
            job.id,
            chunk_id=chunk.id,
            kind=expected_kind.value,
            artifact_key=artifact_key,
            payload=payload,
            content_type=(
                "application/json"
                if expected_kind == JobKind.CHAPTER_BRIEF
                else "text/plain"
            ),
            metadata=metadata,
            provider=job.provider,
            provider_profile_id=job.provider_profile_id,
            model=job.model,
        )
        metrics = consume_ai_call_metrics(gateway)
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
        self.jobs.update_progress(job.id, current=1, total=1, step="章节候选已生成")
        if expected_kind == JobKind.CHAPTER_DRAFT:
            self._materialize_draft(job, task_input, payload)

    def _load_frozen_context_packet(
        self,
        job_id: str,
        task_input: ChapterJobInput,
    ) -> ContextPacket:
        try:
            return self.contexts.get_packet(task_input.context_packet_id)
        except ContextPacketNotFoundError:
            artifact = self.jobs.find_artifact(job_id, "context_packet")
            if artifact is None:
                raise JobExecutionError(
                    "context_packet_missing",
                    "任务冻结的上下文包不存在，无法安全重放",
                ) from None
            if (
                artifact.kind != "context_packet"
                or artifact.content_type != "application/json"
                or sha256(artifact.payload.encode("utf-8")).hexdigest()
                != artifact.payload_sha256
            ):
                raise JobExecutionError(
                    "context_packet_artifact_invalid",
                    "任务冻结的上下文产物完整性校验失败，未调用模型",
                ) from None
            try:
                return ContextPacket.model_validate_json(artifact.payload)
            except ValueError as error:
                raise JobExecutionError(
                    "context_packet_artifact_invalid",
                    "任务冻结的上下文产物无法解析，未调用模型",
                ) from error

    def _ensure_context_artifact(self, job_id: str, packet: ContextPacket) -> None:
        self.jobs.put_artifact(
            job_id,
            kind="context_packet",
            artifact_key="context_packet",
            payload=packet.model_dump_json(),
            content_type="application/json",
            provider="local",
            model=packet.compiler_version,
            metadata={
                "context_packet_id": packet.id,
                "packet_sha256": packet.packet_sha256,
                "used_tokens": packet.used_tokens,
                "token_budget": packet.token_budget,
            },
        )

    def _call_gateway(
        self,
        gateway: AiGateway,
        context: JobExecutionContext,
        kind: JobKind,
        workspace: Workspace,
        chapter: Chapter,
        task_input: ChapterJobInput,
        packet: ContextPacket,
        job: Job,
    ) -> tuple[str, dict[str, object]]:
        metadata: dict[str, object] = {
            "chapter_id": chapter.id,
            "expected_revision": task_input.expected_revision,
            "context_packet_id": packet.id,
            "context_sha256": task_input.context_sha256,
            "context_compiler_version": packet.compiler_version,
            "prompt_version": task_input.prompt_version,
        }
        if kind == JobKind.CHAPTER_BRIEF:
            proposal = (
                gateway.propose_brief_from_context(packet.rendered_context)
                if isinstance(gateway, CompiledContextGateway)
                else gateway.propose_brief(
                    workspace,
                    chapter,
                    task_input.author_intent,
                )
            )
            if not isinstance(proposal, AiChapterBriefProposal):
                raise AiProviderError("AI 未返回可用章纲")
            return proposal.model_dump_json(), metadata
        if isinstance(gateway, (StreamingCompiledContextGateway, StreamingDraftGateway)):
            generated_characters = 0
            checkpoint_characters = 0

            def on_delta(delta: str) -> None:
                nonlocal generated_characters, checkpoint_characters
                generated_characters += len(delta)
                if generated_characters - checkpoint_characters < 256:
                    return
                checkpoint_characters = generated_characters
                try:
                    context.checkpoint()
                except JobCancellationRequested as error:
                    raise ProviderCallError(
                        AiErrorCategory.CANCELLED,
                        "模型生成已按请求停止，可从任务中心重试",
                        retryable=True,
                    ) from error
                self.jobs.update_progress(
                    job.id,
                    current=0,
                    total=1,
                    step=f"AI 已流式生成 {generated_characters:,} 字",
                )

            candidate = (
                gateway.draft_chapter_streaming_from_context(
                    packet.rendered_context,
                    on_delta,
                )
                if isinstance(gateway, StreamingCompiledContextGateway)
                else gateway.draft_chapter_streaming(
                    workspace,
                    chapter,
                    task_input.author_intent,
                    on_delta,
                )
            )
        else:
            candidate = (
                gateway.draft_chapter_from_context(packet.rendered_context)
                if isinstance(gateway, CompiledContextGateway)
                else gateway.draft_chapter(
                    workspace,
                    chapter,
                    task_input.author_intent,
                )
            )
        if not 300 <= len(candidate) <= 100_000:
            raise AiProviderError("AI 返回的正文长度不符合要求")
        metadata["generation_run_id"] = str(uuid5(
            NAMESPACE_URL,
            f"mozhou:{job.id}:generation-run",
        ))
        return candidate, metadata

    def _materialize_draft(
        self,
        job: Job,
        task_input: ChapterJobInput,
        candidate: str,
    ) -> GenerationRun:
        artifact = self.jobs.find_artifact(job.id, "draft")
        if artifact is None:
            raise JobExecutionError("missing_artifact", "正文候选产物不存在")
        run_id = artifact.metadata.get("generation_run_id")
        if not isinstance(run_id, str):
            raise JobExecutionError("invalid_artifact", "正文候选采用标识无效")
        return self.repository.materialize_generation_run(
            run_id,
            task_input.chapter_id,
            task_input.expected_revision,
            candidate,
            job.provider,
            job.model,
        )

    def _load_chapter(
        self,
        chapter_id: str,
        expected_revision: int,
        *,
        require_brief: bool,
    ) -> tuple[Workspace, Chapter]:
        workspace = self.repository.get_workspace_for_chapter(chapter_id)
        try:
            chapter = next(item for item in workspace.chapters if item.id == chapter_id)
        except StopIteration as error:
            raise NotFoundError(chapter_id) from error
        if chapter.revision != expected_revision:
            raise StaleRevisionError(str(chapter.revision))
        if chapter.status not in {ChapterStatus.PLANNED, ChapterStatus.DRAFTED}:
            raise InvalidChapterStateError(chapter.status.value)
        if any(
            application.originality_status != OriginalityStatus.PASSED
            for application in workspace.reference_pattern_applications
        ):
            raise OriginalityGateBlockedError("reference_blueprint_not_passed")
        if require_brief and not all(
            getattr(chapter, field).strip()
            for field in ("opening_hook", "state_change", "ending_cliffhanger")
        ):
            raise InvalidChapterStateError("incomplete_brief")
        return workspace, chapter
