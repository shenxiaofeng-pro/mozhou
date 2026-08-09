from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from re import fullmatch
from secrets import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.ai import (
    AiGatewayManager,
    AiNotConfiguredError,
    AiProviderError,
    AiWritingService,
    ReferenceAnalysisService,
)
from app.archive import (
    MAX_ARCHIVE_BYTES,
    InvalidProjectArchiveError,
    ProjectArchiveService,
    ProjectArchiveTooLargeError,
)
from app.config import default_database_path
from app.database import Database
from app.generation import GenerationService
from app.jobs import (
    Job,
    JobArtifactContent,
    JobDetail,
    JobNotFoundError,
    JobRepository,
    JobRuntime,
)
from app.models import (
    AiChapterBriefProposal,
    AiChapterBriefRequest,
    AiDraftRequest,
    AiStatus,
    ApplyFactChangeSetRequest,
    ApplyGenerationRequest,
    ApplyReferencePatternRequest,
    Chapter,
    ConfigureAiRequest,
    CreateChapterRequest,
    CreateFutureKnowledgeRequest,
    CreateProjectRequest,
    CreateRecoveryPointRequest,
    CreateSourceCardRequest,
    CreateStoryEntityRequest,
    CreateStoryThreadRequest,
    CreateTimelineEventRequest,
    FactChangeSet,
    FutureKnowledge,
    GenerationRun,
    ImportReferenceWorkRequest,
    Project,
    RecoveryPointSummary,
    ReferencePatternApplication,
    ReferencePatternCard,
    ReferenceSynthesisRequest,
    ReferenceWork,
    RejectFactChangeSetRequest,
    ReviewFutureKnowledgeRequest,
    SetSourceCardConfirmationRequest,
    SourceCard,
    StartGenerationRequest,
    StoryEntity,
    StoryThread,
    TimelineEvent,
    TransitionChapterRequest,
    TransitionStoryThreadRequest,
    UpdateChapterBriefRequest,
    UpdateChapterRequest,
    UpdateStoryEntityRequest,
    Workspace,
    WorkspaceSummary,
)
from app.repository import (
    InvalidChapterStateError,
    InvalidFactChangeSetStateError,
    InvalidFactSelectionError,
    InvalidFutureKnowledgeStateError,
    InvalidReferenceApplicationError,
    InvalidReferenceImportError,
    InvalidReferenceSelectionError,
    InvalidStoryThreadStateError,
    NotFoundError,
    ProjectRepository,
    StaleChapterSequenceError,
    StaleRevisionError,
)


def create_app(
    database_path: Path | None = None,
    ai_manager: AiGatewayManager | None = None,
    session_token: str | None = None,
) -> FastAPI:
    if session_token is not None and fullmatch(r"[0-9a-f]{64}", session_token) is None:
        raise ValueError("session token must be 64 lowercase hexadecimal characters")
    database = Database(database_path or default_database_path())

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        database.initialize()
        application.state.repository = ProjectRepository(database)
        application.state.ai_manager = ai_manager or AiGatewayManager()
        application.state.job_repository = JobRepository(database)
        application.state.job_runtime = JobRuntime(application.state.job_repository)
        application.state.job_runtime.start()
        try:
            yield
        finally:
            application.state.job_runtime.stop()

    application = FastAPI(
        title="墨舟本地 API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @application.exception_handler(RequestValidationError)
    async def sanitized_validation_error(
        _request: Request,
        _error: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": "请求内容格式无效"})

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:1420",
            "http://localhost:1420",
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "X-Mozhou-Session-Token"],
    )

    @application.middleware("http")
    async def require_session_token(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if (
            session_token is not None
            and request.method != "OPTIONS"
            and request.url.path.startswith("/api/")
        ):
            supplied_token = request.headers.get("x-mozhou-session-token", "")
            if not compare_digest(supplied_token, session_token):
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "本地会话无效，请重启墨舟"},
                )
        return await call_next(request)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/projects/{project_id}/jobs", response_model=list[Job])
    def list_jobs(
        project_id: UUID,
        jobs: Annotated[JobRepository, Depends(get_job_repository)],
    ) -> list[Job]:
        try:
            return jobs.list_jobs(str(project_id))
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="作品不存在") from error

    @application.get("/api/jobs/{job_id}", response_model=JobDetail)
    def get_job(
        job_id: UUID,
        jobs: Annotated[JobRepository, Depends(get_job_repository)],
    ) -> JobDetail:
        try:
            return jobs.get_job_detail(str(job_id))
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="任务不存在") from error

    @application.get(
        "/api/job-artifacts/{artifact_id}",
        response_model=JobArtifactContent,
    )
    def get_job_artifact(
        artifact_id: UUID,
        jobs: Annotated[JobRepository, Depends(get_job_repository)],
    ) -> JobArtifactContent:
        try:
            return jobs.get_artifact(str(artifact_id))
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="任务产物不存在") from error

    @application.post("/api/jobs/{job_id}/cancel", response_model=Job)
    def cancel_job(
        job_id: UUID,
        jobs: Annotated[JobRepository, Depends(get_job_repository)],
    ) -> Job:
        try:
            job = jobs.request_cancel(str(job_id))
            get_job_runtime_from_repository(application, jobs).wake()
            return job
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="任务不存在") from error

    @application.post("/api/jobs/{job_id}/retry", response_model=Job)
    def retry_job(
        job_id: UUID,
        jobs: Annotated[JobRepository, Depends(get_job_repository)],
    ) -> Job:
        try:
            job = jobs.retry_job(str(job_id))
            get_job_runtime_from_repository(application, jobs).wake()
            return job
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="任务不存在") from error

    @application.get("/api/ai/status", response_model=AiStatus)
    def get_ai_status(
        manager: Annotated[AiGatewayManager, Depends(get_ai_manager)],
    ) -> AiStatus:
        return manager.status()

    @application.post("/api/ai/configure", response_model=AiStatus)
    def configure_ai(
        body: ConfigureAiRequest,
        manager: Annotated[AiGatewayManager, Depends(get_ai_manager)],
    ) -> AiStatus:
        try:
            return manager.configure_openai(body)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="API Key 格式无效") from error

    @application.post(
        "/api/chapters/{chapter_id}/ai-brief-proposals",
        response_model=AiChapterBriefProposal,
    )
    def propose_ai_chapter_brief(
        chapter_id: UUID,
        body: AiChapterBriefRequest,
        service: Annotated[AiWritingService, Depends(get_ai_writing_service)],
    ) -> AiChapterBriefProposal:
        try:
            return service.propose_brief(str(chapter_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="章节已有新版本，请重新生成章纲") from error
        except InvalidChapterStateError as error:
            raise HTTPException(status_code=409, detail="当前章节状态不允许生成章纲") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置 AI 模型") from error
        except AiProviderError as error:
            raise HTTPException(status_code=502, detail="AI 暂时未能生成可用章纲") from error

    @application.post(
        "/api/chapters/{chapter_id}/ai-draft-runs",
        response_model=GenerationRun,
        status_code=status.HTTP_201_CREATED,
    )
    def generate_ai_chapter_draft(
        chapter_id: UUID,
        body: AiDraftRequest,
        service: Annotated[AiWritingService, Depends(get_ai_writing_service)],
    ) -> GenerationRun:
        try:
            return service.generate_draft(str(chapter_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="章节已有新版本，请重新生成正文") from error
        except InvalidChapterStateError as error:
            raise HTTPException(status_code=409, detail="请先保存完整章纲再生成正文") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置 AI 模型") from error
        except AiProviderError as error:
            raise HTTPException(status_code=502, detail="AI 暂时未能生成可用正文") from error

    @application.get("/api/projects", response_model=list[Project])
    def list_projects(
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> list[Project]:
        return repository.list_projects()

    @application.post("/api/projects", response_model=Workspace, status_code=status.HTTP_201_CREATED)
    def create_project(
        body: CreateProjectRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> Workspace:
        return repository.create_project(body)

    @application.get("/api/projects/{project_id}/export")
    def export_project(
        project_id: UUID,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> dict[str, object]:
        try:
            return ProjectArchiveService(repository.database).export_project(str(project_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="项目不存在") from error

    @application.post(
        "/api/project-imports",
        response_model=Workspace,
        status_code=status.HTTP_201_CREATED,
    )
    async def import_project(
        request: Request,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> Workspace:
        content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
        if content_type != "application/json":
            raise HTTPException(status_code=415, detail="请选择墨舟项目归档文件")
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_ARCHIVE_BYTES:
                    raise HTTPException(status_code=413, detail="项目归档不能超过 256 MiB")
            except ValueError as error:
                raise HTTPException(status_code=400, detail="项目归档无效或已损坏") from error
        raw_archive = bytearray()
        async for chunk in request.stream():
            raw_archive.extend(chunk)
            if len(raw_archive) > MAX_ARCHIVE_BYTES:
                raise HTTPException(status_code=413, detail="项目归档不能超过 256 MiB")
        try:
            project_id = ProjectArchiveService(repository.database).import_project(bytes(raw_archive))
            return repository.get_workspace(project_id)
        except ProjectArchiveTooLargeError as error:
            raise HTTPException(status_code=413, detail="项目归档不能超过 256 MiB") from error
        except InvalidProjectArchiveError as error:
            raise HTTPException(status_code=400, detail="项目归档无效或已损坏") from error

    @application.post(
        "/api/projects/{project_id}/recovery-points",
        response_model=RecoveryPointSummary,
        status_code=status.HTTP_201_CREATED,
    )
    def create_recovery_point(
        project_id: UUID,
        body: CreateRecoveryPointRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> RecoveryPointSummary:
        try:
            return ProjectArchiveService(repository.database).create_recovery_point(
                str(project_id), body.label
            )
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="项目不存在") from error

    @application.get(
        "/api/projects/{project_id}/recovery-points",
        response_model=list[RecoveryPointSummary],
    )
    def list_recovery_points(
        project_id: UUID,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> list[RecoveryPointSummary]:
        try:
            return ProjectArchiveService(repository.database).list_recovery_points(str(project_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="项目不存在") from error

    @application.post(
        "/api/recovery-points/{recovery_point_id}/restore",
        response_model=Workspace,
        status_code=status.HTTP_201_CREATED,
    )
    def restore_recovery_point(
        recovery_point_id: UUID,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> Workspace:
        try:
            project_id = ProjectArchiveService(repository.database).restore_recovery_point(
                str(recovery_point_id)
            )
            return repository.get_workspace(project_id)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="恢复点不存在") from error
        except (InvalidProjectArchiveError, ProjectArchiveTooLargeError) as error:
            raise HTTPException(status_code=409, detail="恢复点已损坏，未创建副本") from error

    @application.post(
        "/api/projects/{project_id}/reference-works",
        response_model=ReferenceWork,
        status_code=status.HTTP_201_CREATED,
    )
    def import_reference_work(
        project_id: UUID,
        body: ImportReferenceWorkRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> ReferenceWork:
        try:
            return repository.import_reference_work(str(project_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="项目不存在") from error
        except InvalidReferenceImportError as error:
            raise HTTPException(
                status_code=415,
                detail="当前只支持 UTF-8 TXT 或 Markdown 参考作品",
            ) from error

    @application.post(
        "/api/projects/{project_id}/reference-synthesis-proposals",
        response_model=ReferencePatternCard,
    )
    def synthesize_reference_patterns(
        project_id: UUID,
        body: ReferenceSynthesisRequest,
        service: Annotated[ReferenceAnalysisService, Depends(get_reference_analysis_service)],
    ) -> ReferencePatternCard:
        try:
            return service.synthesize(str(project_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="项目不存在") from error
        except InvalidReferenceSelectionError as error:
            raise HTTPException(
                status_code=400,
                detail="请从至少两本书选择区段并确认外部处理；单次最多分析 200 万字",
            ) from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置 AI 模型") from error
        except AiProviderError as error:
            raise HTTPException(status_code=502, detail="AI 暂时未能完成多书结构萃取") from error

    @application.post(
        "/api/projects/{project_id}/reference-pattern-cards/{card_id}/applications",
        response_model=ReferencePatternApplication,
        status_code=status.HTTP_201_CREATED,
    )
    def apply_reference_pattern(
        project_id: UUID,
        card_id: UUID,
        body: ApplyReferencePatternRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> ReferencePatternApplication:
        try:
            return repository.apply_reference_pattern(str(project_id), str(card_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="模式卡不存在于当前作品") from error
        except InvalidReferenceApplicationError as error:
            raise HTTPException(status_code=409, detail="这张模式卡已经应用到当前作品") from error

    @application.get("/api/projects/{project_id}", response_model=Workspace)
    def get_project(
        project_id: UUID,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> Workspace:
        try:
            return repository.get_workspace(str(project_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="项目不存在") from error

    @application.get(
        "/api/projects/{project_id}/summary",
        response_model=WorkspaceSummary,
    )
    def get_project_summary(
        project_id: UUID,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> WorkspaceSummary:
        try:
            return repository.get_workspace_summary(str(project_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="项目不存在") from error

    @application.post(
        "/api/projects/{project_id}/chapters",
        response_model=Chapter,
        status_code=status.HTTP_201_CREATED,
    )
    def create_chapter(
        project_id: UUID,
        body: CreateChapterRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> Chapter:
        try:
            return repository.create_chapter(str(project_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="项目不存在") from error
        except StaleChapterSequenceError as error:
            raise HTTPException(status_code=409, detail="章节目录已有更新，请重新载入") from error

    @application.post(
        "/api/projects/{project_id}/timeline-events",
        response_model=TimelineEvent,
        status_code=status.HTTP_201_CREATED,
    )
    def create_original_timeline_event(
        project_id: UUID,
        body: CreateTimelineEventRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> TimelineEvent:
        try:
            return repository.create_original_timeline_event(str(project_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="项目不存在") from error

    @application.post(
        "/api/projects/{project_id}/future-knowledge",
        response_model=FutureKnowledge,
        status_code=status.HTTP_201_CREATED,
    )
    def create_future_knowledge(
        project_id: UUID,
        body: CreateFutureKnowledgeRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> FutureKnowledge:
        try:
            return repository.create_future_knowledge(str(project_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="项目不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail="未来知识的年份不能早于重生年份") from error

    @application.post(
        "/api/projects/{project_id}/story-entities",
        response_model=StoryEntity,
        status_code=status.HTTP_201_CREATED,
    )
    def create_story_entity(
        project_id: UUID,
        body: CreateStoryEntityRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> StoryEntity:
        try:
            return repository.create_story_entity(str(project_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="项目不存在") from error

    @application.patch("/api/story-entities/{entity_id}", response_model=StoryEntity)
    def update_story_entity(
        entity_id: UUID,
        body: UpdateStoryEntityRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> StoryEntity:
        try:
            return repository.update_story_entity(str(entity_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="人物或资源不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="人物或资源账本已有新版本") from error

    @application.post(
        "/api/projects/{project_id}/story-threads",
        response_model=StoryThread,
        status_code=status.HTTP_201_CREATED,
    )
    def create_story_thread(
        project_id: UUID,
        body: CreateStoryThreadRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> StoryThread:
        try:
            return repository.create_story_thread(str(project_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="项目或埋设章节不存在") from error

    @application.post("/api/story-threads/{thread_id}/transition", response_model=StoryThread)
    def transition_story_thread(
        thread_id: UUID,
        body: TransitionStoryThreadRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> StoryThread:
        try:
            return repository.transition_story_thread(str(thread_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="伏笔或回收章节不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="伏笔账本已有新版本") from error
        except InvalidStoryThreadStateError as error:
            raise HTTPException(status_code=409, detail="当前伏笔状态不允许该操作") from error

    @application.post(
        "/api/projects/{project_id}/source-cards",
        response_model=SourceCard,
        status_code=status.HTTP_201_CREATED,
    )
    def create_source_card(
        project_id: UUID,
        body: CreateSourceCardRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> SourceCard:
        try:
            return repository.create_source_card(str(project_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="项目不存在") from error

    @application.post("/api/source-cards/{card_id}/confirmation", response_model=SourceCard)
    def set_source_card_confirmation(
        card_id: UUID,
        body: SetSourceCardConfirmationRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> SourceCard:
        try:
            return repository.set_source_card_confirmation(str(card_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="资料卡不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="资料卡已有新版本") from error

    @application.get("/api/chapters/{chapter_id}", response_model=Chapter)
    def get_chapter(
        chapter_id: UUID,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> Chapter:
        try:
            return repository.get_chapter(str(chapter_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error

    @application.patch("/api/chapters/{chapter_id}", response_model=Chapter)
    def update_chapter(
        chapter_id: UUID,
        body: UpdateChapterRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> Chapter:
        try:
            return repository.update_chapter(str(chapter_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="章节已在其他位置更新，请重新载入") from error
        except InvalidChapterStateError as error:
            raise HTTPException(status_code=409, detail="已定稿章节需先重新打开才能修改") from error

    @application.patch("/api/chapters/{chapter_id}/brief", response_model=Chapter)
    def update_chapter_brief(
        chapter_id: UUID,
        body: UpdateChapterBriefRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> Chapter:
        try:
            return repository.update_chapter_brief(str(chapter_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="章节已有新版本，请重新载入章纲") from error
        except InvalidChapterStateError as error:
            raise HTTPException(status_code=409, detail="已定稿章节需先重新打开才能修改") from error

    @application.post("/api/chapters/{chapter_id}/transition", response_model=Chapter)
    def transition_chapter(
        chapter_id: UUID,
        body: TransitionChapterRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> Chapter:
        try:
            return repository.transition_chapter(str(chapter_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="章节已有新版本，请重新载入") from error
        except InvalidChapterStateError as error:
            raise HTTPException(status_code=409, detail="当前章节尚未满足该状态的条件") from error

    @application.post(
        "/api/chapters/{chapter_id}/fact-change-sets",
        response_model=FactChangeSet,
        status_code=status.HTTP_201_CREATED,
    )
    def create_fact_change_set(
        chapter_id: UUID,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> FactChangeSet:
        try:
            return repository.create_fact_change_set(str(chapter_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error
        except InvalidChapterStateError as error:
            raise HTTPException(status_code=409, detail="章节定稿后才能提取候选事实") from error

    @application.post(
        "/api/fact-change-sets/{change_set_id}/apply",
        response_model=FactChangeSet,
    )
    def apply_fact_change_set(
        change_set_id: UUID,
        body: ApplyFactChangeSetRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> FactChangeSet:
        try:
            return repository.apply_fact_change_set(str(change_set_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="候选事实变更集不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="候选事实已在其他位置处理") from error
        except InvalidFactChangeSetStateError as error:
            raise HTTPException(status_code=409, detail="候选事实已经处理，不能重复回灌") from error
        except InvalidFactSelectionError as error:
            raise HTTPException(status_code=400, detail="选择中包含不属于本次候选的事实") from error

    @application.post(
        "/api/fact-change-sets/{change_set_id}/reject",
        response_model=FactChangeSet,
    )
    def reject_fact_change_set(
        change_set_id: UUID,
        body: RejectFactChangeSetRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> FactChangeSet:
        try:
            return repository.reject_fact_change_set(str(change_set_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="候选事实变更集不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="候选事实已在其他位置处理") from error
        except InvalidFactChangeSetStateError as error:
            raise HTTPException(status_code=409, detail="候选事实已经处理，不能重复操作") from error

    @application.post(
        "/api/future-knowledge/{knowledge_id}/review",
        response_model=FutureKnowledge,
    )
    def review_future_knowledge(
        knowledge_id: UUID,
        body: ReviewFutureKnowledgeRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> FutureKnowledge:
        try:
            return repository.review_future_knowledge(str(knowledge_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="未来知识不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="未来知识已在其他位置更新") from error
        except InvalidFutureKnowledgeStateError as error:
            raise HTTPException(status_code=409, detail="只有待复核的未来知识可以确认") from error

    @application.post(
        "/api/chapters/{chapter_id}/generation-runs",
        response_model=GenerationRun,
        status_code=status.HTTP_201_CREATED,
    )
    def start_generation(
        chapter_id: UUID,
        body: StartGenerationRequest,
        service: Annotated[GenerationService, Depends(get_generation_service)],
    ) -> GenerationRun:
        try:
            return service.start(str(chapter_id), body.expected_revision)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="正文已有新版本，请重新准备上下文") from error
        except InvalidChapterStateError as error:
            raise HTTPException(status_code=409, detail="当前章节状态不允许生成候选稿") from error

    @application.post("/api/generation-runs/{run_id}/resume", response_model=GenerationRun)
    def resume_generation(
        run_id: UUID,
        service: Annotated[GenerationService, Depends(get_generation_service)],
    ) -> GenerationRun:
        try:
            return service.resume(str(run_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="生成任务不存在") from error

    @application.post("/api/generation-runs/{run_id}/apply", response_model=Chapter)
    def apply_generation(
        run_id: UUID,
        body: ApplyGenerationRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> Chapter:
        try:
            return repository.apply_generation(str(run_id), body.expected_revision)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="生成任务不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="正文已有新版本，候选稿未覆盖当前内容") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail="生成任务尚无可采用草稿") from error

    return application


def get_repository(request: Request) -> ProjectRepository:
    repository: ProjectRepository = request.app.state.repository
    return repository


def get_job_repository(request: Request) -> JobRepository:
    repository: JobRepository = request.app.state.job_repository
    return repository


def get_job_runtime_from_repository(
    application: FastAPI,
    repository: JobRepository,
) -> JobRuntime:
    del repository
    runtime: JobRuntime = application.state.job_runtime
    return runtime


def get_generation_service(request: Request) -> GenerationService:
    return GenerationService(get_repository(request))


def get_ai_manager(request: Request) -> AiGatewayManager:
    manager: AiGatewayManager = request.app.state.ai_manager
    return manager


def get_ai_writing_service(request: Request) -> AiWritingService:
    return AiWritingService(get_repository(request), get_ai_manager(request))


def get_reference_analysis_service(request: Request) -> ReferenceAnalysisService:
    return ReferenceAnalysisService(get_repository(request), get_ai_manager(request))
