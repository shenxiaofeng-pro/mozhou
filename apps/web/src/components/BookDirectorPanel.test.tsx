import type {
  BookBlueprint,
  BookBlueprintContent,
  Chapter,
  DirectorChapterPipelineResult,
  DirectorOutboundPreview,
  Job,
  Project,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api'
import { BookDirectorPanel } from './BookDirectorPanel'

const project: Project = {
  id: '05f14cb8-d0ed-4489-bc20-31c44c1efbba',
  title: '回到九八年的南平',
  genre: 'urban_rebirth',
  rebirth_year: 1998,
  rebirth_location: '福建南平',
  chapter_target_words: 3000,
  safety_buffer_chapters: 3,
  created_at: '2026-08-11T00:00:00Z',
  updated_at: '2026-08-11T00:00:00Z',
}

const chapter: Chapter = {
  id: '19c7daae-21f2-42f6-9520-daec63e4a726',
  project_id: project.id,
  volume_number: 1,
  chapter_number: 1,
  title: '第一章 未命名',
  content: '',
  reader_promise: '',
  opening_hook: '',
  state_change: '',
  emotional_payoff: '',
  ending_cliffhanger: '',
  status: 'planned',
  revision: 0,
  updated_at: '2026-08-11T00:00:00Z',
}

const content: BookBlueprintContent = {
  title: '闽北春潮',
  genre: 'urban_rebirth',
  rebirth_year: 1998,
  rebirth_location: '福建南平',
  target_audience: '喜欢年代创业与家族成长的男频读者',
  core_selling_points: ['闽北产业变迁', '小人物改命', '现实资源滚雪球'],
  core_desire: '改变父亲下岗后的家庭命运',
  divergence_point: '提前一天拿到停产名单',
  long_term_promise: '从木竹厂自救到改变一座城市的产业路线',
  ending_direction: '主角保住亲情也建成可持续的产业联盟',
  protagonist_arc: '从只想救家人到承担公共责任',
  resource_growth: '记忆信息差→小额现金→供应链→组织信用',
  relationship_design: '父子信任、师徒利益与竞争者合作交错',
}

function blueprint(overrides: Partial<BookBlueprint> = {}): BookBlueprint {
  const fields = Object.keys(content) as Array<keyof BookBlueprintContent>
  return {
    id: '04e0402a-c96c-4936-87bb-a53099136499',
    project_id: project.id,
    idea: '回到 1998 年救下家乡木竹厂',
    content,
    locks: Object.fromEntries(fields.map((field) => [field, false])) as BookBlueprint['locks'],
    field_versions: Object.fromEntries(fields.map((field) => [field, 1])) as BookBlueprint['field_versions'],
    stale_fields: [],
    plan_stale: true,
    source_candidate_id: '05b4e647-7baa-4c65-b311-a0697a553cd7',
    revision: 0,
    created_at: '2026-08-11T00:00:00Z',
    updated_at: '2026-08-11T00:00:00Z',
    ...overrides,
  }
}

function workspace(bookBlueprint: BookBlueprint | null = null): WorkspaceSummary {
  return {
    project,
    chapters: [{ ...chapter, has_content: false, content_characters: 0 }],
    topic_decision: null,
    next_action: 'continue_writing',
    book_blueprint: bookBlueprint,
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
}

function preview(workflow: DirectorOutboundPreview['workflow']): DirectorOutboundPreview {
  return {
    workflow,
    profile_id: null,
    profile_name: '测试线路',
    provider: 'openai',
    model: 'gpt-test',
    data_types: ['创意', '确认资料卡'],
    content_scope: '只外发结构化创意与已确认资料，不包含拆书原文',
    character_count: 800,
    estimated_input_tokens: 500,
    estimated_output_tokens: 1200,
    estimated_calls: workflow === 'director_chapter_pipeline' ? 2 : 1,
    estimated_cost_microusd: 20_000,
  }
}

function job(workflow: Job['workflow']): Job {
  return {
    id: 'b91870dd-a29f-4b8c-b5c2-c87be4c9240e',
    project_id: project.id,
    chapter_id: workflow === 'director_chapter_pipeline' ? chapter.id : null,
    parent_job_id: null,
    kind: 'review',
    workflow,
    state: 'queued',
    idempotency_key: `test-${workflow}`,
    progress_current: 0,
    progress_total: workflow === 'director_chapter_pipeline' ? 4 : 1,
    current_step: '',
    estimated_calls: workflow === 'director_chapter_pipeline' ? 2 : 1,
    completed_calls: 0,
    provider: 'openai',
    provider_profile_id: null,
    model: 'gpt-test',
    lease_owner: null,
    lease_expires_at: null,
    heartbeat_at: null,
    error_code: null,
    error_message: null,
    created_at: '2026-08-11T00:00:00Z',
    updated_at: '2026-08-11T00:00:00Z',
    started_at: null,
    completed_at: null,
  }
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('BookDirectorPanel', () => {
  it('uses fantasy blueprint labels and exposes all four genres', () => {
    const fantasyProject: Project = {
      ...project,
      title: '灰塔之誓',
      genre: 'western_fantasy',
      rebirth_year: 1243,
      rebirth_location: '阿尔登大陆·北境',
    }
    const fantasyBlueprint = blueprint({
      content: {
        ...content,
        title: fantasyProject.title,
        genre: fantasyProject.genre,
        rebirth_year: fantasyProject.rebirth_year,
        rebirth_location: fantasyProject.rebirth_location,
        divergence_point: '灰塔重新点火，王室誓印显现',
      },
    })

    render(
      <BookDirectorPanel
        project={fantasyProject}
        workspace={workspace(fantasyBlueprint)}
        chapter={chapter}
        canUseChapter
        onWorkspaceChanged={vi.fn()}
        onAdoptBrief={vi.fn()}
        onDraftGenerated={vi.fn()}
      />,
    )

    expect(screen.getAllByText('故事纪年')).not.toHaveLength(0)
    expect(screen.getAllByText('起始地域')).not.toHaveLength(0)
    expect(screen.getAllByText('故事引爆点')).not.toHaveLength(0)
    expect(screen.getByRole('option', { name: '东方玄幻' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: '西方奇幻' })).toBeInTheDocument()
  })

  it('turns one idea into three editable choices and persists only the selected direction', async () => {
    const selected = blueprint()
    const startupJob = job('director_startup')
    vi.spyOn(api, 'previewDirectorStartup').mockResolvedValue(preview('director_startup'))
    const start = vi.spyOn(api, 'startDirectorStartupJob').mockResolvedValue(startupJob)
    vi.spyOn(api, 'getJob').mockResolvedValue({
      ...startupJob,
      state: 'succeeded',
      progress_current: 1,
      completed_calls: 1,
      chunks: [],
      attempts: [],
      artifacts: [],
      events: [],
    })
    vi.spyOn(api, 'getDirectorStartupResult').mockResolvedValue({
      job_id: startupJob.id,
      project_id: project.id,
      idea: selected.idea,
      candidates: [1, 2, 3].map((ordinal) => ({
        id: `00000000-0000-4000-8000-00000000000${ordinal}`,
        ordinal,
        label: `方向 ${ordinal}`,
        blueprint: { ...content, title: `闽北春潮 ${ordinal}` },
        why_distinct: `第 ${ordinal} 种资源增长路线`,
        risks: [],
      })),
    })
    const select = vi.spyOn(api, 'selectDirectorStartupCandidate').mockResolvedValue(selected)
    vi.spyOn(api, 'getProjectSummary').mockResolvedValue(workspace(selected))
    const user = userEvent.setup()

    render(
      <BookDirectorPanel
        project={project}
        workspace={workspace()}
        chapter={chapter}
        canUseChapter
        onWorkspaceChanged={vi.fn()}
        onAdoptBrief={vi.fn()}
        onDraftGenerated={vi.fn()}
      />,
    )

    await user.type(screen.getByLabelText('一句话创意'), selected.idea)
    await user.click(screen.getByRole('button', { name: '生成 3 个差异化开书方案' }))
    expect(start).not.toHaveBeenCalled()
    await user.click(await screen.findByRole('button', { name: '确认外发并启动' }))
    expect(start).toHaveBeenCalledWith(project.id, expect.objectContaining({
      idea: selected.idea,
      confirm_external_processing: true,
      max_estimated_cost_microusd: 20_000,
    }))
    expect(await screen.findAllByRole('button', { name: '采用这个方向' })).toHaveLength(3)
    await user.click(screen.getAllByRole('button', { name: '采用这个方向' })[1])
    expect(select).toHaveBeenCalledWith(project.id, expect.objectContaining({
      job_id: startupJob.id,
      candidate_id: '00000000-0000-4000-8000-000000000002',
    }))
    expect(await screen.findByText('整书蓝图')).toBeVisible()
  })

  it('locks blueprint fields and keeps the four-stage chapter output as explicit candidates', async () => {
    const currentBlueprint = blueprint({ plan_stale: false })
    const lockedBlueprint = blueprint({
      revision: 1,
      plan_stale: true,
      locks: { ...currentBlueprint.locks, ending_direction: true },
    })
    const pipelineJob = job('director_chapter_pipeline')
    const generated: DirectorChapterPipelineResult = {
      job_id: pipelineJob.id,
      project_id: project.id,
      chapter_id: chapter.id,
      chapter_revision: 0,
      completed_stages: ['context', 'brief', 'pre_review', 'draft'],
      brief: {
        title: '第一章 停产名单',
        reader_promise: '主角第一次改命',
        opening_hook: '名单提前贴出',
        state_change: '父亲暂时保住工作',
        emotional_payoff: '父子信任出现松动',
        ending_cliffhanger: '厂长叫出主角的小名',
        why_this_works: '信息差立即变成行动',
        risk_notes: [],
      },
      pre_review: { passed: true, findings: [] },
      draft: {
        id: 'cc2ca7be-2dce-4841-a89a-198cc79f0f4c',
        chapter_id: chapter.id,
        state: 'drafted',
        expected_chapter_revision: 0,
        candidate_content: '停产名单比记忆中早了一天。',
        error_message: null,
        provider: 'openai',
        model: 'gpt-test',
        created_at: '2026-08-11T00:00:00Z',
        updated_at: '2026-08-11T00:00:01Z',
      },
    }
    const updateBlueprint = vi.spyOn(api, 'updateBookBlueprint').mockResolvedValue(lockedBlueprint)
    vi.spyOn(api, 'getProjectSummary').mockResolvedValue(workspace(lockedBlueprint))
    vi.spyOn(api, 'previewDirectorPipeline').mockResolvedValue(preview('director_chapter_pipeline'))
    vi.spyOn(api, 'startDirectorPipelineJob').mockResolvedValue(pipelineJob)
    vi.spyOn(api, 'getJob').mockResolvedValue({
      ...pipelineJob,
      state: 'succeeded',
      progress_current: 4,
      completed_calls: 2,
      chunks: [],
      attempts: [],
      artifacts: [],
      events: [],
    })
    vi.spyOn(api, 'getDirectorPipelineResult').mockResolvedValue(generated)
    const adoptBrief = vi.fn()
    const adoptDraft = vi.fn()
    const user = userEvent.setup()

    render(
      <BookDirectorPanel
        project={project}
        workspace={workspace(currentBlueprint)}
        chapter={chapter}
        canUseChapter
        onWorkspaceChanged={vi.fn()}
        onAdoptBrief={adoptBrief}
        onDraftGenerated={adoptDraft}
      />,
    )

    await user.click(screen.getByRole('button', { name: '锁定结局方向' }))
    expect(updateBlueprint).toHaveBeenCalledWith(project.id, expect.objectContaining({
      changed_fields: [],
      lock_updates: { ending_direction: true },
      expected_revision: 0,
    }))

    // Re-render with the non-stale source blueprint to exercise the independent chapter pipeline.
    cleanup()
    render(
      <BookDirectorPanel
        project={project}
        workspace={workspace(currentBlueprint)}
        chapter={chapter}
        canUseChapter
        onWorkspaceChanged={vi.fn()}
        onAdoptBrief={adoptBrief}
        onDraftGenerated={adoptDraft}
      />,
    )
    await user.click(screen.getByRole('button', { name: /\u4e00键跑完/ }))
    await user.click(await screen.findByRole('button', { name: '确认外发并启动' }))
    expect(await screen.findByText('单章候选链已完成')).toBeVisible()
    expect(adoptBrief).not.toHaveBeenCalled()
    expect(adoptDraft).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: '送入章纲编辑区' }))
    await user.click(screen.getByRole('button', { name: '送入正文候选区' }))
    expect(adoptBrief).toHaveBeenCalledWith(generated.brief)
    expect(adoptDraft).toHaveBeenCalledWith(generated.draft)
    await waitFor(() => expect(screen.getByText('写前审查：通过，0 条提示')).toBeVisible())
  })
})
