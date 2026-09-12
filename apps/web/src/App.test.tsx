import type {
  AuthorNextAction,
  BookBlueprint,
  BookBlueprintContent,
  Chapter,
  ChapterDraftCandidate,
  ChapterOutlineCandidate,
  ChapterProductionOutboundPreview,
  ChapterProductionSnapshot,
  CreativePlanImpactPreview,
  Job,
  JobDetail,
  JobKind,
  ModelProfile,
  ReferenceBlueprintState,
  TopicDecision,
  TopicDecisionField,
  Workspace,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { App } from './App'
import { ApiError, api } from './api'

const workspace: Workspace = {
  project: {
    id: '05f14cb8-d0ed-4489-bc20-31c44c1efbba',
    title: '回到九八年的南平',
    genre: 'urban_rebirth',
    rebirth_year: 1998,
    rebirth_location: '福建南平',
    chapter_target_words: 3000,
    safety_buffer_chapters: 3,
    created_at: '2026-08-08T00:00:00Z',
    updated_at: '2026-08-08T00:00:00Z',
  },
  chapters: [{
    id: '19c7daae-21f2-42f6-9520-daec63e4a726',
    project_id: '05f14cb8-d0ed-4489-bc20-31c44c1efbba',
    volume_number: 1,
    chapter_number: 1,
    title: '第一章 未命名',
    content: '',
    reader_promise: '',
    opening_hook: '停产通知提前贴出',
    state_change: '保住父亲的工作',
    emotional_payoff: '',
    ending_cliffhanger: '厂长认出了主角',
    status: 'planned',
    revision: 0,
    updated_at: '2026-08-08T00:00:00Z',
  }],
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
  reference_pattern_cards: [],
  reference_pattern_applications: [],
  continuity_issues: [],
  resume_card: null,
}

const topicFields: TopicDecisionField[] = [
  'target_platform',
  'target_audience',
  'subgenre',
  'premise',
  'core_desire',
  'long_term_promise',
  'first_three_chapter_promise',
  'constraints',
  'forbidden_elements',
  'reference_purpose',
  'reality_anchor',
  'first_ten_chapter_goal',
]

function topicDecision(overrides: Partial<TopicDecision> = {}): TopicDecision {
  return {
    id: 'topic-decision-1',
    project_id: workspace.project.id,
    content: {
      target_platform: '番茄小说',
      target_audience: '喜欢实业升级与家庭情感的读者',
      subgenre: '都市重生·实业创业',
      premise: '失意工程师回到 1998 年南平，从停产纸厂开始改命。',
      core_desire: '挽回家庭，也让技术真正改变故乡。',
      long_term_promise: '每卷完成一次产业升级。',
      first_three_chapter_promise: '停产名单、救厂小胜、债务危机。',
      constraints: ['产业细节有依据'],
      forbidden_elements: ['不写无代价系统'],
      reference_purpose: '只参考资源循环和章末钩子。',
      reality_anchor: '1998 年闽北纸业与交通资料。',
      first_ten_chapter_goal: '保住第一条产线。',
    },
    status: 'draft',
    locks: Object.fromEntries(topicFields.map((field) => [field, false])) as Record<TopicDecisionField, boolean>,
    field_versions: Object.fromEntries(topicFields.map((field) => [field, 1])) as Record<TopicDecisionField, number>,
    rejection_reasons: {},
    source_template_id: null,
    source_job_id: null,
    source_candidate_ids: [],
    revision: 1,
    confirmed_revision: null,
    plan_stale: false,
    created_at: '2026-09-11T00:00:00Z',
    updated_at: '2026-09-11T00:00:00Z',
    ...overrides,
  }
}

function withTopic(
  decision = topicDecision(),
  nextAction: Workspace['next_action'] = 'confirm_topic',
): Workspace {
  return { ...workspace, topic_decision: decision, next_action: nextAction }
}

function withAuthorAction(
  source: Workspace,
  overrides: Partial<AuthorNextAction> = {},
): Workspace {
  return {
    ...source,
    author_next_action: {
      kind: 'plan_chapter',
      target_view: 'writing',
      target_stage: 'plan',
      chapter_id: source.chapters[0]?.id ?? null,
      chapter_number: source.chapters[0]?.chapter_number ?? null,
      last_approved_chapter_id: null,
      reconciliation_id: null,
      rolling_plan_id: null,
      rolling_plan_replenishment_id: null,
      blocked: false,
      ...overrides,
    },
  }
}

function summarizeWorkspace(source: Workspace): WorkspaceSummary {
  return {
    ...source,
    chapters: source.chapters.map(({ content, ...chapter }) => ({
      ...chapter,
      has_content: content.trim().length > 0,
      content_characters: content.length,
    })),
  }
}

function queuedJob(kind: JobKind, chapterId: string | null = null): Job {
  return {
    id: `${kind}-job`,
    project_id: workspace.project.id,
    chapter_id: chapterId,
    parent_job_id: null,
    kind,
    workflow: '',
    state: 'queued',
    idempotency_key: `${kind}-test`,
    progress_current: 0,
    progress_total: 1,
    current_step: '',
    estimated_calls: 1,
    completed_calls: 0,
    provider: 'openai',
    provider_profile_id: null,
    model: 'gpt-5.6',
    lease_owner: null,
    lease_expires_at: null,
    heartbeat_at: null,
    error_code: null,
    error_message: null,
    created_at: '2026-08-09T00:00:00Z',
    updated_at: '2026-08-09T00:00:00Z',
    started_at: null,
    completed_at: null,
  }
}

function productionOutline(chapter: Chapter): ChapterOutlineCandidate {
  return {
    id: 'production-outline-1',
    production_id: 'chapter-production-1',
    ordinal: 1,
    label: 'AI 章纲',
    state: 'available',
    current_version: {
      id: 'production-outline-version-1',
      candidate_id: 'production-outline-1',
      revision: 0,
      content: {
        title: chapter.title,
        reader_promise: chapter.reader_promise,
        opening_hook: chapter.opening_hook,
        state_change: chapter.state_change,
        emotional_payoff: chapter.emotional_payoff,
        ending_cliffhanger: chapter.ending_cliffhanger,
        scene_beats: [],
      },
      content_sha256: 'a'.repeat(64),
      operation: 'model_draft',
      parent_version_id: null,
      trace: null,
      source_job_id: 'outline-job',
      created_at: '2026-09-12T00:00:00Z',
    },
    created_at: '2026-09-12T00:00:00Z',
    updated_at: '2026-09-12T00:00:00Z',
  }
}

function productionCandidate(chapter: Chapter, content = '这是 AI 主写、尚未采用的正文候选。'): ChapterDraftCandidate {
  return {
    id: 'production-candidate-1',
    production_id: 'chapter-production-1',
    label: '正面交锋版',
    state: 'available',
    source_outline_candidate_id: 'production-outline-1',
    source_outline_version_id: 'production-outline-version-1',
    source_outline_revision: 0,
    source_outline_content_sha256: 'a'.repeat(64),
    current_version: {
      id: 'production-candidate-version-1',
      candidate_id: 'production-candidate-1',
      revision: 0,
      content,
      content_sha256: 'b'.repeat(64),
      operation: 'model_draft',
      parent_version_id: null,
      restored_from_version_id: null,
      trace: null,
      source_job_id: 'draft-job',
      instruction: '',
      created_at: '2026-09-12T00:00:00Z',
    },
    locks: [],
    created_at: '2026-09-12T00:00:00Z',
    updated_at: '2026-09-12T00:00:00Z',
  }
}

function productionSnapshot(
  chapter: Chapter,
  options: { outline?: ChapterOutlineCandidate; candidate?: ChapterDraftCandidate; baseRevision?: number } = {},
): ChapterProductionSnapshot {
  const outlines = options.outline ? [options.outline] : []
  const candidates = options.candidate ? [options.candidate] : []
  return {
    production: {
      id: 'chapter-production-1',
      project_id: chapter.project_id,
      chapter_id: chapter.id,
      base_chapter_revision: options.baseRevision ?? chapter.revision,
      base_chapter_content_sha256: 'c'.repeat(64),
      state: candidates.length > 0 ? 'candidate_ready' : outlines.length > 0 ? 'outline_ready' : 'created',
      revision: 0,
      current_outline_candidate_id: options.outline?.id ?? null,
      created_at: '2026-09-12T00:00:00Z',
      updated_at: '2026-09-12T00:00:00Z',
    },
    outlines,
    candidates,
    preflight_checks: [],
    reviews: [],
    outcomes: [],
  }
}

function productionPreview(purpose: 'brief' | 'draft' | 'candidate_review' = 'brief'): ChapterProductionOutboundPreview {
  return {
    purpose,
    profile_id: null,
    profile_name: '当前会话线路',
    provider: 'openai',
    model: 'gpt-5.6',
    data_types: ['已编译创作上下文'],
    content_scope: '当前章节与已确认资料',
    character_count: 1200,
    estimated_input_tokens: 900,
    estimated_output_tokens: 800,
    estimated_cost_microusd: 15_000,
    context_packet_id: 'production-packet-1',
    context_packet_sha256: 'd'.repeat(64),
    context_dependency_fingerprint_sha256: 'e'.repeat(64),
    context_compiler_version: 'creative-context-v2',
  }
}

function jobDetail(job: Job): JobDetail {
  return {
    ...job,
    chunks: [],
    attempts: [],
    artifacts: [],
    events: [],
  }
}

async function openUtilityDestination(name: string): Promise<void> {
  fireEvent.click(screen.getByRole('button', { name: '打开辅助工具' }))
  fireEvent.click(await screen.findByRole('button', { name }))
}

beforeEach(() => {
  window.history.replaceState({}, '', '/')
  window.localStorage.clear()
  vi.spyOn(api, 'listProjects').mockResolvedValue([])
  vi.spyOn(api, 'getProjectSummary').mockResolvedValue(summarizeWorkspace(workspace))
  vi.spyOn(api, 'listJobs').mockResolvedValue([])
  vi.spyOn(api, 'getChapter').mockResolvedValue(workspace.chapters[0])
  vi.spyOn(api, 'getAiStatus').mockResolvedValue({
    configured: false,
    provider: 'unavailable',
    model: '',
    key_source: null,
    profile_id: null,
    profile_name: null,
  })
  vi.spyOn(api, 'listAiProfiles').mockResolvedValue([])
  vi.spyOn(api, 'listAiTaskDefaults').mockResolvedValue([])
  vi.spyOn(api, 'listContextDirectives').mockResolvedValue([])
  vi.spyOn(api, 'listComicProjects').mockResolvedValue([])
  vi.spyOn(api, 'listReferenceCraftAssets').mockResolvedValue([])
  vi.spyOn(api, 'getCurrentChapterProduction').mockRejectedValue(new ApiError('尚无单章生产记录', 404))
  vi.spyOn(api, 'createChapterProduction').mockImplementation(async (_projectId, chapterId) => {
    const current = workspace.chapters.find((item) => item.id === chapterId) ?? workspace.chapters[0]
    return productionSnapshot(current)
  })
})

afterEach(() => {
  cleanup()
  window.history.replaceState({}, '', '/')
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('restores a deep-linked project, chapter and author stage from the URL', async () => {
    const secondChapter: Chapter = {
      ...workspace.chapters[0],
      id: 'deep-linked-chapter-2',
      chapter_number: 2,
      title: '第2章 纸厂夜班',
    }
    const routedWorkspace = withAuthorAction({
      ...workspace,
      chapters: [workspace.chapters[0], secondChapter],
    }, {
      kind: 'generate_chapter_candidate',
      target_stage: 'candidate',
      chapter_id: secondChapter.id,
      chapter_number: 2,
    })
    window.history.replaceState({}, '', `/?project=${workspace.project.id}&view=writing&stage=review&chapter=${secondChapter.id}`)
    vi.mocked(api.listProjects).mockResolvedValue([workspace.project])
    vi.mocked(api.getProjectSummary).mockResolvedValue(summarizeWorkspace(routedWorkspace))
    vi.mocked(api.getChapter).mockImplementation(async (chapterId) => (
      chapterId === secondChapter.id ? secondChapter : workspace.chapters[0]
    ))

    render(<App />)

    expect(await screen.findByRole('heading', { name: secondChapter.title })).toBeVisible()
    expect(screen.getByRole('button', { name: /4，审校定稿/ })).toHaveAttribute('aria-current', 'step')
    expect(window.location.search).toContain(`chapter=${secondChapter.id}`)
    expect(window.location.search).toContain('stage=review')
  })

  it('opens a project at the server-selected current task', async () => {
    const secondChapter: Chapter = {
      ...workspace.chapters[0],
      id: 'suggested-chapter-2',
      chapter_number: 2,
      title: '第2章 名单之外',
    }
    const routedWorkspace = withAuthorAction({
      ...workspace,
      chapters: [workspace.chapters[0], secondChapter],
    }, {
      kind: 'generate_chapter_candidate',
      target_stage: 'candidate',
      chapter_id: secondChapter.id,
      chapter_number: 2,
      last_approved_chapter_id: workspace.chapters[0].id,
    })
    vi.mocked(api.listProjects).mockResolvedValue([workspace.project])
    vi.mocked(api.getProjectSummary).mockResolvedValue(summarizeWorkspace(routedWorkspace))
    vi.mocked(api.getChapter).mockImplementation(async (chapterId) => (
      chapterId === secondChapter.id ? secondChapter : workspace.chapters[0]
    ))
    const user = userEvent.setup()

    render(<App />)
    await user.click(await screen.findByRole('button', { name: `打开《${workspace.project.title}》` }))

    expect(await screen.findByRole('heading', { name: secondChapter.title })).toBeVisible()
    expect(screen.getByRole('button', { name: '生成第 2 章候选' })).toBeVisible()
    expect(window.location.search).toContain('stage=candidate')
  })

  it('restores another project from browser history without leaking the previous chapter', async () => {
    const otherProject = { ...workspace.project, id: 'history-project-2', title: '雾海法师塔' }
    const otherChapter: Chapter = {
      ...workspace.chapters[0],
      id: 'history-project-2-chapter-1',
      project_id: otherProject.id,
      title: '第一章 灰塔来信',
    }
    const otherWorkspace = withAuthorAction({
      ...workspace,
      project: otherProject,
      chapters: [otherChapter],
    })
    window.history.replaceState({}, '', `/?project=${workspace.project.id}&view=writing&stage=plan&chapter=${workspace.chapters[0].id}`)
    vi.mocked(api.listProjects).mockResolvedValue([workspace.project, otherProject])
    vi.mocked(api.getProjectSummary).mockImplementation(async (projectId) => (
      projectId === otherProject.id ? summarizeWorkspace(otherWorkspace) : summarizeWorkspace(workspace)
    ))
    vi.mocked(api.getChapter).mockImplementation(async (chapterId) => (
      chapterId === otherChapter.id ? otherChapter : workspace.chapters[0]
    ))

    render(<App />)
    expect(await screen.findByRole('heading', { name: workspace.project.title })).toBeVisible()

    window.history.pushState({}, '', `/?project=${otherProject.id}&view=writing&stage=plan&chapter=${otherChapter.id}`)
    fireEvent.popState(window)

    expect(await screen.findByRole('heading', { name: otherProject.title })).toBeVisible()
    expect(screen.getByRole('heading', { name: otherChapter.title })).toBeVisible()
    expect(screen.getByLabelText('章节正文')).toHaveValue(otherChapter.content)

    vi.mocked(api.getProjectSummary).mockRejectedValueOnce(new Error('目标作品读取失败'))
    window.history.pushState({}, '', `/?project=${workspace.project.id}&view=writing&stage=review&chapter=${workspace.chapters[0].id}`)
    fireEvent.popState(window)

    await waitFor(() => expect(window.location.search).toContain(`project=${otherProject.id}`))
    expect(window.location.search).toContain(`chapter=${otherChapter.id}`)
    expect(screen.getByRole('heading', { name: otherProject.title })).toBeVisible()
    expect(screen.getByRole('heading', { name: otherChapter.title })).toBeVisible()

    vi.spyOn(api, 'updateChapter').mockRejectedValueOnce(new Error('当前正文保存失败'))
    fireEvent.change(screen.getByLabelText('章节正文'), { target: { value: '这段跨项目前必须保存。' } })
    window.history.pushState({}, '', `/?project=${workspace.project.id}&view=writing&stage=plan&chapter=${workspace.chapters[0].id}`)
    fireEvent.popState(window)

    expect(await screen.findByRole('alert')).toHaveTextContent('当前正文保存失败')
    expect(screen.getByRole('heading', { name: otherProject.title })).toBeVisible()
    expect(screen.getByLabelText('章节正文')).toHaveValue('这段跨项目前必须保存。')
    expect(window.location.search).toContain(`project=${otherProject.id}`)
    expect(window.location.search).toContain(`chapter=${otherChapter.id}`)
  })

  it('opens workflow stages at visible, focusable content instead of empty anchors', async () => {
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    await user.click(screen.getByRole('button', { name: /2，当前章计划/ }))

    expect(await screen.findByRole('dialog', { name: '本章候选生产台' })).toBeVisible()
    await waitFor(() => expect(screen.getByRole('heading', { name: '章纲' })).toHaveFocus())
    expect(document.querySelector('.director-stage-anchor')).not.toBeInTheDocument()
    expect(window.location.search).toContain('stage=plan')

    await user.click(screen.getByRole('button', { name: '关闭单章生产工作台' }))
    await user.click(screen.getByRole('button', { name: /4，审校定稿/ }))

    expect(screen.getByRole('dialog', { name: 'AI 导演' })).toHaveAttribute('data-open', 'true')
    await waitFor(() => expect(document.getElementById('director-stage-review')).toHaveFocus())
    expect(window.location.search).toContain('stage=review')
  })

  it('keeps the author stage in sync with browser back and forward', async () => {
    const secondChapter: Chapter = {
      ...workspace.chapters[0],
      id: 'history-race-chapter-2',
      chapter_number: 2,
      title: '第2章 车站灯火',
      content: '第二章正文',
    }
    const thirdChapter: Chapter = {
      ...workspace.chapters[0],
      id: 'history-race-chapter-3',
      chapter_number: 3,
      title: '第3章 雨夜名单',
      content: '第三章正文',
    }
    const historyWorkspace = {
      ...workspace,
      chapters: [...workspace.chapters, secondChapter, thirdChapter],
    }
    let resolveSecondChapter!: (chapter: Chapter) => void
    let resolveThirdChapter!: (chapter: Chapter) => void
    vi.spyOn(api, 'createProject').mockResolvedValue(historyWorkspace)
    vi.mocked(api.getChapter).mockImplementation((chapterId) => {
      if (chapterId === secondChapter.id) {
        return new Promise((resolve) => { resolveSecondChapter = resolve })
      }
      if (chapterId === thirdChapter.id) {
        return new Promise((resolve) => { resolveThirdChapter = resolve })
      }
      return Promise.resolve(workspace.chapters[0])
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))
    expect(window.location.search).toContain('stage=plan')

    await user.click(screen.getByRole('button', { name: /4，审校定稿/ }))
    await user.keyboard('{Escape}')
    expect(window.location.search).toContain('stage=review')

    await act(async () => { window.history.back() })
    await waitFor(() => expect(window.location.search).toContain('stage=plan'))
    expect(screen.getByRole('button', { name: /2，当前章计划/ })).toHaveAttribute('aria-current', 'step')

    await act(async () => { window.history.forward() })
    await waitFor(() => expect(window.location.search).toContain('stage=review'))
    expect(screen.getByRole('button', { name: /4，审校定稿/ })).toHaveAttribute('aria-current', 'step')

    window.history.pushState({}, '', `/?project=${workspace.project.id}&view=writing&stage=review&chapter=${secondChapter.id}`)
    fireEvent.popState(window)
    await waitFor(() => expect(api.getChapter).toHaveBeenCalledWith(secondChapter.id))
    window.history.pushState({}, '', `/?project=${workspace.project.id}&view=writing&stage=review&chapter=${thirdChapter.id}`)
    fireEvent.popState(window)
    await waitFor(() => expect(api.getChapter).toHaveBeenCalledWith(thirdChapter.id))

    await act(async () => { resolveThirdChapter(thirdChapter) })
    expect(await screen.findByRole('heading', { name: thirdChapter.title })).toBeVisible()
    await act(async () => { resolveSecondChapter(secondChapter) })
    expect(screen.getByRole('heading', { name: thirdChapter.title })).toBeVisible()
    expect(screen.getByLabelText('章节正文')).toHaveValue(thirdChapter.content)
    expect(window.location.search).toContain(`chapter=${thirdChapter.id}`)

    vi.spyOn(api, 'updateChapter').mockRejectedValueOnce(new Error('当前正文保存失败'))
    fireEvent.change(screen.getByLabelText('章节正文'), { target: { value: '返回前必须保存的正文。' } })
    window.history.pushState({}, '', `/?project=${workspace.project.id}&view=writing&stage=plan&chapter=${workspace.chapters[0].id}`)
    fireEvent.popState(window)

    expect(await screen.findByRole('alert')).toHaveTextContent('当前正文保存失败')
    expect(screen.getByRole('button', { name: /4，审校定稿/ })).toHaveAttribute('aria-current', 'step')
    expect(window.location.search).toContain('stage=review')
  })

  it('offers keyboard skip links to the manuscript and the current AI stage', async () => {
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    expect(screen.getByRole('link', { name: '跳到正文' })).toHaveAttribute('href', '#manuscript-editor')
    expect(screen.getByRole('link', { name: '跳到本章 AI' })).toHaveAttribute('href', '#author-workflow')
  })

  it('opens a newly created project in the author topic meeting when the server asks for topic confirmation', async () => {
    const projectWithTopic = withTopic()
    vi.spyOn(api, 'createProject').mockResolvedValue(projectWithTopic)
    const user = userEvent.setup()

    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), projectWithTopic.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    expect(await screen.findByRole('heading', { name: '你定方向，AI 提方案' })).toBeVisible()
    expect(screen.getByRole('heading', { name: '先写你的选题判断' })).toBeVisible()
    expect(screen.queryByLabelText('章节正文')).not.toBeInTheDocument()
  })

  it('restores the topic meeting from server next_action when reopening a project', async () => {
    const projectWithTopic = withTopic()
    vi.mocked(api.listProjects).mockResolvedValue([projectWithTopic.project])
    vi.mocked(api.getProjectSummary).mockResolvedValue(summarizeWorkspace(projectWithTopic))
    const user = userEvent.setup()

    render(<App />)
    await user.click(await screen.findByRole('button', { name: `打开《${projectWithTopic.project.title}》` }))

    expect(await screen.findByRole('heading', { name: '你定方向，AI 提方案' })).toBeVisible()
  })

  it('moves into the existing writing workspace only after explicit topic confirmation', async () => {
    const projectWithTopic = withTopic()
    const confirmedTopic = topicDecision({ status: 'confirmed', confirmed_revision: 1 })
    const confirmedWorkspace = withTopic(confirmedTopic, 'plan_book')
    vi.spyOn(api, 'createProject').mockResolvedValue(projectWithTopic)
    const confirm = vi.spyOn(api, 'confirmTopicDecision').mockResolvedValue(confirmedTopic)
    vi.mocked(api.getProjectSummary).mockResolvedValue(summarizeWorkspace(confirmedWorkspace))
    const user = userEvent.setup()

    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), projectWithTopic.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))
    await user.click(await screen.findByRole('button', { name: '确认选题，进入全书规划' }))

    expect(confirm).toHaveBeenCalledWith(projectWithTopic.project.id, { expected_revision: 1 })
    expect(await screen.findByLabelText('章节正文')).toBeVisible()
  })

  it('keeps a legacy project in writing and offers topic completion as a non-blocking entry', async () => {
    const legacyWorkspace = withTopic(topicDecision(), 'continue_writing')
    vi.spyOn(api, 'createProject').mockResolvedValue(legacyWorkspace)
    const user = userEvent.setup()

    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), legacyWorkspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    expect(await screen.findByLabelText('章节正文')).toBeVisible()
    await user.click(screen.getByRole('button', { name: /补充并确认选题/ }))
    expect(await screen.findByRole('heading', { name: '你定方向，AI 提方案' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: '返回创作台' }))
    expect(await screen.findByLabelText('章节正文')).toBeVisible()
  })

  it('opens the AI comic drama workbench from the writing header', async () => {
    vi.mocked(api.listProjects).mockResolvedValue([workspace.project])
    const user = userEvent.setup()

    render(<App />)
    await user.click(await screen.findByRole('button', {
      name: `打开《${workspace.project.title}》`,
    }))
    await openUtilityDestination('打开 AI 漫剧改编')

    expect(await screen.findByRole('heading', { name: 'AI 漫剧改编' })).toBeVisible()
    expect(screen.getByText('文字剧本与制作包，不修改小说原稿', { exact: false })).toBeVisible()
  })

  it('shows existing projects in the library and opens the selected workspace', async () => {
    vi.mocked(api.listProjects).mockResolvedValue([workspace.project])
    const user = userEvent.setup()

    render(<App />)

    expect(await screen.findByRole('heading', { name: '你的作品，都在这里' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: `打开《${workspace.project.title}》` }))

    expect(api.getProjectSummary).toHaveBeenCalledWith(workspace.project.id)
    expect(api.getChapter).toHaveBeenCalledWith(workspace.chapters[0].id)
    expect(await screen.findByRole('heading', { name: workspace.project.title })).toBeVisible()
    expect(window.localStorage.getItem('mozhou:session:v1')).toContain(workspace.project.id)
  })

  it('exports the default project archive without global raw assets', async () => {
    vi.mocked(api.listProjects).mockResolvedValue([workspace.project])
    const archive = {
      format: 'mozhou-project' as const,
      format_version: 1 as const,
      exported_at: '2026-08-09T00:00:00Z',
      source_project_id: workspace.project.id,
      source_project_title: workspace.project.title,
      schema_version: 2,
      tables: { projects: [{ ...workspace.project }] },
      checksum_sha256: 'a'.repeat(64),
    }
    const exportProject = vi.spyOn(api, 'exportProject').mockResolvedValue(archive)
    const objectUrl = vi.fn(() => 'blob:mozhou-archive')
    const revokeUrl = vi.fn()
    vi.stubGlobal('URL', { createObjectURL: objectUrl, revokeObjectURL: revokeUrl })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const user = userEvent.setup()

    render(<App />)
    await user.click(await screen.findByRole('button', { name: `导出《${workspace.project.title}》归档` }))

    expect(exportProject).toHaveBeenCalledWith(workspace.project.id, false)
    expect(objectUrl).toHaveBeenCalledOnce()
    expect(click).toHaveBeenCalledOnce()
    expect(revokeUrl).toHaveBeenCalledWith('blob:mozhou-archive')
    expect(screen.getByRole('status')).toHaveTextContent('归档已导出')
  })

  it('explicitly exports a full archive with linked reference assets', async () => {
    vi.mocked(api.listProjects).mockResolvedValue([workspace.project])
    const archive = {
      format: 'mozhou-project' as const,
      format_version: 2 as const,
      exported_at: '2026-08-10T00:00:00Z',
      source_project_id: workspace.project.id,
      source_project_title: workspace.project.title,
      schema_version: 11,
      tables: { projects: [{ ...workspace.project }], reference_works: [] },
      checksum_sha256: 'b'.repeat(64),
    }
    const exportProject = vi.spyOn(api, 'exportProject').mockResolvedValue(archive)
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:mozhou-assets-archive'),
      revokeObjectURL: vi.fn(),
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const user = userEvent.setup()

    render(<App />)
    await user.click(await screen.findByRole('button', {
      name: `导出《${workspace.project.title}》含资料原文的完整归档`,
    }))

    expect(exportProject).toHaveBeenCalledWith(workspace.project.id, true)
    expect(screen.getByRole('status')).toHaveTextContent('包含关联资料原文')
  })

  it('imports an archive as a new project copy without opening it', async () => {
    vi.mocked(api.listProjects).mockResolvedValue([workspace.project])
    const restored: Workspace = {
      ...workspace,
      project: {
        ...workspace.project,
        id: 'c39e15d8-153a-4965-a716-1700857c2a8b',
        title: '回到九八年的南平（恢复副本）',
      },
    }
    const importArchive = vi.spyOn(api, 'importProjectArchive').mockResolvedValue(restored)
    const user = userEvent.setup()
    const file = new File(['{"format":"mozhou-project"}'], '南平旧稿.mozhou.json', {
      type: 'application/json',
    })
    if (!file.text) Object.defineProperty(file, 'text', { value: async () => '{"format":"mozhou-project"}' })

    render(<App />)
    await user.upload(await screen.findByLabelText('导入墨舟项目归档'), file)

    expect(importArchive).toHaveBeenCalledWith('{"format":"mozhou-project"}')
    expect(await screen.findByRole('heading', { name: restored.project.title })).toBeVisible()
    expect(screen.queryByLabelText('章节正文')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('已恢复为新副本')
  })

  it('can import an archive before any local project exists', async () => {
    const restored: Workspace = {
      ...workspace,
      project: { ...workspace.project, title: '外部归档（恢复副本）' },
    }
    const importArchive = vi.spyOn(api, 'importProjectArchive').mockResolvedValue(restored)
    const user = userEvent.setup()
    const file = new File(['{"format":"mozhou-project"}'], 'archive.mozhou.json', {
      type: 'application/json',
    })
    if (!file.text) Object.defineProperty(file, 'text', { value: async () => '{"format":"mozhou-project"}' })

    render(<App />)
    await user.upload(await screen.findByLabelText('从本机导入墨舟项目归档'), file)

    expect(importArchive).toHaveBeenCalledOnce()
    expect(await screen.findByRole('heading', { name: restored.project.title })).toBeVisible()
    expect(screen.getByRole('status')).toHaveTextContent('已恢复为新副本')
  })

  it('creates and restores a recovery point from the shelf', async () => {
    vi.mocked(api.listProjects).mockResolvedValue([workspace.project])
    vi.spyOn(api, 'listRecoveryPoints').mockResolvedValue([])
    const recoveryPoint = {
      id: '3158369c-a751-454f-860b-48bb1e6cb120',
      project_id: workspace.project.id,
      label: '第二卷大改前',
      kind: 'manual' as const,
      archive_sha256: 'b'.repeat(64),
      uncompressed_bytes: 2048,
      compressed_bytes: 512,
      created_at: '2026-08-09T00:00:00Z',
    }
    const createPoint = vi.spyOn(api, 'createRecoveryPoint').mockResolvedValue(recoveryPoint)
    const restored: Workspace = {
      ...workspace,
      project: {
        ...workspace.project,
        id: 'b44239aa-33e5-4a14-922e-58ec468766ae',
        title: '回到九八年的南平（恢复副本）',
      },
    }
    const restorePoint = vi.spyOn(api, 'restoreRecoveryPoint').mockResolvedValue(restored)
    const user = userEvent.setup()

    render(<App />)
    await user.click(await screen.findByRole('button', { name: `管理《${workspace.project.title}》恢复点` }))
    await user.type(screen.getByLabelText(`《${workspace.project.title}》恢复点备注`), '第二卷大改前')
    await user.click(screen.getByRole('button', { name: '创建恢复点' }))
    await user.click(await screen.findByRole('button', { name: '从“第二卷大改前”恢复为副本' }))

    expect(createPoint).toHaveBeenCalledWith(workspace.project.id, { label: '第二卷大改前' })
    expect(restorePoint).toHaveBeenCalledWith(recoveryPoint.id)
    expect(await screen.findByRole('heading', { name: restored.project.title })).toBeVisible()
  })

  it('returns to the project library on exit and can reopen the same work', async () => {
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    await user.click(screen.getByRole('button', { name: '退出作品' }))

    expect(await screen.findByRole('heading', { name: '你的作品，都在这里' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: `打开《${workspace.project.title}》` }))
    expect(api.getProjectSummary).toHaveBeenCalledWith(workspace.project.id)
    expect(api.getChapter).toHaveBeenCalledWith(workspace.chapters[0].id)
    expect(await screen.findByRole('heading', { name: workspace.project.title })).toBeVisible()
  })

  it('creates a rebirth project and opens the writing workspace', async () => {
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    const user = userEvent.setup()
    render(<App />)

    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    expect(await screen.findByRole('heading', { name: workspace.project.title })).toBeVisible()
    expect(screen.getByLabelText('章节正文')).toBeVisible()
    expect(window.localStorage.getItem('mozhou:session:v1')).toContain(workspace.project.id)
  })

  it('opens and closes the AI director from the narrow-window entry point', async () => {
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    const user = userEvent.setup()
    render(<App />)

    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    const trigger = await screen.findByRole('button', { name: '打开 AI 导演' })
    const director = screen.getByRole('region', { name: 'AI 导演' })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(director).toHaveAttribute('data-open', 'false')

    await user.click(trigger)

    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(director).toHaveAttribute('data-open', 'true')
    expect(screen.getByRole('button', { name: '关闭 AI 导演' })).toHaveFocus()

    await user.keyboard('{Escape}')

    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(director).toHaveAttribute('data-open', 'false')
    expect(trigger).toHaveFocus()
  })

  it('opens stale-plan impact from the writing workspace and restores keyboard focus', async () => {
    const blueprintContent: BookBlueprintContent = {
      title: workspace.project.title,
      genre: workspace.project.genre,
      rebirth_year: 1998,
      rebirth_location: '福建南平',
      target_audience: '现实创业读者',
      core_selling_points: ['产业改命'],
      core_desire: '先保住父亲的工作',
      divergence_point: '提前拿到停产名单',
      long_term_promise: '改变家族与城市产业路线',
      ending_direction: '建立产业联盟',
      protagonist_arc: '从救家到担责',
      resource_growth: '信息差到组织信用',
      relationship_design: '重构父子与商业盟友关系',
    }
    const fields = Object.keys(blueprintContent) as Array<keyof typeof blueprintContent>
    const staleWorkspace: Workspace = {
      ...workspace,
      next_action: 'review_downstream_plans',
      book_blueprint: {
        id: 'blueprint-1',
        project_id: workspace.project.id,
        idea: '重生后改变家乡产业',
        content: blueprintContent,
        locks: Object.fromEntries(fields.map((field) => [field, field === 'title'])) as BookBlueprint['locks'],
        field_versions: Object.fromEntries(fields.map((field) => [field, 1])) as BookBlueprint['field_versions'],
        stale_fields: ['core_desire'],
        plan_stale: true,
        source_candidate_id: null,
        revision: 4,
        created_at: '2026-09-12T00:00:00Z',
        updated_at: '2026-09-12T00:00:00Z',
      },
    }
    const impact: CreativePlanImpactPreview = {
      project_id: workspace.project.id,
      current_dependency: {
        schema_version: 1,
        topic: null,
        writing_pattern_profile: null,
        writing_pattern_source_availability: null,
        base_blueprint: null,
        subject_sha256: 'a'.repeat(64),
      },
      current_dependency_fingerprint_sha256: 'b'.repeat(64),
      reasons: ['选题或写作模式已更新'],
      affected_blueprint_fields: ['core_desire'],
      locked_blueprint_fields: ['title'],
      targets: [{
        kind: 'book_blueprint',
        id: 'blueprint-1',
        revision: 4,
        locked: false,
        state: 'stale',
        stale_reasons: ['写作模式快照已更新'],
      }],
      approved_chapter_count: 2,
      can_rebase: true,
    }
    vi.mocked(api.listProjects).mockResolvedValue([workspace.project])
    vi.mocked(api.getProjectSummary).mockResolvedValue(summarizeWorkspace(staleWorkspace))
    vi.spyOn(api, 'getCreativeContextImpact').mockResolvedValue(impact)
    vi.spyOn(api, 'getPatternOriginalityGate').mockResolvedValue({
      project_id: workspace.project.id,
      state: 'legacy',
      reason: 'legacy_project',
      requires_check: false,
      adoption: null,
      blueprint_id: null,
      blueprint_revision: null,
      blueprint_content_sha256: null,
      latest_report: null,
      report_is_current: false,
    })
    const user = userEvent.setup()

    render(<App />)
    await user.click(await screen.findByRole('button', { name: `打开《${workspace.project.title}》` }))
    const entry = await screen.findByRole('button', { name: /计划需复核 · 查看影响/ })
    await user.click(entry)

    expect(screen.getByRole('dialog', { name: 'AI 导演' })).toHaveAttribute('data-open', 'true')
    expect(await screen.findByRole('heading', { name: '安全更新全书计划' })).toBeVisible()
    await user.keyboard('{Escape}')
    expect(entry).toHaveFocus()
  })

  it('automatically saves chapter content with the current revision', async () => {
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    const update = vi.spyOn(api, 'updateChapter').mockResolvedValue({
      ...workspace.chapters[0],
      content: '列车驶入南平站。',
      revision: 1,
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))
    await screen.findByLabelText('章节正文')
    vi.useFakeTimers()

    fireEvent.change(screen.getByLabelText('章节正文'), { target: { value: '列车驶入南平站。' } })
    await act(() => vi.advanceTimersByTimeAsync(701))

    expect(update).toHaveBeenCalledWith(workspace.chapters[0].id, {
      content: '列车驶入南平站。',
      expected_revision: 0,
    })
    expect(screen.getByRole('status')).toHaveTextContent('已保存')
  })

  it('flushes the latest chapter text before opening the reference library', async () => {
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    const update = vi.spyOn(api, 'updateChapter').mockResolvedValue({
      ...workspace.chapters[0],
      content: '刚写下、还没有等到自动保存的一句。',
      revision: 1,
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    fireEvent.change(screen.getByLabelText('章节正文'), {
      target: { value: '刚写下、还没有等到自动保存的一句。' },
    })
    await openUtilityDestination('打开拆书库')

    expect(update).toHaveBeenCalledWith(workspace.chapters[0].id, {
      content: '刚写下、还没有等到自动保存的一句。',
      expected_revision: 0,
    })
    expect(await screen.findByRole('heading', { name: '先拆成规律，再带回你的书' })).toBeVisible()
  })

  it('flushes the latest chapter text before opening the independent writing-pattern workbench', async () => {
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    vi.spyOn(api, 'listWritingPatternRecipes').mockResolvedValue({ items: [], total: 0, limit: 12, offset: 0 })
    vi.spyOn(api, 'listWritingPatternProfiles').mockResolvedValue([])
    const update = vi.spyOn(api, 'updateChapter').mockResolvedValue({
      ...workspace.chapters[0],
      content: '配方打开前必须保存的这一句。',
      revision: 1,
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    fireEvent.change(screen.getByLabelText('章节正文'), {
      target: { value: '配方打开前必须保存的这一句。' },
    })
    await openUtilityDestination('打开写作配方')

    expect(update).toHaveBeenCalledWith(workspace.chapters[0].id, {
      content: '配方打开前必须保存的这一句。',
      expected_revision: 0,
    })
    expect(await screen.findByRole('heading', { name: '先看清每条技法，再决定学什么、改什么、避开什么。' })).toBeVisible()
  })

  it('flushes the current chapter before switching to another chapter', async () => {
    const secondChapter = {
      ...workspace.chapters[0],
      id: '8b25af36-1ab6-4a4a-bd23-8f53c8b0a7de',
      chapter_number: 2,
      title: '第2章 名单之外',
      content: '',
    }
    vi.spyOn(api, 'createProject').mockResolvedValue({
      ...workspace,
      chapters: [workspace.chapters[0], secondChapter],
    })
    vi.mocked(api.getChapter).mockResolvedValue(secondChapter)
    const update = vi.spyOn(api, 'updateChapter').mockResolvedValue({
      ...workspace.chapters[0],
      content: '切章前必须留下的最后一句。',
      revision: 1,
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    fireEvent.change(screen.getByLabelText('章节正文'), {
      target: { value: '切章前必须留下的最后一句。' },
    })
    fireEvent.click(screen.getByRole('button', { name: '打开第 2 章：第2章 名单之外' }))

    expect(update).toHaveBeenCalledWith(workspace.chapters[0].id, {
      content: '切章前必须留下的最后一句。',
      expected_revision: 0,
    })
    expect(await screen.findByRole('heading', { name: '第2章 名单之外' })).toBeVisible()
    expect(api.getChapter).toHaveBeenCalledWith(secondChapter.id)

    vi.mocked(api.getChapter).mockRejectedValueOnce(new Error('目标章节读取失败'))
    window.history.pushState({}, '', `/?project=${workspace.project.id}&view=writing&stage=plan&chapter=${workspace.chapters[0].id}`)
    fireEvent.popState(window)

    expect(await screen.findByRole('alert')).toHaveTextContent('目标章节读取失败')
    expect(screen.getByRole('heading', { name: '第2章 名单之外' })).toBeVisible()
    expect(screen.getByLabelText('章节正文')).toHaveValue(secondChapter.content)
    expect(window.location.search).toContain(`chapter=${secondChapter.id}`)

    const chapterRequestsBeforeInvalidRoute = vi.mocked(api.getChapter).mock.calls.length
    const historyLengthBeforeInvalidRoute = window.history.length
    window.history.pushState({}, '', `/?project=${workspace.project.id}&view=writing&stage=review&chapter=missing-chapter`)
    fireEvent.popState(window)

    await waitFor(() => expect(window.location.search).toContain(`chapter=${secondChapter.id}`))
    expect(window.location.search).toContain('stage=review')
    expect(window.history.length).toBe(historyLengthBeforeInvalidRoute + 1)
    expect(screen.getByRole('heading', { name: '第2章 名单之外' })).toBeVisible()
    expect(vi.mocked(api.getChapter).mock.calls).toHaveLength(chapterRequestsBeforeInvalidRoute)
  })

  it('does not run a cross-chapter author action when the target chapter cannot load', async () => {
    const secondChapter = {
      ...workspace.chapters[0],
      id: '14eb18c0-4ea7-44aa-b30f-cb39825a9961',
      chapter_number: 2,
      title: '第2章 还没到站',
      content: '这一章暂时无法读取。',
    }
    const routedWorkspace = withAuthorAction({
      ...workspace,
      chapters: [workspace.chapters[0], secondChapter],
    }, {
      kind: 'generate_chapter_candidate',
      target_stage: 'candidate',
      chapter_id: secondChapter.id,
      chapter_number: 2,
    })
    window.history.replaceState({}, '', `/?project=${workspace.project.id}&view=writing&stage=candidate&chapter=${workspace.chapters[0].id}`)
    vi.mocked(api.listProjects).mockResolvedValue([workspace.project])
    vi.mocked(api.getProjectSummary).mockResolvedValue(summarizeWorkspace(routedWorkspace))
    vi.mocked(api.getChapter).mockImplementation(async (chapterId) => {
      if (chapterId === secondChapter.id) throw new Error('章节正文读取失败')
      return workspace.chapters[0]
    })
    const user = userEvent.setup()
    render(<App />)
    expect(await screen.findByRole('heading', { name: workspace.chapters[0].title })).toBeVisible()

    await user.click(screen.getByRole('button', { name: '生成第 2 章候选' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('章节正文读取失败')
    expect(screen.getByRole('heading', { name: workspace.chapters[0].title })).toBeVisible()
    expect(screen.getByLabelText('章节正文')).toHaveValue(workspace.chapters[0].content)
    expect(screen.queryByRole('dialog', { name: '本章候选生产台' })).not.toBeInTheDocument()
  })

  it('keeps the editor open when navigation cannot save the latest text', async () => {
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    vi.spyOn(api, 'updateChapter').mockRejectedValue(new Error('本地服务暂时不可用'))
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    fireEvent.change(screen.getByLabelText('章节正文'), {
      target: { value: '这句话必须留在编辑器里。' },
    })
    fireEvent.click(screen.getByRole('button', { name: '打开辅助工具' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('本地服务暂时不可用')
    expect(screen.getByLabelText('章节正文')).toHaveValue('这句话必须留在编辑器里。')
    expect(screen.queryByRole('heading', { name: '先拆成规律，再带回你的书' })).not.toBeInTheDocument()
  })

  it('opens the unified chapter-production desk instead of the legacy brief editor', async () => {
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    const legacyBriefSave = vi.spyOn(api, 'updateChapterBrief')
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    const primary = screen.getByRole('button', { name: '打开本章计划' })
    expect(document.querySelectorAll('.author-next-action > button')).toHaveLength(1)
    expect(document.querySelector('.chapter-production-entry')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '准备章节上下文' })).not.toBeInTheDocument()
    await user.click(primary)

    expect(await screen.findByRole('dialog', { name: '本章候选生产台' })).toBeVisible()
    expect(await screen.findByLabelText('开篇钩子')).toHaveValue(workspace.chapters[0].opening_hook)
    expect(legacyBriefSave).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: '关闭单章生产工作台' }))
    await waitFor(() => expect(primary).toHaveFocus())
  })

  it('adds the next chapter to the rolling plan and switches chapters', async () => {
    const secondChapter = {
      ...workspace.chapters[0],
      id: '8b25af36-1ab6-4a4a-bd23-8f53c8b0a7de',
      chapter_number: 2,
      title: '第2章 未命名',
      content: '',
      opening_hook: '',
      state_change: '',
      ending_cliffhanger: '',
      revision: 0,
    }
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    const createChapter = vi.spyOn(api, 'createChapter').mockResolvedValue(secondChapter)
    vi.mocked(api.getChapter).mockResolvedValue(secondChapter)
    vi.mocked(api.getProjectSummary).mockResolvedValue(summarizeWorkspace({
      ...workspace,
      chapters: [...workspace.chapters, secondChapter],
    }))
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    await user.click(screen.getAllByRole('button', { name: '添加下一章' })[1])

    expect(createChapter).toHaveBeenCalledWith(workspace.project.id, {
      expected_last_chapter_number: 1,
    })
    expect(await screen.findByText('1 / 3')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '打开第 2 章：第2章 未命名' }))
    expect(await screen.findByRole('heading', { name: '第2章 未命名' })).toBeVisible()
    expect(api.getChapter).toHaveBeenCalledWith(secondChapter.id)
    expect(screen.getByLabelText('章节正文')).toHaveValue('')
  })

  it('refreshes the server next action after chapter creation and prevents duplicate creation', async () => {
    const secondChapter: Chapter = {
      ...workspace.chapters[0],
      id: 'server-routed-chapter-2',
      chapter_number: 2,
      title: '第2章 夜班名单',
      content: '',
      revision: 0,
    }
    const createRoute = withAuthorAction(workspace, {
      kind: 'create_next_chapter',
      target_stage: 'plan',
      chapter_id: null,
      chapter_number: 2,
    })
    const refreshed = withAuthorAction({ ...workspace, chapters: [...workspace.chapters, secondChapter] }, {
      kind: 'plan_chapter',
      target_stage: 'plan',
      chapter_id: secondChapter.id,
      chapter_number: 2,
    })
    let resolveCreation!: (chapter: Chapter) => void
    let rejectRefresh!: (reason: Error) => void
    vi.spyOn(api, 'createProject').mockResolvedValue(createRoute)
    const createChapter = vi.spyOn(api, 'createChapter').mockImplementation(() => (
      new Promise((resolve) => { resolveCreation = resolve })
    ))
    vi.mocked(api.getProjectSummary)
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectRefresh = reject }))
      .mockResolvedValue(summarizeWorkspace(refreshed))
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    await user.click(screen.getByRole('button', { name: '创建第 2 章' }))
    expect(createChapter).toHaveBeenCalledOnce()
    expect(screen.getByRole('button', { name: '正在处理下一步…' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '正在处理下一步…' }))
    expect(createChapter).toHaveBeenCalledOnce()

    await act(async () => { resolveCreation(secondChapter) })
    expect(await screen.findByRole('heading', { name: secondChapter.title })).toBeVisible()
    expect(screen.getByRole('button', { name: '正在处理下一步…' })).toBeDisabled()

    await act(async () => { rejectRefresh(new Error('下一步同步失败')) })
    const retry = await screen.findByRole('button', { name: '刷新下一步' })
    expect(screen.getByRole('alert')).toHaveTextContent('章节已创建')
    fireEvent.click(screen.getAllByRole('button', { name: '等待刷新下一步' })[0])
    expect(createChapter).toHaveBeenCalledOnce()

    await user.click(retry)
    expect(await screen.findByRole('button', { name: '规划第 2 章' })).toBeVisible()
    expect(api.getProjectSummary).toHaveBeenCalledWith(workspace.project.id)
  })

  it('moves a saved draft into review and binds approval to the current body digest', async () => {
    const draftedWorkspace: Workspace = {
      ...workspace,
      chapters: [{
        ...workspace.chapters[0],
        content: '列车驶进南平站。',
        status: 'drafted',
        revision: 2,
      }],
    }
    vi.spyOn(api, 'createProject').mockResolvedValue(draftedWorkspace)
    const reviewingChapter = {
      ...draftedWorkspace.chapters[0],
      status: 'reviewing' as const,
      revision: 3,
    }
    const transition = vi.spyOn(api, 'transitionChapter')
      .mockResolvedValueOnce(reviewingChapter)
      .mockResolvedValueOnce({ ...reviewingChapter, status: 'approved', revision: 4 })
    vi.spyOn(api, 'getLatestCanonReconciliation').mockResolvedValue(null)
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    await user.click(screen.getByRole('button', { name: '提交审校' }))

    expect(transition).toHaveBeenCalledWith(draftedWorkspace.chapters[0].id, {
      target_status: 'reviewing',
      expected_revision: 2,
    })
    expect(await screen.findByRole('button', { name: '批准定稿' })).toBeEnabled()

    const digest = await crypto.subtle.digest(
      'SHA-256',
      new TextEncoder().encode(reviewingChapter.content),
    )
    const expectedContentSha256 = Array.from(
      new Uint8Array(digest),
      (byte) => byte.toString(16).padStart(2, '0'),
    ).join('')
    await user.click(screen.getByRole('button', { name: '批准定稿' }))

    expect(transition).toHaveBeenLastCalledWith(draftedWorkspace.chapters[0].id, {
      target_status: 'approved',
      expected_revision: 3,
      expected_content_sha256: expectedContentSha256,
    })
    const stateCard = screen.getByRole('heading', { name: '章节状态' }).closest('section')
    const feedbackCard = (await screen.findByRole('heading', { name: '定稿回流审签' })).closest('section')
    expect(stateCard?.nextElementSibling).toBe(feedbackCard)
    expect(feedbackCard).toHaveClass('director-stage-target')
    ;(feedbackCard as HTMLElement).focus()
    expect(feedbackCard).toHaveFocus()
  })

  it('keeps restored AI text isolated in the unified candidate comparison', async () => {
    const content = '1998年的慢车驶进福建南平时，站台广播带着电流声。'
    const restoredCandidate = productionCandidate(workspace.chapters[0], content)
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    vi.mocked(api.getCurrentChapterProduction).mockResolvedValue(productionSnapshot(workspace.chapters[0], {
      outline: productionOutline(workspace.chapters[0]),
      candidate: restoredCandidate,
    }))
    const legacyGeneration = vi.spyOn(api, 'startGeneration')
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    expect(screen.queryByRole('button', { name: '生成示范候选稿' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '打开本章计划' }))
    expect(await screen.findByRole('textbox', { name: '编辑正面交锋版候选副本' })).toHaveValue(content)
    expect((document.querySelector('.manuscript') as HTMLTextAreaElement).value).toBe('')
    expect(legacyGeneration).not.toHaveBeenCalled()
  })

  it('restores author edits while rebasing an old production on the latest chapter', async () => {
    const currentChapter = { ...workspace.chapters[0], content: '作者已改过的正文。', status: 'drafted' as const, revision: 2 }
    const currentWorkspace = { ...workspace, chapters: [currentChapter] }
    const oldCandidate = productionCandidate(currentChapter, '这份候选基于旧正文。')
    vi.spyOn(api, 'createProject').mockResolvedValue(currentWorkspace)
    vi.mocked(api.getCurrentChapterProduction).mockResolvedValue(productionSnapshot(currentChapter, {
      outline: productionOutline(currentChapter), candidate: oldCandidate, baseRevision: 1,
    }))
    vi.mocked(api.getChapter).mockResolvedValue(currentChapter)
    vi.mocked(api.createChapterProduction).mockResolvedValue(productionSnapshot(currentChapter))
    const legacyApply = vi.spyOn(api, 'applyGeneration')
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), currentWorkspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))
    await user.click(screen.getByRole('button', { name: '打开本章计划' }))

    const editor = await screen.findByRole('textbox', { name: '编辑正面交锋版候选副本' })
    await user.clear(editor)
    await user.type(editor, '作者要保留的候选修改。')
    expect(screen.getByRole('button', { name: '确认采用这份候选' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '刷新正文并重新检查' }))

    expect(await screen.findByLabelText('旧候选作者编辑恢复副本')).toHaveValue('作者要保留的候选修改。')
    expect(legacyApply).not.toHaveBeenCalled()
  })

  it('lets AI propose a complete outline candidate without changing the saved chapter', async () => {
    vi.mocked(api.getAiStatus).mockResolvedValue({
      configured: true,
      provider: 'openai',
      model: 'gpt-5.6',
      key_source: 'session',
      profile_id: null,
      profile_name: null,
    })
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    const proposedOutline = productionOutline(workspace.chapters[0])
    proposedOutline.current_version.content = {
      ...proposedOutline.current_version.content,
      title: '第一章 名单之前',
      reader_promise: '主角第一次改变家庭命运',
      opening_hook: '停产名单比记忆中提前贴出',
      state_change: '主角让父亲避开首轮裁员',
      emotional_payoff: '父亲保住岗位却开始怀疑儿子',
      ending_cliffhanger: '厂长拿出一张不该存在的旧照片',
    }
    const briefJob: Job = {
      ...queuedJob('chapter_brief', workspace.chapters[0].id),
      workflow: 'chapter_production_outline',
      current_step: '等待生成章纲候选',
    }
    const previewBrief = vi.spyOn(api, 'previewChapterProductionOutline').mockResolvedValue(
      productionPreview('brief'),
    )
    const startBrief = vi.spyOn(api, 'startChapterProductionOutlineJob').mockResolvedValue(briefJob)
    vi.spyOn(api, 'getJob').mockResolvedValue({
      ...briefJob,
      state: 'succeeded',
      progress_current: 1,
      completed_calls: 1,
      current_step: '章节候选已生成',
      chunks: [],
      attempts: [],
      artifacts: [],
      events: [],
    })
    vi.spyOn(api, 'getChapterProductionOutlineJobResult').mockResolvedValue(proposedOutline)
    vi.spyOn(api, 'getChapterProduction').mockResolvedValue(productionSnapshot(
      workspace.chapters[0],
      { outline: proposedOutline },
    ))
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    await user.click(screen.getByRole('button', { name: '打开本章计划' }))
    await user.type(await screen.findByLabelText('本章创作意图（可选）'), '让主角用信息差救下父亲')
    await user.click(await within(screen.getByRole('dialog', { name: '本章候选生产台' })).findByRole('button', { name: '生成本章候选' }))

    expect(previewBrief).toHaveBeenCalledWith('chapter-production-1', {
      author_intent: '让主角用信息差救下父亲',
      token_budget: 8000,
      label: 'AI 章纲',
    })
    expect(startBrief).not.toHaveBeenCalled()
    expect(await screen.findByRole('heading', { name: '发送前确认' })).toBeVisible()
    expect(screen.getByText('已编译创作上下文')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '确认外发与费用，开始任务' }))
    expect(startBrief).toHaveBeenCalledWith('chapter-production-1', expect.objectContaining({
      author_intent: '让主角用信息差救下父亲',
      context_packet_id: 'production-packet-1',
      context_packet_sha256: 'd'.repeat(64),
      confirm_external_processing: true,
    }))
    await waitFor(() => {
      expect(screen.getByLabelText('读者承诺')).toHaveValue(
        proposedOutline.current_version.content.reader_promise,
      )
    })
    expect(screen.getByLabelText('章节正文')).toHaveValue('')
  })

  it('blocks model submission when the creative-context preflight is not ready', async () => {
    vi.mocked(api.getAiStatus).mockResolvedValue({
      configured: true,
      provider: 'openai',
      model: 'gpt-5.6',
      key_source: 'session',
      profile_id: null,
      profile_name: null,
    })
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    vi.spyOn(api, 'previewChapterProductionOutline').mockRejectedValue(
      new ApiError('请先启用一份写作配方', 409, 'writing_pattern_profile_required'),
    )
    const start = vi.spyOn(api, 'startChapterProductionOutlineJob')
    const user = userEvent.setup()

    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))
    await user.click(await screen.findByRole('button', { name: '打开本章计划' }))
    await user.click(await within(screen.getByRole('dialog', { name: '本章候选生产台' })).findByRole('button', { name: '生成本章候选' }))

    expect(await screen.findByText('缺少已启用的写作模式，请先完成写作配方。')).toBeVisible()
    expect(screen.queryByRole('heading', { name: '发送前确认' })).not.toBeInTheDocument()
    expect(start).not.toHaveBeenCalled()
  })

  it('creates and activates an OpenAI-compatible model route from the routing desk', async () => {
    const profile: ModelProfile = {
      id: '0b4872a9-cba5-45e7-8549-fc31c779e46a',
      name: '本地长章主笔',
      provider: 'openai_compatible',
      base_url: 'http://127.0.0.1:11434/v1',
      model: 'qwen3-32b',
      capabilities: {
        structured_output: false,
        streaming: false,
        server_cancellation: false,
        usage: false,
      },
      input_cost_microusd_per_million: 500_000,
      output_cost_microusd_per_million: 2_000_000,
      revision: 0,
      created_at: '2026-08-10T00:00:00Z',
      updated_at: '2026-08-10T00:00:00Z',
    }
    const activeStatus = {
      configured: true,
      provider: 'openai_compatible' as const,
      model: profile.model,
      key_source: 'session',
      profile_id: profile.id,
      profile_name: profile.name,
    }
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    const createProfile = vi.spyOn(api, 'createAiProfile').mockResolvedValue(profile)
    const activateProfile = vi.spyOn(api, 'activateAiProfile').mockResolvedValue(activeStatus)
    vi.mocked(api.getAiStatus)
      .mockResolvedValueOnce({
        configured: false,
        provider: 'unavailable',
        model: '',
        key_source: null,
        profile_id: null,
        profile_name: null,
      })
      .mockResolvedValue(activeStatus)
    const user = userEvent.setup()

    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))
    const settingsTrigger = await screen.findByRole('button', { name: '打开模型线路台' })
    await user.click(settingsTrigger)

    let dialog = await screen.findByRole('dialog', { name: '模型线路台' })
    expect(within(dialog).getByRole('button', { name: '关闭模型设置' })).toHaveFocus()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(settingsTrigger).toHaveFocus())
    await user.click(settingsTrigger)
    dialog = await screen.findByRole('dialog', { name: '模型线路台' })
    await user.type(within(dialog).getByLabelText('线路名称'), profile.name)
    await user.selectOptions(within(dialog).getByLabelText('端点类型'), 'openai_compatible')
    await user.clear(within(dialog).getByLabelText('API 地址'))
    await user.type(within(dialog).getByLabelText('API 地址'), profile.base_url)
    await user.clear(within(dialog).getByLabelText('模型名'))
    await user.type(within(dialog).getByLabelText('模型名'), profile.model)
    await user.type(within(dialog).getByLabelText(/输入价格/), '0.5')
    await user.type(within(dialog).getByLabelText(/输出价格/), '2')
    await user.type(within(dialog).getByLabelText('模型 API Key'), 'browser-session-test-key')
    await user.click(within(dialog).getByRole('button', { name: '保存并启用' }))

    await waitFor(() => {
      expect(createProfile).toHaveBeenCalledWith({
        name: profile.name,
        provider: profile.provider,
        base_url: profile.base_url,
        model: profile.model,
        input_cost_microusd_per_million: 500_000,
        output_cost_microusd_per_million: 2_000_000,
      })
      expect(activateProfile).toHaveBeenCalledWith(profile.id, 'browser-session-test-key')
    })
    expect(within(dialog).getByLabelText('模型 API Key')).toHaveValue('')
    await user.click(within(dialog).getByRole('button', { name: '关闭模型设置' }))
    expect(await screen.findByText(`${profile.name} · ${profile.model}`)).toBeVisible()
    expect(screen.queryByDisplayValue('browser-session-test-key')).not.toBeInTheDocument()
  })

  it('routes chapter briefs to their own saved model profile', async () => {
    const profile: ModelProfile = {
      id: '0b4872a9-cba5-45e7-8549-fc31c779e46a',
      name: '章纲推演线路',
      provider: 'openai',
      base_url: 'https://api.openai.com/v1',
      model: 'gpt-5.6',
      capabilities: {
        structured_output: true,
        streaming: true,
        server_cancellation: false,
        usage: true,
      },
      input_cost_microusd_per_million: null,
      output_cost_microusd_per_million: null,
      revision: 0,
      created_at: '2026-08-10T00:00:00Z',
      updated_at: '2026-08-10T00:00:00Z',
    }
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    vi.mocked(api.listAiProfiles).mockResolvedValue([profile])
    const setDefault = vi.spyOn(api, 'setAiTaskDefault').mockResolvedValue({
      task_type: 'chapter_brief',
      profile_id: profile.id,
      profile_name: profile.name,
      provider: profile.provider,
      model: profile.model,
      revision: 0,
      updated_at: '2026-08-10T00:00:00Z',
    })
    const user = userEvent.setup()

    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))
    await user.click(await screen.findByRole('button', { name: '打开模型线路台' }))
    const route = await screen.findByLabelText('章纲设计模型线路')
    expect(screen.getByLabelText('写作模式迁移模型线路')).toBeInTheDocument()
    await user.selectOptions(route, profile.id)

    expect(setDefault).toHaveBeenCalledWith('chapter_brief', {
      profile_id: profile.id,
      expected_revision: null,
    })
    expect(route).toHaveValue(profile.id)
  })

  it('keeps an AI-written full chapter candidate isolated until the author adopts it', async () => {
    vi.mocked(api.getAiStatus).mockResolvedValue({
      configured: true,
      provider: 'openai',
      model: 'gpt-5.6',
      key_source: 'session',
      profile_id: null,
      profile_name: null,
    })
    const plannedChapter: Chapter = {
      ...workspace.chapters[0],
      reader_promise: '主角第一次改变家庭命运',
      emotional_payoff: '父亲第一次选择相信主角',
    }
    const draftWorkspace = { ...workspace, chapters: [plannedChapter] }
    const outline = productionOutline(plannedChapter)
    const candidateText = '一九九八年的梅山坡还没有后来那排高楼。沈砚把停产名单压在桌上。'
    const generatedCandidate = productionCandidate(plannedChapter, candidateText)
    vi.spyOn(api, 'createProject').mockResolvedValue(draftWorkspace)
    vi.mocked(api.getCurrentChapterProduction).mockResolvedValue(
      productionSnapshot(plannedChapter, { outline }),
    )
    vi.spyOn(api, 'checkChapterProductionPreflight').mockResolvedValue({
      id: 'preflight-1',
      production_id: 'chapter-production-1',
      outline_candidate_id: outline.id,
      outline_version_id: outline.current_version.id,
      outline_revision: outline.current_version.revision,
      outline_content_sha256: outline.current_version.content_sha256,
      reader_promise: true,
      opening_hook: true,
      state_change: true,
      emotional_payoff: true,
      ending_cliffhanger: true,
      missing_fields: [],
      passed: true,
      created_at: '2026-09-12T00:00:00Z',
    })
    vi.spyOn(api, 'previewChapterProductionDraft').mockResolvedValue({
      ...productionPreview('draft'),
      estimated_cost_microusd: null,
    })
    const draftJob: Job = {
      ...queuedJob('chapter_draft', plannedChapter.id),
      workflow: 'chapter_production_draft',
      current_step: '等待生成正文候选',
    }
    const startDraft = vi.spyOn(api, 'startChapterProductionDraftJob').mockResolvedValue(draftJob)
    vi.spyOn(api, 'getJob').mockResolvedValue({
      ...draftJob,
      state: 'succeeded',
      progress_current: 1,
      completed_calls: 1,
      current_step: '章节候选已生成',
      chunks: [],
      attempts: [],
      artifacts: [],
      events: [],
    })
    vi.spyOn(api, 'getChapterProductionDraftJobResult').mockResolvedValue(generatedCandidate)
    vi.spyOn(api, 'getChapterProduction').mockResolvedValue(productionSnapshot(
      plannedChapter,
      { outline, candidate: generatedCandidate },
    ))
    vi.spyOn(api, 'adoptChapterProductionCandidate').mockResolvedValue({
      id: 'writing-outcome-1',
      production_id: 'chapter-production-1',
      candidate_id: generatedCandidate.id,
      candidate_version_id: generatedCandidate.current_version.id,
      candidate_revision: generatedCandidate.current_version.revision,
      candidate_content_sha256: generatedCandidate.current_version.content_sha256,
      source_outline_candidate_id: outline.id,
      source_outline_version_id: outline.current_version.id,
      source_outline_revision: outline.current_version.revision,
      source_outline_content_sha256: outline.current_version.content_sha256,
      decision: 'adopted',
      adoption_mode: 'whole',
      base_chapter_revision: plannedChapter.revision,
      base_chapter_content_sha256: 'c'.repeat(64),
      final_chapter_revision: 1,
      final_chapter_content_sha256: 'f'.repeat(64),
      final_chapter_status: 'drafted',
      chapter_version_id: 'chapter-version-1',
      adoption_detail: { mode: 'whole' },
      idempotency_key: 'writing-outcome-key',
      reason: '',
      created_at: '2026-09-12T00:00:00Z',
    })
    vi.mocked(api.getChapter).mockResolvedValue({
      ...plannedChapter,
      content: candidateText,
      status: 'drafted',
      revision: 1,
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    await user.click(await screen.findByRole('button', { name: '打开本章计划' }))
    await user.click(await within(screen.getByRole('dialog', { name: '本章候选生产台' })).findByRole('button', { name: '生成本章候选' }))

    expect(startDraft).not.toHaveBeenCalled()
    expect(await screen.findByText('当前线路未配置价格')).toBeVisible()
    await user.click(screen.getByRole('checkbox', { name: '我知道该线路费用未知，仍要启动这一次' }))
    await user.click(screen.getByRole('button', { name: '确认外发与费用，开始任务' }))
    expect(startDraft).toHaveBeenCalledWith('chapter-production-1', expect.objectContaining({
      outline_candidate_id: outline.id,
      confirm_external_processing: true,
      confirm_unknown_cost: true,
    }))
    expect(await screen.findByRole('textbox', { name: '编辑正面交锋版候选副本' })).toHaveValue(candidateText)
    expect(screen.getByLabelText('章节正文')).toHaveValue('')
    await user.click(screen.getByRole('button', { name: '确认采用这份候选' }))
    await waitFor(() => expect(screen.getByLabelText('章节正文')).toHaveValue(candidateText))
  })

  it('adds evidence to the original timeline without changing the novel timeline', async () => {
    const originalEvent = {
      id: '51a17412-307c-4dc0-9f74-76d7e67aa472',
      project_id: workspace.project.id,
      layer: 'original' as const,
      event_year: 1998,
      title: '南平铝厂推进改制',
      summary: '现实资料锚点',
      source_chapter_id: null,
      created_at: '2026-08-08T00:00:00Z',
    }
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    const createEvent = vi.spyOn(api, 'createOriginalTimelineEvent').mockResolvedValue(originalEvent)
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    await user.click(screen.getByText('添加原始时间线事件'))
    await user.type(screen.getByLabelText('原始事件标题'), originalEvent.title)
    await user.type(screen.getByLabelText('原始事件摘要'), originalEvent.summary)
    await user.click(screen.getByRole('button', { name: '写入原始时间线' }))

    expect(createEvent).toHaveBeenCalledWith(workspace.project.id, {
      event_year: 1998,
      title: originalEvent.title,
      summary: originalEvent.summary,
    })
    expect(await screen.findByText(originalEvent.title)).toBeVisible()
    expect(screen.getByText('确认事实后自动落轨。')).toBeVisible()
  })

  it('keeps legacy FactChangeSet candidates available as read-only history', async () => {
    const approvedChapter = {
      ...workspace.chapters[0],
      content: '列车驶入南平站。',
      status: 'approved' as const,
      revision: 5,
    }
    const candidate = {
      id: '6bd15b26-cfe4-4d76-9510-e10a987a3dc0',
      chapter_id: approvedChapter.id,
      chapter_revision: approvedChapter.revision,
      state: 'candidate' as const,
      revision: 0,
      changes: [
        {
          id: 'dd47a0ac-e761-4d05-899e-c84f56cb3a08',
          change_set_id: '6bd15b26-cfe4-4d76-9510-e10a987a3dc0',
          kind: 'state_change' as const,
          content: approvedChapter.state_change,
          event_year: 1998,
        },
        {
          id: '50524ce1-f441-4f07-8327-f3fe91c8273d',
          change_set_id: '6bd15b26-cfe4-4d76-9510-e10a987a3dc0',
          kind: 'open_thread' as const,
          content: approvedChapter.ending_cliffhanger,
          event_year: null,
        },
      ],
      created_at: '2026-08-08T00:00:00Z',
      updated_at: '2026-08-08T00:00:00Z',
    }
    const approvedWorkspace: Workspace = {
      ...workspace,
      chapters: [approvedChapter],
      fact_change_sets: [candidate],
    }
    vi.spyOn(api, 'createProject').mockResolvedValue(approvedWorkspace)
    const createLegacy = vi.spyOn(api, 'createFactChangeSet')
    const applyLegacy = vi.spyOn(api, 'applyFactChangeSet')
    vi.spyOn(api, 'getLatestCanonReconciliation').mockResolvedValue(null)
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    expect(await screen.findByRole('heading', { name: '旧版事实回流记录' })).toBeVisible()
    expect(screen.getByText('这批旧版候选尚未处理，当前版本保持只读。')).toBeVisible()
    expect(screen.queryByRole('button', { name: '提取候选事实' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /确认回灌/ })).not.toBeInTheDocument()
    expect(createLegacy).not.toHaveBeenCalled()
    expect(applyLegacy).not.toHaveBeenCalled()
  })

  it('keeps divergence-affected future knowledge behind an author review gate', async () => {
    const pendingKnowledge = {
      id: 'ab9d2742-c68c-42e4-88b8-0cdce7b1710b',
      project_id: workspace.project.id,
      future_year: 2003,
      content: '建阳会开出第一家大型连锁超市',
      source_note: '上一世亲历',
      confidence: 'certain' as const,
      status: 'candidate_invalid' as const,
      divergence_event_id: '58248730-3457-4667-a57c-3b9a94d85f97',
      revision: 1,
      created_at: '2026-08-08T00:00:00Z',
      updated_at: '2026-08-08T00:00:01Z',
    }
    const knowledgeWorkspace: Workspace = {
      ...workspace,
      future_knowledge: [pendingKnowledge],
    }
    vi.spyOn(api, 'createProject').mockResolvedValue(knowledgeWorkspace)
    const review = vi.spyOn(api, 'reviewFutureKnowledge').mockResolvedValue({
      ...pendingKnowledge,
      status: 'valid',
      revision: 2,
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    expect(await screen.findByText('分歧后待复核')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '仍然有效' }))

    expect(review).toHaveBeenCalledWith(pendingKnowledge.id, 'keep_valid', 1)
    expect(await screen.findByText('当前有效')).toBeVisible()
    expect(screen.getByText(pendingKnowledge.content)).toBeVisible()
  })

  it('creates and updates a character ledger entry', async () => {
    const character = {
      id: 'd37d91c2-ad6d-4b5c-a344-330352a20e46',
      project_id: workspace.project.id,
      kind: 'character' as const,
      name: '沈砚',
      role: '重生者',
      goal: '保住父亲的工作',
      current_state: '刚回到南平',
      relationship_notes: '与父亲有上一世留下的隔阂',
      revision: 0,
      created_at: '2026-08-08T00:00:00Z',
      updated_at: '2026-08-08T00:00:00Z',
    }
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    const createEntity = vi.spyOn(api, 'createStoryEntity').mockResolvedValue(character)
    const updateEntity = vi.spyOn(api, 'updateStoryEntity').mockResolvedValue({
      ...character,
      current_state: '已经进入厂长办公室',
      revision: 1,
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    await user.click(screen.getByText('人物与资源账本'))
    await user.type(screen.getByLabelText('人物或资源名称'), character.name)
    await user.type(screen.getByLabelText('人物或资源定位'), character.role)
    await user.type(screen.getByLabelText('人物欲望或资源用途'), character.goal)
    await user.type(screen.getByLabelText('人物或资源当前状态'), character.current_state)
    await user.type(screen.getByLabelText('人物或资源关系备注'), character.relationship_notes)
    await user.click(screen.getByRole('button', { name: '添加人物' }))

    expect(createEntity).toHaveBeenCalledWith(workspace.project.id, {
      kind: 'character',
      name: character.name,
      role: character.role,
      goal: character.goal,
      current_state: character.current_state,
      relationship_notes: character.relationship_notes,
    })
    await user.click(await screen.findByText(character.name))
    const stateFields = screen.getAllByLabelText('当前状态')
    await user.clear(stateFields[0])
    await user.type(stateFields[0], '已经进入厂长办公室')
    await user.click(screen.getByRole('button', { name: '更新账本' }))

    expect(updateEntity).toHaveBeenCalledWith(character.id, {
      name: character.name,
      role: character.role,
      goal: character.goal,
      current_state: '已经进入厂长办公室',
      relationship_notes: character.relationship_notes,
      expected_revision: 0,
    })
    expect((await screen.findAllByText('已经进入厂长办公室')).length).toBeGreaterThan(0)
  })

  it('keeps a new reality source unconfirmed until the author approves it', async () => {
    const sourceCard = {
      id: 'c86c0ec7-c1b8-4fb4-a7c9-c5d26f41fa13',
      project_id: workspace.project.id,
      source_kind: 'industry' as const,
      title: '南平铝厂改制资料',
      source_reference: '作者本地档案 1998-04',
      applicable_year_start: 1998,
      applicable_year_end: 1999,
      confidence: 'high' as const,
      excerpt: '先岗位摸底，再公布分流方案。',
      source_document_id: null,
      source_date: null,
      page_number_start: null,
      page_number_end: null,
      start_char: null,
      end_char: null,
      confirmed: false,
      revision: 0,
      created_at: '2026-08-08T00:00:00Z',
      updated_at: '2026-08-08T00:00:00Z',
    }
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    const createCard = vi.spyOn(api, 'createSourceCard').mockResolvedValue(sourceCard)
    const confirm = vi.spyOn(api, 'setSourceCardConfirmation').mockResolvedValue({
      ...sourceCard,
      confirmed: true,
      revision: 1,
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    await user.click(screen.getByText('新建资料卡'))
    await user.selectOptions(screen.getByLabelText('资料类型'), 'industry')
    await user.selectOptions(screen.getByLabelText('资料可信度'), 'high')
    await user.type(screen.getByLabelText('资料卡标题'), sourceCard.title)
    await user.type(screen.getByLabelText('资料卡来源'), sourceCard.source_reference)
    fireEvent.change(screen.getByLabelText('资料适用止年'), { target: { value: '1999' } })
    await user.type(screen.getByLabelText('资料卡摘要'), sourceCard.excerpt)
    await user.click(screen.getByRole('button', { name: '保存为待确认资料卡' }))

    expect(createCard).toHaveBeenCalledWith(workspace.project.id, {
      source_kind: 'industry',
      title: sourceCard.title,
      source_reference: sourceCard.source_reference,
      applicable_year_start: 1998,
      applicable_year_end: 1999,
      confidence: 'high',
      excerpt: sourceCard.excerpt,
    })
    expect(await screen.findByText('待确认')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '确认为现实锚点' }))

    expect(confirm).toHaveBeenCalledWith(sourceCard.id, true, 0)
    expect(await screen.findByText('已确认')).toBeVisible()
  })

  it('shows promise and payoff across a three-chapter rhythm window', async () => {
    const rhythmWorkspace: Workspace = {
      ...workspace,
      chapters: [1, 2, 3].map((chapterNumber) => ({
        ...workspace.chapters[0],
        id: `chapter-${chapterNumber}`,
        chapter_number: chapterNumber,
        title: `第${chapterNumber}章 节拍`,
        reader_promise: `承诺 ${chapterNumber}`,
        opening_hook: `钩子 ${chapterNumber}`,
        state_change: `变化 ${chapterNumber}`,
        emotional_payoff: `回报 ${chapterNumber}`,
        ending_cliffhanger: `悬念 ${chapterNumber}`,
      })),
    }
    vi.spyOn(api, 'createProject').mockResolvedValue(rhythmWorkspace)
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    const rhythm = within(screen.getByRole('table', { name: '连续三章节奏分布' }))
    expect(rhythm.getByText('承诺 1')).toBeVisible()
    expect(rhythm.getByText('回报 2')).toBeVisible()
    expect(rhythm.getByText('悬念 3')).toBeVisible()
  })

  it('shows a sourced resume card and deterministic continuity issues', async () => {
    const resumeWorkspace: Workspace = {
      ...workspace,
      continuity_issues: [{
        id: 'rhythm-gap:chapter-1',
        kind: 'rhythm_gap',
        severity: 'warning',
        title: '第 1 章节奏记录不完整',
        detail: '缺少情绪回报。',
        source_labels: ['第一章 未命名'],
      }],
      resume_card: {
        chapter_id: workspace.chapters[0].id,
        chapter_number: 1,
        chapter_title: workspace.chapters[0].title,
        chapter_status: 'drafted',
        last_progress: '主角已经拿到停产名单。',
        next_entry: '承接本章悬念：厂长认出了主角',
        open_threads: [{
          label: '厂长为何认识主角',
          detail: '等待旧照片线索回收。',
          source: '第 1 章埋设',
        }],
        active_entities: [],
        pending_reviews: 1,
        warning_count: 1,
      },
    }
    vi.spyOn(api, 'createProject').mockResolvedValue(resumeWorkspace)
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    expect(await screen.findByText('主角已经拿到停产名单。')).toBeVisible()
    expect(screen.getByText('承接本章悬念：厂长认出了主角')).toBeVisible()
    expect(screen.getByText('第 1 章节奏记录不完整')).toBeVisible()
    expect(screen.getByText('依据：第一章 未命名')).toBeVisible()
  })

  it('retries a failed AI task from the task center', async () => {
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    const failedJob: Job = {
      ...queuedJob('chapter_draft', workspace.chapters[0].id),
      state: 'failed',
      current_step: 'AI 正在写完整章节候选',
      error_code: 'provider_error',
      error_message: '模型服务未完成当前章节任务，可安全重试',
    }
    vi.mocked(api.listJobs).mockResolvedValue([failedJob])
    vi.spyOn(api, 'getJob').mockResolvedValue(jobDetail(failedJob))
    const retryJob = vi.spyOn(api, 'retryJob').mockResolvedValue({
      ...failedJob,
      state: 'queued',
      error_code: null,
      error_message: null,
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    await openUtilityDestination('打开任务中心')
    expect(await screen.findByRole('heading', { name: '任务中心' })).toBeVisible()
    expect(await screen.findByText('模型服务未完成当前章节任务，可安全重试')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '从断点继续' }))

    expect(retryJob).toHaveBeenCalledWith(failedJob.id)
    expect(screen.getByText(/排队中 · 0\/1/)).toBeVisible()
  })

  it('views an immutable artifact and returns chapter work to the unified production desk', async () => {
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    const completedJob: Job = {
      ...queuedJob('chapter_brief', workspace.chapters[0].id),
      workflow: 'chapter_production_outline',
      state: 'succeeded',
      progress_current: 1,
      completed_calls: 1,
      current_step: '章节候选已生成',
    }
    const artifact = {
      id: 'brief-artifact-1',
      job_id: completedJob.id,
      chunk_id: null,
      kind: 'chapter_brief',
      artifact_key: 'brief',
      content_type: 'application/json' as const,
      payload_sha256: 'a'.repeat(64),
      metadata: {},
      provider: 'openai',
      provider_profile_id: null,
      model: 'gpt-5.6',
      created_at: '2026-08-09T00:00:01Z',
    }
    vi.mocked(api.listJobs).mockResolvedValue([completedJob])
    vi.spyOn(api, 'getJob').mockResolvedValue({
      ...jobDetail(completedJob),
      artifacts: [artifact],
    })
    vi.spyOn(api, 'getJobArtifact').mockResolvedValue({
      ...artifact,
      payload: '{"title":"第一章 名单之前"}',
    })
    const outline = productionOutline(workspace.chapters[0])
    vi.mocked(api.getCurrentChapterProduction).mockResolvedValue(
      productionSnapshot(workspace.chapters[0], { outline }),
    )
    const legacyUpdate = vi.spyOn(api, 'updateChapterBrief')
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    await openUtilityDestination('打开任务中心')
    await user.click(await screen.findByText('章节候选已生成'))
    await user.click(await screen.findByRole('button', { name: 'chapter_brief · aaaaaaaa' }))
    expect(await screen.findByText('{"title":"第一章 名单之前"}')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '回到单章生产台' }))
    expect(await screen.findByRole('dialog', { name: '本章候选生产台' })).toBeVisible()
    expect(await screen.findByLabelText('开篇钩子')).toHaveValue(outline.current_version.content.opening_hook)
    expect(legacyUpdate).not.toHaveBeenCalled()
  })

  it('blocks an old chapter draft in the task center and returns to the writing workspace', async () => {
    const currentWorkspace: Workspace = {
      ...workspace,
      chapters: [{
        ...workspace.chapters[0],
        content: '作者已经修改的正文。',
        status: 'drafted',
        revision: 2,
      }],
    }
    const completedJob: Job = {
      ...queuedJob('chapter_draft', currentWorkspace.chapters[0].id),
      workflow: 'chapter_production_draft',
      state: 'succeeded',
      progress_current: 1,
      completed_calls: 1,
      current_step: '章节候选已生成',
    }
    const oldCandidate = productionCandidate(currentWorkspace.chapters[0], '旧版本候选正文。')
    const outline = productionOutline(currentWorkspace.chapters[0])
    vi.spyOn(api, 'createProject').mockResolvedValue(currentWorkspace)
    vi.mocked(api.listJobs).mockResolvedValue([completedJob])
    vi.spyOn(api, 'getJob').mockResolvedValue(jobDetail(completedJob))
    vi.mocked(api.getCurrentChapterProduction).mockResolvedValue(productionSnapshot(
      currentWorkspace.chapters[0],
      { outline, candidate: oldCandidate, baseRevision: 1 },
    ))
    const applyGeneration = vi.spyOn(api, 'applyGeneration')
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), currentWorkspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    await openUtilityDestination('打开任务中心')
    await user.click(await screen.findByRole('button', { name: '回到单章生产台' }))

    expect(await screen.findByText('候选基于旧版本，作者编辑已保留。')).toBeVisible()
    expect(screen.getByRole('button', { name: '确认采用这份候选' })).toBeDisabled()
    expect(applyGeneration).not.toHaveBeenCalled()
    expect(screen.getByLabelText('章节正文')).toHaveValue('作者已经修改的正文。')
  })

  it('keeps a chapter-production candidate recoverable when adoption hits a revision conflict', async () => {
    const completedJob: Job = {
      ...queuedJob('chapter_draft', workspace.chapters[0].id),
      workflow: 'chapter_production_draft',
      state: 'succeeded',
      progress_current: 1,
      completed_calls: 1,
      current_step: '章节候选已生成',
    }
    const generatedCandidate = productionCandidate(
      workspace.chapters[0],
      '提交采用时才发现过期的候选。',
    )
    const outline = productionOutline(workspace.chapters[0])
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    vi.mocked(api.listJobs).mockResolvedValue([completedJob])
    vi.spyOn(api, 'getJob').mockResolvedValue(jobDetail(completedJob))
    vi.mocked(api.getCurrentChapterProduction).mockResolvedValue(productionSnapshot(
      workspace.chapters[0],
      { outline, candidate: generatedCandidate },
    ))
    const adopt = vi.spyOn(api, 'adoptChapterProductionCandidate').mockRejectedValue(
      new ApiError('正式正文已变更', 409, 'chapter_changed'),
    )
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))
    await openUtilityDestination('打开任务中心')
    await user.click(await screen.findByRole('button', { name: '回到单章生产台' }))
    await user.click(await screen.findByRole('button', { name: '确认采用这份候选' }))

    expect(adopt).toHaveBeenCalledOnce()
    expect(await screen.findByText('正式正文已变更；候选编辑已保留，请刷新后重新检查。')).toBeVisible()
    expect(screen.getByRole('textbox', { name: '编辑正面交锋版候选副本' })).toHaveValue(
      generatedCandidate.current_version.content,
    )
  })

  it('imports another reference work, keeps raw analysis single-book, and preserves old v1 cards', async () => {
    const existingWork = {
      id: 'reference-alpha',
      project_id: workspace.project.id,
      project_ids: [workspace.project.id],
      title: '参考甲',
      source_filename: 'alpha.txt',
      source_format: 'txt' as const,
      rights_basis: 'self_owned' as const,
      total_characters: 500_000,
      segment_target_characters: 500_000,
      content_sha256: 'a'.repeat(64),
      source_sha256: 'a'.repeat(64),
      source_encoding: 'utf-8',
      encoding_confidence: 1,
      import_state: 'ready' as const,
      duplicate_of_id: null,
      source_spans: [],
      segments: [{
        id: 'segment-alpha-1',
        reference_work_id: 'reference-alpha',
        ordinal: 1,
        start_char: 0,
        end_char: 500_000,
        character_count: 500_000,
        chapter_start: '第一章 开端',
        chapter_end: '第一百章 变局',
        created_at: '2026-08-09T00:00:00Z',
      }],
      created_at: '2026-08-09T00:00:00Z',
      updated_at: '2026-08-09T00:00:00Z',
    }
    const importedWork = {
      ...existingWork,
      id: 'reference-beta',
      title: 'beta',
      source_filename: 'beta.md',
      source_format: 'markdown' as const,
      rights_basis: 'public_domain' as const,
      total_characters: 12,
      segments: [{
        ...existingWork.segments[0],
        id: 'segment-beta-1',
        reference_work_id: 'reference-beta',
        end_char: 12,
        character_count: 12,
        chapter_start: '第一章 新局',
        chapter_end: '第一章 新局',
      }],
    }
    const filePreview = {
      source_filename: 'beta.md',
      source_format: 'markdown' as const,
      source_encoding: 'utf-8',
      encoding_confidence: 0.99,
      import_state: 'ready' as const,
      source_sha256: 'b'.repeat(64),
      content_sha256: 'c'.repeat(64),
      total_characters: 12,
      page_count: 0,
      preview: '第一章 新局\n新的结构',
      warnings: [],
      source_spans: [],
    }
    vi.spyOn(api, 'previewReferenceFile').mockResolvedValue(filePreview)
    const importWork = vi.spyOn(api, 'importReferenceFile').mockResolvedValue(importedWork)
    const sourceSegmentIds = [existingWork.segments[0].id, importedWork.segments[0].id]
    const dimension = (summary: string) => ({
      summary,
      source_segment_ids: sourceSegmentIds,
      transferable_logic: '保留功能，重写具体人物和事件。',
      adaptation_risk: '避免沿用专名和独特场景顺序。',
    })
    const patternCard = {
      id: 'pattern-card-1',
      project_id: workspace.project.id,
      source_job_id: 'reference-job-1',
      selected_segment_ids: sourceSegmentIds,
      author_focus: '重点比较资源增长',
      provider: 'openai' as const,
      model: 'test-reference-model',
      created_at: '2026-08-09T01:00:00Z',
      era: dimension('时代转型提供机会窗口。'),
      core_desire: dimension('主角渴望改写家庭命运。'),
      conflict_causality: dimension('信息差触发行动，旧秩序随后反制。'),
      resource_system: dimension('知识逐步转化为人脉和组织资源。'),
      key_scene_sequence: dimension('发现机会—小胜验证—强敌注意—阶段反转。'),
      ending: dimension('阶段胜利打开更高层冲突。'),
      shared_patterns: ['信息差必须转化为可见行动'],
      differences: ['一个偏家庭生存，一个偏商业扩张'],
      relationship_recomposition: '新作改为师徒与竞争者的三角制衡。',
      originality_risks: ['不能复用产业、专名和相同场景顺序'],
    }
    const workspaceWithLegacyCard = {
      ...workspace,
      reference_works: [existingWork],
      reference_pattern_cards: [patternCard],
    }
    vi.spyOn(api, 'createProject').mockResolvedValue(workspaceWithLegacyCard)
    vi.mocked(api.getProjectSummary).mockResolvedValue(summarizeWorkspace({
      ...workspaceWithLegacyCard,
      reference_works: [existingWork, importedWork],
    }))
    const appliedDimensions = ['era', 'core_desire', 'conflict_causality', 'resource_system', 'key_scene_sequence'] as const
    const appliedBlueprint: ReferenceBlueprintState = {
      dimensions: Object.fromEntries(appliedDimensions.map((key) => [key, {
        source: patternCard[key],
        mode: 'adjust',
        author_edits: '落到南平本地产业，人物关系全部重组。',
        generated_variant: {
          summary: patternCard[key].summary,
          transferable_logic: patternCard[key].transferable_logic,
        },
        version: 1,
        locked: false,
        named_entities: [],
        source_beats: [],
        key_beats: [],
      }])) as ReferenceBlueprintState['dimensions'],
      relationship: {
        source: patternCard.relationship_recomposition,
        mode: 'reconstruct',
        author_edits: '人物关系全部重组。',
        generated_variant: '改为家庭伙伴与创业竞争者的三角制衡。',
        version: 1,
        locked: false,
        relationships: [],
      },
    }
    const patternApplication = {
      id: 'pattern-application-1',
      project_id: workspace.project.id,
      pattern_card_id: patternCard.id,
      lifecycle_state: 'active' as const,
      lifecycle_revision: 0,
      selected_dimensions: [...appliedDimensions],
      dimensions: {
        era: { summary: patternCard.era.summary, transferable_logic: patternCard.era.transferable_logic },
      },
      relationship_recomposition: patternCard.relationship_recomposition,
      application_note: '落到南平本地产业，人物关系全部重组。',
      blueprint: appliedBlueprint,
      originality_status: 'review_required' as const,
      risk_level: 'medium' as const,
      latest_report_id: 'originality-report-1',
      threshold_version: 'originality-rules-v1',
      revision: 0,
      created_at: '2026-08-09T01:05:00Z',
      updated_at: '2026-08-09T01:05:00Z',
    }
    const applyPattern = vi.spyOn(api, 'applyReferencePattern').mockResolvedValue(patternApplication)
    vi.spyOn(api, 'getOriginalityReport').mockResolvedValue({
      id: 'originality-report-1',
      application_id: patternApplication.id,
      blueprint_revision: 0,
      risk_level: 'medium',
      score: 35,
      threshold_version: 'originality-rules-v1',
      checked_dimensions: [...appliedDimensions],
      evidence: [{
        signal: 'multi_dimension',
        score: 35,
        summary: '最终组合保留了 5 个来源维度；需要作者明确确认。',
        dimension: null,
        source_segment_id: null,
        source_character_start: null,
        source_character_end: null,
        evidence_sha256: 'd'.repeat(64),
      }],
      source_segment_ids: sourceSegmentIds,
      input_sha256: 'e'.repeat(64),
      legal_notice: '原创性风险提示用于创作风控，不是法律结论。',
      viewed_at: null,
      created_at: '2026-08-09T01:05:00Z',
    })
    vi.spyOn(api, 'acknowledgeOriginalityReport').mockResolvedValue({
      ...patternApplication,
      originality_status: 'review_required',
    })
    const sceneReport = {
      id: 'scene-report-1',
      application_id: patternApplication.id,
      blueprint_revision: 0,
      risk_level: 'medium' as const,
      score: 48,
      threshold_version: 'scene-plot-graph-v1',
      candidate_graph: {
        nodes: [
          { id: 'scene-1', label: '发现机会窗口', semantic_terms: ['调查'] },
          { id: 'scene-2', label: '小胜验证资源', semantic_terms: ['取得'] },
        ],
        edges: [{ source: 'scene-1', target: 'scene-2', relation: 'leads_to' }],
      },
      findings: [{
        signal: 'ordered_sequence' as const,
        score: 48,
        summary: '候选场景的功能顺序与来源节拍序列接近，建议重排触发条件与结果链。',
        source_segment_ids: sourceSegmentIds,
        evidence_sha256: 'f'.repeat(64),
      }],
      source_segment_ids: sourceSegmentIds,
      source_work_count: 2,
      input_sha256: '1'.repeat(64),
      legal_notice: '场景语义与情节图检测用于创作风控，不是抄袭认定或法律结论。',
      status: 'review_required' as const,
      viewed_at: null,
      acknowledged_at: null,
      created_at: '2026-08-09T01:05:00Z',
    }
    vi.spyOn(api, 'getOrRunSceneOriginalityCheck').mockResolvedValue(sceneReport)
    vi.spyOn(api, 'getSceneOriginalityCheck').mockResolvedValue({
      ...sceneReport,
      viewed_at: '2026-08-09T01:06:00Z',
    })
    vi.spyOn(api, 'acknowledgeSceneOriginalityCheck').mockResolvedValue({
      ...patternApplication,
      originality_status: 'passed',
    })
    vi.spyOn(api, 'updateReferenceBlueprint').mockImplementation(
      async (_projectId, _applicationId, input) => ({
        ...patternApplication,
        blueprint: input.blueprint,
        originality_status: 'passed',
        risk_level: 'low',
        revision: 1,
      }),
    )
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))
    await openUtilityDestination('打开拆书库')

    expect(screen.getByRole('heading', { name: '先拆成规律，再带回你的书' })).toBeVisible()

    const file = new File(['第一章 新局\n新的结构'], 'beta.md', { type: 'text/markdown' })
    if (!file.text) Object.defineProperty(file, 'text', { value: async () => '第一章 新局\n新的结构' })
    await user.upload(screen.getByLabelText('选择参考小说文件'), file)
    await user.selectOptions(screen.getByLabelText('作品权利基础'), 'public_domain')
    await user.click(screen.getByRole('button', { name: '检测编码并查看预览' }))
    expect(await screen.findByLabelText('参考文件预览')).toHaveTextContent('第一章 新局 新的结构')
    await user.click(screen.getByRole('button', { name: '导入并按 50 万字切段' }))

    expect(importWork).toHaveBeenCalledWith(file, {
      title: 'beta',
      rights_basis: 'public_domain',
      segment_target_characters: 500_000,
      expected_source_sha256: filePreview.source_sha256,
      confirm_preview: true,
      confirm_uncertain_encoding: false,
      project_id: workspace.project.id,
    })
    const alphaStage = await screen.findByRole('checkbox', { name: '选择参考甲第 1 阶段' })
    const betaStage = screen.getByRole('checkbox', { name: '选择beta第 1 阶段' })
    await user.click(alphaStage)
    expect(alphaStage).toBeChecked()
    await user.click(betaStage)
    expect(alphaStage).not.toBeChecked()
    expect(betaStage).toBeChecked()
    expect(screen.getByText('切换到另一本书时，上一本的勾选会自动清空。', { exact: false })).toBeVisible()

    expect(await screen.findByText('知识逐步转化为人脉和组织资源。')).toBeVisible()
    expect(screen.getByText('新作改为师徒与竞争者的三角制衡。')).toBeVisible()
    expect(screen.getByText('这张旧版卡片仅供查看，不再新建应用。', { exact: false })).toBeVisible()
    expect(screen.queryByRole('button', { name: `应用到《${workspace.project.title}》` })).not.toBeInTheDocument()
    expect(applyPattern).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: '返回创作台' }))
    expect(screen.getByLabelText('章节正文')).toBeVisible()
    expect(screen.queryByRole('heading', { name: '先拆成规律，再带回你的书' })).not.toBeInTheDocument()
  })
})
