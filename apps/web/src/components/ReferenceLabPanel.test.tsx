import type {
  OriginalityStatus,
  ReferenceApplicationLifecycleState,
  ReferenceBlueprintState,
  ReferencePatternApplication,
  ReferencePatternCard,
  Workspace,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api } from '../api'
import { ReferenceLabPanel } from './ReferenceLabPanel'
import { ReferenceLibraryPage } from './ReferenceLibraryPage'

const dimension = {
  summary: '时代机会推动主角做出选择。',
  source_segment_ids: [],
  transferable_logic: '保留功能，重写具体人物与事件。',
  adaptation_risk: '避免沿用专名和场景顺序。',
}

const patternCard: ReferencePatternCard = {
  id: 'pattern-card-1',
  project_id: 'project-1',
  source_job_id: null,
  selected_segment_ids: [],
  author_focus: '测试参考模式',
  provider: 'openai',
  model: 'test-model',
  created_at: '2026-09-11T00:00:00Z',
  era: dimension,
  core_desire: dimension,
  conflict_causality: dimension,
  resource_system: dimension,
  key_scene_sequence: dimension,
  ending: dimension,
  shared_patterns: ['把信息差转化为行动'],
  differences: ['具体人物和场景不同'],
  relationship_recomposition: '重组为合作者与竞争者。',
  originality_risks: ['不复用具体桥段'],
}

const blueprint: ReferenceBlueprintState = {
  dimensions: {
    era: {
      source: dimension,
      mode: 'adjust',
      author_edits: '换成当前作品的时代背景。',
      generated_variant: {
        summary: '本地产业变迁带来机会。',
        transferable_logic: '用行动验证信息差。',
      },
      version: 1,
      locked: false,
      named_entities: [],
      source_beats: [],
      key_beats: [],
    },
  },
  relationship: {
    source: patternCard.relationship_recomposition,
    mode: 'reconstruct',
    author_edits: '重组人物关系。',
    generated_variant: '合作者和竞争者形成三角制衡。',
    version: 1,
    locked: false,
    relationships: [],
  },
}

function application(
  lifecycleState: ReferenceApplicationLifecycleState,
  originalityStatus: OriginalityStatus,
  lifecycleRevision = 0,
): ReferencePatternApplication {
  return {
    id: 'application-1',
    project_id: 'project-1',
    pattern_card_id: patternCard.id,
    lifecycle_state: lifecycleState,
    lifecycle_revision: lifecycleRevision,
    selected_dimensions: ['era'],
    dimensions: {
      era: {
        summary: dimension.summary,
        transferable_logic: dimension.transferable_logic,
      },
    },
    relationship_recomposition: patternCard.relationship_recomposition,
    application_note: '仅参考抽象功能。',
    blueprint,
    originality_status: originalityStatus,
    risk_level: originalityStatus === 'passed' ? 'low' : 'medium',
    latest_report_id: 'report-1',
    threshold_version: 'originality-rules-v1',
    revision: 0,
    created_at: '2026-09-11T00:00:00Z',
    updated_at: '2026-09-11T00:00:00Z',
  }
}

function workspaceWith(...applications: ReferencePatternApplication[]): WorkspaceSummary {
  return {
    project: {
      id: 'project-1',
      title: '回到九八年的南平',
      genre: 'urban_rebirth',
      rebirth_year: 1998,
      rebirth_location: '福建南平',
      chapter_target_words: 3000,
      safety_buffer_chapters: 3,
      created_at: '2026-09-11T00:00:00Z',
      updated_at: '2026-09-11T00:00:00Z',
    },
    chapters: [],
    topic_decision: null,
    next_action: 'continue_writing',
    book_blueprint: null,
    volume_plans: [],
    rolling_chapter_plans: [],
    timeline_events: [],
    story_facts: [],
    fact_change_sets: [],
    future_knowledge: [],
    story_entities: [],
    story_threads: [],
    source_cards: [],
    reference_works: [],
    reference_pattern_cards: [patternCard],
    reference_pattern_applications: applications,
    continuity_issues: [],
    resume_card: null,
  }
}

function LifecycleHarness({
  initialWorkspace,
  onWorkspaceChanged = () => undefined,
}: {
  initialWorkspace: WorkspaceSummary
  onWorkspaceChanged?: (workspace: WorkspaceSummary) => void
}) {
  const [workspace, setWorkspace] = useState(initialWorkspace)
  function updateWorkspace(updated: Workspace | WorkspaceSummary) {
    const summary = updated as WorkspaceSummary
    setWorkspace(summary)
    onWorkspaceChanged(summary)
  }
  return <ReferenceLabPanel workspace={workspace} onWorkspaceChanged={updateWorkspace} />
}

beforeEach(() => {
  vi.spyOn(api, 'listJobs').mockResolvedValue([])
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('reference application lifecycle', () => {
  it('pauses an active unchecked blueprint and keeps activation disabled', async () => {
    const current = application('active', 'review_required')
    const update = vi.spyOn(api, 'updateReferenceApplicationLifecycle').mockResolvedValue({
      ...current,
      lifecycle_state: 'draft',
      lifecycle_revision: 1,
    })
    const user = userEvent.setup()
    render(<LifecycleHarness initialWorkspace={workspaceWith(current)} />)

    expect(screen.getByText('使用中')).toBeVisible()
    expect(screen.getByText(/可能阻断 AI 写作/)).toBeVisible()
    await user.click(screen.getByRole('button', { name: '暂停用于 AI' }))

    expect(update).toHaveBeenCalledWith('project-1', 'application-1', {
      lifecycle_state: 'draft',
      expected_lifecycle_revision: 0,
    })
    expect(await screen.findByText('已暂停')).toBeVisible()
    expect(screen.getByRole('button', { name: '启用给 AI' })).toBeDisabled()
    expect(screen.getByText(/通过原创性检查后才能启用/)).toBeVisible()
  })

  it('enables a passed draft with the lifecycle revision', async () => {
    const current = application('draft', 'passed', 2)
    const update = vi.spyOn(api, 'updateReferenceApplicationLifecycle').mockResolvedValue({
      ...current,
      lifecycle_state: 'active',
      lifecycle_revision: 3,
    })
    const user = userEvent.setup()
    render(<LifecycleHarness initialWorkspace={workspaceWith(current)} />)

    await user.click(screen.getByRole('button', { name: '启用给 AI' }))

    expect(update).toHaveBeenCalledWith('project-1', 'application-1', {
      lifecycle_state: 'active',
      expected_lifecycle_revision: 2,
    })
    expect(await screen.findByText('使用中')).toBeVisible()
    expect(screen.getByText(/已启用给 AI/)).toBeVisible()
  })

  it('archives an application and restores it only as a draft', async () => {
    const current = application('active', 'passed')
    const update = vi.spyOn(api, 'updateReferenceApplicationLifecycle')
      .mockResolvedValueOnce({
        ...current,
        lifecycle_state: 'archived',
        lifecycle_revision: 1,
      })
      .mockResolvedValueOnce({
        ...current,
        lifecycle_state: 'draft',
        lifecycle_revision: 2,
      })
    const user = userEvent.setup()
    render(<LifecycleHarness initialWorkspace={workspaceWith(current)} />)

    await user.click(screen.getByRole('button', { name: '归档' }))
    expect(await screen.findByText('已归档')).toBeVisible()
    expect(screen.queryByRole('button', { name: `应用到《${workspaceWith().project.title}》` })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '恢复为草稿' }))

    expect(update).toHaveBeenNthCalledWith(2, 'project-1', 'application-1', {
      lifecycle_state: 'draft',
      expected_lifecycle_revision: 1,
    })
    expect(await screen.findByText('已暂停')).toBeVisible()
    expect(screen.getByText(/已恢复为草稿/)).toBeVisible()
  })

  it('refreshes the workspace after a lifecycle conflict without guessing the state', async () => {
    const current = application('active', 'passed')
    const latest = application('archived', 'passed', 4)
    vi.spyOn(api, 'updateReferenceApplicationLifecycle').mockRejectedValue(
      new ApiError('参考应用已有新版本，请刷新后再处理', 409),
    )
    vi.spyOn(api, 'getProjectSummary').mockResolvedValue(workspaceWith(latest))
    const user = userEvent.setup()
    render(<LifecycleHarness initialWorkspace={workspaceWith(current)} />)

    await user.click(screen.getByRole('button', { name: '暂停用于 AI' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('已刷新最新状态')
    expect(screen.getByText('已归档')).toBeVisible()
    expect(screen.queryByText('已暂停')).not.toBeInTheDocument()
  })

  it('counts only active applications in the library summary', () => {
    render(
      <ReferenceLibraryPage
        workspace={workspaceWith(application('archived', 'passed'))}
        onWorkspaceChanged={vi.fn()}
        onBack={vi.fn()}
        onOpenTaskCenter={vi.fn()}
        onOpenGlobalLibrary={vi.fn()}
      />,
    )

    const label = screen.getByText('使用中')
    expect(label.tagName).toBe('DT')
    expect(label.parentElement).toHaveTextContent('使用中0')
  })
})
