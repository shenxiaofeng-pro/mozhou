import type {
  AuthorPreferenceCandidate,
  CanonDeltaCandidate,
  CanonReconciliationSnapshot,
  Chapter,
  RollingPlanReplenishment,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api } from '../api'
import { ChapterFeedbackPanel } from './ChapterFeedbackPanel'

const chapter: Chapter = {
  id: 'chapter-1',
  project_id: 'project-1',
  volume_number: 1,
  chapter_number: 1,
  title: '第一章 归来',
  content: '沈砚回到南平，攥紧父亲留下的工牌。',
  reader_promise: '主角开始改写命运',
  opening_hook: '旧日工牌重新出现',
  state_change: '沈砚决定救下父亲',
  emotional_payoff: '父子重新并肩',
  ending_cliffhanger: '名单上还有另一个熟悉名字',
  status: 'approved',
  revision: 7,
  updated_at: '2026-09-12T00:00:00Z',
}

const project = { id: chapter.project_id, genre: 'urban_rebirth' as const }
const sha = 'a'.repeat(64)

function snapshot(
  state: 'pending' | 'ready' | 'decided' | 'stale' | 'failed' = 'ready',
  overrides: Partial<CanonReconciliationSnapshot> = {},
): CanonReconciliationSnapshot {
  const base: CanonReconciliationSnapshot = {
    approval: {
      id: 'approval-1',
      project_id: project.id,
      chapter_id: chapter.id,
      chapter_revision: chapter.revision,
      chapter_content_sha256: sha,
      chapter_version_id: 'version-1',
      source_writing_outcome_id: null,
      created_at: '2026-09-12T00:00:00Z',
    },
    reconciliation: {
      id: 'reconciliation-1',
      approval_id: 'approval-1',
      project_id: project.id,
      chapter_id: chapter.id,
      job_id: 'job-1',
      state,
      revision: state === 'pending' ? 0 : 1,
      context_packet_id: state === 'pending' ? null : 'packet-1',
      context_packet_sha256: state === 'pending' ? null : sha,
      context_dependency_fingerprint_sha256: state === 'pending' ? null : sha,
      preference_skip_reason: null,
      error_message: null,
      created_at: '2026-09-12T00:00:00Z',
      updated_at: '2026-09-12T00:00:00Z',
      completed_at: state === 'pending' ? null : '2026-09-12T00:00:01Z',
    },
    canon_candidates: [],
    preference_candidates: [],
    rolling_plan_replenishment: null,
  }
  return {
    ...base,
    ...overrides,
    reconciliation: {
      ...base.reconciliation,
      ...overrides.reconciliation,
    },
  }
}

function canonCandidate(overrides: Partial<CanonDeltaCandidate> = {}): CanonDeltaCandidate {
  const excerpt = '沈砚攥紧父亲留下的工牌。'
  return {
    id: 'canon-1',
    reconciliation_id: 'reconciliation-1',
    project_id: project.id,
    ordinal: 1,
    kind: 'character_state',
    subject_key: '沈砚',
    summary: '沈砚决定救下父亲',
    payload: {
      character_name: '沈砚',
      state: '回到一九九八年',
      change: '决定介入父亲的命运',
    },
    payload_sha256: sha,
    evidence: {
      approval_version_id: 'version-1',
      chapter_id: chapter.id,
      chapter_revision: chapter.revision,
      chapter_content_sha256: sha,
      start_char: 8,
      end_char: 8 + excerpt.length,
      excerpt,
      excerpt_sha256: sha,
    },
    evidence_sha256: sha,
    conflicts: [{ kind: 'supersedes', summary: '替代人物上一章的犹豫状态', existing_record_id: 'record-old' }],
    state: 'candidate',
    revision: 2,
    rejection_reason: null,
    accepted_record_id: null,
    created_at: '2026-09-12T00:00:01Z',
    updated_at: '2026-09-12T00:00:01Z',
    decided_at: null,
    ...overrides,
  }
}

function preferenceCandidate(overrides: Partial<AuthorPreferenceCandidate> = {}): AuthorPreferenceCandidate {
  return {
    id: 'preference-1',
    reconciliation_id: 'reconciliation-1',
    project_id: project.id,
    ordinal: 1,
    scope_kind: 'project',
    scope_value: project.id,
    dimension: 'pacing',
    compact_rule: '关键决定前保留一个短促停顿。',
    rule_sha256: sha,
    confidence: 0.8,
    comparison_metrics: { paragraph_delta: -2, dialogue_ratio: 0.35 },
    source_writing_outcome_id: 'outcome-1',
    source_candidate_version_id: 'candidate-version-1',
    candidate_content_sha256: sha,
    final_content_sha256: sha,
    state: 'candidate',
    revision: 1,
    rejection_reason: null,
    confirmed_preference_id: null,
    created_at: '2026-09-12T00:00:01Z',
    updated_at: '2026-09-12T00:00:01Z',
    decided_at: null,
    ...overrides,
  }
}

function rollingPlan(overrides: Partial<RollingPlanReplenishment> = {}): RollingPlanReplenishment {
  return {
    id: 'replenishment-1',
    project_id: project.id,
    reconciliation_id: 'reconciliation-1',
    source_decision_batch_id: 'batch-1',
    source_chapter_id: chapter.id,
    source_canon_record_ids: ['record-1'],
    state: 'candidate',
    revision: 0,
    volume_plan_id: 'volume-1',
    base_blueprint_id: 'blueprint-1',
    base_blueprint_revision: 3,
    base_blueprint_content_sha256: sha,
    protected_chapter_numbers: [2],
    plans: [3, 4, 5].map((chapterNumber) => ({
      chapter_number: chapterNumber,
      title: `第 ${chapterNumber} 章新计划`,
      reader_promise: '主角取得可见进展',
      opening_hook: '名单出现异常',
      state_change: '主角掌握新线索',
      resource_change: '获得一份旧档案',
      emotional_payoff: '父子信任加深',
      ending_cliffhanger: '对手提前出现',
      verification: '核对名单来源',
      scene_beats: [{
        ordinal: 1,
        summary: '查名单',
        state_change: '发现涂改痕迹',
        resource_change: '取得旧档案',
        emotional_turn: '怀疑转为笃定',
        verification: '档案页码可核验',
      }],
    })),
    plans_sha256: sha,
    blocked_reason: null,
    adoption_idempotency_key: null,
    created_at: '2026-09-12T00:00:02Z',
    updated_at: '2026-09-12T00:00:02Z',
    decided_at: null,
    ...overrides,
  }
}

const refreshedWorkspace = { project: { id: project.id } } as WorkspaceSummary

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('ChapterFeedbackPanel', () => {
  it('does not request reconciliation before the chapter is approved', async () => {
    const request = vi.spyOn(api, 'getLatestCanonReconciliation')

    render(
      <ChapterFeedbackPanel
        project={project}
        chapter={{ ...chapter, status: 'reviewing' }}
        onWorkspaceChanged={vi.fn()}
      />,
    )
    await act(async () => undefined)

    expect(request).not.toHaveBeenCalled()
    expect(screen.queryByRole('heading', { name: '定稿回流审签' })).not.toBeInTheDocument()
  })

  it('retries a failed reconciliation and polls until ready without retrying a stale archive', async () => {
    vi.useFakeTimers()
    const failed = snapshot('failed', {
      reconciliation: {
        ...snapshot('failed').reconciliation,
        error_message: '模型服务暂时不可用',
      },
    })
    const request = vi.spyOn(api, 'getLatestCanonReconciliation')
      .mockResolvedValueOnce(failed)
      .mockResolvedValueOnce(snapshot('pending'))
      .mockResolvedValueOnce(snapshot('ready'))
      .mockResolvedValueOnce(snapshot('stale'))
    const retry = vi.spyOn(api, 'retryJob').mockResolvedValue({
      id: failed.reconciliation.job_id,
      state: 'queued',
    } as Awaited<ReturnType<typeof api.retryJob>>)

    const view = render(
      <ChapterFeedbackPanel
        project={project}
        chapter={chapter}
        onWorkspaceChanged={vi.fn()}
      />,
    )
    await act(async () => undefined)

    expect(screen.getByText('模型服务暂时不可用')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '重试定稿回流' }))
    expect(retry).toHaveBeenCalledWith(failed.reconciliation.job_id)
    await act(async () => undefined)
    expect(screen.getByText('正在从最终正文整理事实与作者偏好')).toBeVisible()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(700)
    })

    expect(request).toHaveBeenCalledTimes(3)
    expect(screen.getByText('已生成 0 条事实与 0 条偏好候选。')).toBeVisible()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_400)
    })
    expect(request).toHaveBeenCalledTimes(3)

    view.rerender(
      <ChapterFeedbackPanel
        project={project}
        chapter={{ ...chapter, revision: chapter.revision + 1 }}
        onWorkspaceChanged={vi.fn()}
      />,
    )
    await act(async () => undefined)

    expect(screen.getByText('正文版本已变化，这批候选只能查看，不能再写入正式设定。')).toBeVisible()
    expect(screen.queryByRole('button', { name: '重试定稿回流' })).not.toBeInTheDocument()
    expect(request).toHaveBeenCalledTimes(4)
    expect(retry).toHaveBeenCalledTimes(1)
  })

  it('caps pending polling and cancels its timer when the panel unmounts', async () => {
    vi.useFakeTimers()
    const request = vi.spyOn(api, 'getLatestCanonReconciliation').mockResolvedValue(snapshot('pending'))
    const view = render(<ChapterFeedbackPanel project={project} chapter={chapter} onWorkspaceChanged={vi.fn()} />)
    await act(async () => undefined)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(8_400)
    })

    expect(request).toHaveBeenCalledTimes(13)
    expect(screen.getByText('任务仍在后台运行，你可以稍后刷新结果。')).toBeVisible()
    view.unmount()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_100)
    })
    expect(request).toHaveBeenCalledTimes(13)
  })

  it('offers field editors for every typed Canon payload without exposing raw JSON', async () => {
    const cases: Array<{ candidate: CanonDeltaCandidate; labels: string[] }> = [
      {
        candidate: canonCandidate(),
        labels: ['人物', '当前状态', '本章变化'],
      },
      {
        candidate: canonCandidate({ id: 'canon-2', ordinal: 2, kind: 'relationship', summary: '沈砚与父亲重新结盟', payload: { source_name: '沈砚', target_name: '沈父', relation_type: '盟友', summary: '共同保住工厂' } }),
        labels: ['关系发起方', '关系对象', '关系类型', '关系说明'],
      },
      {
        candidate: canonCandidate({ id: 'canon-3', ordinal: 3, kind: 'resource_state', summary: '沈砚取得旧档案', payload: { owner_name: '沈砚', resource_name: '旧档案', delta: '+1', state: '随身保管' } }),
        labels: ['资源', '归属者', '增减变化', '变化后状态'],
      },
      {
        candidate: canonCandidate({ id: 'canon-4', ordinal: 4, kind: 'location_state', summary: '沈砚抵达南平站', payload: { subject_name: '沈砚', location: '南平站', movement: '从列车进入站台' } }),
        labels: ['人物或物件', '所在地点', '移动说明'],
      },
      {
        candidate: canonCandidate({ id: 'canon-5', ordinal: 5, kind: 'character_knowledge', summary: '沈父知道名单被改过', payload: { character_name: '沈父', knowledge: '停产名单被人涂改' } }),
        labels: ['知情角色', '新获认知'],
      },
      {
        candidate: canonCandidate({ id: 'canon-6', ordinal: 6, kind: 'future_knowledge', summary: '沈砚记得改制年份', payload: { holder_name: '沈砚', knowledge: '工厂将在两年后改制', confidence: 'likely', event_year: 2000 } }),
        labels: ['持有者', '未来知识', '可信程度', '发生年份'],
      },
      {
        candidate: canonCandidate({ id: 'canon-7', ordinal: 7, kind: 'story_thread', summary: '名单来源成为新伏笔', payload: { title: '谁改了名单', status: 'open', summary: '纸张来自厂长办公室' } }),
        labels: ['线索标题', '线索状态', '线索说明'],
      },
      {
        candidate: canonCandidate({ id: 'canon-8', ordinal: 8, kind: 'progression', summary: '沈砚掌握谈判能力', payload: { character_name: '沈砚', system: '商业能力', rank: '入门', change: '第一次说服工人代表' } }),
        labels: ['成长角色', '体系', '境界或能力', '成长变化'],
      },
      {
        candidate: canonCandidate({ id: 'canon-9', ordinal: 9, kind: 'timeline_event', summary: '停产名单提前张贴', payload: { layer: 'novel', event_year: 1998, title: '停产名单张贴', summary: '较原时间线提前三天' } }),
        labels: ['时间线', '事件年份', '事件标题', '事件摘要'],
      },
    ]
    vi.spyOn(api, 'getLatestCanonReconciliation').mockResolvedValue(snapshot('ready', {
      canon_candidates: cases.map(({ candidate }) => candidate),
    }))
    const user = userEvent.setup()

    render(<ChapterFeedbackPanel project={project} chapter={chapter} onWorkspaceChanged={vi.fn()} />)

    for (const { candidate, labels } of cases) {
      const card = await screen.findByRole('article', { name: candidate.summary })
      await user.click(within(card).getByRole('button', { name: '编辑后接受' }))
      expect(within(card).getByLabelText('归档对象')).toBeEnabled()
      expect(within(card).getByLabelText('事实摘要')).toBeEnabled()
      labels.forEach((label) => expect(within(card).getByLabelText(label)).toBeEnabled())
    }
    expect(screen.queryByLabelText(/JSON/i)).not.toBeInTheDocument()
  })

  it('submits a fully edited typed Canon decision and refreshes the workspace', async () => {
    const candidate = canonCandidate()
    const initial = snapshot('ready', { canon_candidates: [candidate] })
    const accepted = canonCandidate({
      state: 'accepted',
      revision: 3,
      accepted_record_id: 'record-1',
      decided_at: '2026-09-12T00:00:03Z',
    })
    const after = snapshot('ready', {
      reconciliation: { ...initial.reconciliation, revision: 2 },
      canon_candidates: [accepted],
    })
    vi.spyOn(api, 'getLatestCanonReconciliation')
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce(after)
    const decide = vi.spyOn(api, 'decideCanonReconciliation').mockResolvedValue({
      batch_id: 'batch-1',
      reconciliation_id: initial.reconciliation.id,
      reconciliation_revision: 2,
      replayed: false,
      accepted_canon_record_ids: ['record-1'],
      confirmed_preference_ids: [],
      rejected_candidate_ids: [],
      rolling_plan_replenishment_id: null,
    })
    vi.spyOn(api, 'getProjectSummary').mockResolvedValue(refreshedWorkspace)
    const onWorkspaceChanged = vi.fn()
    const user = userEvent.setup()

    render(<ChapterFeedbackPanel project={project} chapter={chapter} onWorkspaceChanged={onWorkspaceChanged} />)
    const card = await screen.findByRole('article', { name: candidate.summary })
    await user.click(within(card).getByRole('button', { name: '编辑后接受' }))
    await user.clear(within(card).getByLabelText('归档对象'))
    await user.type(within(card).getByLabelText('归档对象'), '沈砚：抉择')
    await user.clear(within(card).getByLabelText('事实摘要'))
    await user.type(within(card).getByLabelText('事实摘要'), '沈砚正式决定改变父亲命运')
    await user.clear(within(card).getByLabelText('当前状态'))
    await user.type(within(card).getByLabelText('当前状态'), '目标明确')
    await user.clear(within(card).getByLabelText('本章变化'))
    await user.type(within(card).getByLabelText('本章变化'), '从旁观转为行动')
    await user.click(screen.getByRole('button', { name: '提交 1 条事实决定' }))

    await waitFor(() => expect(decide).toHaveBeenCalledTimes(1))
    expect(decide).toHaveBeenCalledWith(project.id, initial.reconciliation.id, {
      reconciliation_id: initial.reconciliation.id,
      expected_reconciliation_revision: 1,
      idempotency_key: expect.stringMatching(/^canon-feedback:/),
      canon_decisions: [{
        candidate_id: candidate.id,
        expected_revision: 2,
        action: 'edit',
        edited_subject_key: '沈砚：抉择',
        edited_summary: '沈砚正式决定改变父亲命运',
        edited_payload: {
          character_name: '沈砚',
          state: '目标明确',
          change: '从旁观转为行动',
        },
      }],
      preference_decisions: [],
    })
    expect(onWorkspaceChanged).toHaveBeenCalledWith(refreshedWorkspace)
    expect(await screen.findByText('已记录 1 条事实决定，正式账本已刷新。')).toBeVisible()
  })

  it('submits preference edits as a separate atomic batch', async () => {
    const preference = preferenceCandidate()
    const initial = snapshot('ready', { preference_candidates: [preference] })
    const confirmed = preferenceCandidate({
      state: 'confirmed',
      revision: 2,
      confirmed_preference_id: 'memory-1',
      decided_at: '2026-09-12T00:00:03Z',
    })
    const after = snapshot('decided', {
      reconciliation: { ...initial.reconciliation, state: 'decided', revision: 2 },
      preference_candidates: [confirmed],
    })
    vi.spyOn(api, 'getLatestCanonReconciliation')
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce(after)
    const decide = vi.spyOn(api, 'decideCanonReconciliation').mockResolvedValue({
      batch_id: 'batch-2',
      reconciliation_id: initial.reconciliation.id,
      reconciliation_revision: 2,
      replayed: false,
      accepted_canon_record_ids: [],
      confirmed_preference_ids: ['memory-1'],
      rejected_candidate_ids: [],
      rolling_plan_replenishment_id: null,
    })
    vi.spyOn(api, 'getProjectSummary').mockResolvedValue(refreshedWorkspace)
    const user = userEvent.setup()

    render(<ChapterFeedbackPanel project={project} chapter={chapter} onWorkspaceChanged={vi.fn()} />)
    const card = await screen.findByRole('article', { name: preference.compact_rule })
    await user.click(within(card).getByRole('button', { name: '编辑后接受' }))
    await user.selectOptions(within(card).getByLabelText('适用范围'), 'chapter')
    await user.selectOptions(within(card).getByLabelText('偏好维度'), 'tension')
    await user.clear(within(card).getByLabelText('抽象偏好规则'))
    await user.type(within(card).getByLabelText('抽象偏好规则'), '揭示答案前先制造一次错误判断。')
    await user.clear(within(card).getByLabelText('置信度'))
    await user.type(within(card).getByLabelText('置信度'), '0.9')
    await user.click(screen.getByRole('button', { name: '提交 1 条偏好决定' }))

    await waitFor(() => expect(decide).toHaveBeenCalledTimes(1))
    expect(decide.mock.calls[0]?.[2]).toMatchObject({
      expected_reconciliation_revision: 1,
      canon_decisions: [],
      preference_decisions: [{
        candidate_id: preference.id,
        expected_revision: 1,
        action: 'edit',
        edited_scope_kind: 'chapter',
        edited_scope_value: chapter.id,
        edited_dimension: 'tension',
        edited_compact_rule: '揭示答案前先制造一次错误判断。',
        edited_confidence: 0.9,
      }],
    })
  })

  it('keeps local edits and the same idempotency key after a revision conflict', async () => {
    const candidate = canonCandidate()
    vi.spyOn(api, 'getLatestCanonReconciliation').mockResolvedValue(snapshot('ready', { canon_candidates: [candidate] }))
    const decide = vi.spyOn(api, 'decideCanonReconciliation')
      .mockRejectedValue(new ApiError('stale revision', 409, 'stale_reconciliation'))
    const user = userEvent.setup()

    render(<ChapterFeedbackPanel project={project} chapter={chapter} onWorkspaceChanged={vi.fn()} />)
    const card = await screen.findByRole('article', { name: candidate.summary })
    await user.click(within(card).getByRole('button', { name: '编辑后接受' }))
    const summary = within(card).getByLabelText('事实摘要')
    await user.clear(summary)
    await user.type(summary, '保留下来的本地事实编辑')
    await user.click(screen.getByRole('button', { name: '提交 1 条事实决定' }))

    expect(await screen.findByText('候选已有新版本。你的选择和编辑仍保留，请刷新后核对再提交。')).toBeVisible()
    expect(within(card).getByLabelText('事实摘要')).toHaveValue('保留下来的本地事实编辑')

    await user.click(screen.getByRole('button', { name: '提交 1 条事实决定' }))
    await waitFor(() => expect(decide).toHaveBeenCalledTimes(2))
    expect(decide.mock.calls[0]?.[2].idempotency_key).toBe(decide.mock.calls[1]?.[2].idempotency_key)
  })

  it('shows the preference skip reason and adopts rolling plans only after an explicit click', async () => {
    const plan = rollingPlan()
    vi.spyOn(api, 'getLatestCanonReconciliation').mockResolvedValue(snapshot('ready', {
      reconciliation: {
        ...snapshot('ready').reconciliation,
        preference_skip_reason: '本章没有可比较的 AI 候选与作者定稿。',
      },
      rolling_plan_replenishment: plan,
    }))
    const adopt = vi.spyOn(api, 'adoptRollingPlanReplenishment').mockResolvedValue({
      ...plan,
      state: 'adopted',
      revision: 1,
      adoption_idempotency_key: 'adopt-key',
      decided_at: '2026-09-12T00:00:04Z',
    })
    vi.spyOn(api, 'getProjectSummary').mockResolvedValue(refreshedWorkspace)
    const user = userEvent.setup()

    render(<ChapterFeedbackPanel project={project} chapter={chapter} onWorkspaceChanged={vi.fn()} />)
    expect(await screen.findByText('本章没有可比较的 AI 候选与作者定稿。')).toBeVisible()
    expect(adopt).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: '采用未来 3 章计划' }))

    await waitFor(() => expect(adopt).toHaveBeenCalledTimes(1))
    expect(adopt).toHaveBeenCalledWith(
      project.id,
      plan.id,
      plan.revision,
      plan.plans_sha256,
      expect.stringMatching(/^canon-feedback:/),
    )
    expect(await screen.findByText('已采用未来 3 章滚动计划。')).toBeVisible()
  })
})
