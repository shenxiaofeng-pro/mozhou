import json
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, Field

from app.ai import (
    AiGateway,
    AiGatewayManager,
    AiNotConfiguredError,
    AiProviderError,
    build_chapter_context,
)
from app.jobs.models import AttemptState, ChunkState, Job, JobKind
from app.jobs.repository import JobRepository
from app.jobs.runtime import JobExecutionContext, JobExecutionError
from app.models import (
    AiChapterBriefProposal,
    AiChapterBriefRequest,
    AiDraftRequest,
    Chapter,
    ChapterStatus,
    GenerationRun,
    Workspace,
)
from app.repository import (
    InvalidChapterStateError,
    NotFoundError,
    ProjectRepository,
    StaleRevisionError,
)

CHAPTER_JOB_PROMPT_VERSION = "chapter-writing-v1"


class ChapterJobInput(BaseModel):
    chapter_id: str
    expected_revision: int = Field(ge=0)
    author_intent: str = Field(default="", max_length=1000)
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_version: str


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ChapterJobService:
    def __init__(
        self,
        repository: ProjectRepository,
        jobs: JobRepository,
        manager: AiGatewayManager,
    ) -> None:
        self.repository = repository
        self.jobs = jobs
        self.manager = manager

    def submit_brief(self, chapter_id: str, request: AiChapterBriefRequest) -> Job:
        return self._submit(JobKind.CHAPTER_BRIEF, chapter_id, request)

    def submit_draft(self, chapter_id: str, request: AiDraftRequest) -> Job:
        return self._submit(JobKind.CHAPTER_DRAFT, chapter_id, request)

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
        status = self.manager.status()
        if not status.configured:
            raise AiNotConfiguredError
        workspace, chapter = self._load_chapter(
            chapter_id,
            request.expected_revision,
            require_brief=kind == JobKind.CHAPTER_DRAFT,
        )
        context_sha256 = sha256(
            build_chapter_context(workspace, chapter, request.author_intent).encode("utf-8")
        ).hexdigest()
        input_payload = ChapterJobInput(
            chapter_id=chapter_id,
            expected_revision=request.expected_revision,
            author_intent=request.author_intent,
            context_sha256=context_sha256,
            prompt_version=CHAPTER_JOB_PROMPT_VERSION,
        ).model_dump(mode="json")
        idempotency_key = sha256(_canonical_json({
            **input_payload,
            "provider": status.provider.value,
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
            model=status.model,
            progress_total=1,
            estimated_calls=1,
        )
        artifact_key = "brief" if kind == JobKind.CHAPTER_BRIEF else "draft"
        self.jobs.ensure_chunk(
            job.id,
            kind=kind,
            ordinal=0,
            idempotency_key=artifact_key,
            input_payload={
                "chapter_id": chapter.id,
                "expected_revision": request.expected_revision,
                "context_sha256": context_sha256,
            },
        )
        return self.jobs.get_job(job.id)

    def _handle(
        self,
        context: JobExecutionContext,
        job: Job,
        expected_kind: JobKind,
    ) -> None:
        if job.kind != expected_kind:
            raise JobExecutionError("invalid_job_kind", "章节任务类型无效")
        task_input = ChapterJobInput.model_validate(self.jobs.load_input(job.id))
        status = self.manager.status()
        if (
            not status.configured
            or status.provider.value != job.provider
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
        actual_context = build_chapter_context(
            workspace,
            chapter,
            task_input.author_intent,
        )
        if sha256(actual_context.encode("utf-8")).hexdigest() != task_input.context_sha256:
            raise JobExecutionError(
                "context_changed",
                "作品资料已变化，请重新提交以使用最新上下文",
            )

        artifact_key = "brief" if expected_kind == JobKind.CHAPTER_BRIEF else "draft"
        chunks = self.jobs.list_chunks(job.id)
        if len(chunks) != 1:
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
            model=job.model,
        )
        gateway = self.manager.gateway()
        try:
            payload, metadata = self._call_gateway(
                gateway,
                expected_kind,
                workspace,
                chapter,
                task_input,
                job,
            )
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
            model=job.model,
        )
        self.jobs.finish_attempt(attempt.id, AttemptState.SUCCEEDED)
        self.jobs.transition_chunk(chunk.id, ChunkState.SUCCEEDED)
        self.jobs.update_progress(job.id, current=1, total=1, step="章节候选已生成")
        if expected_kind == JobKind.CHAPTER_DRAFT:
            self._materialize_draft(job, task_input, payload)

    def _call_gateway(
        self,
        gateway: AiGateway,
        kind: JobKind,
        workspace: Workspace,
        chapter: Chapter,
        task_input: ChapterJobInput,
        job: Job,
    ) -> tuple[str, dict[str, object]]:
        metadata: dict[str, object] = {
            "chapter_id": chapter.id,
            "expected_revision": task_input.expected_revision,
            "context_sha256": task_input.context_sha256,
            "prompt_version": task_input.prompt_version,
        }
        if kind == JobKind.CHAPTER_BRIEF:
            proposal = gateway.propose_brief(
                workspace,
                chapter,
                task_input.author_intent,
            )
            if not isinstance(proposal, AiChapterBriefProposal):
                raise AiProviderError("AI 未返回可用章纲")
            return proposal.model_dump_json(), metadata
        candidate = gateway.draft_chapter(
            workspace,
            chapter,
            task_input.author_intent,
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
        if require_brief and not all(
            getattr(chapter, field).strip()
            for field in ("opening_hook", "state_change", "ending_cliffhanger")
        ):
            raise InvalidChapterStateError("incomplete_brief")
        return workspace, chapter
