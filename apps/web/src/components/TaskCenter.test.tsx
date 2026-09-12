import type { Job, JobDetail } from '@mozhou/contracts'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api } from '../api'
import { TaskCenter } from './TaskCenter'

function craftJob(workflow: 'craft_pattern_analysis_v2' | 'craft_pattern_fusion_v2'): Job {
  return {
    id: `${workflow}-job`,
    project_id: 'project-1',
    chapter_id: null,
    parent_job_id: null,
    kind: 'reference_fusion',
    workflow,
    state: 'succeeded',
    idempotency_key: `${workflow}-key`,
    progress_current: 2,
    progress_total: 2,
    current_step: '素材已生成',
    estimated_calls: 2,
    completed_calls: 2,
    provider: 'openai',
    provider_profile_id: null,
    model: 'gpt-5.6',
    lease_owner: null,
    lease_expires_at: null,
    heartbeat_at: null,
    error_code: null,
    error_message: null,
    created_at: '2026-09-11T00:00:00Z',
    updated_at: '2026-09-11T00:00:01Z',
    started_at: '2026-09-11T00:00:00Z',
    completed_at: '2026-09-11T00:00:01Z',
  }
}

function failedCraftJob(errorCode: string): Job {
  return {
    ...craftJob('craft_pattern_analysis_v2'),
    state: 'interrupted',
    progress_current: 1,
    error_code: errorCode,
    error_message: '恢复后需重新提交',
  }
}

function adaptationJob(): Job {
  return {
    ...craftJob('craft_pattern_analysis_v2'),
    id: 'pattern-adaptation-job',
    kind: 'pattern_adaptation',
    workflow: 'pattern_adaptation',
    current_step: '3 套原创迁移方案已生成',
  }
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('TaskCenter craft pattern jobs', () => {
  it('labels the approval-driven Canon reconciliation workflow', async () => {
    const job: Job = {
      ...craftJob('craft_pattern_analysis_v2'),
      id: 'canon-reconciliation-job',
      chapter_id: 'chapter-1',
      kind: 'review',
      workflow: 'canon_reconciliation_v1',
      state: 'running',
      progress_current: 1,
      progress_total: 2,
      current_step: '正在整理定稿证据',
      completed_at: null,
    }
    vi.spyOn(api, 'listJobs').mockResolvedValue([job])

    render(
      <TaskCenter
        projectId="project-1"
        chapters={[]}
        open
        onClose={vi.fn()}
        onChapterChanged={vi.fn()}
        onWorkspaceChanged={vi.fn()}
        onOpenReferenceLibrary={vi.fn()}
      />,
    )

    expect(await screen.findByText('定稿事实与偏好整理')).toBeVisible()
    expect(screen.getByText('正在整理定稿证据')).toBeVisible()
  })

  it('returns completed chapter work to the unified production desk without using legacy adoption', async () => {
    const productionJob: Job = {
      ...craftJob('craft_pattern_analysis_v2'),
      id: 'chapter-production-draft-job',
      chapter_id: 'chapter-7',
      kind: 'chapter_draft',
      workflow: 'chapter_production_draft',
      current_step: '正文候选已生成',
    }
    vi.spyOn(api, 'listJobs').mockResolvedValue([productionJob])
    const legacyResult = vi.spyOn(api, 'getAiChapterDraftJobResult')
    const onClose = vi.fn()
    const onOpenChapterProduction = vi.fn()
    const user = userEvent.setup()

    render(
      <TaskCenter
        projectId="project-1"
        chapters={[]}
        open
        onClose={onClose}
        onChapterChanged={vi.fn()}
        onWorkspaceChanged={vi.fn()}
        onOpenReferenceLibrary={vi.fn()}
        onOpenChapterProduction={onOpenChapterProduction}
      />,
    )

    expect(await screen.findByText('本章正文候选')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '回到单章生产台' }))
    expect(onClose).toHaveBeenCalledOnce()
    expect(onOpenChapterProduction).toHaveBeenCalledWith('chapter-7')
    expect(legacyResult).not.toHaveBeenCalled()
  })

  it('labels a single-book workflow correctly and navigates to its persisted assets', async () => {
    const job = craftJob('craft_pattern_analysis_v2')
    vi.spyOn(api, 'listJobs').mockResolvedValue([job])
    vi.spyOn(api, 'getJob').mockResolvedValue({
      ...job,
      chunks: [],
      attempts: [],
      artifacts: [],
      events: [],
    } satisfies JobDetail)
    const onClose = vi.fn()
    const onOpenReferenceLibrary = vi.fn()
    const refreshWorkspace = vi.spyOn(api, 'getProjectSummary')
    const user = userEvent.setup()

    render(
      <TaskCenter
        projectId="project-1"
        chapters={[]}
        open
        onClose={onClose}
        onChapterChanged={vi.fn()}
        onWorkspaceChanged={vi.fn()}
        onOpenReferenceLibrary={onOpenReferenceLibrary}
      />,
    )

    expect(await screen.findByText('单书写作模式拆解')).toBeVisible()
    expect(screen.queryByText('多书六维合成')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '查看模式素材' }))

    await waitFor(() => expect(onOpenReferenceLibrary).toHaveBeenCalledTimes(1))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(refreshWorkspace).not.toHaveBeenCalled()
  })

  it('sends a restored craft job to a fresh preflight instead of retrying it', async () => {
    const job = failedCraftJob('restored_requires_resubmission')
    vi.spyOn(api, 'listJobs').mockResolvedValue([job])
    const retry = vi.spyOn(api, 'retryJob')
    const onClose = vi.fn()
    const onOpenReferenceLibrary = vi.fn()
    const user = userEvent.setup()

    render(
      <TaskCenter
        projectId="project-1"
        chapters={[]}
        open
        onClose={onClose}
        onChapterChanged={vi.fn()}
        onWorkspaceChanged={vi.fn()}
        onOpenReferenceLibrary={onOpenReferenceLibrary}
      />,
    )

    await user.click(await screen.findByRole('button', { name: '重新预检' }))
    expect(retry).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onOpenReferenceLibrary).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('从缓存继续')).not.toBeInTheDocument()
  })

  it('turns a retry conflict into a clear fresh-preflight recovery action', async () => {
    const job = failedCraftJob('provider_error')
    vi.spyOn(api, 'listJobs').mockResolvedValue([job])
    vi.spyOn(api, 'retryJob').mockRejectedValue(
      new ApiError('该拆书任务需要从写作模式工作台重新预检并提交', 409),
    )
    const user = userEvent.setup()

    render(
      <TaskCenter
        projectId="project-1"
        chapters={[]}
        open
        onClose={vi.fn()}
        onChapterChanged={vi.fn()}
        onWorkspaceChanged={vi.fn()}
        onOpenReferenceLibrary={vi.fn()}
      />,
    )

    await user.click(await screen.findByRole('button', { name: '从断点继续' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('原预检依据已过期')
    expect(screen.getByRole('button', { name: '重新预检' })).toBeVisible()
  })

  it('returns a completed writing-pattern migration job to its three isolated candidates', async () => {
    const job = adaptationJob()
    vi.spyOn(api, 'listJobs').mockResolvedValue([job])
    vi.spyOn(api, 'getJob').mockResolvedValue({
      ...job,
      chunks: [], attempts: [], artifacts: [], events: [],
    } satisfies JobDetail)
    const onClose = vi.fn()
    const onOpenWritingPatterns = vi.fn()
    const user = userEvent.setup()

    render(
      <TaskCenter
        projectId="project-1"
        chapters={[]}
        open
        onClose={onClose}
        onChapterChanged={vi.fn()}
        onWorkspaceChanged={vi.fn()}
        onOpenReferenceLibrary={vi.fn()}
        onOpenWritingPatterns={onOpenWritingPatterns}
      />,
    )

    expect(await screen.findByText('写作模式原创迁移')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '查看三套候选' }))
    await waitFor(() => expect(onOpenWritingPatterns).toHaveBeenCalledTimes(1))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
