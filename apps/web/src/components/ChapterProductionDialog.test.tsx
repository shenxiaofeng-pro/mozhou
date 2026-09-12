import type {
  Chapter,
  ChapterDraftCandidate,
  ChapterOutlineCandidate,
  ChapterProductionOutboundPreview,
  ChapterProductionPreflightCheck,
  ChapterProductionSnapshot,
  Job,
  Project,
} from '@mozhou/contracts'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api'
import { ChapterProductionDialog } from './ChapterProductionDialog'

const project: Project = {
  id: 'project-1',
  title: '南平旧事',
  genre: 'urban_rebirth',
  rebirth_year: 1998,
  rebirth_location: '福建南平',
  chapter_target_words: 3000,
  safety_buffer_chapters: 3,
  created_at: '2026-09-12T00:00:00Z',
  updated_at: '2026-09-12T00:00:00Z',
}

const chapter: Chapter = {
  id: 'chapter-1',
  project_id: project.id,
  volume_number: 1,
  chapter_number: 1,
  title: '第一章 提前的名单',
  content: '父亲把停产通知放在桌上。',
  reader_promise: '主角第一次改变家庭命运。',
  opening_hook: '停产名单比记忆中提前贴出。',
  state_change: '主角拿到仓库钥匙。',
  emotional_payoff: '父亲第一次选择相信主角。',
  ending_cliffhanger: '厂长拿出一张旧照片。',
  status: 'drafted',
  revision: 3,
  updated_at: '2026-09-12T00:00:00Z',
}

const outlineContent = {
  title: chapter.title,
  reader_promise: chapter.reader_promise,
  opening_hook: chapter.opening_hook,
  state_change: chapter.state_change,
  emotional_payoff: chapter.emotional_payoff,
  ending_cliffhanger: chapter.ending_cliffhanger,
  scene_beats: ['通知提前贴出', '主角夺回钥匙'],
}

function outline(): ChapterOutlineCandidate {
  return {
    id: 'outline-1',
    production_id: 'production-1',
    ordinal: 1,
    label: 'AI 章纲',
    state: 'available',
    current_version: {
      id: 'outline-version-1',
      candidate_id: 'outline-1',
      revision: 0,
      content: outlineContent,
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

function candidate(content = '父亲没有接话。沈砚拿起钥匙，径直走向仓库。'): ChapterDraftCandidate {
  return {
    id: 'candidate-1',
    production_id: 'production-1',
    label: '正面交锋版',
    state: 'available',
    source_outline_candidate_id: 'outline-1',
    source_outline_version_id: 'outline-version-1',
    source_outline_revision: 0,
    source_outline_content_sha256: 'a'.repeat(64),
    current_version: {
      id: 'candidate-version-1',
      candidate_id: 'candidate-1',
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

function snapshot(options: {
  outlines?: ChapterOutlineCandidate[]
  candidates?: ChapterDraftCandidate[]
  checks?: ChapterProductionPreflightCheck[]
  baseRevision?: number
} = {}): ChapterProductionSnapshot {
  const outlines = options.outlines ?? []
  return {
    production: {
      id: 'production-1',
      project_id: project.id,
      chapter_id: chapter.id,
      base_chapter_revision: options.baseRevision ?? chapter.revision,
      base_chapter_content_sha256: 'c'.repeat(64),
      state: (options.candidates?.length ?? 0) > 0 ? 'candidate_ready' : outlines.length > 0 ? 'outline_ready' : 'created',
      revision: 0,
      current_outline_candidate_id: outlines.at(-1)?.id ?? null,
      created_at: '2026-09-12T00:00:00Z',
      updated_at: '2026-09-12T00:00:00Z',
    },
    outlines,
    candidates: options.candidates ?? [],
    preflight_checks: options.checks ?? [],
    reviews: [],
    outcomes: [],
  }
}

const preview: ChapterProductionOutboundPreview = {
  purpose: 'brief',
  profile_id: null,
  profile_name: '当前会话线路',
  provider: 'openai',
  model: 'gpt-5.6',
  data_types: ['章节计划', '正式资料'],
  content_scope: '本章纲要与经编译的创作上下文',
  character_count: 1800,
  estimated_input_tokens: 1200,
  estimated_output_tokens: 800,
  estimated_cost_microusd: 12_000,
  context_packet_id: 'packet-1',
  context_packet_sha256: 'd'.repeat(64),
  context_dependency_fingerprint_sha256: 'e'.repeat(64),
  context_compiler_version: 'creative-context-v2',
}

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: 'outline-job',
    project_id: project.id,
    chapter_id: chapter.id,
    parent_job_id: null,
    kind: 'chapter_brief',
    workflow: 'chapter_production_outline',
    state: 'queued',
    idempotency_key: 'outline-job-key',
    progress_current: 0,
    progress_total: 1,
    current_step: '等待生成章纲',
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
    created_at: '2026-09-12T00:00:00Z',
    updated_at: '2026-09-12T00:00:00Z',
    started_at: null,
    completed_at: null,
    ...overrides,
  }
}

function mockRestore(restored: ChapterProductionSnapshot, jobs: Job[] = []) {
  vi.spyOn(api, 'getCurrentChapterProduction').mockResolvedValue(restored)
  vi.spyOn(api, 'listJobs').mockResolvedValue(jobs)
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('ChapterProductionDialog', () => {
  it('restores server state, traps keyboard focus, makes the background inert and returns on Escape', async () => {
    mockRestore(snapshot())
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(
      <>
        <button type="button">background action</button>
        <ChapterProductionDialog project={project} chapter={chapter} onClose={onClose} onChapterChanged={vi.fn()} onOpenTaskCenter={vi.fn()} />
      </>,
    )

    const dialog = await screen.findByRole('dialog', { name: '本章候选生产台' })
    const background = screen.getByText('background action', { selector: 'button' })
    expect(background).toHaveAttribute('aria-hidden', 'true')
    expect((background as HTMLElement).inert).toBe(true)
    const close = within(dialog).getByRole('button', { name: '关闭单章生产工作台' })
    await waitFor(() => expect(close).toHaveFocus())

    await user.keyboard('{Shift>}{Tab}{/Shift}')
    expect(dialog).toContainElement(document.activeElement as HTMLElement)
    expect(document.activeElement).not.toBe(background)
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('shows an immutable outbound preview and does not queue work before explicit confirmation', async () => {
    const restored = snapshot()
    mockRestore(restored)
    const previewOutline = vi.spyOn(api, 'previewChapterProductionOutline').mockResolvedValue(preview)
    const start = vi.spyOn(api, 'startChapterProductionOutlineJob').mockResolvedValue(job({ state: 'failed' }))
    vi.spyOn(api, 'getAiStatus').mockResolvedValue({
      configured: true,
      provider: 'openai',
      model: 'gpt-5.6',
      key_source: 'session',
      profile_id: null,
      profile_name: null,
    })
    const user = userEvent.setup()
    render(<ChapterProductionDialog project={project} chapter={chapter} onClose={vi.fn()} onChapterChanged={vi.fn()} onOpenTaskCenter={vi.fn()} />)

    await user.click(await screen.findByRole('button', { name: '生成本章候选' }))
    expect(previewOutline).toHaveBeenCalledWith('production-1', {
      author_intent: '',
      token_budget: 8000,
      label: 'AI 章纲',
    })
    expect(start).not.toHaveBeenCalled()
    expect(await screen.findByRole('heading', { name: '发送前确认' })).toHaveFocus()
    expect(screen.getByText('章节计划')).toBeVisible()

    await user.click(screen.getByRole('button', { name: '确认外发与费用，开始任务' }))
    expect(start).toHaveBeenCalledWith('production-1', expect.objectContaining({
      context_packet_id: preview.context_packet_id,
      context_packet_sha256: preview.context_packet_sha256,
      confirm_external_processing: true,
      confirm_unknown_cost: false,
      max_estimated_cost_microusd: preview.estimated_cost_microusd,
    }))
  })

  it('repeats server preflight and never previews the draft when the current outline is blocked', async () => {
    const currentOutline = outline()
    mockRestore(snapshot({ outlines: [currentOutline] }))
    const blocked: ChapterProductionPreflightCheck = {
      id: 'check-1',
      production_id: 'production-1',
      outline_candidate_id: currentOutline.id,
      outline_version_id: currentOutline.current_version.id,
      outline_revision: currentOutline.current_version.revision,
      outline_content_sha256: currentOutline.current_version.content_sha256,
      reader_promise: true,
      opening_hook: true,
      state_change: true,
      emotional_payoff: false,
      ending_cliffhanger: true,
      missing_fields: ['emotional_payoff'],
      passed: false,
      created_at: '2026-09-12T00:00:00Z',
    }
    vi.spyOn(api, 'checkChapterProductionPreflight').mockResolvedValue(blocked)
    const draftPreview = vi.spyOn(api, 'previewChapterProductionDraft')
    const user = userEvent.setup()
    render(<ChapterProductionDialog project={project} chapter={chapter} onClose={vi.fn()} onChapterChanged={vi.fn()} onOpenTaskCenter={vi.fn()} />)

    await user.click(await screen.findByRole('button', { name: '生成本章候选' }))
    expect(api.checkChapterProductionPreflight).toHaveBeenCalledOnce()
    expect(draftPreview).not.toHaveBeenCalled()
    expect(await screen.findByText(/写前检查未通过/)).toBeVisible()
  })

  it('materializes a recovered completed job through its result route before refreshing candidates', async () => {
    const running = job({
      id: 'draft-job',
      kind: 'chapter_draft',
      workflow: 'chapter_production_draft',
      state: 'running',
      current_step: '生成正文候选',
    })
    const resultCandidate = candidate()
    const finished = job({ ...running, state: 'succeeded', progress_current: 1, completed_calls: 1 })
    mockRestore(snapshot({ outlines: [outline()] }), [running])
    vi.spyOn(api, 'getJob').mockResolvedValue({
      ...finished,
      chunks: [],
      attempts: [],
      artifacts: [],
      events: [],
    })
    const getResult = vi.spyOn(api, 'getChapterProductionDraftJobResult').mockResolvedValue(resultCandidate)
    vi.spyOn(api, 'getChapterProduction').mockResolvedValue(snapshot({ outlines: [outline()], candidates: [resultCandidate] }))
    render(<ChapterProductionDialog project={project} chapter={chapter} onClose={vi.fn()} onChapterChanged={vi.fn()} onOpenTaskCenter={vi.fn()} />)

    expect(await screen.findByText('任务已完成，结果已进入候选区。')).toBeVisible()
    expect(getResult).toHaveBeenCalledWith('production-1', 'draft-job')
    expect(await screen.findByRole('heading', { name: '1 份正文候选待审校' })).toBeVisible()
  })

  it('persists a minimal author edit and adopts only through guarded candidate APIs', async () => {
    const original = candidate()
    const editedText = `${original.current_version.content}门外传来脚步声。`
    const edited: ChapterDraftCandidate = {
      ...original,
      current_version: {
        ...original.current_version,
        id: 'candidate-version-2',
        revision: 1,
        content: editedText,
        content_sha256: 'f'.repeat(64),
        operation: 'author_edit',
        parent_version_id: original.current_version.id,
        source_job_id: null,
      },
    }
    const restored = snapshot({ outlines: [outline()], candidates: [original] })
    mockRestore(restored)
    const edit = vi.spyOn(api, 'editChapterProductionCandidate').mockResolvedValue(edited)
    vi.spyOn(api, 'adoptChapterProductionCandidate').mockResolvedValue({
      id: 'outcome-1',
      production_id: 'production-1',
      candidate_id: edited.id,
      candidate_version_id: edited.current_version.id,
      candidate_revision: 1,
      candidate_content_sha256: edited.current_version.content_sha256,
      decision: 'adopted',
      adoption_mode: 'whole',
      base_chapter_revision: chapter.revision,
      base_chapter_content_sha256: 'c'.repeat(64),
      final_chapter_revision: 4,
      final_chapter_content_sha256: '9'.repeat(64),
      final_chapter_status: 'drafted',
      chapter_version_id: 'chapter-version-4',
      source_outline_candidate_id: 'outline-1',
      source_outline_version_id: 'outline-version-1',
      source_outline_revision: 0,
      source_outline_content_sha256: 'a'.repeat(64),
      adoption_detail: { mode: 'whole' },
      idempotency_key: 'decision-key',
      reason: '',
      created_at: '2026-09-12T00:00:00Z',
    })
    const updatedChapter = { ...chapter, content: editedText, revision: 4 }
    vi.spyOn(api, 'getChapter').mockResolvedValue(updatedChapter)
    vi.spyOn(api, 'getChapterProduction').mockResolvedValue(snapshot({ outlines: [outline()], candidates: [edited] }))
    const onChapterChanged = vi.fn()
    const user = userEvent.setup()
    render(<ChapterProductionDialog project={project} chapter={chapter} onClose={vi.fn()} onChapterChanged={onChapterChanged} onOpenTaskCenter={vi.fn()} />)

    const editor = await screen.findByRole('textbox', { name: '编辑正面交锋版候选副本' })
    fireEvent.change(editor, { target: { value: editedText } })
    await user.click(screen.getByRole('button', { name: '保存候选修改' }))
    expect(edit).toHaveBeenCalledWith('production-1', 'candidate-1', expect.objectContaining({
      expected_candidate_revision: 0,
      selection: expect.objectContaining({
        start_char: original.current_version.content.length,
        end_char: original.current_version.content.length,
      }),
      replacement: '门外传来脚步声。',
    }))

    await user.click(screen.getByRole('button', { name: '确认采用这份候选' }))
    expect(api.adoptChapterProductionCandidate).toHaveBeenCalledWith(
      'production-1',
      'candidate-1',
      expect.objectContaining({ expected_candidate_revision: 1, expected_chapter_revision: chapter.revision, mode: 'whole' }),
    )
    expect(onChapterChanged).toHaveBeenCalledWith(updatedChapter)
  })
})
