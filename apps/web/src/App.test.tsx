import type { GenerationRun, Job, JobKind, Workspace, WorkspaceSummary } from '@mozhou/contracts'
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { App } from './App'
import { api } from './api'

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
    state: 'queued',
    idempotency_key: `${kind}-test`,
    progress_current: 0,
    progress_total: 1,
    current_step: '',
    estimated_calls: 1,
    completed_calls: 0,
    provider: 'openai',
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

beforeEach(() => {
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
  })
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('App', () => {
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

  it('exports a complete archive from the project shelf', async () => {
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

    expect(exportProject).toHaveBeenCalledWith(workspace.project.id)
    expect(objectUrl).toHaveBeenCalledOnce()
    expect(click).toHaveBeenCalledOnce()
    expect(revokeUrl).toHaveBeenCalledWith('blob:mozhou-archive')
    expect(screen.getByRole('status')).toHaveTextContent('归档已导出')
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
    fireEvent.click(screen.getByRole('button', { name: '打开拆书库' }))

    expect(update).toHaveBeenCalledWith(workspace.chapters[0].id, {
      content: '刚写下、还没有等到自动保存的一句。',
      expected_revision: 0,
    })
    expect(await screen.findByRole('heading', { name: '先拆成规律，再带回你的书' })).toBeVisible()
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
  })

  it('keeps the current chapter open when the next chapter body cannot load', async () => {
    const secondChapter = {
      ...workspace.chapters[0],
      id: '14eb18c0-4ea7-44aa-b30f-cb39825a9961',
      chapter_number: 2,
      title: '第2章 还没到站',
      content: '这一章暂时无法读取。',
    }
    vi.spyOn(api, 'createProject').mockResolvedValue({
      ...workspace,
      chapters: [workspace.chapters[0], secondChapter],
    })
    vi.mocked(api.getChapter).mockRejectedValue(new Error('章节正文读取失败'))
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    await user.click(screen.getByRole('button', { name: '打开第 2 章：第2章 还没到站' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('章节正文读取失败')
    expect(screen.getByRole('heading', { name: workspace.chapters[0].title })).toBeVisible()
    expect(screen.getByLabelText('章节正文')).toHaveValue(workspace.chapters[0].content)
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
    fireEvent.click(screen.getByRole('button', { name: '打开拆书库' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('本地服务暂时不可用')
    expect(screen.getByLabelText('章节正文')).toHaveValue('这句话必须留在编辑器里。')
    expect(screen.queryByRole('heading', { name: '先拆成规律，再带回你的书' })).not.toBeInTheDocument()
  })

  it('saves the chapter brief before preparing generation context', async () => {
    const emptyWorkspace: Workspace = {
      ...workspace,
      chapters: [{
        ...workspace.chapters[0],
        opening_hook: '',
        state_change: '',
        ending_cliffhanger: '',
      }],
    }
    vi.spyOn(api, 'createProject').mockResolvedValue(emptyWorkspace)
    const saveBrief = vi.spyOn(api, 'updateChapterBrief').mockResolvedValue({
      ...emptyWorkspace.chapters[0],
      opening_hook: '洪水预警只剩六小时',
      state_change: '说服父亲调走仓库物资',
      ending_cliffhanger: '失踪多年的舅舅打来电话',
      revision: 1,
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    expect(screen.getByRole('button', { name: '先完成并保存章纲' })).toBeDisabled()
    await user.type(screen.getByLabelText('开篇钩子'), '洪水预警只剩六小时')
    await user.type(screen.getByLabelText('状态变化'), '说服父亲调走仓库物资')
    await user.type(screen.getByLabelText('章尾悬念'), '失踪多年的舅舅打来电话')
    await user.click(screen.getByRole('button', { name: '保存章纲' }))

    expect(saveBrief).toHaveBeenCalledWith(emptyWorkspace.chapters[0].id, {
      title: '第一章 未命名',
      reader_promise: '',
      opening_hook: '洪水预警只剩六小时',
      state_change: '说服父亲调走仓库物资',
      emotional_payoff: '',
      ending_cliffhanger: '失踪多年的舅舅打来电话',
      expected_revision: 0,
    })
    expect(await screen.findByRole('button', { name: '准备章节上下文' })).toBeEnabled()
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

  it('moves a saved draft into review through the chapter state command', async () => {
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
    const transition = vi.spyOn(api, 'transitionChapter').mockResolvedValue({
      ...draftedWorkspace.chapters[0],
      status: 'reviewing',
      revision: 3,
    })
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
  })

  it('keeps generated text as a candidate until the author applies it', async () => {
    const candidate = '1998年的慢车驶进福建南平时，站台广播带着电流声。'
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    vi.spyOn(api, 'startGeneration').mockResolvedValue({
      id: 'd80eb27a-5f0c-45dc-92ea-ea40e66e1c4c',
      chapter_id: workspace.chapters[0].id,
      state: 'drafted' as const,
      expected_chapter_revision: 0,
      candidate_content: candidate,
      error_message: null,
      provider: 'demo',
      model: 'replay-v1',
      created_at: '2026-08-08T00:00:00Z',
      updated_at: '2026-08-08T00:00:01Z',
    })
    vi.spyOn(api, 'applyGeneration').mockResolvedValue({
      ...workspace.chapters[0],
      content: candidate,
      status: 'drafted',
      revision: 1,
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    await user.click(await screen.findByRole('button', { name: '准备章节上下文' }))
    await user.click(screen.getByRole('button', { name: '生成示范候选稿' }))
    expect(await screen.findByText(candidate)).toBeVisible()
    expect(screen.getByLabelText('章节正文')).toHaveValue('')

    await user.click(screen.getByRole('button', { name: '采用并写入编辑器' }))

    expect(screen.getByLabelText('章节正文')).toHaveValue(candidate)
    expect(screen.getByRole('button', { name: '已写入草稿' })).toBeDisabled()
  })

  it('lets AI propose a complete brief without changing the saved chapter', async () => {
    vi.mocked(api.getAiStatus).mockResolvedValue({
      configured: true,
      provider: 'openai',
      model: 'gpt-5.6',
      key_source: 'session',
    })
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    const proposal = {
      title: '第一章 名单之前',
      reader_promise: '主角第一次改变家庭命运',
      opening_hook: '停产名单比记忆中提前贴出',
      state_change: '主角让父亲避开首轮裁员',
      emotional_payoff: '父亲保住岗位却开始怀疑儿子',
      ending_cliffhanger: '厂长拿出一张不该存在的旧照片',
      why_this_works: '信息差立即转化为行动和家庭回报。',
      risk_notes: ['厂办流程需要现实资料校验'],
    }
    const briefJob = queuedJob('chapter_brief', workspace.chapters[0].id)
    const startBrief = vi.spyOn(api, 'startAiChapterBriefJob').mockResolvedValue(briefJob)
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
    vi.spyOn(api, 'getAiChapterBriefJobResult').mockResolvedValue(proposal)
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    await user.type(await screen.findByLabelText('本章创作意图'), '让主角用信息差救下父亲')
    await user.click(screen.getByRole('button', { name: 'AI 设计本章' }))

    expect(startBrief).toHaveBeenCalledWith(workspace.chapters[0].id, {
      expected_revision: 0,
      author_intent: '让主角用信息差救下父亲',
    })
    expect(await screen.findByText(proposal.why_this_works)).toBeVisible()
    expect(screen.getByLabelText('章节标题')).toHaveValue(workspace.chapters[0].title)
    await user.click(screen.getByRole('button', { name: '采用到章纲，继续确认' }))

    expect(screen.getByLabelText('章节标题')).toHaveValue(proposal.title)
    expect(screen.getByLabelText('读者承诺')).toHaveValue(proposal.reader_promise)
    expect(screen.getByLabelText('情绪回报')).toHaveValue(proposal.emotional_payoff)
    expect(screen.getByRole('button', { name: '保存章纲' })).toBeEnabled()
  })

  it('keeps an AI-written full chapter isolated until the author applies it', async () => {
    vi.mocked(api.getAiStatus).mockResolvedValue({
      configured: true,
      provider: 'openai',
      model: 'gpt-5.6',
      key_source: 'session',
    })
    vi.spyOn(api, 'createProject').mockResolvedValue(workspace)
    const candidate = '一九九八年的梅山坡还没有后来那排高楼。沈砚把停产名单压在桌上。'
    const generatedRun: GenerationRun = {
      id: '58463d2b-b298-45ca-a4d0-87af9f068bc6',
      chapter_id: workspace.chapters[0].id,
      state: 'drafted',
      expected_chapter_revision: 0,
      candidate_content: candidate,
      error_message: null,
      provider: 'openai',
      model: 'gpt-5.6',
      created_at: '2026-08-09T00:00:00Z',
      updated_at: '2026-08-09T00:00:01Z',
    }
    const draftJob = queuedJob('chapter_draft', workspace.chapters[0].id)
    const startDraft = vi.spyOn(api, 'startAiChapterDraftJob').mockResolvedValue(draftJob)
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
    vi.spyOn(api, 'getAiChapterDraftJobResult').mockResolvedValue(generatedRun)
    vi.spyOn(api, 'applyGeneration').mockResolvedValue({
      ...workspace.chapters[0],
      content: candidate,
      status: 'drafted',
      revision: 1,
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    await user.click(await screen.findByRole('button', { name: 'AI 写完整章节' }))

    expect(startDraft).toHaveBeenCalledWith(workspace.chapters[0].id, {
      expected_revision: 0,
      author_intent: '',
    })
    expect(await screen.findByText(candidate)).toBeVisible()
    expect(screen.getByLabelText('章节正文')).toHaveValue('')
    await user.click(screen.getByRole('button', { name: '采用并写入编辑器' }))
    expect(screen.getByLabelText('章节正文')).toHaveValue(candidate)
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

  it('backfills approved chapter facts only after the author confirms them', async () => {
    const approvedChapter = {
      ...workspace.chapters[0],
      content: '列车驶入南平站。',
      status: 'approved' as const,
      revision: 5,
    }
    const approvedWorkspace: Workspace = { ...workspace, chapters: [approvedChapter] }
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
    const appliedWorkspace: Workspace = {
      ...approvedWorkspace,
      fact_change_sets: [{ ...candidate, state: 'applied', revision: 1 }],
      story_facts: candidate.changes.map((change) => ({
        id: `fact-${change.id}`,
        project_id: workspace.project.id,
        source_chapter_id: approvedChapter.id,
        kind: change.kind,
        content: change.content,
        created_at: '2026-08-08T00:00:01Z',
      })),
      timeline_events: [{
        id: '58248730-3457-4667-a57c-3b9a94d85f97',
        project_id: workspace.project.id,
        layer: 'novel',
        event_year: 1998,
        title: approvedChapter.title,
        summary: approvedChapter.state_change,
        source_chapter_id: approvedChapter.id,
        created_at: '2026-08-08T00:00:01Z',
      }],
    }
    vi.spyOn(api, 'createProject').mockResolvedValue(approvedWorkspace)
    vi.spyOn(api, 'createFactChangeSet').mockResolvedValue(candidate)
    const apply = vi.spyOn(api, 'applyFactChangeSet').mockResolvedValue({
      ...candidate,
      state: 'applied',
      revision: 1,
    })
    vi.spyOn(api, 'getProject').mockResolvedValue(appliedWorkspace)
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    await user.click(screen.getByRole('button', { name: '提取候选事实' }))
    expect((await screen.findAllByText(approvedChapter.state_change)).length).toBeGreaterThan(1)
    expect(screen.getByText('确认事实后自动落轨。')).toBeVisible()

    await user.click(screen.getByRole('button', { name: '确认回灌 2 条' }))

    expect(apply).toHaveBeenCalledWith(candidate.id, {
      selected_change_ids: candidate.changes.map((change) => change.id),
      expected_revision: 0,
    })
    expect(await screen.findByText('本次已有 2 条事实进入正式设定。')).toBeVisible()
    expect(screen.getAllByText(approvedChapter.title).length).toBeGreaterThan(1)
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

  it('imports another reference work and selects segments across books', async () => {
    const existingWork = {
      id: 'reference-alpha',
      project_id: workspace.project.id,
      title: '参考甲',
      source_filename: 'alpha.txt',
      source_format: 'txt' as const,
      rights_basis: 'self_owned' as const,
      total_characters: 500_000,
      segment_target_characters: 500_000,
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
    vi.spyOn(api, 'createProject').mockResolvedValue({
      ...workspace,
      reference_works: [existingWork],
    })
    const importWork = vi.spyOn(api, 'importReferenceWork').mockResolvedValue(importedWork)
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
    const referenceJob = {
      id: patternCard.source_job_id,
      project_id: workspace.project.id,
      chapter_id: null,
      parent_job_id: null,
      kind: 'reference_fusion' as const,
      state: 'queued' as const,
      idempotency_key: 'reference-test',
      progress_current: 0,
      progress_total: 5,
      current_step: '',
      estimated_calls: 5,
      completed_calls: 0,
      provider: 'openai',
      model: 'test-reference-model',
      lease_owner: null,
      lease_expires_at: null,
      heartbeat_at: null,
      error_code: null,
      error_message: null,
      created_at: '2026-08-09T01:00:00Z',
      updated_at: '2026-08-09T01:00:00Z',
      started_at: null,
      completed_at: null,
    }
    const startAnalysis = vi.spyOn(api, 'startReferenceAnalysisJob').mockResolvedValue(referenceJob)
    vi.spyOn(api, 'getJob').mockResolvedValue({
      ...referenceJob,
      state: 'succeeded',
      progress_current: 5,
      completed_calls: 5,
      current_step: '跨书合成六维结构',
      chunks: [],
      attempts: [],
      artifacts: [],
      events: [],
    })
    vi.mocked(api.getProjectSummary).mockResolvedValue(summarizeWorkspace({
      ...workspace,
      reference_works: [existingWork, importedWork],
      reference_pattern_cards: [patternCard],
    }))
    const applyPattern = vi.spyOn(api, 'applyReferencePattern').mockResolvedValue({
      id: 'pattern-application-1',
      project_id: workspace.project.id,
      pattern_card_id: patternCard.id,
      selected_dimensions: ['era', 'core_desire', 'conflict_causality', 'resource_system', 'key_scene_sequence'],
      dimensions: {
        era: { summary: patternCard.era.summary, transferable_logic: patternCard.era.transferable_logic },
      },
      relationship_recomposition: patternCard.relationship_recomposition,
      application_note: '落到南平本地产业，人物关系全部重组。',
      created_at: '2026-08-09T01:05:00Z',
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(await screen.findByLabelText('作品名'), workspace.project.title)
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))
    await user.click(await screen.findByRole('button', { name: '打开拆书库' }))

    expect(screen.getByRole('heading', { name: '先拆成规律，再带回你的书' })).toBeVisible()

    const file = new File(['第一章 新局\n新的结构'], 'beta.md', { type: 'text/markdown' })
    if (!file.text) Object.defineProperty(file, 'text', { value: async () => '第一章 新局\n新的结构' })
    await user.upload(screen.getByLabelText('选择参考小说文件'), file)
    await user.selectOptions(screen.getByLabelText('作品权利基础'), 'public_domain')
    await user.click(screen.getByRole('button', { name: '导入并按 50 万字切段' }))

    expect(importWork).toHaveBeenCalledWith(workspace.project.id, {
      title: 'beta',
      source_filename: 'beta.md',
      rights_basis: 'public_domain',
      segment_target_characters: 500_000,
      content: '第一章 新局\n新的结构',
    })
    await user.click(await screen.findByRole('checkbox', { name: '选择参考甲第 1 段' }))
    await user.click(screen.getByRole('checkbox', { name: '选择beta第 1 段' }))
    expect(screen.getByText('已跨 2 本书选择 2 个区段')).toBeVisible()
    await user.click(screen.getByRole('checkbox', { name: '允许把选中区段分块发送给当前 AI' }))
    await user.type(screen.getByLabelText('多书分析重点'), '重点比较资源增长')
    await user.click(screen.getByRole('button', { name: 'AI 萃取六维结构' }))

    expect(startAnalysis).toHaveBeenCalledWith(workspace.project.id, {
      selected_segment_ids: sourceSegmentIds,
      author_focus: '重点比较资源增长',
      confirm_external_processing: true,
    })
    expect(await screen.findByText('知识逐步转化为人脉和组织资源。')).toBeVisible()
    expect(screen.getByText('新作改为师徒与竞争者的三角制衡。')).toBeVisible()
    await user.click(screen.getByRole('checkbox', { name: '应用维度：结局' }))
    await user.type(screen.getByLabelText('用于当前作品的改编备注'), '落到南平本地产业，人物关系全部重组。')
    await user.click(screen.getByRole('checkbox', { name: '确认原创改编边界' }))
    await user.click(screen.getByRole('button', { name: `应用到《${workspace.project.title}》` }))

    expect(applyPattern).toHaveBeenCalledWith(workspace.project.id, patternCard.id, {
      selected_dimensions: ['era', 'core_desire', 'conflict_causality', 'resource_system', 'key_scene_sequence'],
      application_note: '落到南平本地产业，人物关系全部重组。',
      confirm_original_adaptation: true,
    })
    expect(await screen.findByText('已应用到当前作品')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '返回创作台' }))
    expect(screen.getByLabelText('章节正文')).toBeVisible()
    expect(screen.queryByRole('heading', { name: '先拆成规律，再带回你的书' })).not.toBeInTheDocument()
  })
})
