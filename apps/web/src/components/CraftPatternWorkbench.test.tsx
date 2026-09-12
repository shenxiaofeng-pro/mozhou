import type {
  CraftPatternAsset,
  CraftPatternAssetSummary,
  CraftPatternPreflight,
  Job,
  JobDetail,
  ReferenceWork,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api } from '../api'
import { CraftPatternWorkbench } from './CraftPatternWorkbench'

const projectId = '05f14cb8-d0ed-4489-bc20-31c44c1efbba'
const segmentAId = '7e4dbbc5-af7d-40a5-a8ee-69322bc8b667'
const segmentBId = '22a721d6-daf4-481d-b0a4-b91a0ad67327'

function work(
  id: string,
  title: string,
  segmentId: string,
  characters = 500_000,
): ReferenceWork {
  return {
    id,
    project_id: projectId,
    project_ids: [projectId],
    title,
    source_filename: `${title}.txt`,
    source_format: 'txt',
    rights_basis: 'self_owned',
    total_characters: characters,
    segment_target_characters: 500_000,
    content_sha256: 'a'.repeat(64),
    source_sha256: 'b'.repeat(64),
    source_encoding: 'utf-8',
    encoding_confidence: 1,
    import_state: 'ready',
    duplicate_of_id: null,
    source_spans: [],
    segments: [{
      id: segmentId,
      reference_work_id: id,
      ordinal: 1,
      start_char: 0,
      end_char: characters,
      character_count: characters,
      chapter_start: '第一章 入局',
      chapter_end: '第一百章 变局',
      created_at: '2026-09-11T00:00:00Z',
    }],
    created_at: '2026-09-11T00:00:00Z',
    updated_at: '2026-09-11T00:00:00Z',
  }
}

const workA = work('a44ada18-cf9e-4993-a4cb-bcd0442a33fe', '长篇甲', segmentAId)
const workB = work('5fe7dc51-86c8-40ff-9a0f-d007c36e7291', '长篇乙', segmentBId)

function workspace(referenceWorks: ReferenceWork[] = [workA, workB]): WorkspaceSummary {
  return {
    project: {
      id: projectId,
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
    reference_works: referenceWorks,
    reference_pattern_cards: [],
    reference_pattern_applications: [],
    continuity_issues: [],
    resume_card: null,
  }
}

function asset(
  id: string,
  title: string,
  workId: string,
  overrides: Partial<CraftPatternAssetSummary> = {},
): CraftPatternAssetSummary {
  return {
    id,
    series_id: `series-${id}`,
    asset_type: 'stage',
    version: 1,
    content_sha256: 'c'.repeat(64),
    lifecycle_state: 'active',
    lifecycle_revision: 0,
    source_work_ids: [workId],
    source_segment_ids: [workId === workA.id ? segmentAId : segmentBId],
    source_asset_version_ids: [],
    title,
    summary: `${title}总结章末钩子与兑现的阶段规律。`,
    provider: 'openai',
    model: 'gpt-5.6',
    prompt_version: 'craft-pattern-v2',
    created_at: '2026-09-11T00:00:00Z',
    updated_at: '2026-09-11T00:00:00Z',
    ...overrides,
  }
}

const assetA = asset('62c9d281-9194-4e5e-b358-f022d30c479e', '长篇甲·开局阶段', workA.id)
const assetB = asset('f3182e5f-1233-45d8-8efe-5da2c97d54ce', '长篇乙·开局阶段', workB.id, {
  asset_type: 'book_evolution',
})

function assetDetail(summary: CraftPatternAssetSummary): CraftPatternAsset {
  return {
    ...summary,
    schema_version: 2,
    source_job_id: null,
    author_focus: '比较章末钩子和情绪回报',
    craft_items: [{
      dimension: 'hook_mechanics',
      name: '行动结果反转钩子',
      observation: '先兑现小目标，再让结果暴露更高层压力。',
      transferable_rule: '每次小胜都改变下一章的行动条件。',
      adaptation_risk: '不要复用来源作品的具体事件和专名。',
      evidence: [{
        id: '5ad39267-cebe-4c39-8a06-a591a64dfb71',
        work_id: summary.source_work_ids[0],
        work_title: summary.source_work_ids[0] === workA.id ? workA.title : workB.title,
        segment_id: summary.source_segment_ids[0],
        stage_label: '第 1 阶段',
        chapter_label: '第 88–90 章',
        absolute_start_char: 420_000,
        absolute_end_char: 421_200,
        evidence_summary: '一次阶段小胜立即引出更高层对手的注意。',
        evidence_sha256: 'd'.repeat(64),
        confidence: 0.86,
      }],
    }],
  }
}

function preflight(
  operation: 'analysis' | 'fusion',
  overrides: Partial<CraftPatternPreflight> = {},
): CraftPatternPreflight {
  const analysis = operation === 'analysis'
  return {
    operation,
    selected_works: analysis
      ? [{ work_id: workA.id, title: workA.title, segment_count: 1, character_count: 500_000 }]
      : [
        { work_id: workA.id, title: workA.title, segment_count: 1, character_count: 500_000 },
        { work_id: workB.id, title: workB.title, segment_count: 1, character_count: 500_000 },
      ],
    selected_segments: analysis ? [{
      segment_id: segmentAId,
      work_id: workA.id,
      work_title: workA.title,
      ordinal: 1,
      start_char: 0,
      end_char: 500_000,
      chapter_start: '第一章 入局',
      chapter_end: '第一百章 变局',
      character_count: 500_000,
    }] : [],
    selected_assets: analysis ? [] : [assetA, assetB].map((item) => ({
      asset_version_id: item.id,
      content_sha256: item.content_sha256,
      title: item.title,
      asset_type: item.asset_type,
      version: item.version,
      source_work_ids: item.source_work_ids,
    })),
    selected_character_count: analysis ? 500_000 : 0,
    stage_card_count: analysis ? 1 : 0,
    book_evolution_count: analysis ? 1 : 0,
    fusion_material_count: analysis ? 0 : 1,
    map_calls: analysis ? 4 : 0,
    stage_calls: analysis ? 1 : 0,
    book_calls: analysis ? 1 : 0,
    fusion_calls: analysis ? 0 : 1,
    planned_calls: analysis ? 6 : 1,
    cache_hit_calls: analysis ? 2 : 0,
    uncached_calls: analysis ? 4 : 1,
    estimated_input_tokens: 12_500,
    estimated_output_tokens: 3_200,
    estimated_cost_microusd: 25_000,
    profile_id: 'profile-1',
    profile_name: '长篇分析线路',
    provider: 'openai',
    model: 'gpt-5.6',
    data_types: analysis ? ['参考作品选中阶段原文'] : ['写作模式素材'],
    content_scope: analysis ? '仅发送所选阶段，正文创作不可读取' : '仅发送不可变抽象素材，不读取原文',
    prompt_version: 'craft-pattern-v2',
    preflight_sha256: analysis ? 'e'.repeat(64) : 'f'.repeat(64),
    ...overrides,
  }
}

function completedJob(operation: 'analysis' | 'fusion'): Job {
  return {
    id: operation === 'analysis' ? 'analysis-job' : 'fusion-job',
    project_id: projectId,
    chapter_id: null,
    parent_job_id: null,
    kind: 'reference_fusion',
    workflow: operation === 'analysis' ? 'craft_pattern_analysis_v2' : 'craft_pattern_fusion_v2',
    state: 'succeeded',
    idempotency_key: `${operation}-job-key`,
    progress_current: 1,
    progress_total: 1,
    current_step: '素材已生成',
    estimated_calls: 1,
    completed_calls: 1,
    provider: 'openai',
    provider_profile_id: 'profile-1',
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

beforeEach(() => {
  vi.spyOn(api, 'listReferenceCraftAssets').mockResolvedValue([])
  vi.spyOn(api, 'listJobs').mockResolvedValue([])
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('CraftPatternWorkbench', () => {
  it('keeps completed assets when their response arrives after the job state update', async () => {
    const runningJob: Job = {
      ...completedJob('analysis'),
      state: 'running',
      progress_current: 0,
      completed_calls: 0,
      completed_at: null,
    }
    vi.mocked(api.listJobs).mockResolvedValue([runningJob])
    vi.spyOn(api, 'getJob').mockResolvedValue({
      ...completedJob('analysis'),
      chunks: [],
      attempts: [],
      artifacts: [],
      events: [],
    } satisfies JobDetail)
    let resolveAssets!: (assets: CraftPatternAsset[]) => void
    const delayedAssets = new Promise<CraftPatternAsset[]>((resolve) => {
      resolveAssets = resolve
    })
    const resultCall = vi.spyOn(api, 'listJobReferenceCraftAssets').mockReturnValue(delayedAssets)

    render(<CraftPatternWorkbench workspace={workspace([workA])} onWorkspaceChanged={vi.fn()} />)
    await waitFor(() => expect(resultCall).toHaveBeenCalledWith('analysis-job'))

    await act(async () => {
      resolveAssets([assetDetail(assetA)])
      await delayedAssets
    })

    expect(await screen.findByRole('heading', { name: assetA.title })).toBeVisible()
    expect(screen.getByRole('status')).toHaveTextContent('已生成 1 张可追溯模式素材')
    expect(screen.queryByText('生成单书演变卡')).not.toBeInTheDocument()
  })

  it('preflights and submits one selected book stage with an explicit known-cost budget', async () => {
    const previewResult = preflight('analysis')
    const previewCall = vi.spyOn(api, 'previewCraftPatternAnalysis').mockResolvedValue(previewResult)
    const startCall = vi.spyOn(api, 'startCraftPatternAnalysisJob').mockResolvedValue(completedJob('analysis'))
    const user = userEvent.setup()

    render(<CraftPatternWorkbench workspace={workspace()} onWorkspaceChanged={vi.fn()} />)

    expect(screen.queryByText(/多书融合需要至少两本/)).not.toBeInTheDocument()
    await user.click(await screen.findByRole('checkbox', { name: '选择长篇甲第 1 阶段' }))
    await user.type(screen.getByLabelText('这次想重点研究什么？'), '章末钩子')
    await user.click(screen.getByRole('button', { name: '预检“拆一本书”' }))

    expect(previewCall).toHaveBeenCalledWith(projectId, {
      selected_segment_ids: [segmentAId],
      author_focus: '章末钩子',
    })
    expect(await screen.findByLabelText('拆书调用预检')).toHaveTextContent('长篇甲')
    expect(screen.getByLabelText('拆书调用预检')).toHaveTextContent('缓存命中2')
    expect(screen.getByLabelText('拆书调用预检')).toHaveTextContent('预计计费调用4')
    expect(screen.getByLabelText('拆书调用预检')).toHaveTextContent('50 万')

    await user.type(screen.getByRole('spinbutton', { name: /预估费用上限/ }), '0.025')
    await user.click(screen.getByRole('checkbox', { name: /确认按上述范围发送给 gpt-5.6/ }))
    await user.click(screen.getByRole('button', { name: '确认预检并开始拆书' }))

    expect(startCall).toHaveBeenCalledWith(projectId, {
      selected_segment_ids: [segmentAId],
      author_focus: '章末钩子',
      expected_preflight_sha256: previewResult.preflight_sha256,
      confirm_external_processing: true,
      confirm_unknown_cost: false,
      max_estimated_cost_microusd: 25_000,
    })
  })

  it('makes a cache-only run explicit without inventing cost or a budget', async () => {
    vi.spyOn(api, 'previewCraftPatternAnalysis').mockResolvedValue(preflight('analysis', {
      planned_calls: 6,
      cache_hit_calls: 6,
      uncached_calls: 0,
      estimated_cost_microusd: 0,
    }))
    const startCall = vi.spyOn(api, 'startCraftPatternAnalysisJob').mockResolvedValue(completedJob('analysis'))
    const user = userEvent.setup()

    render(<CraftPatternWorkbench workspace={workspace([workA])} onWorkspaceChanged={vi.fn()} />)
    await user.click(await screen.findByRole('checkbox', { name: '选择长篇甲第 1 阶段' }))
    await user.click(screen.getByRole('button', { name: '预检“拆一本书”' }))

    expect(await screen.findByText('本次全部复用本地缓存，确认按这份预检生成素材。')).toBeVisible()
    expect(screen.queryByRole('spinbutton', { name: /预估费用上限/ })).not.toBeInTheDocument()
    await user.click(screen.getByRole('checkbox', { name: /本次全部复用本地缓存/ }))
    await user.click(screen.getByRole('button', { name: '确认预检并开始拆书' }))

    expect(startCall).toHaveBeenCalledWith(projectId, expect.objectContaining({
      confirm_external_processing: false,
      confirm_unknown_cost: false,
      max_estimated_cost_microusd: null,
    }))
  })

  it('requires a separate acknowledgement when the external-call cost is unknown', async () => {
    vi.spyOn(api, 'previewCraftPatternAnalysis').mockResolvedValue(preflight('analysis', {
      estimated_cost_microusd: null,
    }))
    const startCall = vi.spyOn(api, 'startCraftPatternAnalysisJob').mockResolvedValue(completedJob('analysis'))
    const user = userEvent.setup()

    render(<CraftPatternWorkbench workspace={workspace([workA])} onWorkspaceChanged={vi.fn()} />)
    await user.click(await screen.findByRole('checkbox', { name: '选择长篇甲第 1 阶段' }))
    await user.click(screen.getByRole('button', { name: '预检“拆一本书”' }))
    expect(await screen.findByText('费用未知')).toBeVisible()

    await user.click(screen.getByRole('checkbox', { name: /确认按上述范围发送/ }))
    expect(screen.getByRole('button', { name: '确认预检并开始拆书' })).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: /我理解费用未知/ }))
    await user.click(screen.getByRole('button', { name: '确认预检并开始拆书' }))

    expect(startCall).toHaveBeenCalledWith(projectId, expect.objectContaining({
      confirm_external_processing: true,
      confirm_unknown_cost: true,
      max_estimated_cost_microusd: null,
    }))
  })

  it('loads abstract evidence only on demand and updates lifecycle with conflict recovery', async () => {
    vi.mocked(api.listReferenceCraftAssets)
      .mockResolvedValueOnce([assetA])
      .mockResolvedValueOnce([{ ...assetA, lifecycle_state: 'archived', lifecycle_revision: 3 }])
    const detailCall = vi.spyOn(api, 'getReferenceCraftAsset').mockResolvedValue(assetDetail(assetA))
    vi.spyOn(api, 'updateCraftPatternLifecycle').mockRejectedValue(new ApiError('素材状态已变化', 409))
    vi.spyOn(api, 'getProjectSummary').mockResolvedValue(workspace())
    const changed = vi.fn()
    const user = userEvent.setup()

    render(<CraftPatternWorkbench workspace={workspace()} onWorkspaceChanged={changed} />)
    expect(await screen.findByRole('heading', { name: assetA.title })).toBeVisible()
    expect(detailCall).not.toHaveBeenCalled()
    expect(screen.queryByText('来源作品原文绝不能出现在这里')).not.toBeInTheDocument()

    await user.click(screen.getByText('查看技法与来源证据'))
    await screen.findByText('一次阶段小胜立即引出更高层对手的注意。')
    await user.click(screen.getByText('查看 1 条来源证据'))
    expect(screen.getByText('一次阶段小胜立即引出更高层对手的注意。')).toBeVisible()
    expect(screen.getByText(/第 88–90 章 · 420,001–421,200 字/)).toBeVisible()
    expect(screen.getByText('86% 置信')).toBeVisible()
    expect(detailCall).toHaveBeenCalledWith(assetA.id, projectId)

    await user.click(screen.getByRole('button', { name: `归档素材《${assetA.title}》` }))
    expect(await screen.findByRole('alert')).toHaveTextContent('已载入最新素材状态')
    expect(screen.getByText('已归档')).toBeVisible()
    expect(changed).toHaveBeenCalled()
  })

  it('opens the immutable parent card from a book-evolution lineage chip', async () => {
    const bookAsset = asset('57a9cb9d-6595-42fd-8921-1f9b14b1bd31', '长篇甲·整书演变', workA.id, {
      asset_type: 'book_evolution',
      source_asset_version_ids: [assetA.id],
    })
    vi.mocked(api.listReferenceCraftAssets).mockResolvedValue([assetA, bookAsset])
    const detailCall = vi.spyOn(api, 'getReferenceCraftAsset').mockImplementation(async (assetId) => (
      assetDetail(assetId === bookAsset.id ? bookAsset : assetA)
    ))
    const user = userEvent.setup()

    render(<CraftPatternWorkbench workspace={workspace([workA])} onWorkspaceChanged={vi.fn()} />)
    const bookHeading = await screen.findByRole('heading', { name: bookAsset.title })
    const bookCard = bookHeading.closest('.craft-asset-card')
    expect(bookCard).not.toBeNull()
    await user.click(within(bookCard as HTMLElement).getByText('查看技法与来源证据'))
    await user.click(await within(bookCard as HTMLElement).findByRole('button', { name: assetA.title }))

    await waitFor(() => {
      expect(detailCall).toHaveBeenCalledWith(assetA.id, projectId)
    })
  })

  it('fuses only immutable saved assets from two books and keeps long catalogs complete', async () => {
    const longAssets = Array.from({ length: 60 }, (_, index) => asset(
      `asset-${String(index).padStart(2, '0')}`,
      `阶段素材 ${String(index + 1).padStart(2, '0')}`,
      index % 2 === 0 ? workA.id : workB.id,
    ))
    longAssets[0] = assetA
    longAssets[1] = assetB
    vi.mocked(api.listReferenceCraftAssets).mockResolvedValue(longAssets)
    const fusionPreview = preflight('fusion', {
      cache_hit_calls: 1,
      uncached_calls: 0,
      estimated_cost_microusd: 0,
    })
    const previewCall = vi.spyOn(api, 'previewCraftPatternFusion').mockResolvedValue(fusionPreview)
    const startCall = vi.spyOn(api, 'startCraftPatternFusionJob').mockResolvedValue(completedJob('fusion'))
    const user = userEvent.setup()
    const { container } = render(<CraftPatternWorkbench workspace={workspace()} onWorkspaceChanged={vi.fn()} />)

    await screen.findByRole('heading', { name: assetA.title })
    expect(container.querySelectorAll('.craft-asset-card')).toHaveLength(60)
    expect(screen.queryByText(/多书融合需要至少两本/)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '预检“融合多本”' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('至少两本不同来源作品')

    await user.click(screen.getByRole('checkbox', { name: `选择《${assetA.title}》用于多书融合` }))
    await user.click(screen.getByRole('checkbox', { name: `选择《${assetB.title}》用于多书融合` }))
    await user.click(screen.getByRole('button', { name: '预检“融合多本”' }))
    await screen.findByLabelText('拆书调用预检')

    expect(previewCall).toHaveBeenCalledWith(projectId, {
      selected_asset_version_ids: [assetA.id, assetB.id],
      author_focus: '',
    })
    await user.click(screen.getByRole('checkbox', { name: /本次全部复用本地缓存/ }))
    await user.click(screen.getByRole('button', { name: '确认预检并融合多本' }))
    expect(startCall).toHaveBeenCalledWith(projectId, expect.objectContaining({
      selected_asset_version_ids: [assetA.id, assetB.id],
    }))
    expect(startCall.mock.calls[0]?.[1]).not.toHaveProperty('selected_segment_ids')
  })
})
