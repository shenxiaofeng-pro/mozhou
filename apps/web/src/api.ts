import type {
  AiChapterBriefInput,
  AiChapterBriefProposal,
  AiOutboundPreview,
  AiStatus,
  AiTaskDefault,
  AiTaskType,
  ApplyFactChangeSetInput,
  ApplyReferencePatternInput,
  Chapter,
  ConfigureAiInput,
  CreateModelProfileInput,
  CreateChapterInput,
  CreateFutureKnowledgeInput,
  CreateProjectInput,
  CreateRecoveryPointInput,
  CreateSourceCardInput,
  CreateStoryEntityInput,
  CreateStoryThreadInput,
  CreateTimelineEventInput,
  FactChangeSet,
  FutureKnowledge,
  ImportReferenceWorkInput,
  Job,
  JobArtifactContent,
  JobDetail,
  KnowledgeReviewAction,
  ModelProfile,
  Project,
  ProjectArchive,
  ReferenceWork,
  ReferencePatternApplication,
  ReferencePatternCard,
  ReferenceSynthesisInput,
  RecoveryPointSummary,
  SourceCard,
  StoryEntity,
  StoryThread,
  TransitionStoryThreadInput,
  GenerationRun,
  TransitionChapterInput,
  TimelineEvent,
  UpdateChapterBriefInput,
  UpdateChapterInput,
  UpdateModelProfileInput,
  UpdateAiTaskDefaultInput,
  UpdateStoryEntityInput,
  Workspace,
  WorkspaceSummary,
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
  if (init?.body) headers.set('Content-Type', 'application/json')
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

export const api = {
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
  createProject(input: CreateProjectInput) {
    return request<Workspace>('/api/projects', { method: 'POST', body: JSON.stringify(input) })
  },
  exportProject(projectId: string) {
    return request<ProjectArchive>(`/api/projects/${encodeURIComponent(projectId)}/export`)
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
  importReferenceWork(projectId: string, input: ImportReferenceWorkInput) {
    return request<ReferenceWork>(`/api/projects/${encodeURIComponent(projectId)}/reference-works`, {
      method: 'POST',
      body: JSON.stringify(input),
    })
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
}

export interface AiCredentialStatus {
  profileId: string
  stored: boolean
  active: boolean
}

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
    if (!isTauri()) return { profileId, stored: false, active: false }
    return assertAiCredentialStatus(await invoke('ai_credential_status', { profileId }))
  },
  async storeAndActivate(profileId: string, apiKey: string): Promise<AiCredentialStatus> {
    if (!isTauri()) {
      await api.activateAiProfile(profileId, apiKey)
      return { profileId, stored: false, active: true }
    }
    return assertAiCredentialStatus(await invoke('store_ai_credential', { profileId, apiKey }))
  },
  async activateSaved(profileId: string): Promise<AiCredentialStatus> {
    if (!isTauri()) throw new Error('浏览器开发模式没有系统凭据库，请重新输入 API Key')
    return assertAiCredentialStatus(await invoke('activate_ai_credential', { profileId }))
  },
  async delete(profileId: string): Promise<AiCredentialStatus> {
    if (!isTauri()) {
      await api.deactivateAiProfile()
      return { profileId, stored: false, active: false }
    }
    return assertAiCredentialStatus(await invoke('delete_ai_credential', { profileId }))
  },
}
