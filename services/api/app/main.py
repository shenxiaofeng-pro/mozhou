import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from re import fullmatch
from secrets import compare_digest
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi import Path as PathParam
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
from app.author_productivity import (
    AuthorIdea,
    AuthorProductivityService,
    ChapterAnnotation,
    CreateAnnotationRequest,
    CreateIdeaRequest,
    CreateRelationshipRequest,
    PrepareIdeaRequest,
    ResolveAnnotationRequest,
    StoryGraphs,
    StoryRelationship,
    UpdateIdeaRequest,
    WritingCalendar,
)
from app.beta import (
    BetaEvaluationReport,
    BetaEvaluationService,
    BetaEventType,
    BetaFeedback,
    BetaTemplate,
    CreateBetaFeedbackRequest,
)
from app.chapter_jobs import ChapterJobService
from app.comic_drama import (
    AdoptComicSeasonRequest,
    ComicAiPreview,
    ComicAsset,
    ComicAuditIssue,
    ComicDeleteImpact,
    ComicDramaNotFoundError,
    ComicDramaService,
    ComicEpisodeScriptRequest,
    ComicEpisodeSubmission,
    ComicSeasonPlanRequest,
    ComicSeasonSubmission,
    ComicStateConflictError,
    InvalidComicSourceError,
    ReviewComicEpisodeRequest,
    SubmitComicEpisodeScriptRequest,
    SubmitComicSeasonPlanRequest,
)
from app.config import default_database_path
from app.context import (
    ContextDirective,
    ContextDirectiveNotFoundError,
    ContextDirectiveRequest,
    ContextPacket,
    ContextRepository,
    InvalidContextDirectiveError,
    InvalidContextPacketError,
    StaleContextDirectiveError,
)
from app.database import Database
from app.diagnostics import (
    DiagnosticService,
    DiagnosticSummary,
    classify_sqlite_operational_error,
    elapsed_milliseconds,
    request_timer,
    safe_route_template,
)
from app.director.repository import (
    DirectorNotFoundError,
    DirectorRepository,
    InvalidDirectorChangeError,
    StaleDirectorRevisionError,
)
from app.director.rules import regeneration_impact
from app.director.service import DirectorService
from app.generation import GenerationService
from app.jobs import (
    Job,
    JobArtifactContent,
    JobDetail,
    JobKind,
    JobNotFoundError,
    JobRepository,
    JobRuntime,
)
from app.jobs.runtime import JobExecutionContext
from app.manuscript.directory import (
    DirectoryConfirmationRequiredError,
    DirectoryConflictError,
    DirectoryService,
)
from app.manuscript.importer import preview_manuscript_file
from app.manuscript.serial import SerialService
from app.manuscript.service import ManuscriptService
from app.models import (
    AcknowledgeOriginalityReportRequest,
    AiChapterBriefProposal,
    AiChapterBriefRequest,
    AiDraftRequest,
    AiStatus,
    ApplyDirectorProposalRequest,
    ApplyFactChangeSetRequest,
    ApplyGenerationRequest,
    ApplyReferencePatternRequest,
    ApplyTextChangeSetRequest,
    BookBlueprint,
    Chapter,
    ChapterVersion,
    ComicProject,
    ComicWorkspace,
    ConfigureAiRequest,
    ConfirmManuscriptImportRequest,
    CreateChapterRequest,
    CreateComicProjectRequest,
    CreateDirectoryNodeRequest,
    CreateFutureKnowledgeRequest,
    CreateProjectRequest,
    CreateRecoveryPointRequest,
    CreateSourceCardRequest,
    CreateStoryEntityRequest,
    CreateStoryThreadRequest,
    CreateTextChangeSetRequest,
    CreateTimelineEventRequest,
    DeleteDirectoryNodeRequest,
    DirectorChapterPipelineRequest,
    DirectorChapterPipelineResult,
    DirectorExpansionProposal,
    DirectorExpansionRequest,
    DirectorFieldProposal,
    DirectorFieldRegenerationRequest,
    DirectorOutboundPreview,
    DirectorPlanningSnapshot,
    DirectorRegenerationImpact,
    DirectorRegenerationImpactRequest,
    DirectorStartupProposalSet,
    DirectorStartupRequest,
    DirectoryDeleteImpact,
    DirectoryEvent,
    FactChangeSet,
    FutureKnowledge,
    GenerationRun,
    ImportReferenceWorkRequest,
    ManuscriptExport,
    ManuscriptImportPreview,
    MoveDirectoryNodeRequest,
    OriginalityReport,
    Project,
    RecoveryPointSummary,
    ReferenceFilePreview,
    ReferenceFormat,
    ReferencePatternApplication,
    ReferencePatternCard,
    ReferenceRightsBasis,
    ReferenceSourceSpan,
    ReferenceSynthesisRequest,
    ReferenceWork,
    ReferenceWorkImpactResponse,
    RejectFactChangeSetRequest,
    RejectTextChangeSetRequest,
    RenameDirectoryNodeRequest,
    ReviewChapterRequest,
    ReviewFinding,
    ReviewFutureKnowledgeRequest,
    ReviewJobResult,
    ReviewOutboundPreview,
    RollbackChapterVersionRequest,
    RollingChapterPlan,
    SceneOriginalityCheck,
    SelectDirectorCandidateRequest,
    SerialDashboard,
    SetSerialDailyGoalRequest,
    SetSourceCardConfirmationRequest,
    SourceCard,
    SourceConfidence,
    SourceDocument,
    SourceKind,
    StartGenerationRequest,
    StoryEntity,
    StoryThread,
    TextChangeSet,
    TimelineEvent,
    TransitionChapterRequest,
    TransitionStoryThreadRequest,
    UpdateBookBlueprintRequest,
    UpdateChapterBriefRequest,
    UpdateChapterRequest,
    UpdateReferenceBlueprintRequest,
    UpdateRollingChapterPlanRequest,
    UpdateStoryEntityRequest,
    UpdateVolumePlanRequest,
    VolumePlan,
    Workspace,
    WorkspaceSearchResult,
    WorkspaceSummary,
)
from app.providers import (
    ActivateModelProfileRequest,
    AiOutboundPreview,
    AiTaskDefault,
    AiTaskType,
    CreateModelProfileRequest,
    DuplicateModelProfileError,
    ModelProfile,
    ModelProfileNotFoundError,
    ModelProfileRepository,
    StaleModelProfileError,
    StaleTaskDefaultError,
    UpdateAiTaskDefaultRequest,
    UpdateModelProfileRequest,
)
from app.reference_jobs import ReferenceJobService
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
    OriginalityGateBlockedError,
    ProjectRepository,
    StaleChapterSequenceError,
    StaleRevisionError,
)
from app.research import (
    ResearchFinding,
    ResearchPreview,
    ResearchRequest,
    ResearchService,
    ResearchSession,
    ResearchSubmission,
    ResearchWorkspace,
    ReviewResearchFindingRequest,
    SubmitResearchRequest,
)
from app.review.repository import (
    InvalidTextChangeError,
    ReviewNotFoundError,
    ReviewRepository,
    StaleReviewRevisionError,
)
from app.review.service import REVIEW_WORKFLOW, ReviewService
from app.safe_import import (
    MAX_PDF_FILE_BYTES,
    ParsedReferenceFile,
    UnsafeImportError,
    parse_reference_file,
)
from app.sandbox import (
    CompareSandboxRunsRequest,
    CreateSandboxBranchRequest,
    CreateSandboxCandidateRequest,
    CreateSandboxRunRequest,
    CreateSandboxSnapshotRequest,
    NarrativeSandboxService,
    SandboxBranch,
    SandboxCandidate,
    SandboxComparison,
    SandboxConflictError,
    SandboxInterview,
    SandboxReport,
    SandboxRun,
    SandboxSnapshot,
    SandboxTemplate,
    SandboxValidationError,
    SandboxWorkspace,
)
from app.sandbox_ai import (
    SandboxAiPreview,
    SandboxAiService,
    SubmitSandboxAiRoundRequest,
)


def create_app(
    database_path: Path | None = None,
    ai_manager: AiGatewayManager | None = None,
    session_token: str | None = None,
    *,
    defer_job_runtime: bool = False,
) -> FastAPI:
    if session_token is not None and fullmatch(r"[0-9a-f]{64}", session_token) is None:
        raise ValueError("session token must be 64 lowercase hexadecimal characters")
    database = Database(database_path or default_database_path())
    diagnostics = DiagnosticService(database)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        database.initialize()
        application.state.repository = ProjectRepository(database)
        application.state.beta_evaluation = BetaEvaluationService(database)
        application.state.narrative_sandbox = NarrativeSandboxService(database)
        application.state.diagnostics = diagnostics
        application.state.manuscript_service = ManuscriptService(
            database,
            application.state.repository,
        )
        application.state.directory_service = DirectoryService(
            database,
            application.state.repository,
        )
        application.state.serial_service = SerialService(database)
        application.state.model_profiles = ModelProfileRepository(database)
        application.state.context_repository = ContextRepository(database)
        application.state.ai_manager = ai_manager or AiGatewayManager()
        application.state.job_repository = JobRepository(database)
        application.state.sandbox_ai_service = SandboxAiService(
            application.state.narrative_sandbox,
            application.state.job_repository,
            application.state.ai_manager,
            application.state.model_profiles,
        )
        application.state.research_service = ResearchService(
            database,
            application.state.job_repository,
            application.state.ai_manager,
            application.state.model_profiles,
        )
        application.state.author_productivity = AuthorProductivityService(database)
        application.state.comic_drama_service = ComicDramaService(
            database,
            application.state.job_repository,
            application.state.ai_manager,
            application.state.model_profiles,
        )
        application.state.director_repository = DirectorRepository(database)
        application.state.review_repository = ReviewRepository(database)
        application.state.reference_job_service = ReferenceJobService(
            application.state.repository,
            application.state.job_repository,
            application.state.ai_manager,
            application.state.model_profiles,
        )
        application.state.chapter_job_service = ChapterJobService(
            application.state.repository,
            application.state.job_repository,
            application.state.ai_manager,
            application.state.model_profiles,
            application.state.context_repository,
        )
        application.state.director_service = DirectorService(
            application.state.repository,
            application.state.director_repository,
            application.state.job_repository,
            application.state.ai_manager,
            application.state.model_profiles,
            application.state.context_repository,
        )

        application.state.review_service = ReviewService(
            application.state.repository,
            application.state.review_repository,
            application.state.job_repository,
            application.state.ai_manager,
            application.state.model_profiles,
        )

        def handle_review_job(context: JobExecutionContext, job: Job) -> None:
            if job.workflow == REVIEW_WORKFLOW:
                application.state.review_service.handle(context, job)
            else:
                application.state.director_service.handle(context, job)

        application.state.job_runtime = JobRuntime(
            application.state.job_repository,
            {
                JobKind.REFERENCE_FUSION: application.state.reference_job_service.handle,
                JobKind.CHAPTER_BRIEF: application.state.chapter_job_service.handle_brief,
                JobKind.CHAPTER_DRAFT: application.state.chapter_job_service.handle_draft,
                JobKind.REVIEW: handle_review_job,
                JobKind.SANDBOX_AI_ROUND: application.state.sandbox_ai_service.handle,
                JobKind.RESEARCH_EXTRACTION: application.state.research_service.handle,
                JobKind.COMIC_SEASON_PLAN: (
                    application.state.comic_drama_service.handle_season_plan
                ),
                JobKind.COMIC_EPISODE_SCRIPT: (
                    application.state.comic_drama_service.handle_episode_script
                ),
            },
        )
        if not defer_job_runtime:
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

    @application.exception_handler(sqlite3.OperationalError)
    async def sanitized_database_operational_error(
        _request: Request,
        error: sqlite3.OperationalError,
    ) -> JSONResponse:
        status_code, detail, code = classify_sqlite_operational_error(error)
        diagnostics.events.system_event(
            event="database_operation_failed",
            level="error",
            code=code,
        )
        headers = {"Retry-After": "1"} if status_code == 503 else None
        return JSONResponse(
            status_code=status_code,
            content={"detail": detail, "code": code},
            headers=headers,
        )

    @application.exception_handler(sqlite3.DatabaseError)
    async def sanitized_database_error(
        _request: Request,
        _error: sqlite3.DatabaseError,
    ) -> JSONResponse:
        diagnostics.events.system_event(
            event="database_operation_failed",
            level="error",
            code="database_error",
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "本地数据库操作失败，请导出诊断包并保留现有数据文件",
                "code": "database_error",
            },
        )

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
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
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

    @application.middleware("http")
    async def record_sanitized_request_event(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id, started_at = request_timer()
        response = await call_next(request)
        diagnostics.events.request_completed(
            request_id=request_id,
            method=request.method,
            route=safe_route_template(request.scope),
            status_code=response.status_code,
            duration_ms=elapsed_milliseconds(started_at),
        )
        response.headers["X-Mozhou-Request-Id"] = request_id
        return response

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/diagnostics", response_model=DiagnosticSummary)
    def get_diagnostics() -> DiagnosticSummary:
        return diagnostics.summary()

    @application.post("/api/diagnostics/bundle")
    def export_diagnostic_bundle() -> Response:
        filename, payload = diagnostics.bundle()
        return Response(
            content=payload,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    @application.get("/api/beta/templates", response_model=list[BetaTemplate])
    def list_beta_templates() -> list[BetaTemplate]:
        return application.state.beta_evaluation.list_templates()

    @application.get(
        "/api/projects/{project_id}/beta-report",
        response_model=BetaEvaluationReport,
    )
    def get_beta_report(project_id: UUID) -> BetaEvaluationReport:
        try:
            return application.state.beta_evaluation.report(str(project_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="作品不存在") from error

    @application.post(
        "/api/projects/{project_id}/beta-feedback",
        response_model=BetaFeedback,
        status_code=status.HTTP_201_CREATED,
    )
    def create_beta_feedback(
        project_id: UUID,
        body: CreateBetaFeedbackRequest,
    ) -> BetaFeedback:
        try:
            return application.state.beta_evaluation.create_feedback(str(project_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="作品不存在") from error

    @application.post(
        "/api/projects/{project_id}/beta-events/{event_type}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def record_beta_event(project_id: UUID, event_type: BetaEventType) -> Response:
        try:
            application.state.beta_evaluation.record_event(str(project_id), event_type)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="作品不存在") from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.get("/api/sandbox/templates", response_model=list[SandboxTemplate])
    def list_sandbox_templates() -> list[SandboxTemplate]:
        return application.state.narrative_sandbox.list_templates()

    @application.get(
        "/api/projects/{project_id}/sandbox",
        response_model=SandboxWorkspace,
    )
    def get_sandbox_workspace(project_id: UUID) -> SandboxWorkspace:
        try:
            return application.state.narrative_sandbox.workspace(str(project_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="作品不存在") from error

    @application.post(
        "/api/projects/{project_id}/sandbox/snapshots",
        response_model=SandboxSnapshot,
        status_code=status.HTTP_201_CREATED,
    )
    def create_sandbox_snapshot(
        project_id: UUID,
        body: CreateSandboxSnapshotRequest,
    ) -> SandboxSnapshot:
        try:
            return application.state.narrative_sandbox.create_snapshot(str(project_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="作品不存在") from error
        except SandboxValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post(
        "/api/sandbox/snapshots/{snapshot_id}/branches",
        response_model=SandboxBranch,
        status_code=status.HTTP_201_CREATED,
    )
    def create_sandbox_branch(
        snapshot_id: UUID,
        body: CreateSandboxBranchRequest,
    ) -> SandboxBranch:
        try:
            return application.state.narrative_sandbox.create_branch(str(snapshot_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="沙盘快照不存在") from error
        except SandboxValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except SandboxConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post(
        "/api/sandbox/branches/{branch_id}/runs",
        response_model=SandboxRun,
        status_code=status.HTTP_201_CREATED,
    )
    def create_sandbox_run(
        branch_id: UUID,
        body: CreateSandboxRunRequest,
    ) -> SandboxRun:
        try:
            return application.state.narrative_sandbox.create_run(str(branch_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="沙盘分支不存在") from error
        except SandboxValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except SandboxConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get("/api/sandbox/runs/{run_id}", response_model=SandboxRun)
    def get_sandbox_run(run_id: UUID) -> SandboxRun:
        try:
            return application.state.narrative_sandbox.get_run(str(run_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="沙盘运行不存在") from error

    @application.post("/api/sandbox/runs/{run_id}/advance", response_model=SandboxRun)
    def advance_sandbox_run(run_id: UUID) -> SandboxRun:
        try:
            return application.state.narrative_sandbox.advance_run(str(run_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="沙盘运行不存在") from error
        except SandboxValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except SandboxConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get(
        "/api/sandbox/runs/{run_id}/ai-preview",
        response_model=SandboxAiPreview,
    )
    def preview_sandbox_ai_round(run_id: UUID) -> SandboxAiPreview:
        try:
            return application.state.sandbox_ai_service.preview(str(run_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="沙盘运行不存在") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置剧情沙盘模型线路") from error
        except (SandboxValidationError, SandboxConflictError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            messages = {
                "sandbox_run_not_found": "沙盘运行不存在",
                "sandbox_context_too_large": "沙盘外发上下文超过安全上限",
                "originality_gate_blocked": "场景原创性检查为高风险，AI 沙盘已阻断",
            }
            raise HTTPException(
                status_code=409,
                detail=messages.get(str(error), "当前 AI 沙盘无法预览"),
            ) from error

    @application.post(
        "/api/sandbox/runs/{run_id}/ai-jobs",
        response_model=Job,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_sandbox_ai_round(
        run_id: UUID,
        body: SubmitSandboxAiRoundRequest,
        jobs: Annotated[JobRepository, Depends(get_job_repository)],
    ) -> Job:
        try:
            job = application.state.sandbox_ai_service.submit(str(run_id), body)
            get_job_runtime_from_repository(application, jobs).wake()
            return job
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="沙盘运行不存在") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置剧情沙盘模型线路") from error
        except (SandboxValidationError, SandboxConflictError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            messages = {
                "sandbox_run_not_found": "沙盘运行不存在",
                "sandbox_context_too_large": "沙盘外发上下文超过安全上限",
                "external_processing_not_confirmed": "请先确认本轮沙盘外发范围",
                "estimated_cost_exceeds_limit": "预计费用超过本次上限",
                "sandbox_state_changed": "沙盘状态已经变化，请重新预览",
                "originality_gate_blocked": "场景原创性检查为高风险，AI 沙盘已阻断",
            }
            raise HTTPException(
                status_code=409,
                detail=messages.get(str(error), "当前 AI 沙盘任务无法提交"),
            ) from error

    @application.post("/api/sandbox/runs/{run_id}/cancel", response_model=SandboxRun)
    def cancel_sandbox_run(run_id: UUID) -> SandboxRun:
        try:
            return application.state.narrative_sandbox.cancel_run(str(run_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="沙盘运行不存在") from error
        except SandboxConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post("/api/projects/{project_id}/research/preview", response_model=ResearchPreview)
    def preview_research(project_id: UUID, body: ResearchRequest) -> ResearchPreview:
        try:
            return application.state.research_service.preview(str(project_id), body)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="作品不存在") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置资料研究模型线路") from error
        except ValueError as error:
            messages = {
                "research_source_not_found": "所选全局资料不存在",
                "research_material_too_large": "本次研究资料超过 200 万字符上限",
            }
            raise HTTPException(
                status_code=409, detail=messages.get(str(error), "研究预览失败")
            ) from error

    @application.post(
        "/api/projects/{project_id}/research/jobs",
        response_model=ResearchSubmission,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_research(
        project_id: UUID,
        body: SubmitResearchRequest,
        jobs: Annotated[JobRepository, Depends(get_job_repository)],
    ) -> ResearchSubmission:
        try:
            session, job = application.state.research_service.submit(str(project_id), body)
            get_job_runtime_from_repository(application, jobs).wake()
            return ResearchSubmission(session=session, job=job)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="作品不存在") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置资料研究模型线路") from error
        except ValueError as error:
            messages = {
                "research_source_not_found": "所选全局资料不存在",
                "research_material_too_large": "本次研究资料超过 200 万字符上限",
                "research_source_changed": "资料范围已变化，请重新预览",
                "external_processing_not_confirmed": "请先确认研究资料外发范围",
                "estimated_cost_exceeds_limit": "研究预计费用超过本次上限",
            }
            raise HTTPException(
                status_code=409, detail=messages.get(str(error), "研究任务无法提交")
            ) from error

    @application.get(
        "/api/projects/{project_id}/research/sessions", response_model=list[ResearchSession]
    )
    def list_research_sessions(project_id: UUID) -> list[ResearchSession]:
        return application.state.research_service.list_sessions(str(project_id))

    @application.get("/api/research/sessions/{session_id}", response_model=ResearchWorkspace)
    def get_research_session(session_id: UUID) -> ResearchWorkspace:
        try:
            return application.state.research_service.get_session(str(session_id))
        except LookupError as error:
            raise HTTPException(status_code=404, detail="研究会话不存在") from error

    @application.post("/api/research/findings/{finding_id}/review", response_model=ResearchFinding)
    def review_research_finding(
        finding_id: UUID, body: ReviewResearchFindingRequest
    ) -> ResearchFinding:
        try:
            return application.state.research_service.review_finding(str(finding_id), body)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="研究候选不存在") from error
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "research_revision_conflict": "研究候选已在其他窗口更改",
                    "research_finding_already_reviewed": "该研究候选已完成审核",
                }.get(str(error), "研究候选无法审核"),
            ) from error

    @application.get("/api/projects/{project_id}/writing-calendar", response_model=WritingCalendar)
    def get_writing_calendar(
        project_id: UUID, days: Annotated[int, Query(ge=7, le=366)] = 42
    ) -> WritingCalendar:
        try:
            return application.state.author_productivity.calendar(str(project_id), days)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="作品不存在") from error

    @application.get(
        "/api/chapters/{chapter_id}/annotations", response_model=list[ChapterAnnotation]
    )
    def list_chapter_annotations(chapter_id: UUID) -> list[ChapterAnnotation]:
        try:
            return application.state.author_productivity.list_annotations(str(chapter_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error

    @application.post(
        "/api/chapters/{chapter_id}/annotations",
        response_model=ChapterAnnotation,
        status_code=status.HTTP_201_CREATED,
    )
    def create_chapter_annotation(
        chapter_id: UUID, body: CreateAnnotationRequest
    ) -> ChapterAnnotation:
        try:
            return application.state.author_productivity.create_annotation(str(chapter_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="正文已变化，请重新选中批注范围") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail="请先选中一段正文") from error

    @application.post(
        "/api/chapter-annotations/{annotation_id}/resolve", response_model=ChapterAnnotation
    )
    def resolve_chapter_annotation(
        annotation_id: UUID, body: ResolveAnnotationRequest
    ) -> ChapterAnnotation:
        try:
            return application.state.author_productivity.resolve_annotation(
                str(annotation_id), body
            )
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="批注不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="批注已在其他窗口更改") from error

    @application.get("/api/author-ideas", response_model=list[AuthorIdea])
    def list_author_ideas(project_id: UUID | None = None) -> list[AuthorIdea]:
        return application.state.author_productivity.list_ideas(
            str(project_id) if project_id else None
        )

    @application.post(
        "/api/author-ideas", response_model=AuthorIdea, status_code=status.HTTP_201_CREATED
    )
    def create_author_idea(body: CreateIdeaRequest) -> AuthorIdea:
        try:
            return application.state.author_productivity.create_idea(body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="灵感所属作品不存在") from error

    @application.patch("/api/author-ideas/{idea_id}", response_model=AuthorIdea)
    def update_author_idea(idea_id: UUID, body: UpdateIdeaRequest) -> AuthorIdea:
        try:
            return application.state.author_productivity.update_idea(str(idea_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="灵感不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="灵感已在其他窗口更改") from error

    @application.post("/api/author-ideas/{idea_id}/prepare", response_model=AuthorIdea)
    def prepare_author_idea(idea_id: UUID, body: PrepareIdeaRequest) -> AuthorIdea:
        try:
            return application.state.author_productivity.prepare_idea(str(idea_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="灵感不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="灵感已在其他窗口更改") from error

    @application.post(
        "/api/projects/{project_id}/story-relationships",
        response_model=StoryRelationship,
        status_code=status.HTTP_201_CREATED,
    )
    def create_story_relationship(
        project_id: UUID, body: CreateRelationshipRequest
    ) -> StoryRelationship:
        try:
            return application.state.author_productivity.create_relationship(str(project_id), body)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="人物关系的角色或来源章节无效") from error

    @application.get("/api/projects/{project_id}/story-graphs", response_model=StoryGraphs)
    def get_story_graphs(project_id: UUID) -> StoryGraphs:
        return application.state.author_productivity.graphs(str(project_id))

    @application.post(
        "/api/sandbox/runs/{run_id}/replay",
        response_model=SandboxRun,
        status_code=status.HTTP_201_CREATED,
    )
    def replay_sandbox_run(run_id: UUID) -> SandboxRun:
        try:
            return application.state.narrative_sandbox.replay_run(str(run_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="沙盘运行不存在") from error
        except (SandboxValidationError, SandboxConflictError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get(
        "/api/sandbox/runs/{run_id}/report",
        response_model=SandboxReport,
    )
    def get_sandbox_report(run_id: UUID) -> SandboxReport:
        try:
            return application.state.narrative_sandbox.report(str(run_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="沙盘运行不存在") from error
        except SandboxConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get(
        "/api/sandbox/runs/{run_id}/interviews/{actor_id}",
        response_model=SandboxInterview,
    )
    def get_sandbox_interview(run_id: UUID, actor_id: str) -> SandboxInterview:
        try:
            return application.state.narrative_sandbox.interview(str(run_id), actor_id)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="沙盘运行或角色不存在") from error
        except SandboxConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post(
        "/api/sandbox/runs/{run_id}/candidates",
        response_model=SandboxCandidate,
        status_code=status.HTTP_201_CREATED,
    )
    def create_sandbox_candidate(
        run_id: UUID,
        body: CreateSandboxCandidateRequest,
    ) -> SandboxCandidate:
        try:
            return application.state.narrative_sandbox.create_candidate(str(run_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="沙盘运行不存在") from error
        except SandboxValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post(
        "/api/sandbox/candidates/{candidate_id}/{decision}",
        response_model=SandboxCandidate,
    )
    def decide_sandbox_candidate(
        candidate_id: UUID,
        decision: Literal["approve", "reject"],
    ) -> SandboxCandidate:
        try:
            return application.state.narrative_sandbox.decide_candidate(str(candidate_id), decision)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="沙盘候选不存在") from error
        except SandboxConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post(
        "/api/projects/{project_id}/sandbox/comparisons",
        response_model=SandboxComparison,
    )
    def compare_sandbox_runs(
        project_id: UUID,
        body: CompareSandboxRunsRequest,
    ) -> SandboxComparison:
        try:
            return application.state.narrative_sandbox.compare_runs(str(project_id), body.run_ids)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="沙盘运行不存在") from error
        except (SandboxValidationError, SandboxConflictError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post("/api/runtime/start")
    def start_job_runtime(
        jobs: Annotated[JobRepository, Depends(get_job_repository)],
    ) -> dict[str, str]:
        runtime = get_job_runtime_from_repository(application, jobs)
        runtime.start()
        return {"status": "running"}

    @application.get("/api/projects/{project_id}/jobs", response_model=list[Job])
    def list_jobs(
        project_id: UUID,
        jobs: Annotated[JobRepository, Depends(get_job_repository)],
    ) -> list[Job]:
        try:
            return jobs.list_jobs(str(project_id))
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="作品不存在") from error

    @application.get(
        "/api/chapters/{chapter_id}/context-packets",
        response_model=list[ContextPacket],
    )
    def list_context_packets(
        chapter_id: UUID,
        contexts: Annotated[ContextRepository, Depends(get_context_repository)],
    ) -> list[ContextPacket]:
        return contexts.list_packets(str(chapter_id))

    @application.get("/api/context-packets/{packet_id}", response_model=ContextPacket)
    def get_context_packet(
        packet_id: UUID,
        contexts: Annotated[ContextRepository, Depends(get_context_repository)],
    ) -> ContextPacket:
        try:
            return contexts.get_packet(str(packet_id))
        except LookupError as error:
            raise HTTPException(status_code=404, detail="上下文包不存在") from error

    @application.get(
        "/api/chapters/{chapter_id}/context-directives",
        response_model=list[ContextDirective],
    )
    def list_context_directives(
        chapter_id: UUID,
        contexts: Annotated[ContextRepository, Depends(get_context_repository)],
    ) -> list[ContextDirective]:
        try:
            return contexts.list_directives(str(chapter_id))
        except ContextDirectiveNotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error

    @application.put(
        "/api/chapters/{chapter_id}/context-directives",
        response_model=ContextDirective,
    )
    def set_context_directive(
        chapter_id: UUID,
        body: ContextDirectiveRequest,
        contexts: Annotated[ContextRepository, Depends(get_context_repository)],
    ) -> ContextDirective:
        try:
            return contexts.set_directive(str(chapter_id), body)
        except ContextDirectiveNotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error
        except InvalidContextDirectiveError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except StaleContextDirectiveError as error:
            raise HTTPException(status_code=409, detail="上下文选择已更新，请重新预览") from error

    @application.delete(
        "/api/context-directives/{directive_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_context_directive(
        directive_id: UUID,
        expected_revision: int,
        contexts: Annotated[ContextRepository, Depends(get_context_repository)],
    ) -> Response:
        if expected_revision < 0:
            raise HTTPException(status_code=422, detail="请求内容格式无效")
        try:
            contexts.delete_directive(str(directive_id), expected_revision)
        except ContextDirectiveNotFoundError as error:
            raise HTTPException(status_code=404, detail="上下文选择不存在") from error
        except StaleContextDirectiveError as error:
            raise HTTPException(status_code=409, detail="上下文选择已更新，请重新预览") from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.get(
        "/api/reference-library/works/{work_id}/impact",
        response_model=ReferenceWorkImpactResponse,
    )
    def get_reference_work_impact(
        work_id: UUID,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> ReferenceWorkImpactResponse:
        try:
            impact = repository.get_reference_work_impact(str(work_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="参考资产不存在") from error
        return ReferenceWorkImpactResponse(
            work=impact.work,
            projects=impact.projects,
            cache_entries=impact.cache_entries,
        )

    @application.delete(
        "/api/reference-library/works/{work_id}",
        response_model=ReferenceWorkImpactResponse,
    )
    def purge_global_reference_work(
        work_id: UUID,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
        confirm_purge: bool = False,
    ) -> ReferenceWorkImpactResponse:
        if not confirm_purge:
            raise HTTPException(status_code=409, detail="请先查看受影响作品并确认清理")
        try:
            impact = repository.purge_reference_work(str(work_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="参考资产不存在") from error
        return ReferenceWorkImpactResponse(
            work=impact.work,
            projects=impact.projects,
            cache_entries=impact.cache_entries,
        )

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

    @application.get("/api/ai/profiles", response_model=list[ModelProfile])
    def list_ai_profiles(
        profiles: Annotated[ModelProfileRepository, Depends(get_model_profile_repository)],
    ) -> list[ModelProfile]:
        return profiles.list_profiles()

    @application.get("/api/ai/task-defaults", response_model=list[AiTaskDefault])
    def list_ai_task_defaults(
        profiles: Annotated[ModelProfileRepository, Depends(get_model_profile_repository)],
    ) -> list[AiTaskDefault]:
        return profiles.list_task_defaults()

    @application.put(
        "/api/ai/task-defaults/{task_type}",
        response_model=AiTaskDefault,
    )
    def set_ai_task_default(
        task_type: AiTaskType,
        body: UpdateAiTaskDefaultRequest,
        profiles: Annotated[ModelProfileRepository, Depends(get_model_profile_repository)],
    ) -> AiTaskDefault:
        try:
            return profiles.set_task_default(task_type, body)
        except ModelProfileNotFoundError as error:
            raise HTTPException(status_code=404, detail="模型配置不存在") from error
        except StaleTaskDefaultError as error:
            raise HTTPException(
                status_code=409, detail="任务默认模型已更新，请刷新后重试"
            ) from error

    @application.delete(
        "/api/ai/task-defaults/{task_type}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_ai_task_default(
        task_type: AiTaskType,
        expected_revision: int,
        profiles: Annotated[ModelProfileRepository, Depends(get_model_profile_repository)],
    ) -> Response:
        if expected_revision < 0:
            raise HTTPException(status_code=422, detail="请求内容格式无效")
        try:
            profiles.delete_task_default(
                task_type,
                expected_revision,
            )
        except StaleTaskDefaultError as error:
            raise HTTPException(
                status_code=409, detail="任务默认模型已更新，请刷新后重试"
            ) from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.post(
        "/api/ai/profiles",
        response_model=ModelProfile,
        status_code=status.HTTP_201_CREATED,
    )
    def create_ai_profile(
        body: CreateModelProfileRequest,
        profiles: Annotated[ModelProfileRepository, Depends(get_model_profile_repository)],
    ) -> ModelProfile:
        try:
            return profiles.create_profile(body)
        except DuplicateModelProfileError as error:
            raise HTTPException(status_code=409, detail="模型配置名称已存在") from error

    @application.put("/api/ai/profiles/{profile_id}", response_model=ModelProfile)
    def update_ai_profile(
        profile_id: UUID,
        body: UpdateModelProfileRequest,
        profiles: Annotated[ModelProfileRepository, Depends(get_model_profile_repository)],
        manager: Annotated[AiGatewayManager, Depends(get_ai_manager)],
    ) -> ModelProfile:
        try:
            profile = profiles.update_profile(str(profile_id), body)
            manager.unload_profile(str(profile_id))
            return profile
        except ModelProfileNotFoundError as error:
            raise HTTPException(status_code=404, detail="模型配置不存在") from error
        except StaleModelProfileError as error:
            raise HTTPException(status_code=409, detail="模型配置已更新，请刷新后重试") from error
        except DuplicateModelProfileError as error:
            raise HTTPException(status_code=409, detail="模型配置名称已存在") from error

    @application.post(
        "/api/ai/profiles/{profile_id}/activate",
        response_model=AiStatus,
    )
    def activate_ai_profile(
        profile_id: UUID,
        body: ActivateModelProfileRequest,
        profiles: Annotated[ModelProfileRepository, Depends(get_model_profile_repository)],
        manager: Annotated[AiGatewayManager, Depends(get_ai_manager)],
    ) -> AiStatus:
        try:
            profile = profiles.get_profile(str(profile_id))
            return manager.activate_profile(
                profile,
                body.api_key.get_secret_value(),
                key_source="runtime",
                make_active=body.make_active,
            )
        except ModelProfileNotFoundError as error:
            raise HTTPException(status_code=404, detail="模型配置不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail="API Key 格式无效") from error

    @application.post("/api/ai/deactivate", response_model=AiStatus)
    def deactivate_ai_profile(
        manager: Annotated[AiGatewayManager, Depends(get_ai_manager)],
    ) -> AiStatus:
        return manager.deactivate()

    @application.post(
        "/api/ai/profiles/{profile_id}/deactivate",
        response_model=AiStatus,
    )
    def deactivate_one_ai_profile(
        profile_id: UUID,
        manager: Annotated[AiGatewayManager, Depends(get_ai_manager)],
    ) -> AiStatus:
        return manager.unload_profile(str(profile_id))

    @application.delete("/api/ai/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_ai_profile(
        profile_id: UUID,
        expected_revision: int,
        profiles: Annotated[ModelProfileRepository, Depends(get_model_profile_repository)],
        manager: Annotated[AiGatewayManager, Depends(get_ai_manager)],
    ) -> Response:
        if expected_revision < 0:
            raise HTTPException(status_code=422, detail="请求内容格式无效")
        if manager.status().profile_id == str(profile_id):
            raise HTTPException(status_code=409, detail="请先切换到其他模型配置")
        try:
            profiles.delete_profile(
                str(profile_id),
                expected_revision,
            )
            manager.unload_profile(str(profile_id))
        except ModelProfileNotFoundError as error:
            raise HTTPException(status_code=404, detail="模型配置不存在") from error
        except StaleModelProfileError as error:
            raise HTTPException(status_code=409, detail="模型配置已更新，请刷新后重试") from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

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
        except OriginalityGateBlockedError as error:
            raise HTTPException(status_code=409, detail="请先处理蓝图原创性检查") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置 AI 模型") from error
        except InvalidContextPacketError as error:
            raise HTTPException(status_code=409, detail="上下文已变化，请重新预览后确认") from error
        except AiProviderError as error:
            raise HTTPException(status_code=502, detail="AI 暂时未能生成可用章纲") from error

    @application.post(
        "/api/chapters/{chapter_id}/ai-brief-preview",
        response_model=AiOutboundPreview,
    )
    def preview_ai_chapter_brief(
        chapter_id: UUID,
        body: AiChapterBriefRequest,
    ) -> AiOutboundPreview:
        service: ChapterJobService = application.state.chapter_job_service
        try:
            return service.preview_brief(str(chapter_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="章节已有新版本，请重新预览") from error
        except InvalidChapterStateError as error:
            raise HTTPException(status_code=409, detail="当前章节状态不允许生成章纲") from error
        except OriginalityGateBlockedError as error:
            raise HTTPException(status_code=409, detail="请先处理蓝图原创性检查") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置 AI 模型") from error
        except InvalidContextPacketError as error:
            raise HTTPException(status_code=409, detail="上下文已变化，请重新预览后确认") from error

    @application.post(
        "/api/chapters/{chapter_id}/ai-brief-jobs",
        response_model=Job,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_ai_chapter_brief_job(
        chapter_id: UUID,
        body: AiChapterBriefRequest,
    ) -> Job:
        service: ChapterJobService = application.state.chapter_job_service
        try:
            job = service.submit_brief(str(chapter_id), body)
            application.state.job_runtime.wake()
            return job
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="章节已有新版本，请重新提交") from error
        except InvalidChapterStateError as error:
            raise HTTPException(status_code=409, detail="当前章节状态不允许生成章纲") from error
        except OriginalityGateBlockedError as error:
            raise HTTPException(status_code=409, detail="请先处理蓝图原创性检查") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置 AI 模型") from error
        except InvalidContextPacketError as error:
            raise HTTPException(status_code=409, detail="上下文已变化，请重新预览后确认") from error

    @application.get(
        "/api/jobs/{job_id}/chapter-brief-result",
        response_model=AiChapterBriefProposal,
    )
    def get_ai_chapter_brief_job_result(job_id: UUID) -> AiChapterBriefProposal:
        service: ChapterJobService = application.state.chapter_job_service
        try:
            return service.get_brief_result(str(job_id))
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="任务不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail="章纲任务尚无可用结果") from error

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
        except OriginalityGateBlockedError as error:
            raise HTTPException(status_code=409, detail="请先处理蓝图原创性检查") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置 AI 模型") from error
        except InvalidContextPacketError as error:
            raise HTTPException(status_code=409, detail="上下文已变化，请重新预览后确认") from error
        except AiProviderError as error:
            raise HTTPException(status_code=502, detail="AI 暂时未能生成可用正文") from error

    @application.post(
        "/api/chapters/{chapter_id}/ai-draft-preview",
        response_model=AiOutboundPreview,
    )
    def preview_ai_chapter_draft(
        chapter_id: UUID,
        body: AiDraftRequest,
    ) -> AiOutboundPreview:
        service: ChapterJobService = application.state.chapter_job_service
        try:
            return service.preview_draft(str(chapter_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="章节已有新版本，请重新预览") from error
        except InvalidChapterStateError as error:
            raise HTTPException(status_code=409, detail="请先保存完整章纲再生成正文") from error
        except OriginalityGateBlockedError as error:
            raise HTTPException(status_code=409, detail="请先处理蓝图原创性检查") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置 AI 模型") from error

    @application.post(
        "/api/chapters/{chapter_id}/ai-draft-jobs",
        response_model=Job,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_ai_chapter_draft_job(
        chapter_id: UUID,
        body: AiDraftRequest,
    ) -> Job:
        service: ChapterJobService = application.state.chapter_job_service
        try:
            job = service.submit_draft(str(chapter_id), body)
            application.state.job_runtime.wake()
            return job
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="章节已有新版本，请重新提交") from error
        except InvalidChapterStateError as error:
            raise HTTPException(status_code=409, detail="请先保存完整章纲再生成正文") from error
        except OriginalityGateBlockedError as error:
            raise HTTPException(status_code=409, detail="请先处理蓝图原创性检查") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置 AI 模型") from error
        except InvalidContextPacketError as error:
            raise HTTPException(status_code=409, detail="上下文已变化，请重新预览后确认") from error

    @application.get(
        "/api/jobs/{job_id}/chapter-draft-result",
        response_model=GenerationRun,
    )
    def get_ai_chapter_draft_job_result(job_id: UUID) -> GenerationRun:
        service: ChapterJobService = application.state.chapter_job_service
        try:
            return service.get_draft_result(str(job_id))
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="任务不存在") from error
        except (NotFoundError, TypeError, ValueError) as error:
            raise HTTPException(status_code=409, detail="正文任务尚无可用结果") from error

    @application.get("/api/projects", response_model=list[Project])
    def list_projects(
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> list[Project]:
        return repository.list_projects()

    @application.post(
        "/api/projects", response_model=Workspace, status_code=status.HTTP_201_CREATED
    )
    def create_project(
        body: CreateProjectRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> Workspace:
        return repository.create_project(body)

    @application.get(
        "/api/projects/{project_id}/director",
        response_model=DirectorPlanningSnapshot,
    )
    def get_director_snapshot(
        project_id: UUID,
        director: Annotated[DirectorRepository, Depends(get_director_repository)],
    ) -> DirectorPlanningSnapshot:
        try:
            return director.get_snapshot(str(project_id))
        except DirectorNotFoundError as error:
            raise HTTPException(status_code=404, detail="作品不存在") from error

    @application.patch(
        "/api/projects/{project_id}/director/book-blueprint",
        response_model=BookBlueprint,
    )
    def update_book_blueprint(
        project_id: UUID,
        body: UpdateBookBlueprintRequest,
        director: Annotated[DirectorRepository, Depends(get_director_repository)],
    ) -> BookBlueprint:
        try:
            return director.update_book_blueprint(str(project_id), body)
        except DirectorNotFoundError as error:
            raise HTTPException(status_code=404, detail="整书蓝图不存在") from error
        except StaleDirectorRevisionError as error:
            raise HTTPException(status_code=409, detail="整书蓝图已有新版本，请刷新") from error
        except InvalidDirectorChangeError as error:
            raise HTTPException(status_code=409, detail="整书蓝图变更与锁定状态冲突") from error

    @application.post(
        "/api/projects/{project_id}/director/regeneration-impact",
        response_model=DirectorRegenerationImpact,
    )
    def get_director_regeneration_impact(
        project_id: UUID,
        body: DirectorRegenerationImpactRequest,
        director: Annotated[DirectorRepository, Depends(get_director_repository)],
    ) -> DirectorRegenerationImpact:
        try:
            return regeneration_impact(
                director.require_book_blueprint(str(project_id)),
                body.target_field,
            )
        except DirectorNotFoundError as error:
            raise HTTPException(status_code=404, detail="整书蓝图不存在") from error

    @application.post(
        "/api/projects/{project_id}/director/startup-preview",
        response_model=DirectorOutboundPreview,
    )
    def preview_director_startup(
        project_id: UUID,
        body: DirectorStartupRequest,
        service: Annotated[DirectorService, Depends(get_director_service)],
    ) -> DirectorOutboundPreview:
        try:
            return service.preview_startup(str(project_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="作品不存在") from error
        except OriginalityGateBlockedError as error:
            raise HTTPException(status_code=409, detail="请先处理蓝图原创性检查") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置 AI 模型") from error

    @application.post(
        "/api/projects/{project_id}/director/startup-jobs",
        response_model=Job,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_director_startup(
        project_id: UUID,
        body: DirectorStartupRequest,
        service: Annotated[DirectorService, Depends(get_director_service)],
        jobs: Annotated[JobRepository, Depends(get_job_repository)],
    ) -> Job:
        try:
            job = service.submit_startup(str(project_id), body)
            get_job_runtime_from_repository(application, jobs).wake()
            return job
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="作品不存在") from error
        except OriginalityGateBlockedError as error:
            raise HTTPException(status_code=409, detail="请先处理蓝图原创性检查") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置 AI 模型") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail="请确认外发范围和费用上限") from error

    @application.get(
        "/api/jobs/{job_id}/director-startup-result",
        response_model=DirectorStartupProposalSet,
    )
    def get_director_startup_result(
        job_id: UUID,
        service: Annotated[DirectorService, Depends(get_director_service)],
    ) -> DirectorStartupProposalSet:
        try:
            return service.get_startup_result(str(job_id))
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="开书任务不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail="开书任务尚无可用候选") from error

    @application.post(
        "/api/projects/{project_id}/director/startup-selection",
        response_model=BookBlueprint,
    )
    def select_director_startup_candidate(
        project_id: UUID,
        body: SelectDirectorCandidateRequest,
        service: Annotated[DirectorService, Depends(get_director_service)],
    ) -> BookBlueprint:
        try:
            return service.select_startup_candidate(str(project_id), body)
        except (DirectorNotFoundError, JobNotFoundError) as error:
            raise HTTPException(status_code=404, detail="开书候选不存在") from error
        except StaleDirectorRevisionError as error:
            raise HTTPException(status_code=409, detail="整书蓝图已有新版本，请刷新") from error
        except InvalidDirectorChangeError as error:
            raise HTTPException(status_code=409, detail="已经选择过开书方向") from error

    @application.post(
        "/api/projects/{project_id}/director/expansion-preview",
        response_model=DirectorOutboundPreview,
    )
    def preview_director_expansion(
        project_id: UUID,
        body: DirectorExpansionRequest,
        service: Annotated[DirectorService, Depends(get_director_service)],
    ) -> DirectorOutboundPreview:
        try:
            return service.preview_expansion(str(project_id), body)
        except DirectorNotFoundError as error:
            raise HTTPException(status_code=404, detail="整书蓝图不存在") from error
        except StaleDirectorRevisionError as error:
            raise HTTPException(status_code=409, detail="整书蓝图已有新版本，请刷新") from error
        except OriginalityGateBlockedError as error:
            raise HTTPException(status_code=409, detail="请先处理蓝图原创性检查") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置 AI 模型") from error

    @application.post(
        "/api/projects/{project_id}/director/expansion-jobs",
        response_model=Job,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_director_expansion(
        project_id: UUID,
        body: DirectorExpansionRequest,
        service: Annotated[DirectorService, Depends(get_director_service)],
        jobs: Annotated[JobRepository, Depends(get_job_repository)],
    ) -> Job:
        try:
            job = service.submit_expansion(str(project_id), body)
            get_job_runtime_from_repository(application, jobs).wake()
            return job
        except DirectorNotFoundError as error:
            raise HTTPException(status_code=404, detail="整书蓝图不存在") from error
        except StaleDirectorRevisionError as error:
            raise HTTPException(status_code=409, detail="整书蓝图已有新版本，请刷新") from error
        except OriginalityGateBlockedError as error:
            raise HTTPException(status_code=409, detail="请先处理蓝图原创性检查") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置 AI 模型") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail="请确认外发范围和费用上限") from error

    @application.get(
        "/api/jobs/{job_id}/director-expansion-result",
        response_model=DirectorExpansionProposal,
    )
    def get_director_expansion_result(
        job_id: UUID,
        service: Annotated[DirectorService, Depends(get_director_service)],
    ) -> DirectorExpansionProposal:
        try:
            return service.get_expansion_result(str(job_id))
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="整书展开任务不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail="整书展开任务尚无可用候选") from error

    @application.post(
        "/api/projects/{project_id}/director/expansion-application",
        response_model=DirectorPlanningSnapshot,
    )
    def apply_director_expansion(
        project_id: UUID,
        body: ApplyDirectorProposalRequest,
        service: Annotated[DirectorService, Depends(get_director_service)],
    ) -> DirectorPlanningSnapshot:
        try:
            return service.apply_expansion(str(project_id), body)
        except (DirectorNotFoundError, JobNotFoundError) as error:
            raise HTTPException(status_code=404, detail="整书展开候选不存在") from error
        except StaleDirectorRevisionError as error:
            raise HTTPException(status_code=409, detail="整书蓝图已有新版本，请刷新") from error
        except InvalidDirectorChangeError as error:
            raise HTTPException(status_code=409, detail="计划与锁定字段冲突，请先处理") from error

    @application.post(
        "/api/projects/{project_id}/director/field-preview",
        response_model=DirectorOutboundPreview,
    )
    def preview_director_field(
        project_id: UUID,
        body: DirectorFieldRegenerationRequest,
        service: Annotated[DirectorService, Depends(get_director_service)],
    ) -> DirectorOutboundPreview:
        try:
            return service.preview_field_regeneration(str(project_id), body)
        except DirectorNotFoundError as error:
            raise HTTPException(status_code=404, detail="整书蓝图不存在") from error
        except StaleDirectorRevisionError as error:
            raise HTTPException(status_code=409, detail="整书蓝图已有新版本，请刷新") from error
        except OriginalityGateBlockedError as error:
            raise HTTPException(status_code=409, detail="请先处理蓝图原创性检查") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置 AI 模型") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail="目标字段已锁定") from error

    @application.post(
        "/api/projects/{project_id}/director/field-jobs",
        response_model=Job,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_director_field(
        project_id: UUID,
        body: DirectorFieldRegenerationRequest,
        service: Annotated[DirectorService, Depends(get_director_service)],
        jobs: Annotated[JobRepository, Depends(get_job_repository)],
    ) -> Job:
        try:
            job = service.submit_field_regeneration(str(project_id), body)
            get_job_runtime_from_repository(application, jobs).wake()
            return job
        except DirectorNotFoundError as error:
            raise HTTPException(status_code=404, detail="整书蓝图不存在") from error
        except StaleDirectorRevisionError as error:
            raise HTTPException(status_code=409, detail="整书蓝图已有新版本，请刷新") from error
        except OriginalityGateBlockedError as error:
            raise HTTPException(status_code=409, detail="请先处理蓝图原创性检查") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置 AI 模型") from error
        except ValueError as error:
            raise HTTPException(
                status_code=409, detail="请确认字段锁、外发范围和费用上限"
            ) from error

    @application.get(
        "/api/jobs/{job_id}/director-field-result",
        response_model=DirectorFieldProposal,
    )
    def get_director_field_result(
        job_id: UUID,
        service: Annotated[DirectorService, Depends(get_director_service)],
    ) -> DirectorFieldProposal:
        try:
            return service.get_field_result(str(job_id))
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="字段任务不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail="字段任务尚无可用候选") from error

    @application.post(
        "/api/projects/{project_id}/director/field-application",
        response_model=BookBlueprint,
    )
    def apply_director_field_result(
        project_id: UUID,
        body: ApplyDirectorProposalRequest,
        service: Annotated[DirectorService, Depends(get_director_service)],
    ) -> BookBlueprint:
        try:
            return service.apply_field_result(str(project_id), body)
        except (DirectorNotFoundError, JobNotFoundError) as error:
            raise HTTPException(status_code=404, detail="字段候选不存在") from error
        except StaleDirectorRevisionError as error:
            raise HTTPException(status_code=409, detail="整书蓝图已有新版本，请刷新") from error
        except InvalidDirectorChangeError as error:
            raise HTTPException(status_code=409, detail="字段候选与锁定状态冲突") from error

    @application.patch(
        "/api/projects/{project_id}/director/volume-plans/{plan_id}",
        response_model=VolumePlan,
    )
    def update_director_volume_plan(
        project_id: UUID,
        plan_id: UUID,
        body: UpdateVolumePlanRequest,
        director: Annotated[DirectorRepository, Depends(get_director_repository)],
    ) -> VolumePlan:
        try:
            return director.update_volume_plan(str(project_id), str(plan_id), body)
        except DirectorNotFoundError as error:
            raise HTTPException(status_code=404, detail="卷计划不存在") from error
        except StaleDirectorRevisionError as error:
            raise HTTPException(status_code=409, detail="卷计划已有新版本，请刷新") from error
        except InvalidDirectorChangeError as error:
            raise HTTPException(status_code=409, detail="卷计划已锁定") from error

    @application.patch(
        "/api/projects/{project_id}/director/rolling-plans/{plan_id}",
        response_model=RollingChapterPlan,
    )
    def update_director_rolling_plan(
        project_id: UUID,
        plan_id: UUID,
        body: UpdateRollingChapterPlanRequest,
        director: Annotated[DirectorRepository, Depends(get_director_repository)],
    ) -> RollingChapterPlan:
        try:
            return director.update_rolling_plan(str(project_id), str(plan_id), body)
        except DirectorNotFoundError as error:
            raise HTTPException(status_code=404, detail="滚动章纲不存在") from error
        except StaleDirectorRevisionError as error:
            raise HTTPException(status_code=409, detail="滚动章纲已有新版本，请刷新") from error
        except InvalidDirectorChangeError as error:
            raise HTTPException(status_code=409, detail="滚动章纲已锁定") from error

    @application.post(
        "/api/chapters/{chapter_id}/director-pipeline-preview",
        response_model=DirectorOutboundPreview,
    )
    def preview_director_chapter_pipeline(
        chapter_id: UUID,
        body: DirectorChapterPipelineRequest,
        service: Annotated[DirectorService, Depends(get_director_service)],
    ) -> DirectorOutboundPreview:
        try:
            return service.preview_chapter_pipeline(str(chapter_id), body)
        except (NotFoundError, DirectorNotFoundError) as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="章节已有新版本，请重新预览") from error
        except InvalidChapterStateError as error:
            raise HTTPException(status_code=409, detail="当前章节状态不允许 AI 流水线") from error
        except InvalidDirectorChangeError as error:
            raise HTTPException(status_code=409, detail="整书蓝图存在待联动复核字段") from error
        except OriginalityGateBlockedError as error:
            raise HTTPException(status_code=409, detail="请先处理蓝图原创性检查") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置 AI 模型") from error

    @application.post(
        "/api/chapters/{chapter_id}/director-pipeline-jobs",
        response_model=Job,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_director_chapter_pipeline(
        chapter_id: UUID,
        body: DirectorChapterPipelineRequest,
        service: Annotated[DirectorService, Depends(get_director_service)],
        jobs: Annotated[JobRepository, Depends(get_job_repository)],
    ) -> Job:
        try:
            job = service.submit_chapter_pipeline(str(chapter_id), body)
            get_job_runtime_from_repository(application, jobs).wake()
            return job
        except (NotFoundError, DirectorNotFoundError) as error:
            raise HTTPException(status_code=404, detail="章节或父任务不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="章节已有新版本，请重新提交") from error
        except InvalidChapterStateError as error:
            raise HTTPException(status_code=409, detail="当前章节状态不允许 AI 流水线") from error
        except InvalidDirectorChangeError as error:
            raise HTTPException(status_code=409, detail="整书蓝图存在待联动复核字段") from error
        except OriginalityGateBlockedError as error:
            raise HTTPException(status_code=409, detail="请先处理蓝图原创性检查") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置 AI 模型") from error
        except ValueError as error:
            raise HTTPException(
                status_code=409, detail="请确认外发范围、费用上限或重跑阶段"
            ) from error

    @application.get(
        "/api/jobs/{job_id}/director-pipeline-result",
        response_model=DirectorChapterPipelineResult,
    )
    def get_director_chapter_pipeline_result(
        job_id: UUID,
        service: Annotated[DirectorService, Depends(get_director_service)],
    ) -> DirectorChapterPipelineResult:
        try:
            return service.get_chapter_pipeline_result(str(job_id))
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="单章流水线任务不存在") from error
        except (ValueError, StaleRevisionError) as error:
            raise HTTPException(
                status_code=409, detail="单章流水线尚无可用候选或章节已更新"
            ) from error

    @application.get("/api/projects/{project_id}/export")
    def export_project(
        project_id: UUID,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
        include_reference_assets: bool = False,
    ) -> dict[str, object]:
        try:
            return ProjectArchiveService(repository.database).export_project(
                str(project_id),
                include_reference_assets=include_reference_assets,
            )
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="项目不存在") from error

    @application.get(
        "/api/projects/{project_id}/manuscript-export",
        response_model=ManuscriptExport,
    )
    def export_manuscript_markdown(
        project_id: UUID,
        service: Annotated[ManuscriptService, Depends(get_manuscript_service)],
    ) -> ManuscriptExport:
        try:
            return service.export_markdown(str(project_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="项目不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail="作品没有可导出的正文") from error

    @application.get("/api/projects/{project_id}/manuscript-export/{export_format}")
    def export_manuscript_binary(
        project_id: UUID,
        export_format: Literal["docx", "epub"],
        service: Annotated[ManuscriptService, Depends(get_manuscript_service)],
    ) -> Response:
        try:
            exported = service.export_binary(str(project_id), export_format)
            return Response(
                content=exported.payload,
                media_type=exported.media_type,
                headers={
                    "Content-Disposition": f"attachment; filename*=UTF-8''{quote(exported.filename)}",
                    "X-Content-SHA256": exported.content_sha256,
                    "X-Manuscript-Volumes": str(exported.volume_count),
                    "X-Manuscript-Chapters": str(exported.chapter_count),
                },
            )
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="项目不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail="作品没有可导出的正文") from error

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
            project_id = ProjectArchiveService(repository.database).import_project(
                bytes(raw_archive)
            )
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

    @application.get(
        "/api/reference-library/works",
        response_model=list[ReferenceWork],
    )
    def list_global_reference_works(
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> list[ReferenceWork]:
        return repository.list_reference_works()

    @application.post(
        "/api/reference-library/works",
        response_model=ReferenceWork,
        status_code=status.HTTP_201_CREATED,
    )
    def import_global_reference_work(
        body: ImportReferenceWorkRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> ReferenceWork:
        try:
            return repository.import_global_reference_work(body)
        except InvalidReferenceImportError as error:
            raise HTTPException(
                status_code=415,
                detail="当前只支持 UTF-8 TXT 或 Markdown 参考作品",
            ) from error

    async def read_reference_upload(request: Request) -> bytes:
        content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
        if content_type not in {
            "application/octet-stream",
            "application/pdf",
            "application/epub+zip",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/plain",
            "text/markdown",
        }:
            raise HTTPException(status_code=415, detail="参考文件类型不受支持")
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_PDF_FILE_BYTES:
                    raise HTTPException(status_code=413, detail="参考文件超过安全体积上限")
            except ValueError as error:
                raise HTTPException(status_code=400, detail="参考文件请求无效") from error
        payload = bytearray()
        async for chunk in request.stream():
            payload.extend(chunk)
            if len(payload) > MAX_PDF_FILE_BYTES:
                raise HTTPException(status_code=413, detail="参考文件超过安全体积上限")
        return bytes(payload)

    def parse_safe_reference(source_filename: str, payload: bytes) -> ParsedReferenceFile:
        try:
            return parse_reference_file(source_filename, payload)
        except UnsafeImportError as error:
            code = str(error)
            if code == "file_too_large":
                raise HTTPException(status_code=413, detail="参考文件超过安全体积上限") from error
            if code in {"unsupported_format", "invalid_pdf_magic"}:
                raise HTTPException(status_code=415, detail="参考文件格式与内容不匹配") from error
            messages = {
                "encrypted_pdf": "加密 PDF 不允许导入",
                "active_pdf_content": "包含脚本或主动内容的 PDF 不允许导入",
                "empty_pdf_text": "PDF 没有可提取的正文文本",
                "pdf_page_limit": "PDF 页数超过安全上限",
                "pdf_expansion_limit": "PDF 解压后的文本量异常",
                "unsupported_or_mixed_encoding": "文本编码混杂或不受支持",
            }
            raise HTTPException(
                status_code=422,
                detail=messages.get(code, "参考文件无法安全解析"),
            ) from error

    @application.post(
        "/api/reference-library/file-previews",
        response_model=ReferenceFilePreview,
    )
    async def preview_reference_file(
        request: Request,
        source_filename: Annotated[str, Query(min_length=1, max_length=255)],
    ) -> ReferenceFilePreview:
        parsed = parse_safe_reference(source_filename, await read_reference_upload(request))
        return ReferenceFilePreview(
            source_filename=source_filename,
            source_format=ReferenceFormat(parsed.source_format),
            source_encoding=parsed.source_encoding,
            encoding_confidence=parsed.encoding_confidence,
            import_state=parsed.import_state,
            source_sha256=parsed.source_sha256,
            content_sha256=parsed.content_sha256,
            total_characters=len(parsed.content),
            page_count=parsed.page_count,
            preview=parsed.preview,
            warnings=list(parsed.warnings),
            source_spans=[
                ReferenceSourceSpan(
                    page_number=span.page_number,
                    start_char=span.start_char,
                    end_char=span.end_char,
                )
                for span in parsed.spans
            ],
        )

    @application.post(
        "/api/manuscript-imports/preview",
        response_model=ManuscriptImportPreview,
    )
    async def preview_manuscript_import(
        request: Request,
        source_filename: Annotated[str, Query(min_length=1, max_length=255)],
    ) -> ManuscriptImportPreview:
        try:
            return preview_manuscript_file(
                source_filename,
                await read_reference_upload(request),
            )
        except UnsafeImportError as error:
            code = str(error)
            if code == "file_too_large":
                raise HTTPException(status_code=413, detail="稿件文件不能超过 20 MiB") from error
            if code in {"unsupported_format", "unsupported_manuscript_format"}:
                raise HTTPException(
                    status_code=415, detail="请选择 TXT、Markdown、DOCX 或 EPUB 稿件"
                ) from error
            messages = {
                "empty_content": "稿件没有可导入的正文",
                "unsupported_or_mixed_encoding": "稿件编码混杂或不受支持",
                "null_byte": "稿件包含不安全的空字节",
                "unsafe_control_characters": "稿件包含过多控制字符",
                "active_docx_content": "DOCX 包含宏、OLE 或嵌入对象，已拒绝",
                "external_docx_relationship": "DOCX 包含外部链接或模板，已拒绝",
                "active_epub_content": "EPUB 包含脚本或远程资源，已拒绝",
                "encrypted_zip": "加密的 DOCX/EPUB 不允许导入",
                "zip_unsafe_path": "文件包含越界路径，已拒绝",
                "zip_expanded_limit": "文件包解压后超过安全上限",
                "zip_expansion_ratio": "文件包压缩比异常，已拒绝",
            }
            raise HTTPException(
                status_code=422,
                detail=messages.get(code, "稿件无法安全解析"),
            ) from error

    @application.post(
        "/api/manuscript-imports",
        response_model=Workspace,
        status_code=status.HTTP_201_CREATED,
    )
    def confirm_manuscript_import(
        body: ConfirmManuscriptImportRequest,
        service: Annotated[ManuscriptService, Depends(get_manuscript_service)],
    ) -> Workspace:
        return service.confirm_import(body)

    @application.post(
        "/api/reference-library/file-imports",
        response_model=ReferenceWork,
        status_code=status.HTTP_201_CREATED,
    )
    async def import_reference_file(
        request: Request,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
        source_filename: Annotated[str, Query(min_length=1, max_length=255)],
        title: Annotated[str, Query(min_length=1, max_length=200)],
        rights_basis: ReferenceRightsBasis,
        expected_source_sha256: Annotated[str, Query(min_length=64, max_length=64)],
        segment_target_characters: int = 500_000,
        confirm_preview: bool = False,
        confirm_uncertain_encoding: bool = False,
        project_id: UUID | None = None,
    ) -> ReferenceWork:
        if not 100_000 <= segment_target_characters <= 1_000_000:
            raise HTTPException(status_code=422, detail="参考区段大小无效")
        if not confirm_preview:
            raise HTTPException(status_code=409, detail="请先查看文件预览并确认")
        if project_id is not None and not repository.project_exists(str(project_id)):
            raise HTTPException(status_code=404, detail="作品不存在")
        parsed = parse_safe_reference(source_filename, await read_reference_upload(request))
        if parsed.source_sha256 != expected_source_sha256.lower():
            raise HTTPException(status_code=409, detail="文件已变化，请重新预览")
        if parsed.import_state == "needs_review" and not confirm_uncertain_encoding:
            raise HTTPException(status_code=409, detail="编码置信度不足，请确认预览文本")
        try:
            imported = repository.import_parsed_reference_work(
                title=title.strip(),
                source_filename=source_filename,
                rights_basis=rights_basis,
                segment_target_characters=segment_target_characters,
                parsed=parsed,
            )
            return (
                repository.link_reference_work(str(project_id), imported.id)
                if project_id is not None
                else imported
            )
        except (InvalidReferenceImportError, ValueError) as error:
            raise HTTPException(status_code=422, detail="参考文件导入参数无效") from error

    @application.get(
        "/api/source-library/documents",
        response_model=list[SourceDocument],
    )
    def list_source_documents(
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> list[SourceDocument]:
        return repository.list_source_documents()

    @application.post(
        "/api/source-library/file-imports",
        response_model=SourceCard,
        status_code=status.HTTP_201_CREATED,
    )
    async def import_reality_source_file(
        request: Request,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
        project_id: UUID,
        source_filename: Annotated[str, Query(min_length=1, max_length=255)],
        title: Annotated[str, Query(min_length=1, max_length=200)],
        source_kind: SourceKind,
        source_reference: Annotated[str, Query(min_length=1, max_length=1000)],
        applicable_year_start: int,
        applicable_year_end: int,
        expected_source_sha256: Annotated[str, Query(min_length=64, max_length=64)],
        confidence: SourceConfidence = SourceConfidence.MEDIUM,
        source_date: Annotated[str | None, Query(max_length=40)] = None,
        confirm_preview: bool = False,
        confirm_uncertain_encoding: bool = False,
    ) -> SourceCard:
        if not repository.project_exists(str(project_id)):
            raise HTTPException(status_code=404, detail="作品不存在")
        if not confirm_preview:
            raise HTTPException(status_code=409, detail="请先查看文件预览并确认")
        try:
            card_request = CreateSourceCardRequest(
                source_kind=source_kind,
                title=title,
                source_reference=source_reference,
                applicable_year_start=applicable_year_start,
                applicable_year_end=applicable_year_end,
                confidence=confidence,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail="现实资料参数无效") from error
        parsed = parse_safe_reference(source_filename, await read_reference_upload(request))
        if parsed.source_sha256 != expected_source_sha256.lower():
            raise HTTPException(status_code=409, detail="文件已变化，请重新预览")
        if parsed.import_state == "needs_review" and not confirm_uncertain_encoding:
            raise HTTPException(status_code=409, detail="编码置信度不足，请确认预览文本")
        document = repository.import_source_document(
            title=title.strip(),
            source_filename=source_filename,
            parsed=parsed,
        )
        return repository.apply_source_document(
            str(project_id),
            document.id,
            card_request,
            source_date=source_date,
        )

    @application.post(
        "/api/projects/{project_id}/source-documents/{document_id}/cards",
        response_model=SourceCard,
        status_code=status.HTTP_201_CREATED,
    )
    def apply_existing_source_document(
        project_id: UUID,
        document_id: UUID,
        body: CreateSourceCardRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
        source_date: Annotated[str | None, Query(max_length=40)] = None,
    ) -> SourceCard:
        try:
            return repository.apply_source_document(
                str(project_id), str(document_id), body, source_date=source_date
            )
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="作品或现实资料不存在") from error

    @application.delete("/api/source-library/documents/{document_id}")
    def delete_source_document(
        document_id: UUID,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
        confirm_purge: bool = False,
    ) -> dict[str, int]:
        if not confirm_purge:
            raise HTTPException(status_code=409, detail="请确认清理现实资料原文")
        try:
            impacted_cards = repository.delete_source_document(str(document_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="现实资料不存在") from error
        return {"affected_cards": impacted_cards}

    @application.post(
        "/api/projects/{project_id}/reference-works/{work_id}",
        response_model=ReferenceWork,
    )
    def link_global_reference_work(
        project_id: UUID,
        work_id: UUID,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> ReferenceWork:
        try:
            return repository.link_reference_work(str(project_id), str(work_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="作品或参考资产不存在") from error

    @application.delete(
        "/api/projects/{project_id}/reference-works/{work_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def unlink_global_reference_work(
        project_id: UUID,
        work_id: UUID,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> Response:
        try:
            repository.unlink_reference_work(str(project_id), str(work_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="作品未关联该参考资产") from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.post(
        "/api/projects/{project_id}/reference-analysis-jobs",
        response_model=Job,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_reference_analysis_job(
        project_id: UUID,
        body: ReferenceSynthesisRequest,
    ) -> Job:
        service: ReferenceJobService = application.state.reference_job_service
        try:
            job = service.submit(str(project_id), body)
            application.state.job_runtime.wake()
            return job
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="作品或参考区段不存在") from error
        except InvalidReferenceSelectionError as error:
            messages = {
                "external_processing_not_confirmed": "必须确认允许把选中区段发送给当前 AI",
                "multiple_works_required": "至少选择两本不同作品的区段",
                "selection_too_large": "单次最多处理 200 万字参考内容",
                "missing_or_cross_project_segment": "选择中包含无效参考区段",
            }
            raise HTTPException(
                status_code=400,
                detail=messages.get(str(error), "参考区段选择无效"),
            ) from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置 AI") from error

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
            raise HTTPException(
                status_code=409, detail="蓝图无法应用，请检查来源或是否已应用"
            ) from error

    @application.get(
        "/api/originality-reports/{report_id}",
        response_model=OriginalityReport,
    )
    def get_originality_report(
        report_id: UUID,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> OriginalityReport:
        try:
            return repository.get_originality_report(str(report_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="原创性报告不存在") from error

    @application.post(
        "/api/projects/{project_id}/reference-blueprints/{application_id}/scene-originality-checks",
        response_model=SceneOriginalityCheck,
    )
    def get_or_run_scene_originality_check(
        project_id: UUID,
        application_id: UUID,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> SceneOriginalityCheck:
        try:
            return repository.get_latest_scene_originality_check(
                str(project_id),
                str(application_id),
            )
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="场景原创性报告不存在") from error
        except InvalidReferenceApplicationError as error:
            raise HTTPException(
                status_code=409,
                detail="蓝图缺少可重检的来源或旧版报告，请重新应用模式卡",
            ) from error

    @application.get(
        "/api/scene-originality-checks/{check_id}",
        response_model=SceneOriginalityCheck,
    )
    def get_scene_originality_check(
        check_id: UUID,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> SceneOriginalityCheck:
        try:
            return repository.get_scene_originality_check(str(check_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="场景原创性报告不存在") from error

    @application.patch(
        "/api/projects/{project_id}/reference-blueprints/{application_id}",
        response_model=ReferencePatternApplication,
    )
    def update_reference_blueprint(
        project_id: UUID,
        application_id: UUID,
        body: UpdateReferenceBlueprintRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> ReferencePatternApplication:
        try:
            return repository.update_reference_blueprint(str(project_id), str(application_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="蓝图不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="蓝图已有新版本，请刷新后再修改") from error
        except InvalidReferenceApplicationError as error:
            raise HTTPException(
                status_code=409, detail="蓝图修改不合法，请检查变更维度和锁定状态"
            ) from error

    @application.post(
        "/api/projects/{project_id}/reference-blueprints/{application_id}/originality-acknowledgements",
        response_model=ReferencePatternApplication,
    )
    def acknowledge_originality_report(
        project_id: UUID,
        application_id: UUID,
        body: AcknowledgeOriginalityReportRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> ReferencePatternApplication:
        try:
            return repository.acknowledge_originality_report(
                str(project_id), str(application_id), body
            )
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="蓝图不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="蓝图已有新版本，请刷新后再处理") from error
        except InvalidReferenceApplicationError as error:
            raise HTTPException(
                status_code=409, detail="当前报告不能确认，高风险蓝图必须先修改"
            ) from error

    @application.post(
        "/api/projects/{project_id}/reference-blueprints/{application_id}/scene-originality-acknowledgements",
        response_model=ReferencePatternApplication,
    )
    def acknowledge_scene_originality_check(
        project_id: UUID,
        application_id: UUID,
        body: AcknowledgeOriginalityReportRequest,
        repository: Annotated[ProjectRepository, Depends(get_repository)],
    ) -> ReferencePatternApplication:
        try:
            return repository.acknowledge_scene_originality_check(
                str(project_id),
                str(application_id),
                body,
            )
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="蓝图不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="蓝图已有新版本，请刷新后再处理") from error
        except InvalidReferenceApplicationError as error:
            raise HTTPException(
                status_code=409,
                detail="场景报告尚未查看、不是中风险，或高风险必须先修改",
            ) from error

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
        "/api/projects/{project_id}/comic-projects",
        response_model=ComicWorkspace,
        status_code=status.HTTP_201_CREATED,
    )
    def create_comic_project(
        project_id: UUID,
        body: CreateComicProjectRequest,
    ) -> ComicWorkspace:
        try:
            return application.state.comic_drama_service.create_project(str(project_id), body)
        except ComicDramaNotFoundError as error:
            raise HTTPException(status_code=404, detail="作品不存在") from error
        except InvalidComicSourceError as error:
            raise HTTPException(status_code=422, detail="漫剧来源章节无效") from error

    @application.get(
        "/api/projects/{project_id}/comic-projects",
        response_model=list[ComicProject],
    )
    def list_comic_projects(project_id: UUID) -> list[ComicProject]:
        try:
            return application.state.comic_drama_service.list_projects(str(project_id))
        except ComicDramaNotFoundError as error:
            raise HTTPException(status_code=404, detail="作品不存在") from error

    @application.get(
        "/api/comic-projects/{comic_project_id}",
        response_model=ComicWorkspace,
    )
    def get_comic_project(comic_project_id: UUID) -> ComicWorkspace:
        try:
            return application.state.comic_drama_service.get_workspace(str(comic_project_id))
        except ComicDramaNotFoundError as error:
            raise HTTPException(status_code=404, detail="漫剧项目不存在") from error

    @application.get(
        "/api/comic-projects/{comic_project_id}/delete-impact",
        response_model=ComicDeleteImpact,
    )
    def get_comic_project_delete_impact(comic_project_id: UUID) -> ComicDeleteImpact:
        try:
            return application.state.comic_drama_service.delete_impact(str(comic_project_id))
        except ComicDramaNotFoundError as error:
            raise HTTPException(status_code=404, detail="漫剧项目不存在") from error

    @application.post(
        "/api/comic-projects/{comic_project_id}/season-plan/preview",
        response_model=ComicAiPreview,
    )
    def preview_comic_season_plan(
        comic_project_id: UUID,
        body: ComicSeasonPlanRequest,
    ) -> ComicAiPreview:
        try:
            return application.state.comic_drama_service.preview_season_plan(
                str(comic_project_id), body
            )
        except ComicDramaNotFoundError as error:
            raise HTTPException(status_code=404, detail="漫剧项目不存在") from error
        except ComicStateConflictError as error:
            raise HTTPException(status_code=409, detail="漫剧来源已变化，请重新创建项目") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置漫剧 AI 模型线路") from error

    @application.post(
        "/api/comic-projects/{comic_project_id}/season-plan",
        response_model=ComicSeasonSubmission,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_comic_season_plan(
        comic_project_id: UUID,
        body: SubmitComicSeasonPlanRequest,
    ) -> ComicSeasonSubmission:
        try:
            return application.state.comic_drama_service.submit_season_plan(
                str(comic_project_id), body
            )
        except ComicDramaNotFoundError as error:
            raise HTTPException(status_code=404, detail="漫剧项目不存在") from error
        except ComicStateConflictError as error:
            details = {
                "external_processing_not_confirmed": "请先确认外发范围与费用",
                "estimated_cost_exceeds_limit": "预计费用超过本次上限",
                "comic_source_changed": "漫剧来源已变化，请重新预览",
            }
            raise HTTPException(status_code=409, detail=details.get(str(error), "漫剧状态冲突"))
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置漫剧 AI 模型线路") from error

    @application.post(
        "/api/comic-projects/{comic_project_id}/season-plan/adopt",
        response_model=ComicWorkspace,
    )
    def adopt_comic_season_plan(
        comic_project_id: UUID,
        body: AdoptComicSeasonRequest,
    ) -> ComicWorkspace:
        try:
            return application.state.comic_drama_service.adopt_season(
                str(comic_project_id), body
            )
        except ComicDramaNotFoundError as error:
            raise HTTPException(status_code=404, detail="漫剧项目或候选不存在") from error
        except ComicStateConflictError as error:
            raise HTTPException(status_code=409, detail="季方案状态或版本已变化") from error

    @application.post(
        "/api/comic-episodes/{episode_id}/outline/review",
        response_model=ComicWorkspace,
    )
    def review_comic_episode_outline(
        episode_id: UUID,
        body: ReviewComicEpisodeRequest,
    ) -> ComicWorkspace:
        try:
            return application.state.comic_drama_service.review_episode_outline(
                str(episode_id), body
            )
        except ComicDramaNotFoundError as error:
            raise HTTPException(status_code=404, detail="漫剧剧集不存在") from error
        except ComicStateConflictError as error:
            raise HTTPException(status_code=409, detail="分集大纲状态或版本已变化") from error

    @application.post(
        "/api/comic-episodes/{episode_id}/script/preview",
        response_model=ComicAiPreview,
    )
    def preview_comic_episode_script(
        episode_id: UUID,
        body: ComicEpisodeScriptRequest,
    ) -> ComicAiPreview:
        try:
            return application.state.comic_drama_service.preview_episode_script(
                str(episode_id), body
            )
        except ComicDramaNotFoundError as error:
            raise HTTPException(status_code=404, detail="漫剧剧集不存在") from error
        except ComicStateConflictError as error:
            raise HTTPException(status_code=409, detail="请先批准本集大纲或刷新来源") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置漫剧 AI 模型线路") from error

    @application.post(
        "/api/comic-episodes/{episode_id}/script",
        response_model=ComicEpisodeSubmission,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_comic_episode_script(
        episode_id: UUID,
        body: SubmitComicEpisodeScriptRequest,
    ) -> ComicEpisodeSubmission:
        try:
            return application.state.comic_drama_service.submit_episode_script(
                str(episode_id), body
            )
        except ComicDramaNotFoundError as error:
            raise HTTPException(status_code=404, detail="漫剧剧集不存在") from error
        except ComicStateConflictError as error:
            raise HTTPException(status_code=409, detail="剧本生成条件或确认信息已变化") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置漫剧 AI 模型线路") from error

    @application.post(
        "/api/comic-episodes/{episode_id}/script/review",
        response_model=ComicWorkspace,
    )
    def review_comic_episode_script(
        episode_id: UUID,
        body: ReviewComicEpisodeRequest,
    ) -> ComicWorkspace:
        try:
            return application.state.comic_drama_service.review_episode_script(
                str(episode_id), body
            )
        except ComicDramaNotFoundError as error:
            raise HTTPException(status_code=404, detail="漫剧剧集不存在") from error
        except ComicStateConflictError as error:
            raise HTTPException(status_code=409, detail="剧本候选状态或版本已变化") from error

    @application.get(
        "/api/comic-projects/{comic_project_id}/audit",
        response_model=list[ComicAuditIssue],
    )
    def audit_comic_project(comic_project_id: UUID) -> list[ComicAuditIssue]:
        try:
            return application.state.comic_drama_service.audit(str(comic_project_id))
        except ComicDramaNotFoundError as error:
            raise HTTPException(status_code=404, detail="漫剧项目不存在") from error

    @application.get(
        "/api/comic-projects/{comic_project_id}/assets",
        response_model=list[ComicAsset],
    )
    def list_comic_assets(comic_project_id: UUID) -> list[ComicAsset]:
        try:
            return application.state.comic_drama_service.assets(str(comic_project_id))
        except ComicDramaNotFoundError as error:
            raise HTTPException(status_code=404, detail="漫剧项目不存在") from error

    @application.get("/api/comic-projects/{comic_project_id}/production-package")
    def get_comic_production_package(comic_project_id: UUID) -> dict[str, object]:
        try:
            return application.state.comic_drama_service.production_package(
                str(comic_project_id)
            )
        except ComicDramaNotFoundError as error:
            raise HTTPException(status_code=404, detail="漫剧项目不存在") from error

    @application.get("/api/comic-projects/{comic_project_id}/export")
    def export_comic_production_package(
        comic_project_id: UUID,
        format: Literal["json", "markdown", "docx"] = Query(default="json"),
    ) -> Response:
        try:
            exported = application.state.comic_drama_service.export_production_package(
                str(comic_project_id), format
            )
        except ComicDramaNotFoundError as error:
            raise HTTPException(status_code=404, detail="漫剧项目不存在") from error
        return Response(
            content=exported.payload,
            media_type=exported.media_type,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(exported.filename)}",
                "X-Content-SHA256": exported.content_sha256,
                "Cache-Control": "no-store",
            },
        )

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
        "/api/projects/{project_id}/directory-nodes",
        response_model=WorkspaceSummary,
        status_code=status.HTTP_201_CREATED,
    )
    def create_directory_node(
        project_id: UUID,
        body: CreateDirectoryNodeRequest,
        service: Annotated[DirectoryService, Depends(get_directory_service)],
    ) -> WorkspaceSummary:
        try:
            return service.create_node(str(project_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="作品或父级目录不存在") from error
        except DirectoryConflictError as error:
            raise HTTPException(status_code=409, detail="目录层级不允许此操作") from error

    @application.patch(
        "/api/directory-nodes/{node_kind}/{node_id}",
        response_model=WorkspaceSummary,
    )
    def rename_directory_node(
        node_kind: Literal["volume", "chapter", "scene"],
        node_id: UUID,
        body: RenameDirectoryNodeRequest,
        service: Annotated[DirectoryService, Depends(get_directory_service)],
    ) -> WorkspaceSummary:
        try:
            return service.rename_node(node_kind, str(node_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="目录节点不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="目录节点已有新版本") from error

    @application.post(
        "/api/directory-nodes/{node_kind}/{node_id}/move",
        response_model=WorkspaceSummary,
    )
    def move_directory_node(
        node_kind: Literal["volume", "chapter", "scene"],
        node_id: UUID,
        body: MoveDirectoryNodeRequest,
        service: Annotated[DirectoryService, Depends(get_directory_service)],
    ) -> WorkspaceSummary:
        try:
            return service.move_node(node_kind, str(node_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="目录节点或目标父级不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="目录节点已有新版本") from error
        except DirectoryConflictError as error:
            raise HTTPException(status_code=409, detail="移动目标不在同一层级") from error

    @application.get(
        "/api/directory-nodes/{node_kind}/{node_id}/delete-impact",
        response_model=DirectoryDeleteImpact,
    )
    def get_directory_delete_impact(
        node_kind: Literal["volume", "chapter", "scene"],
        node_id: UUID,
        service: Annotated[DirectoryService, Depends(get_directory_service)],
    ) -> DirectoryDeleteImpact:
        try:
            return service.delete_impact(node_kind, str(node_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="目录节点不存在") from error

    @application.delete(
        "/api/directory-nodes/{node_kind}/{node_id}",
        response_model=WorkspaceSummary,
    )
    def delete_directory_node(
        node_kind: Literal["volume", "chapter", "scene"],
        node_id: UUID,
        body: DeleteDirectoryNodeRequest,
        service: Annotated[DirectoryService, Depends(get_directory_service)],
    ) -> WorkspaceSummary:
        try:
            return service.delete_node(node_kind, str(node_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="目录节点不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="目录节点已有新版本") from error
        except DirectoryConfirmationRequiredError as error:
            raise HTTPException(status_code=409, detail="请先查看影响并确认删除") from error
        except DirectoryConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get(
        "/api/projects/{project_id}/directory-events",
        response_model=list[DirectoryEvent],
    )
    def list_directory_events(
        project_id: UUID,
        service: Annotated[DirectoryService, Depends(get_directory_service)],
    ) -> list[DirectoryEvent]:
        return service.list_events(str(project_id))

    @application.post(
        "/api/projects/{project_id}/directory-events/undo",
        response_model=WorkspaceSummary,
    )
    def undo_directory_event(
        project_id: UUID,
        service: Annotated[DirectoryService, Depends(get_directory_service)],
    ) -> WorkspaceSummary:
        try:
            return service.undo_latest(str(project_id))
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="没有可撤销的目录操作") from error
        except DirectoryConflictError as error:
            raise HTTPException(status_code=409, detail="目录已发生后续修改，不能撤销") from error

    @application.get(
        "/api/projects/{project_id}/serial-dashboard",
        response_model=SerialDashboard,
    )
    def get_serial_dashboard(
        project_id: UUID,
        service: Annotated[SerialService, Depends(get_serial_service)],
        goal_date: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
    ) -> SerialDashboard:
        try:
            return service.dashboard(str(project_id), goal_date)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="作品不存在") from error

    @application.put(
        "/api/projects/{project_id}/serial-goals/{goal_date}",
        response_model=SerialDashboard,
    )
    def set_serial_daily_goal(
        project_id: UUID,
        goal_date: Annotated[str, PathParam(pattern=r"^\d{4}-\d{2}-\d{2}$")],
        body: SetSerialDailyGoalRequest,
        service: Annotated[SerialService, Depends(get_serial_service)],
    ) -> SerialDashboard:
        try:
            return service.set_goal(str(project_id), goal_date, body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="作品不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="日更目标已有新版本") from error

    @application.get(
        "/api/projects/{project_id}/search",
        response_model=list[WorkspaceSearchResult],
    )
    def search_workspace(
        project_id: UUID,
        query: Annotated[str, Query(alias="q", min_length=1, max_length=100)],
        service: Annotated[SerialService, Depends(get_serial_service)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> list[WorkspaceSearchResult]:
        try:
            return service.search(str(project_id), query, limit)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="作品不存在") from error

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
            raise HTTPException(status_code=400, detail="未来或先验知识的年份不能早于作品起始纪年") from error

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

    @application.get(
        "/api/chapters/{chapter_id}/versions",
        response_model=list[ChapterVersion],
    )
    def list_chapter_versions(
        chapter_id: UUID,
        reviews: Annotated[ReviewRepository, Depends(get_review_repository)],
    ) -> list[ChapterVersion]:
        try:
            return reviews.list_chapter_versions(str(chapter_id))
        except ReviewNotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error

    @application.post(
        "/api/chapters/{chapter_id}/versions/{version_id}/rollback",
        response_model=Chapter,
    )
    def rollback_chapter_version(
        chapter_id: UUID,
        version_id: UUID,
        body: RollbackChapterVersionRequest,
        reviews: Annotated[ReviewRepository, Depends(get_review_repository)],
    ) -> Chapter:
        try:
            return reviews.rollback_chapter_version(str(chapter_id), str(version_id), body)
        except ReviewNotFoundError as error:
            raise HTTPException(status_code=404, detail="章节版本不存在") from error
        except StaleReviewRevisionError as error:
            raise HTTPException(status_code=409, detail="正文已有新版本，未执行回滚") from error

    @application.post(
        "/api/chapters/{chapter_id}/review-preview",
        response_model=ReviewOutboundPreview,
    )
    def preview_chapter_review(
        chapter_id: UUID,
        body: ReviewChapterRequest,
        service: Annotated[ReviewService, Depends(get_review_service)],
    ) -> ReviewOutboundPreview:
        try:
            return service.preview(str(chapter_id), body)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="正文已有新版本，请重新预览") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置审校模型线路") from error

    @application.post(
        "/api/chapters/{chapter_id}/review-jobs",
        response_model=Job,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_chapter_review(
        chapter_id: UUID,
        body: ReviewChapterRequest,
        service: Annotated[ReviewService, Depends(get_review_service)],
        jobs: Annotated[JobRepository, Depends(get_job_repository)],
    ) -> Job:
        try:
            job = service.submit(str(chapter_id), body)
            get_job_runtime_from_repository(application, jobs).wake()
            return job
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="父审校任务不存在") from error
        except StaleRevisionError as error:
            raise HTTPException(status_code=409, detail="正文已有新版本，请重新预览") from error
        except AiNotConfiguredError as error:
            raise HTTPException(status_code=409, detail="请先配置审校模型线路") from error
        except ValueError as error:
            messages = {
                "external_processing_not_confirmed": "请先确认本次审校的外发范围",
                "estimated_cost_exceeds_limit": "预计费用超过本次上限",
                "review_parent_mismatch": "父审校任务与当前章节不匹配",
            }
            raise HTTPException(
                status_code=409,
                detail=messages.get(str(error), "当前审校请求无法提交"),
            ) from error

    @application.get(
        "/api/jobs/{job_id}/review-result",
        response_model=ReviewJobResult,
    )
    def get_chapter_review_result(
        job_id: UUID,
        service: Annotated[ReviewService, Depends(get_review_service)],
    ) -> ReviewJobResult:
        try:
            return service.get_result(str(job_id))
        except (JobNotFoundError, ValueError) as error:
            raise HTTPException(status_code=404, detail="审校结果不存在") from error

    @application.get(
        "/api/chapters/{chapter_id}/review-findings",
        response_model=list[ReviewFinding],
    )
    def list_review_findings(
        chapter_id: UUID,
        reviews: Annotated[ReviewRepository, Depends(get_review_repository)],
        chapter_revision: int | None = Query(default=None, ge=0),
    ) -> list[ReviewFinding]:
        try:
            return reviews.list_findings(str(chapter_id), chapter_revision=chapter_revision)
        except ReviewNotFoundError as error:
            raise HTTPException(status_code=404, detail="章节不存在") from error

    @application.get(
        "/api/chapters/{chapter_id}/text-change-sets",
        response_model=list[TextChangeSet],
    )
    def list_text_change_sets(
        chapter_id: UUID,
        reviews: Annotated[ReviewRepository, Depends(get_review_repository)],
    ) -> list[TextChangeSet]:
        return reviews.list_text_change_sets(str(chapter_id))

    @application.post(
        "/api/chapters/{chapter_id}/text-change-sets",
        response_model=TextChangeSet,
        status_code=status.HTTP_201_CREATED,
    )
    def create_text_change_set(
        chapter_id: UUID,
        body: CreateTextChangeSetRequest,
        reviews: Annotated[ReviewRepository, Depends(get_review_repository)],
    ) -> TextChangeSet:
        try:
            return reviews.create_text_change_set(str(chapter_id), body)
        except ReviewNotFoundError as error:
            raise HTTPException(status_code=404, detail="章节或审校建议不存在") from error
        except InvalidTextChangeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post(
        "/api/text-change-sets/{change_set_id}/apply",
        response_model=Chapter,
    )
    def apply_text_change_set(
        change_set_id: UUID,
        body: ApplyTextChangeSetRequest,
        reviews: Annotated[ReviewRepository, Depends(get_review_repository)],
    ) -> Chapter:
        try:
            return reviews.apply_text_change_set(str(change_set_id), body)
        except ReviewNotFoundError as error:
            raise HTTPException(status_code=404, detail="文本变更集不存在") from error
        except StaleReviewRevisionError as error:
            raise HTTPException(status_code=409, detail="正文或变更集已有新版本") from error
        except InvalidTextChangeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post(
        "/api/text-change-sets/{change_set_id}/reject",
        response_model=TextChangeSet,
    )
    def reject_text_change_set(
        change_set_id: UUID,
        body: RejectTextChangeSetRequest,
        reviews: Annotated[ReviewRepository, Depends(get_review_repository)],
    ) -> TextChangeSet:
        try:
            return reviews.reject_text_change_set(str(change_set_id), body)
        except ReviewNotFoundError as error:
            raise HTTPException(status_code=404, detail="文本变更集不存在") from error
        except StaleReviewRevisionError as error:
            raise HTTPException(status_code=409, detail="文本变更集已有新版本") from error
        except InvalidTextChangeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

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
            raise HTTPException(
                status_code=409, detail="章节已在其他位置更新，请重新载入"
            ) from error
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
            chapter = repository.transition_chapter(str(chapter_id), body)
            if chapter.status.value == "approved":
                repository.create_fact_change_set(chapter.id)
            return chapter
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
            raise HTTPException(
                status_code=409, detail="正文已有新版本，请重新准备上下文"
            ) from error
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
            raise HTTPException(
                status_code=409, detail="正文已有新版本，候选稿未覆盖当前内容"
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail="生成任务尚无可采用草稿") from error

    return application


def get_repository(request: Request) -> ProjectRepository:
    repository: ProjectRepository = request.app.state.repository
    return repository


def get_manuscript_service(request: Request) -> ManuscriptService:
    service: ManuscriptService = request.app.state.manuscript_service
    return service


def get_directory_service(request: Request) -> DirectoryService:
    service: DirectoryService = request.app.state.directory_service
    return service


def get_serial_service(request: Request) -> SerialService:
    service: SerialService = request.app.state.serial_service
    return service


def get_job_repository(request: Request) -> JobRepository:
    repository: JobRepository = request.app.state.job_repository
    return repository


def get_model_profile_repository(request: Request) -> ModelProfileRepository:
    repository: ModelProfileRepository = request.app.state.model_profiles
    return repository


def get_context_repository(request: Request) -> ContextRepository:
    repository: ContextRepository = request.app.state.context_repository
    return repository


def get_director_repository(request: Request) -> DirectorRepository:
    repository: DirectorRepository = request.app.state.director_repository
    return repository


def get_director_service(request: Request) -> DirectorService:
    service: DirectorService = request.app.state.director_service
    return service


def get_review_repository(request: Request) -> ReviewRepository:
    repository: ReviewRepository = request.app.state.review_repository
    return repository


def get_review_service(request: Request) -> ReviewService:
    service: ReviewService = request.app.state.review_service
    return service


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
    return AiWritingService(
        get_repository(request),
        get_ai_manager(request),
        get_context_repository(request),
    )


def get_reference_analysis_service(request: Request) -> ReferenceAnalysisService:
    return ReferenceAnalysisService(get_repository(request), get_ai_manager(request))
