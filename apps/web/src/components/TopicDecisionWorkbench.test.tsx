import type {
  Job,
  JobDetail,
  TopicDecision,
  TopicDecisionCandidateSet,
  TopicDecisionContent,
  TopicDecisionField,
  TopicDecisionOutboundPreview,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api'
import { TopicDecisionWorkbench } from './TopicDecisionWorkbench'

const fields: TopicDecisionField[] = [
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

const content: TopicDecisionContent = {
  target_platform: '番茄小说',
  target_audience: '喜欢快节奏创业升级的男性读者',
  subgenre: '都市重生·实业创业',
  premise: '失意工程师回到 1998 年南平，从一座停产纸厂开始改命。',
  core_desire: '挽回家庭，也证明被时代错过的技术可以改变一座城。',
  long_term_promise: '每卷完成一次产业升级，同时付出更高的人情与制度成本。',
  first_three_chapter_promise: '停产名单、第一次救厂、小胜背后的债务危机。',
  constraints: ['产业细节有依据', '能力来自未来经验而非系统'],
  forbidden_elements: ['不写无代价碾压', '不照搬参考人物关系'],
  reference_purpose: '参考资源循环和章末钩子，不参考具体桥段。',
  reality_anchor: '1998 年闽北交通、纸业与国企改制资料。',
  first_ten_chapter_goal: '保住第一条产线，并把家庭矛盾转成共同目标。',
}

function topicDecision(overrides: Partial<TopicDecision> = {}): TopicDecision {
  return {
    id: 'topic-1',
    project_id: 'project-1',
    content,
    status: 'draft',
    locks: Object.fromEntries(fields.map((field) => [field, false])) as Record<TopicDecisionField, boolean>,
    field_versions: Object.fromEntries(fields.map((field) => [field, 1])) as Record<TopicDecisionField, number>,
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

function workspace(topic = topicDecision()): WorkspaceSummary {
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
    topic_decision: topic,
    next_action: topic.status === 'confirmed' ? 'plan_book' : 'confirm_topic',
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
}

function topicJob(): Job {
  return {
    id: 'topic-job-1',
    project_id: 'project-1',
    chapter_id: null,
    parent_job_id: null,
    kind: 'topic_decision',
    workflow: 'topic_candidates',
    state: 'queued',
    idempotency_key: 'topic-job-fixture',
    progress_current: 0,
    progress_total: 3,
    current_step: '构思差异化方案',
    estimated_calls: 3,
    completed_calls: 0,
    provider: 'openai_compatible',
    provider_profile_id: 'profile-1',
    model: 'fixture-model',
    lease_owner: null,
    lease_expires_at: null,
    heartbeat_at: null,
    error_code: null,
    error_message: null,
    created_at: '2026-09-11T00:00:00Z',
    updated_at: '2026-09-11T00:00:00Z',
    started_at: null,
    completed_at: null,
  }
}

function completedJob(job: Job): JobDetail {
  return {
    ...job,
    state: 'succeeded',
    progress_current: 3,
    completed_calls: 3,
    completed_at: '2026-09-11T00:01:00Z',
    chunks: [],
    attempts: [],
    artifacts: [],
    events: [],
  }
}

function outboundPreview(targetField: TopicDecisionField | null = null): TopicDecisionOutboundPreview {
  return {
    mode: targetField ? 'field_regeneration' : 'full',
    target_field: targetField,
    profile_id: 'profile-1',
    profile_name: '我的写作模型',
    provider: 'openai_compatible',
    model: 'fixture-model',
    data_types: ['作者选题单', '参考模式用途'],
    content_scope: '当前作品的选题字段，不含参考原文',
    character_count: 980,
    estimated_input_tokens: 800,
    estimated_output_tokens: 1800,
    estimated_calls: 3,
    estimated_cost_microusd: 12_000,
  }
}

function candidates(rejectedId?: string): TopicDecisionCandidateSet {
  return {
    job_id: 'topic-job-1',
    project_id: 'project-1',
    based_on_revision: 1,
    target_field: null,
    candidates: [1, 2, 3].map((ordinal) => ({
      id: `candidate-${ordinal}`,
      ordinal,
      label: `方向${['一', '二', '三'][ordinal - 1]}`,
      content: {
        ...content,
        premise: `方向 ${ordinal} 的一句话命题`,
        core_desire: `方向 ${ordinal} 的核心欲望`,
      },
      changed_fields: ['premise', 'core_desire'],
      rationale: `用第 ${ordinal} 种冲突结构强化开篇。`,
      risks: ordinal === 1 ? ['产业线可能挤压家庭线'] : [],
      state: rejectedId === `candidate-${ordinal}` ? 'rejected' : 'candidate',
      rejection_reason: rejectedId === `candidate-${ordinal}` ? '核心欲望不够具体' : null,
    })),
  }
}

function candidateSetAt(
  revision: number,
  states: Partial<Record<string, 'candidate' | 'selected' | 'rejected'>> = {},
): TopicDecisionCandidateSet {
  const result = candidates()
  return {
    ...result,
    based_on_revision: revision,
    candidates: result.candidates.map((candidate) => ({
      ...candidate,
      state: states[candidate.id] ?? candidate.state,
      rejection_reason: states[candidate.id] === 'rejected' ? '核心欲望不够具体' : candidate.rejection_reason,
    })),
  }
}

function renderWorkbench(source = workspace()) {
  const onWorkspaceChanged = vi.fn()
  const onContinue = vi.fn()
  render(
    <TopicDecisionWorkbench
      workspace={source}
      onWorkspaceChanged={onWorkspaceChanged}
      onContinue={onContinue}
      onClose={vi.fn()}
      onOpenTaskCenter={vi.fn()}
    />,
  )
  return { onWorkspaceChanged, onContinue }
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

beforeEach(() => {
  vi.spyOn(api, 'listJobs').mockResolvedValue([])
  vi.spyOn(api, 'getAiStatus').mockResolvedValue({
    configured: true,
    provider: 'openai_compatible',
    model: 'fixture-model',
    key_source: 'runtime',
    profile_id: 'profile-1',
    profile_name: '我的写作模型',
  })
})

describe('TopicDecisionWorkbench', () => {
  it('offers model setup in place instead of leaving a new author at a dead end', async () => {
    vi.mocked(api.getAiStatus).mockResolvedValue({
      configured: false,
      provider: 'unavailable',
      model: '',
      key_source: null,
      profile_id: null,
      profile_name: null,
    })

    renderWorkbench()

    expect(await screen.findByRole('button', { name: '打开模型线路台' })).toBeVisible()
    expect(screen.getByRole('button', { name: '预览完整选题候选' })).toBeDisabled()
  })

  it('saves manual decisions and field locks before allowing confirmation', async () => {
    const nextTopic = topicDecision({
      content: { ...content, premise: '主角回到停产前夜，用技术和人情债救下一座纸厂。' },
      locks: { ...topicDecision().locks, core_desire: true },
      revision: 2,
    })
    const update = vi.spyOn(api, 'updateTopicDecision').mockResolvedValue(nextTopic)
    vi.spyOn(api, 'getProjectSummary').mockResolvedValue(workspace(nextTopic))
    const user = userEvent.setup()

    renderWorkbench()

    const confirm = screen.getByRole('button', { name: '确认选题，进入全书规划' })
    await user.clear(screen.getByLabelText('一句话命题', { selector: 'textarea' }))
    await user.type(screen.getByLabelText('一句话命题', { selector: 'textarea' }), nextTopic.content.premise)
    await user.click(screen.getByRole('button', { name: '锁定核心欲望' }))

    expect(confirm).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '保存选题草稿' }))

    expect(update).toHaveBeenCalledWith('project-1', expect.objectContaining({
      content: expect.objectContaining({ premise: nextTopic.content.premise }),
      changed_fields: ['premise'],
      lock_updates: { core_desire: true },
      expected_revision: 1,
    }))
    expect(await screen.findByRole('status')).toHaveTextContent('选题草稿和字段锁定已保存')
  })

  it('names the incomplete fields instead of sending an avoidable confirmation error', () => {
    const incomplete = topicDecision({
      content: { ...content, target_platform: '', first_ten_chapter_goal: '' },
    })

    renderWorkbench(workspace(incomplete))

    expect(screen.getByText(/确认前还要补齐：首发平台、前十章目标/)).toBeVisible()
    expect(screen.getByRole('button', { name: '确认选题，进入全书规划' })).toBeDisabled()
  })

  it('requires an outbound preview and explicit confirmation before showing three candidates', async () => {
    const job = topicJob()
    const result = candidates()
    const preview = vi.spyOn(api, 'previewTopicDecisionCandidates').mockResolvedValue(outboundPreview())
    const start = vi.spyOn(api, 'startTopicDecisionCandidateJob').mockResolvedValue(job)
    vi.spyOn(api, 'getJob').mockResolvedValue(completedJob(job))
    vi.spyOn(api, 'getTopicDecisionCandidates').mockResolvedValue(result)
    const user = userEvent.setup()

    renderWorkbench()
    await user.type(screen.getByLabelText('这轮特别想让 AI 解决什么？'), '强化前三章兑现')
    await user.click(screen.getByRole('button', { name: '预览完整选题候选' }))

    expect(preview).toHaveBeenCalledWith('project-1', {
      expected_revision: 1,
      author_intent: '强化前三章兑现',
      confirm_external_processing: false,
      max_estimated_cost_microusd: null,
    })
    expect(screen.getByText('$0.0120')).toBeVisible()
    const startButton = screen.getByRole('button', { name: '确认外发并生成 3 个候选' })
    expect(startButton).toBeDisabled()
    expect(start).not.toHaveBeenCalled()

    await user.click(screen.getByRole('checkbox', { name: /确认把这一版选题信息发送/ }))
    await user.click(startButton)

    expect(start).toHaveBeenCalledWith('project-1', {
      expected_revision: 1,
      author_intent: '强化前三章兑现',
      confirm_external_processing: true,
      max_estimated_cost_microusd: 12_000,
    })
    expect(await screen.findByRole('heading', { name: '方向一' })).toBeVisible()
    expect(screen.getByRole('heading', { name: '方向二' })).toBeVisible()
    expect(screen.getByRole('heading', { name: '方向三' })).toBeVisible()
  })

  it('restores the latest completed topic candidates after a page reload', async () => {
    const job = topicJob()
    vi.mocked(api.listJobs).mockResolvedValue([completedJob(job)])
    vi.spyOn(api, 'getTopicDecisionCandidates').mockResolvedValue(candidates())

    renderWorkbench()

    expect(await screen.findByRole('heading', { name: '方向一' })).toBeVisible()
    expect(screen.getByRole('heading', { name: '方向二' })).toBeVisible()
    expect(screen.getByRole('heading', { name: '方向三' })).toBeVisible()
  })

  it('records rejection reasons and adopts only checked fields without confirming the topic', async () => {
    const job = topicJob()
    const initialSet = candidates()
    const rejectedSet = candidates('candidate-3')
    const selectedSet = candidateSetAt(2, {
      'candidate-1': 'selected',
      'candidate-3': 'rejected',
    })
    vi.spyOn(api, 'previewTopicDecisionCandidates').mockResolvedValue(outboundPreview())
    vi.spyOn(api, 'startTopicDecisionCandidateJob').mockResolvedValue(job)
    vi.spyOn(api, 'getJob').mockResolvedValue(completedJob(job))
    vi.spyOn(api, 'getTopicDecisionCandidates')
      .mockResolvedValueOnce(initialSet)
      .mockResolvedValueOnce(rejectedSet)
      .mockResolvedValueOnce(selectedSet)
    const reject = vi.spyOn(api, 'rejectTopicDecisionCandidate').mockResolvedValue(rejectedSet.candidates[2])
    const selectedTopic = topicDecision({
      content: { ...content, premise: initialSet.candidates[0].content.premise },
      source_candidate_ids: ['candidate-1'],
      revision: 2,
    })
    const select = vi.spyOn(api, 'selectTopicDecisionCandidate').mockResolvedValue(selectedTopic)
    const confirm = vi.spyOn(api, 'confirmTopicDecision')
    vi.spyOn(api, 'getProjectSummary').mockResolvedValue(workspace(selectedTopic))
    const user = userEvent.setup()

    renderWorkbench()
    await user.click(screen.getByRole('button', { name: '预览完整选题候选' }))
    await user.click(screen.getByRole('checkbox', { name: /确认把这一版选题信息发送/ }))
    await user.click(screen.getByRole('button', { name: '确认外发并生成 3 个候选' }))
    const thirdCard = (await screen.findByRole('heading', { name: '方向三' })).closest('article')
    expect(thirdCard).not.toBeNull()
    await user.type(within(thirdCard!).getByLabelText('不采用原因'), '核心欲望不够具体')
    await user.click(within(thirdCard!).getByRole('button', { name: '记录不采用' }))

    expect(reject).toHaveBeenCalledWith('project-1', {
      job_id: 'topic-job-1',
      candidate_id: 'candidate-3',
      reason: '核心欲望不够具体',
      expected_revision: 1,
    })

    const firstCard = screen.getByRole('heading', { name: '方向一' }).closest('article')
    expect(firstCard).not.toBeNull()
    await user.click(within(firstCard!).getByRole('checkbox', { name: /核心欲望/ }))
    await user.click(within(firstCard!).getByRole('button', { name: '并入勾选字段（不会确认）' }))

    expect(select).toHaveBeenCalledWith('project-1', {
      job_id: 'topic-job-1',
      candidate_id: 'candidate-1',
      selected_fields: ['premise'],
      expected_revision: 1,
    })
    expect(confirm).not.toHaveBeenCalled()
  })

  it('keeps the candidate set available while the author merges fields from different candidates', async () => {
    const job = topicJob()
    const initialSet = candidateSetAt(1)
    const afterFirstSelection = candidateSetAt(2, { 'candidate-1': 'selected' })
    const afterSecondSelection = candidateSetAt(3, {
      'candidate-1': 'selected',
      'candidate-2': 'selected',
    })
    const topicAfterFirstSelection = topicDecision({
      content: { ...content, premise: initialSet.candidates[0].content.premise },
      source_candidate_ids: ['candidate-1'],
      revision: 2,
    })
    const topicAfterSecondSelection = topicDecision({
      content: {
        ...topicAfterFirstSelection.content,
        core_desire: initialSet.candidates[1].content.core_desire,
      },
      source_candidate_ids: ['candidate-1', 'candidate-2'],
      revision: 3,
    })
    vi.spyOn(api, 'previewTopicDecisionCandidates').mockResolvedValue(outboundPreview())
    vi.spyOn(api, 'startTopicDecisionCandidateJob').mockResolvedValue(job)
    vi.spyOn(api, 'getJob').mockResolvedValue(completedJob(job))
    vi.spyOn(api, 'getTopicDecisionCandidates')
      .mockResolvedValueOnce(initialSet)
      .mockResolvedValueOnce(afterFirstSelection)
      .mockResolvedValueOnce(afterSecondSelection)
    const select = vi.spyOn(api, 'selectTopicDecisionCandidate')
      .mockResolvedValueOnce(topicAfterFirstSelection)
      .mockResolvedValueOnce(topicAfterSecondSelection)
    vi.spyOn(api, 'getProjectSummary')
      .mockResolvedValueOnce(workspace(topicAfterFirstSelection))
      .mockResolvedValueOnce(workspace(topicAfterSecondSelection))
    const user = userEvent.setup()

    renderWorkbench()
    await user.click(screen.getByRole('button', { name: '预览完整选题候选' }))
    await user.click(screen.getByRole('checkbox', { name: /确认把这一版选题信息发送/ }))
    await user.click(screen.getByRole('button', { name: '确认外发并生成 3 个候选' }))

    const firstCard = (await screen.findByRole('heading', { name: '方向一' })).closest('article')
    expect(firstCard).not.toBeNull()
    await user.click(within(firstCard!).getByRole('checkbox', { name: /核心欲望/ }))
    await user.click(within(firstCard!).getByRole('button', { name: '并入勾选字段（不会确认）' }))

    await waitFor(() => expect(select).toHaveBeenNthCalledWith(1, 'project-1', {
      job_id: 'topic-job-1',
      candidate_id: 'candidate-1',
      selected_fields: ['premise'],
      expected_revision: 1,
    }))
    await waitFor(() => expect(within(firstCard!).getByText('已采用过')).toBeVisible())
    for (const checkbox of within(firstCard!).getAllByRole('checkbox')) {
      expect(checkbox).toBeDisabled()
    }
    expect(within(firstCard!).getByLabelText('不采用原因')).toBeDisabled()
    expect(within(firstCard!).getByRole('button', { name: '并入勾选字段（不会确认）' })).toBeDisabled()
    expect(within(firstCard!).getByRole('button', { name: '记录不采用' })).toBeDisabled()

    const secondCard = screen.getByRole('heading', { name: '方向二' }).closest('article')
    expect(secondCard).not.toBeNull()
    await user.click(within(secondCard!).getByRole('checkbox', { name: /一句话命题/ }))
    await user.click(within(secondCard!).getByRole('button', { name: '并入勾选字段（不会确认）' }))

    await waitFor(() => expect(select).toHaveBeenNthCalledWith(2, 'project-1', {
      job_id: 'topic-job-1',
      candidate_id: 'candidate-2',
      selected_fields: ['core_desire'],
      expected_revision: 2,
    }))
    expect(await within(secondCard!).findByText('已采用过')).toBeVisible()
    expect(screen.getByRole('heading', { name: '方向三' })).toBeVisible()
  })

  it('never offers a locked field for local AI regeneration', async () => {
    const lockedTopic = topicDecision({ locks: { ...topicDecision().locks, premise: true } })
    const preview = vi.spyOn(api, 'previewTopicDecisionRegeneration').mockResolvedValue(outboundPreview('core_desire'))
    const user = userEvent.setup()

    renderWorkbench(workspace(lockedTopic))

    expect(screen.queryByRole('option', { name: '一句话命题' })).not.toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('只重生成一个未锁字段'), 'core_desire')
    await user.click(screen.getByRole('button', { name: '预览局部候选' }))

    expect(preview).toHaveBeenCalledWith('project-1', {
      expected_revision: 1,
      author_intent: '',
      confirm_external_processing: false,
      max_estimated_cost_microusd: null,
      target_field: 'core_desire',
    })
  })

  it('enters planning only after the author confirms the saved server revision', async () => {
    const confirmed = topicDecision({ status: 'confirmed', confirmed_revision: 1 })
    const confirm = vi.spyOn(api, 'confirmTopicDecision').mockResolvedValue(confirmed)
    vi.spyOn(api, 'getProjectSummary').mockResolvedValue(workspace(confirmed))
    const user = userEvent.setup()
    const { onContinue } = renderWorkbench()

    await user.click(screen.getByRole('button', { name: '确认选题，进入全书规划' }))

    await waitFor(() => expect(confirm).toHaveBeenCalledWith('project-1', { expected_revision: 1 }))
    expect(onContinue).toHaveBeenCalledOnce()
  })
})
