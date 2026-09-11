import type {
  AiChapterBriefInput,
  AiChapterBriefProposal,
  AiOutboundPreview,
  AiStatus,
  AiTaskDefault,
  AiTaskType,
  AcknowledgeOriginalityReportInput,
  ApplyFactChangeSetInput,
  ApplyDirectorProposalInput,
  ApplyReferencePatternInput,
  ApplyTextChangeSetInput,
  Chapter,
  ChapterVersion,
  ComicAiPreview,
  ComicAsset,
  ComicAuditIssue,
  ComicEpisodeSubmission,
  ComicProductionPackage,
  ComicProject,
  ComicSeasonSubmission,
  ComicWorkspace,
  CreateComicProjectInput,
  BookBlueprint,
  BookBlueprintField,
  BetaEvaluationReport,
  BetaEventType,
  BetaFeedback,
  BetaTemplate,
  ConfigureAiInput,
  ConfirmManuscriptImportInput,
  ContextDirective,
  ContextDirectiveInput,
  ContextPacket,
  CreateModelProfileInput,
  CreateDirectoryNodeInput,
  CreateChapterInput,
  CreateBetaFeedbackInput,
  CreateSandboxBranchInput,
  CreateSandboxCandidateInput,
  CreateSandboxSnapshotInput,
  CreateFutureKnowledgeInput,
  CreateProjectInput,
  CreateRecoveryPointInput,
  CreateSourceCardInput,
  CreateStoryEntityInput,
  CreateStoryThreadInput,
  CreateTextChangeSetInput,
  CreateTimelineEventInput,
  DeleteDirectoryNodeInput,
  DirectoryDeleteImpact,
  DirectoryEvent,
  DirectoryNodeKind,
  FactChangeSet,
  FutureKnowledge,
  ImportReferenceFileInput,
  ImportRealitySourceFileInput,
  ImportReferenceWorkInput,
  Job,
  JobArtifactContent,
  JobDetail,
  KnowledgeReviewAction,
  ModelProfile,
  ManuscriptExport,
  ManuscriptImportPreview,
  MoveDirectoryNodeInput,
  OriginalityReport,
  Project,
  ProjectArchive,
  ReferenceWork,
  RollingChapterPlan,
  ReferenceWorkImpact,
  ReferenceFilePreview,
  ReferencePatternApplication,
  ReferencePatternCard,
  ReferenceSynthesisInput,
  ResearchFinding,
  ResearchInput,
  ResearchPreview,
  ResearchSession,
  ResearchSubmission,
  ResearchWorkspace,
  RejectTextChangeSetInput,
  RenameDirectoryNodeInput,
  RecoveryPointSummary,
  SerialDashboard,
  SceneOriginalityCheck,
  SandboxBranch,
  SandboxAiPreview,
  SandboxCandidate,
  SandboxComparison,
  SandboxInterview,
  SandboxReport,
  SandboxRun,
  SandboxTemplate,
  SandboxWorkspace,
  SubmitSandboxAiRoundInput,
  SourceCard,
  SourceDocument,
  StoryEntity,
  StoryThread,
  TransitionStoryThreadInput,
  GenerationRun,
  DirectorChapterPipelineRequest,
  DirectorChapterPipelineResult,
  DirectorExpansionProposal,
  DirectorExpansionRequest,
  DirectorFieldProposal,
  DirectorFieldRegenerationRequest,
  DirectorOutboundPreview,
  DirectorPlanningSnapshot,
  DirectorRegenerationImpact,
  DirectorStartupProposalSet,
  DirectorStartupRequest,
  DiagnosticSummary,
  TransitionChapterInput,
  TimelineEvent,
  VolumePlan,
  UpdateChapterBriefInput,
  UpdateChapterInput,
  UpdateBookBlueprintInput,
  UpdateRollingChapterPlanInput,
  UpdateVolumePlanInput,
  UpdateModelProfileInput,
  UpdateReferenceApplicationLifecycleInput,
  UpdateReferenceBlueprintInput,
  UpdateAiTaskDefaultInput,
  UpdateStoryEntityInput,
  Workspace,
  WorkspaceSummary,
  WorkspaceSearchResult,
  WritingCalendar,
  ChapterAnnotation,
  AuthorIdea,
  StoryGraphs,
  StoryRelationship,
  SelectDirectorCandidateInput,
  ReviewChapterInput,
  ReviewFinding,
  ReviewJobResult,
  ReviewOutboundPreview,
  RollbackChapterVersionInput,
  TextChangeSet,
} from '@mozhou/contracts'
import { invoke, isTauri } from '@tauri-apps/api/core'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}

let tauriApiConnection: Promise<ApiConnection> | null = null

interface ApiConnection {
  baseUrl: string
  sessionToken: string | null
}

function configuredApiBaseUrl(): string {
  return (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
}

function assertLoopbackApiBaseUrl(value: string): string {
  const url = new URL(value)
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.pathname !== '/') {
    throw new Error('桌面本地服务返回了无效地址')
  }
  return url.origin
}

function assertTauriApiConnection(value: unknown): ApiConnection {
  if (
    !value
    || typeof value !== 'object'
    || !('baseUrl' in value)
    || typeof value.baseUrl !== 'string'
    || !('sessionToken' in value)
    || typeof value.sessionToken !== 'string'
    || !/^[0-9a-f]{64}$/.test(value.sessionToken)
  ) {
    throw new Error('桌面本地服务返回了无效会话')
  }
  return {
    baseUrl: assertLoopbackApiBaseUrl(value.baseUrl),
    sessionToken: value.sessionToken,
  }
}

async function resolveApiConnection(): Promise<ApiConnection> {
  if (isTauri()) {
    tauriApiConnection ??= invoke<unknown>('api_connection').then(assertTauriApiConnection)
    return tauriApiConnection
  }
  return { baseUrl: configuredApiBaseUrl(), sessionToken: null }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const connection = await resolveApiConnection()
  const headers = new Headers(init?.headers)
  if (init?.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (connection.sessionToken) {
    headers.set('X-Mozhou-Session-Token', connection.sessionToken)
  }
  const response = await fetch(`${connection.baseUrl}${path}`, {
    ...init,
    headers,
  })
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null)
    const detail =
      payload && typeof payload === 'object' && 'detail' in payload && typeof payload.detail === 'string'
        ? payload.detail
        : '本地服务暂时无法完成操作'
    throw new ApiError(detail, response.status)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

async function requestBlob(path: string, init?: RequestInit): Promise<{ blob: Blob; filename: string }> {
  const connection = await resolveApiConnection()
  const headers = new Headers(init?.headers)
  if (connection.sessionToken) headers.set('X-Mozhou-Session-Token', connection.sessionToken)
  const response = await fetch(`${connection.baseUrl}${path}`, { ...init, headers })
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null)
    const detail = payload && typeof payload === 'object' && 'detail' in payload && typeof payload.detail === 'string'
      ? payload.detail
      : '本地服务暂时无法完成操作'
    throw new ApiError(detail, response.status)
  }
  const disposition = response.headers.get('content-disposition') ?? ''
  const encodedFilename = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1]
  const filename = encodedFilename ? decodeURIComponent(encodedFilename) : (/filename="([^"]+)"/.exec(disposition)?.[1] ?? 'mozhou-download.bin')
  return { blob: await response.blob(), filename }
}

export const api = {
  listComicProjects(projectId: string) {
    return request<ComicProject[]>(
      `/api/projects/${encodeURIComponent(projectId)}/comic-projects`,
    )
  },
  createComicProject(projectId: string, input: CreateComicProjectInput) {
    return request<ComicWorkspace>(
      `/api/projects/${encodeURIComponent(projectId)}/comic-projects`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  getComicProject(comicProjectId: string) {
    return request<ComicWorkspace>(
      `/api/comic-projects/${encodeURIComponent(comicProjectId)}`,
    )
  },
  previewComicSeason(comicProjectId: string, authorDirection = '') {
    return request<ComicAiPreview>(
      `/api/comic-projects/${encodeURIComponent(comicProjectId)}/season-plan/preview`,
      { method: 'POST', body: JSON.stringify({ author_direction: authorDirection }) },
    )
  },
  submitComicSeason(
    comicProjectId: string,
    input: {
      author_direction: string
      expected_source_snapshot_sha256: string
      confirm_external_processing: boolean
      max_estimated_cost_microusd?: number
    },
  ) {
    return request<ComicSeasonSubmission>(
      `/api/comic-projects/${encodeURIComponent(comicProjectId)}/season-plan`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  adoptComicSeason(comicProjectId: string, versionId: string, expectedRevision: number) {
    return request<ComicWorkspace>(
      `/api/comic-projects/${encodeURIComponent(comicProjectId)}/season-plan/adopt`,
      {
        method: 'POST',
        body: JSON.stringify({ version_id: versionId, expected_revision: expectedRevision }),
      },
    )
  },
  reviewComicOutline(
    episodeId: string,
    action: 'approve' | 'reject',
    expectedRevision: number,
    versionId?: string,
  ) {
    return request<ComicWorkspace>(
      `/api/comic-episodes/${encodeURIComponent(episodeId)}/outline/review`,
      {
        method: 'POST',
        body: JSON.stringify({
          action,
          expected_revision: expectedRevision,
          ...(versionId ? { version_id: versionId } : {}),
        }),
      },
    )
  },
  previewComicEpisode(episodeId: string, authorDirection = '') {
    return request<ComicAiPreview>(
      `/api/comic-episodes/${encodeURIComponent(episodeId)}/script/preview`,
      { method: 'POST', body: JSON.stringify({ author_direction: authorDirection }) },
    )
  },
  submitComicEpisode(
    episodeId: string,
    input: {
      author_direction: string
      expected_source_snapshot_sha256: string
      expected_outline_revision: number
      confirm_external_processing: boolean
      max_estimated_cost_microusd?: number
    },
  ) {
    return request<ComicEpisodeSubmission>(
      `/api/comic-episodes/${encodeURIComponent(episodeId)}/script`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  reviewComicScript(
    episodeId: string,
    action: 'approve' | 'reject',
    expectedRevision: number,
    versionId?: string,
  ) {
    return request<ComicWorkspace>(
      `/api/comic-episodes/${encodeURIComponent(episodeId)}/script/review`,
      {
        method: 'POST',
        body: JSON.stringify({
          action,
          expected_revision: expectedRevision,
          ...(versionId ? { version_id: versionId } : {}),
        }),
      },
    )
  },
  getComicAudit(comicProjectId: string) {
    return request<ComicAuditIssue[]>(
      `/api/comic-projects/${encodeURIComponent(comicProjectId)}/audit`,
    )
  },
  getComicAssets(comicProjectId: string) {
    return request<ComicAsset[]>(
      `/api/comic-projects/${encodeURIComponent(comicProjectId)}/assets`,
    )
  },
  getComicProductionPackage(comicProjectId: string) {
    return request<ComicProductionPackage>(
      `/api/comic-projects/${encodeURIComponent(comicProjectId)}/production-package`,
    )
  },
  exportComicProductionPackage(
    comicProjectId: string,
    format: 'json' | 'markdown' | 'docx',
  ) {
    return requestBlob(
      `/api/comic-projects/${encodeURIComponent(comicProjectId)}/export?format=${encodeURIComponent(format)}`,
    )
  },
  getDiagnostics() {
    return request<DiagnosticSummary>('/api/diagnostics')
  },
  exportDiagnosticBundle() {
    return requestBlob('/api/diagnostics/bundle', { method: 'POST' })
  },
  listBetaTemplates() {
    return request<BetaTemplate[]>('/api/beta/templates')
  },
  getBetaReport(projectId: string) {
    return request<BetaEvaluationReport>(`/api/projects/${encodeURIComponent(projectId)}/beta-report`)
  },
  createBetaFeedback(projectId: string, input: CreateBetaFeedbackInput) {
    return request<BetaFeedback>(`/api/projects/${encodeURIComponent(projectId)}/beta-feedback`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  recordBetaEvent(projectId: string, eventType: BetaEventType) {
    return request<void>(
      `/api/projects/${encodeURIComponent(projectId)}/beta-events/${encodeURIComponent(eventType)}`,
      { method: 'POST' },
    )
  },
  listSandboxTemplates() {
    return request<SandboxTemplate[]>('/api/sandbox/templates')
  },
  getSandboxWorkspace(projectId: string) {
    return request<SandboxWorkspace>(`/api/projects/${encodeURIComponent(projectId)}/sandbox`)
  },
  createSandboxSnapshot(projectId: string, input: CreateSandboxSnapshotInput) {
    return request<SandboxWorkspace['snapshots'][number]>(
      `/api/projects/${encodeURIComponent(projectId)}/sandbox/snapshots`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  createSandboxBranch(snapshotId: string, input: CreateSandboxBranchInput) {
    return request<SandboxBranch>(
      `/api/sandbox/snapshots/${encodeURIComponent(snapshotId)}/branches`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  createSandboxRun(
    branchId: string,
    requestedRounds: number,
    actionBudget: number,
    executionMode: 'rules' | 'ai' = 'rules',
  ) {
    return request<SandboxRun>(`/api/sandbox/branches/${encodeURIComponent(branchId)}/runs`, {
      method: 'POST',
      body: JSON.stringify({
        requested_rounds: requestedRounds,
        action_budget: actionBudget,
        execution_mode: executionMode,
      }),
    })
  },
  getSandboxRun(runId: string) {
    return request<SandboxRun>(`/api/sandbox/runs/${encodeURIComponent(runId)}`)
  },
  advanceSandboxRun(runId: string) {
    return request<SandboxRun>(`/api/sandbox/runs/${encodeURIComponent(runId)}/advance`, {
      method: 'POST',
    })
  },
  previewSandboxAiRound(runId: string) {
    return request<SandboxAiPreview>(
      `/api/sandbox/runs/${encodeURIComponent(runId)}/ai-preview`,
    )
  },
  submitSandboxAiRound(runId: string, input: SubmitSandboxAiRoundInput) {
    return request<Job>(`/api/sandbox/runs/${encodeURIComponent(runId)}/ai-jobs`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  cancelSandboxRun(runId: string) {
    return request<SandboxRun>(`/api/sandbox/runs/${encodeURIComponent(runId)}/cancel`, {
      method: 'POST',
    })
  },
  replaySandboxRun(runId: string) {
    return request<SandboxRun>(`/api/sandbox/runs/${encodeURIComponent(runId)}/replay`, {
      method: 'POST',
    })
  },
  getSandboxReport(runId: string) {
    return request<SandboxReport>(`/api/sandbox/runs/${encodeURIComponent(runId)}/report`)
  },
  getSandboxInterview(runId: string, actorId: string) {
    return request<SandboxInterview>(
      `/api/sandbox/runs/${encodeURIComponent(runId)}/interviews/${encodeURIComponent(actorId)}`,
    )
  },
  createSandboxCandidate(runId: string, input: CreateSandboxCandidateInput) {
    return request<SandboxCandidate>(`/api/sandbox/runs/${encodeURIComponent(runId)}/candidates`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  decideSandboxCandidate(candidateId: string, decision: 'approve' | 'reject') {
    return request<SandboxCandidate>(
      `/api/sandbox/candidates/${encodeURIComponent(candidateId)}/${decision}`,
      { method: 'POST' },
    )
  },
  compareSandboxRuns(projectId: string, runIds: string[]) {
    return request<SandboxComparison>(
      `/api/projects/${encodeURIComponent(projectId)}/sandbox/comparisons`,
      { method: 'POST', body: JSON.stringify({ run_ids: runIds }) },
    )
  },
  listProjects() {
    return request<Project[]>('/api/projects')
  },
  listJobs(projectId: string) {
    return request<Job[]>(`/api/projects/${encodeURIComponent(projectId)}/jobs`)
  },
  getJob(jobId: string) {
    return request<JobDetail>(`/api/jobs/${encodeURIComponent(jobId)}`)
  },
  getJobArtifact(artifactId: string) {
    return request<JobArtifactContent>(`/api/job-artifacts/${encodeURIComponent(artifactId)}`)
  },
  cancelJob(jobId: string) {
    return request<Job>(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' })
  },
  retryJob(jobId: string) {
    return request<Job>(`/api/jobs/${encodeURIComponent(jobId)}/retry`, { method: 'POST' })
  },
  getAiStatus() {
    return request<AiStatus>('/api/ai/status')
  },
  configureAi(input: ConfigureAiInput) {
    return request<AiStatus>('/api/ai/configure', {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  listAiProfiles() {
    return request<ModelProfile[]>('/api/ai/profiles')
  },
  listAiTaskDefaults() {
    return request<AiTaskDefault[]>('/api/ai/task-defaults')
  },
  setAiTaskDefault(taskType: AiTaskType, input: UpdateAiTaskDefaultInput) {
    return request<AiTaskDefault>(`/api/ai/task-defaults/${encodeURIComponent(taskType)}`, {
      method: 'PUT',
      body: JSON.stringify(input),
    })
  },
  deleteAiTaskDefault(taskType: AiTaskType, expectedRevision: number) {
    const query = new URLSearchParams({ expected_revision: String(expectedRevision) })
    return request<void>(`/api/ai/task-defaults/${encodeURIComponent(taskType)}?${query}`, {
      method: 'DELETE',
    })
  },
  createAiProfile(input: CreateModelProfileInput) {
    return request<ModelProfile>('/api/ai/profiles', {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  updateAiProfile(profileId: string, input: UpdateModelProfileInput) {
    return request<ModelProfile>(`/api/ai/profiles/${encodeURIComponent(profileId)}`, {
      method: 'PUT',
      body: JSON.stringify(input),
    })
  },
  activateAiProfile(profileId: string, apiKey: string) {
    return request<AiStatus>(`/api/ai/profiles/${encodeURIComponent(profileId)}/activate`, {
      method: 'POST',
      body: JSON.stringify({ api_key: apiKey }),
    })
  },
  deactivateAiProfile() {
    return request<AiStatus>('/api/ai/deactivate', { method: 'POST' })
  },
  deactivateOneAiProfile(profileId: string) {
    return request<AiStatus>(`/api/ai/profiles/${encodeURIComponent(profileId)}/deactivate`, {
      method: 'POST',
    })
  },
  deleteAiProfile(profileId: string, expectedRevision: number) {
    const query = new URLSearchParams({ expected_revision: String(expectedRevision) })
    return request<void>(`/api/ai/profiles/${encodeURIComponent(profileId)}?${query}`, {
      method: 'DELETE',
    })
  },
  proposeAiChapterBrief(chapterId: string, input: AiChapterBriefInput) {
    return request<AiChapterBriefProposal>(`/api/chapters/${encodeURIComponent(chapterId)}/ai-brief-proposals`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  startAiChapterBriefJob(chapterId: string, input: AiChapterBriefInput) {
    return request<Job>(`/api/chapters/${encodeURIComponent(chapterId)}/ai-brief-jobs`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  previewAiChapterBrief(chapterId: string, input: AiChapterBriefInput) {
    return request<AiOutboundPreview>(`/api/chapters/${encodeURIComponent(chapterId)}/ai-brief-preview`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  getAiChapterBriefJobResult(jobId: string) {
    return request<AiChapterBriefProposal>(`/api/jobs/${encodeURIComponent(jobId)}/chapter-brief-result`)
  },
  generateAiDraft(chapterId: string, input: AiChapterBriefInput) {
    return request<GenerationRun>(`/api/chapters/${encodeURIComponent(chapterId)}/ai-draft-runs`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  startAiChapterDraftJob(chapterId: string, input: AiChapterBriefInput) {
    return request<Job>(`/api/chapters/${encodeURIComponent(chapterId)}/ai-draft-jobs`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  previewAiChapterDraft(chapterId: string, input: AiChapterBriefInput) {
    return request<AiOutboundPreview>(`/api/chapters/${encodeURIComponent(chapterId)}/ai-draft-preview`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  getAiChapterDraftJobResult(jobId: string) {
    return request<GenerationRun>(`/api/jobs/${encodeURIComponent(jobId)}/chapter-draft-result`)
  },
  listContextPackets(chapterId: string) {
    return request<ContextPacket[]>(`/api/chapters/${encodeURIComponent(chapterId)}/context-packets`)
  },
  getContextPacket(packetId: string) {
    return request<ContextPacket>(`/api/context-packets/${encodeURIComponent(packetId)}`)
  },
  listContextDirectives(chapterId: string) {
    return request<ContextDirective[]>(`/api/chapters/${encodeURIComponent(chapterId)}/context-directives`)
  },
  setContextDirective(chapterId: string, input: ContextDirectiveInput) {
    return request<ContextDirective>(`/api/chapters/${encodeURIComponent(chapterId)}/context-directives`, {
      method: 'PUT',
      body: JSON.stringify(input),
    })
  },
  deleteContextDirective(directiveId: string, expectedRevision: number) {
    const query = new URLSearchParams({ expected_revision: String(expectedRevision) })
    return request<void>(`/api/context-directives/${encodeURIComponent(directiveId)}?${query}`, {
      method: 'DELETE',
    })
  },
  createProject(input: CreateProjectInput) {
    return request<Workspace>('/api/projects', { method: 'POST', body: JSON.stringify(input) })
  },
  previewManuscript(file: File) {
    const query = new URLSearchParams({ source_filename: file.name })
    return request<ManuscriptImportPreview>(`/api/manuscript-imports/preview?${query}`, {
      method: 'POST',
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      body: file,
    })
  },
  confirmManuscriptImport(input: ConfirmManuscriptImportInput) {
    return request<Workspace>('/api/manuscript-imports', {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  exportManuscript(projectId: string) {
    return request<ManuscriptExport>(
      `/api/projects/${encodeURIComponent(projectId)}/manuscript-export`,
    )
  },
  exportManuscriptBinary(projectId: string, format: 'docx' | 'epub') {
    return requestBlob(`/api/projects/${encodeURIComponent(projectId)}/manuscript-export/${format}`)
  },
  createDirectoryNode(projectId: string, input: CreateDirectoryNodeInput) {
    return request<WorkspaceSummary>(
      `/api/projects/${encodeURIComponent(projectId)}/directory-nodes`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  renameDirectoryNode(kind: DirectoryNodeKind, nodeId: string, input: RenameDirectoryNodeInput) {
    return request<WorkspaceSummary>(
      `/api/directory-nodes/${encodeURIComponent(kind)}/${encodeURIComponent(nodeId)}`,
      { method: 'PATCH', body: JSON.stringify(input) },
    )
  },
  moveDirectoryNode(kind: DirectoryNodeKind, nodeId: string, input: MoveDirectoryNodeInput) {
    return request<WorkspaceSummary>(
      `/api/directory-nodes/${encodeURIComponent(kind)}/${encodeURIComponent(nodeId)}/move`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  getDirectoryDeleteImpact(kind: DirectoryNodeKind, nodeId: string) {
    return request<DirectoryDeleteImpact>(
      `/api/directory-nodes/${encodeURIComponent(kind)}/${encodeURIComponent(nodeId)}/delete-impact`,
    )
  },
  deleteDirectoryNode(kind: DirectoryNodeKind, nodeId: string, input: DeleteDirectoryNodeInput) {
    return request<WorkspaceSummary>(
      `/api/directory-nodes/${encodeURIComponent(kind)}/${encodeURIComponent(nodeId)}`,
      { method: 'DELETE', body: JSON.stringify(input) },
    )
  },
  listDirectoryEvents(projectId: string) {
    return request<DirectoryEvent[]>(`/api/projects/${encodeURIComponent(projectId)}/directory-events`)
  },
  undoDirectoryEvent(projectId: string) {
    return request<WorkspaceSummary>(
      `/api/projects/${encodeURIComponent(projectId)}/directory-events/undo`,
      { method: 'POST' },
    )
  },
  getSerialDashboard(projectId: string, goalDate?: string) {
    const query = new URLSearchParams()
    if (goalDate) query.set('goal_date', goalDate)
    return request<SerialDashboard>(
      `/api/projects/${encodeURIComponent(projectId)}/serial-dashboard${query.size ? `?${query}` : ''}`,
    )
  },
  setSerialDailyGoal(projectId: string, goalDate: string, targetCharacters: number, expectedRevision: number | null) {
    return request<SerialDashboard>(
      `/api/projects/${encodeURIComponent(projectId)}/serial-goals/${encodeURIComponent(goalDate)}`,
      {
        method: 'PUT',
        body: JSON.stringify({ target_characters: targetCharacters, expected_revision: expectedRevision }),
      },
    )
  },
  searchWorkspace(projectId: string, query: string, limit = 50) {
    const params = new URLSearchParams({ q: query, limit: String(limit) })
    return request<WorkspaceSearchResult[]>(
      `/api/projects/${encodeURIComponent(projectId)}/search?${params}`,
    )
  },
  getDirectorSnapshot(projectId: string) {
    return request<DirectorPlanningSnapshot>(
      `/api/projects/${encodeURIComponent(projectId)}/director`,
    )
  },
  updateBookBlueprint(projectId: string, input: UpdateBookBlueprintInput) {
    return request<BookBlueprint>(
      `/api/projects/${encodeURIComponent(projectId)}/director/book-blueprint`,
      { method: 'PATCH', body: JSON.stringify(input) },
    )
  },
  getDirectorRegenerationImpact(projectId: string, targetField: BookBlueprintField) {
    return request<DirectorRegenerationImpact>(
      `/api/projects/${encodeURIComponent(projectId)}/director/regeneration-impact`,
      { method: 'POST', body: JSON.stringify({ target_field: targetField }) },
    )
  },
  previewDirectorStartup(projectId: string, input: DirectorStartupRequest) {
    return request<DirectorOutboundPreview>(
      `/api/projects/${encodeURIComponent(projectId)}/director/startup-preview`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  startDirectorStartupJob(projectId: string, input: DirectorStartupRequest) {
    return request<Job>(
      `/api/projects/${encodeURIComponent(projectId)}/director/startup-jobs`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  getDirectorStartupResult(jobId: string) {
    return request<DirectorStartupProposalSet>(
      `/api/jobs/${encodeURIComponent(jobId)}/director-startup-result`,
    )
  },
  selectDirectorStartupCandidate(projectId: string, input: SelectDirectorCandidateInput) {
    return request<BookBlueprint>(
      `/api/projects/${encodeURIComponent(projectId)}/director/startup-selection`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  previewDirectorExpansion(projectId: string, input: DirectorExpansionRequest) {
    return request<DirectorOutboundPreview>(
      `/api/projects/${encodeURIComponent(projectId)}/director/expansion-preview`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  startDirectorExpansionJob(projectId: string, input: DirectorExpansionRequest) {
    return request<Job>(
      `/api/projects/${encodeURIComponent(projectId)}/director/expansion-jobs`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  getDirectorExpansionResult(jobId: string) {
    return request<DirectorExpansionProposal>(
      `/api/jobs/${encodeURIComponent(jobId)}/director-expansion-result`,
    )
  },
  applyDirectorExpansion(projectId: string, input: ApplyDirectorProposalInput) {
    return request<DirectorPlanningSnapshot>(
      `/api/projects/${encodeURIComponent(projectId)}/director/expansion-application`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  previewDirectorField(projectId: string, input: DirectorFieldRegenerationRequest) {
    return request<DirectorOutboundPreview>(
      `/api/projects/${encodeURIComponent(projectId)}/director/field-preview`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  startDirectorFieldJob(projectId: string, input: DirectorFieldRegenerationRequest) {
    return request<Job>(
      `/api/projects/${encodeURIComponent(projectId)}/director/field-jobs`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  getDirectorFieldResult(jobId: string) {
    return request<DirectorFieldProposal>(
      `/api/jobs/${encodeURIComponent(jobId)}/director-field-result`,
    )
  },
  applyDirectorField(projectId: string, input: ApplyDirectorProposalInput) {
    return request<BookBlueprint>(
      `/api/projects/${encodeURIComponent(projectId)}/director/field-application`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  updateDirectorVolumePlan(projectId: string, planId: string, input: UpdateVolumePlanInput) {
    return request<VolumePlan>(
      `/api/projects/${encodeURIComponent(projectId)}/director/volume-plans/${encodeURIComponent(planId)}`,
      { method: 'PATCH', body: JSON.stringify(input) },
    )
  },
  updateDirectorRollingPlan(projectId: string, planId: string, input: UpdateRollingChapterPlanInput) {
    return request<RollingChapterPlan>(
      `/api/projects/${encodeURIComponent(projectId)}/director/rolling-plans/${encodeURIComponent(planId)}`,
      { method: 'PATCH', body: JSON.stringify(input) },
    )
  },
  previewDirectorPipeline(chapterId: string, input: DirectorChapterPipelineRequest) {
    return request<DirectorOutboundPreview>(
      `/api/chapters/${encodeURIComponent(chapterId)}/director-pipeline-preview`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  startDirectorPipelineJob(chapterId: string, input: DirectorChapterPipelineRequest) {
    return request<Job>(
      `/api/chapters/${encodeURIComponent(chapterId)}/director-pipeline-jobs`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  getDirectorPipelineResult(jobId: string) {
    return request<DirectorChapterPipelineResult>(
      `/api/jobs/${encodeURIComponent(jobId)}/director-pipeline-result`,
    )
  },
  exportProject(projectId: string, includeReferenceAssets = false) {
    const suffix = includeReferenceAssets ? '?include_reference_assets=true' : ''
    return request<ProjectArchive>(`/api/projects/${encodeURIComponent(projectId)}/export${suffix}`)
  },
  importProjectArchive(rawArchive: string) {
    return request<Workspace>('/api/project-imports', {
      method: 'POST',
      body: rawArchive,
    })
  },
  listRecoveryPoints(projectId: string) {
    return request<RecoveryPointSummary[]>(
      `/api/projects/${encodeURIComponent(projectId)}/recovery-points`,
    )
  },
  createRecoveryPoint(projectId: string, input: CreateRecoveryPointInput) {
    return request<RecoveryPointSummary>(
      `/api/projects/${encodeURIComponent(projectId)}/recovery-points`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  restoreRecoveryPoint(recoveryPointId: string) {
    return request<Workspace>(
      `/api/recovery-points/${encodeURIComponent(recoveryPointId)}/restore`,
      { method: 'POST' },
    )
  },
  getProject(projectId: string) {
    return request<Workspace>(`/api/projects/${encodeURIComponent(projectId)}`)
  },
  getProjectSummary(projectId: string) {
    return request<WorkspaceSummary>(`/api/projects/${encodeURIComponent(projectId)}/summary`)
  },
  getChapter(chapterId: string) {
    return request<Chapter>(`/api/chapters/${encodeURIComponent(chapterId)}`)
  },
  listChapterVersions(chapterId: string) {
    return request<ChapterVersion[]>(`/api/chapters/${encodeURIComponent(chapterId)}/versions`)
  },
  rollbackChapterVersion(chapterId: string, versionId: string, input: RollbackChapterVersionInput) {
    return request<Chapter>(
      `/api/chapters/${encodeURIComponent(chapterId)}/versions/${encodeURIComponent(versionId)}/rollback`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  previewChapterReview(chapterId: string, input: ReviewChapterInput) {
    return request<ReviewOutboundPreview>(`/api/chapters/${encodeURIComponent(chapterId)}/review-preview`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  startChapterReviewJob(chapterId: string, input: ReviewChapterInput) {
    return request<Job>(`/api/chapters/${encodeURIComponent(chapterId)}/review-jobs`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  getChapterReviewJobResult(jobId: string) {
    return request<ReviewJobResult>(`/api/jobs/${encodeURIComponent(jobId)}/review-result`)
  },
  listReviewFindings(chapterId: string, chapterRevision?: number) {
    const query = chapterRevision === undefined
      ? ''
      : `?${new URLSearchParams({ chapter_revision: String(chapterRevision) })}`
    return request<ReviewFinding[]>(`/api/chapters/${encodeURIComponent(chapterId)}/review-findings${query}`)
  },
  listTextChangeSets(chapterId: string) {
    return request<TextChangeSet[]>(`/api/chapters/${encodeURIComponent(chapterId)}/text-change-sets`)
  },
  createTextChangeSet(chapterId: string, input: CreateTextChangeSetInput) {
    return request<TextChangeSet>(`/api/chapters/${encodeURIComponent(chapterId)}/text-change-sets`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  applyTextChangeSet(changeSetId: string, input: ApplyTextChangeSetInput) {
    return request<Chapter>(`/api/text-change-sets/${encodeURIComponent(changeSetId)}/apply`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  rejectTextChangeSet(changeSetId: string, input: RejectTextChangeSetInput) {
    return request<TextChangeSet>(`/api/text-change-sets/${encodeURIComponent(changeSetId)}/reject`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  createChapter(projectId: string, input: CreateChapterInput) {
    return request<Chapter>(`/api/projects/${encodeURIComponent(projectId)}/chapters`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  updateChapter(chapterId: string, input: UpdateChapterInput) {
    return request<Chapter>(`/api/chapters/${encodeURIComponent(chapterId)}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    })
  },
  updateChapterBrief(chapterId: string, input: UpdateChapterBriefInput) {
    return request<Chapter>(`/api/chapters/${encodeURIComponent(chapterId)}/brief`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    })
  },
  transitionChapter(chapterId: string, input: TransitionChapterInput) {
    return request<Chapter>(`/api/chapters/${encodeURIComponent(chapterId)}/transition`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  startGeneration(chapterId: string, expectedRevision: number) {
    return request<GenerationRun>(`/api/chapters/${encodeURIComponent(chapterId)}/generation-runs`, {
      method: 'POST',
      body: JSON.stringify({ expected_revision: expectedRevision }),
    })
  },
  resumeGeneration(runId: string) {
    return request<GenerationRun>(`/api/generation-runs/${encodeURIComponent(runId)}/resume`, {
      method: 'POST',
    })
  },
  applyGeneration(runId: string, expectedRevision: number) {
    return request<Chapter>(`/api/generation-runs/${encodeURIComponent(runId)}/apply`, {
      method: 'POST',
      body: JSON.stringify({ expected_revision: expectedRevision }),
    })
  },
  createOriginalTimelineEvent(projectId: string, input: CreateTimelineEventInput) {
    return request<TimelineEvent>(`/api/projects/${encodeURIComponent(projectId)}/timeline-events`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  createFactChangeSet(chapterId: string) {
    return request<FactChangeSet>(`/api/chapters/${encodeURIComponent(chapterId)}/fact-change-sets`, {
      method: 'POST',
    })
  },
  applyFactChangeSet(changeSetId: string, input: ApplyFactChangeSetInput) {
    return request<FactChangeSet>(`/api/fact-change-sets/${encodeURIComponent(changeSetId)}/apply`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  rejectFactChangeSet(changeSetId: string, expectedRevision: number) {
    return request<FactChangeSet>(`/api/fact-change-sets/${encodeURIComponent(changeSetId)}/reject`, {
      method: 'POST',
      body: JSON.stringify({ expected_revision: expectedRevision }),
    })
  },
  createFutureKnowledge(projectId: string, input: CreateFutureKnowledgeInput) {
    return request<FutureKnowledge>(`/api/projects/${encodeURIComponent(projectId)}/future-knowledge`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  reviewFutureKnowledge(
    knowledgeId: string,
    action: KnowledgeReviewAction,
    expectedRevision: number,
  ) {
    return request<FutureKnowledge>(`/api/future-knowledge/${encodeURIComponent(knowledgeId)}/review`, {
      method: 'POST',
      body: JSON.stringify({ action, expected_revision: expectedRevision }),
    })
  },
  createStoryEntity(projectId: string, input: CreateStoryEntityInput) {
    return request<StoryEntity>(`/api/projects/${encodeURIComponent(projectId)}/story-entities`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  updateStoryEntity(entityId: string, input: UpdateStoryEntityInput) {
    return request<StoryEntity>(`/api/story-entities/${encodeURIComponent(entityId)}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    })
  },
  createStoryThread(projectId: string, input: CreateStoryThreadInput) {
    return request<StoryThread>(`/api/projects/${encodeURIComponent(projectId)}/story-threads`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  transitionStoryThread(threadId: string, input: TransitionStoryThreadInput) {
    return request<StoryThread>(`/api/story-threads/${encodeURIComponent(threadId)}/transition`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  createSourceCard(projectId: string, input: CreateSourceCardInput) {
    return request<SourceCard>(`/api/projects/${encodeURIComponent(projectId)}/source-cards`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  setSourceCardConfirmation(cardId: string, confirmed: boolean, expectedRevision: number) {
    return request<SourceCard>(`/api/source-cards/${encodeURIComponent(cardId)}/confirmation`, {
      method: 'POST',
      body: JSON.stringify({ confirmed, expected_revision: expectedRevision }),
    })
  },
  previewResearch(projectId: string, input: ResearchInput) {
    return request<ResearchPreview>(`/api/projects/${encodeURIComponent(projectId)}/research/preview`, {
      method: 'POST', body: JSON.stringify(input),
    })
  },
  submitResearch(projectId: string, input: ResearchInput & {
    expected_source_set_sha256: string
    confirm_external_processing: boolean
    max_estimated_cost_microusd?: number
  }) {
    return request<ResearchSubmission>(`/api/projects/${encodeURIComponent(projectId)}/research/jobs`, {
      method: 'POST', body: JSON.stringify(input),
    })
  },
  listResearchSessions(projectId: string) {
    return request<ResearchSession[]>(`/api/projects/${encodeURIComponent(projectId)}/research/sessions`)
  },
  getResearchSession(sessionId: string) {
    return request<ResearchWorkspace>(`/api/research/sessions/${encodeURIComponent(sessionId)}`)
  },
  reviewResearchFinding(findingId: string, action: 'approve' | 'reject', expectedRevision: number) {
    return request<ResearchFinding>(`/api/research/findings/${encodeURIComponent(findingId)}/review`, {
      method: 'POST', body: JSON.stringify({ action, expected_revision: expectedRevision }),
    })
  },
  getWritingCalendar(projectId: string, days = 42) {
    return request<WritingCalendar>(`/api/projects/${encodeURIComponent(projectId)}/writing-calendar?days=${days}`)
  },
  listChapterAnnotations(chapterId: string) {
    return request<ChapterAnnotation[]>(`/api/chapters/${encodeURIComponent(chapterId)}/annotations`)
  },
  createChapterAnnotation(chapterId: string, input: { comment: string; start_char: number; end_char: number; expected_chapter_revision: number }) {
    return request<ChapterAnnotation>(`/api/chapters/${encodeURIComponent(chapterId)}/annotations`, { method: 'POST', body: JSON.stringify(input) })
  },
  resolveChapterAnnotation(annotationId: string, expectedRevision: number) {
    return request<ChapterAnnotation>(`/api/chapter-annotations/${encodeURIComponent(annotationId)}/resolve`, { method: 'POST', body: JSON.stringify({ expected_revision: expectedRevision }) })
  },
  listAuthorIdeas(projectId: string) {
    return request<AuthorIdea[]>(`/api/author-ideas?project_id=${encodeURIComponent(projectId)}`)
  },
  createAuthorIdea(input: { project_id?: string; title: string; content: string; tags: string[] }) {
    return request<AuthorIdea>('/api/author-ideas', { method: 'POST', body: JSON.stringify(input) })
  },
  updateAuthorIdea(ideaId: string, input: { title: string; content: string; tags: string[]; status: AuthorIdea['status']; expected_revision: number }) {
    return request<AuthorIdea>(`/api/author-ideas/${encodeURIComponent(ideaId)}`, { method: 'PATCH', body: JSON.stringify(input) })
  },
  prepareAuthorIdea(ideaId: string, targetKind: NonNullable<AuthorIdea['target_kind']>, expectedRevision: number) {
    return request<AuthorIdea>(`/api/author-ideas/${encodeURIComponent(ideaId)}/prepare`, { method: 'POST', body: JSON.stringify({ target_kind: targetKind, expected_revision: expectedRevision }) })
  },
  getStoryGraphs(projectId: string) {
    return request<StoryGraphs>(`/api/projects/${encodeURIComponent(projectId)}/story-graphs`)
  },
  createStoryRelationship(projectId: string, input: { source_entity_id: string; target_entity_id: string; relation_type: string; summary: string; source_chapter_id?: string }) {
    return request<StoryRelationship>(`/api/projects/${encodeURIComponent(projectId)}/story-relationships`, { method: 'POST', body: JSON.stringify(input) })
  },
  importReferenceWork(projectId: string, input: ImportReferenceWorkInput) {
    return request<ReferenceWork>(`/api/projects/${encodeURIComponent(projectId)}/reference-works`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  listReferenceWorks() {
    return request<ReferenceWork[]>('/api/reference-library/works')
  },
  previewReferenceFile(file: File) {
    const query = new URLSearchParams({ source_filename: file.name })
    return request<ReferenceFilePreview>(`/api/reference-library/file-previews?${query}`, {
      method: 'POST',
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      body: file,
    })
  },
  importReferenceFile(file: File, input: ImportReferenceFileInput) {
    const query = new URLSearchParams({
      source_filename: file.name,
      title: input.title,
      rights_basis: input.rights_basis,
      segment_target_characters: String(input.segment_target_characters),
      expected_source_sha256: input.expected_source_sha256,
      confirm_preview: String(input.confirm_preview),
      confirm_uncertain_encoding: String(input.confirm_uncertain_encoding),
    })
    if (input.project_id) query.set('project_id', input.project_id)
    return request<ReferenceWork>(`/api/reference-library/file-imports?${query}`, {
      method: 'POST',
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      body: file,
    })
  },
  linkReferenceWork(projectId: string, workId: string) {
    return request<ReferenceWork>(
      `/api/projects/${encodeURIComponent(projectId)}/reference-works/${encodeURIComponent(workId)}`,
      { method: 'POST' },
    )
  },
  unlinkReferenceWork(projectId: string, workId: string) {
    return request<void>(
      `/api/projects/${encodeURIComponent(projectId)}/reference-works/${encodeURIComponent(workId)}`,
      { method: 'DELETE' },
    )
  },
  getReferenceWorkImpact(workId: string) {
    return request<ReferenceWorkImpact>(
      `/api/reference-library/works/${encodeURIComponent(workId)}/impact`,
    )
  },
  purgeReferenceWork(workId: string) {
    return request<ReferenceWorkImpact>(
      `/api/reference-library/works/${encodeURIComponent(workId)}?confirm_purge=true`,
      { method: 'DELETE' },
    )
  },
  listSourceDocuments() {
    return request<SourceDocument[]>('/api/source-library/documents')
  },
  importRealitySourceFile(file: File, input: ImportRealitySourceFileInput) {
    const query = new URLSearchParams({
      project_id: input.project_id,
      source_filename: file.name,
      title: input.title,
      source_kind: input.source_kind,
      source_reference: input.source_reference,
      applicable_year_start: String(input.applicable_year_start),
      applicable_year_end: String(input.applicable_year_end),
      confidence: input.confidence,
      expected_source_sha256: input.expected_source_sha256,
      confirm_preview: String(input.confirm_preview),
      confirm_uncertain_encoding: String(input.confirm_uncertain_encoding),
    })
    if (input.source_date) query.set('source_date', input.source_date)
    return request<SourceCard>(`/api/source-library/file-imports?${query}`, {
      method: 'POST',
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      body: file,
    })
  },
  applySourceDocument(projectId: string, documentId: string, input: CreateSourceCardInput, sourceDate?: string) {
    const query = new URLSearchParams()
    if (sourceDate) query.set('source_date', sourceDate)
    const suffix = query.size ? `?${query}` : ''
    return request<SourceCard>(
      `/api/projects/${encodeURIComponent(projectId)}/source-documents/${encodeURIComponent(documentId)}/cards${suffix}`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  deleteSourceDocument(documentId: string) {
    return request<{ affected_cards: number }>(
      `/api/source-library/documents/${encodeURIComponent(documentId)}?confirm_purge=true`,
      { method: 'DELETE' },
    )
  },
  synthesizeReferencePatterns(projectId: string, input: ReferenceSynthesisInput) {
    return request<ReferencePatternCard>(`/api/projects/${encodeURIComponent(projectId)}/reference-synthesis-proposals`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  startReferenceAnalysisJob(projectId: string, input: ReferenceSynthesisInput) {
    return request<Job>(`/api/projects/${encodeURIComponent(projectId)}/reference-analysis-jobs`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },
  applyReferencePattern(projectId: string, cardId: string, input: ApplyReferencePatternInput) {
    return request<ReferencePatternApplication>(
      `/api/projects/${encodeURIComponent(projectId)}/reference-pattern-cards/${encodeURIComponent(cardId)}/applications`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  updateReferenceApplicationLifecycle(
    projectId: string,
    applicationId: string,
    input: UpdateReferenceApplicationLifecycleInput,
  ) {
    return request<ReferencePatternApplication>(
      `/api/projects/${encodeURIComponent(projectId)}/reference-pattern-applications/${encodeURIComponent(applicationId)}/lifecycle`,
      { method: 'PATCH', body: JSON.stringify(input) },
    )
  },
  getOriginalityReport(reportId: string) {
    return request<OriginalityReport>(
      `/api/originality-reports/${encodeURIComponent(reportId)}`,
    )
  },
  updateReferenceBlueprint(
    projectId: string,
    applicationId: string,
    input: UpdateReferenceBlueprintInput,
  ) {
    return request<ReferencePatternApplication>(
      `/api/projects/${encodeURIComponent(projectId)}/reference-blueprints/${encodeURIComponent(applicationId)}`,
      { method: 'PATCH', body: JSON.stringify(input) },
    )
  },
  acknowledgeOriginalityReport(
    projectId: string,
    applicationId: string,
    input: AcknowledgeOriginalityReportInput,
  ) {
    return request<ReferencePatternApplication>(
      `/api/projects/${encodeURIComponent(projectId)}/reference-blueprints/${encodeURIComponent(applicationId)}/originality-acknowledgements`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
  getOrRunSceneOriginalityCheck(projectId: string, applicationId: string) {
    return request<SceneOriginalityCheck>(
      `/api/projects/${encodeURIComponent(projectId)}/reference-blueprints/${encodeURIComponent(applicationId)}/scene-originality-checks`,
      { method: 'POST' },
    )
  },
  getSceneOriginalityCheck(checkId: string) {
    return request<SceneOriginalityCheck>(
      `/api/scene-originality-checks/${encodeURIComponent(checkId)}`,
    )
  },
  acknowledgeSceneOriginalityCheck(
    projectId: string,
    applicationId: string,
    input: AcknowledgeOriginalityReportInput,
  ) {
    return request<ReferencePatternApplication>(
      `/api/projects/${encodeURIComponent(projectId)}/reference-blueprints/${encodeURIComponent(applicationId)}/scene-originality-acknowledgements`,
      { method: 'POST', body: JSON.stringify(input) },
    )
  },
}

export interface AiCredentialStatus {
  profileId: string
  stored: boolean
  active: boolean
}

const browserSessionCredentials = new Map<string, string>()
let browserActiveProfileId: string | null = null

function assertAiCredentialStatus(value: unknown): AiCredentialStatus {
  if (
    !value
    || typeof value !== 'object'
    || !('profileId' in value)
    || typeof value.profileId !== 'string'
    || !('stored' in value)
    || typeof value.stored !== 'boolean'
    || !('active' in value)
    || typeof value.active !== 'boolean'
  ) {
    throw new Error('系统凭据库返回了无效状态')
  }
  return {
    profileId: value.profileId,
    stored: value.stored,
    active: value.active,
  }
}

export const aiCredentialStore = {
  isSystemStoreAvailable: isTauri(),
  async status(profileId: string): Promise<AiCredentialStatus> {
    if (!isTauri()) {
      return {
        profileId,
        stored: browserSessionCredentials.has(profileId),
        active: browserActiveProfileId === profileId,
      }
    }
    return assertAiCredentialStatus(await invoke('ai_credential_status', { profileId }))
  },
  async storeAndActivate(profileId: string, apiKey: string): Promise<AiCredentialStatus> {
    if (!isTauri()) {
      await api.activateAiProfile(profileId, apiKey)
      browserSessionCredentials.set(profileId, apiKey)
      browserActiveProfileId = profileId
      return { profileId, stored: true, active: true }
    }
    return assertAiCredentialStatus(await invoke('store_ai_credential', { profileId, apiKey }))
  },
  async activateSaved(profileId: string): Promise<AiCredentialStatus> {
    if (!isTauri()) {
      const apiKey = browserSessionCredentials.get(profileId)
      if (!apiKey) throw new Error('该线路的会话密钥已清除，请重新输入 API Key')
      await api.activateAiProfile(profileId, apiKey)
      browserActiveProfileId = profileId
      return { profileId, stored: true, active: true }
    }
    return assertAiCredentialStatus(await invoke('activate_ai_credential', { profileId }))
  },
  async delete(profileId: string): Promise<AiCredentialStatus> {
    if (!isTauri()) {
      await api.deactivateOneAiProfile(profileId)
      browserSessionCredentials.delete(profileId)
      if (browserActiveProfileId === profileId) browserActiveProfileId = null
      return { profileId, stored: false, active: false }
    }
    return assertAiCredentialStatus(await invoke('delete_ai_credential', { profileId }))
  },
}
