import type {
  Project,
  SandboxBranch,
  SandboxCandidate,
  SandboxReport,
  SandboxRun,
  SandboxSnapshot,
  SandboxTemplate,
  SandboxWorkspace,
} from '@mozhou/contracts'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api'
import { NarrativeSandboxDialog } from './NarrativeSandboxDialog'

const project: Project = {
  id: '05f14cb8-d0ed-4489-bc20-31c44c1efbba',
  title: '闽北新局',
  genre: 'urban_rebirth',
  rebirth_year: 1998,
  rebirth_location: '福建南平',
  chapter_target_words: 3000,
  safety_buffer_chapters: 3,
  created_at: '2026-08-11T00:00:00Z',
  updated_at: '2026-08-11T00:00:00Z',
}

const actors = Array.from({ length: 5 }, (_, index) => ({
  id: `actor_${index + 1}`,
  name: `势力${index + 1}`,
  kind: 'faction' as const,
  goal: '验证局势',
  location: '福建南平',
  resources: { influence: 3 },
  knowledge: ['公开信息'],
  capabilities: [],
  allowed_actions: ['observe' as const],
  relationships: {},
}))

const template: SandboxTemplate = {
  id: 'urban-business',
  label: '都市商战 · 首单与渠道',
  description: '五方围绕首单与现金流博弈。',
  suggested_variables: { 竞争者降价: true },
  actors,
}

const snapshot: SandboxSnapshot = {
  id: '11111111-1111-4111-8111-111111111111',
  project_id: project.id,
  label: '都市商战快照',
  engine_version: 'mozhou-sandbox-v1',
  actor_count: 5,
  snapshot_sha256: 'a'.repeat(64),
  source_counts: { fact: 2, timeline_original: 1, timeline_novel: 1, reality: 3 },
  actors,
  created_at: '2026-08-11T00:00:00Z',
}

const branch: SandboxBranch = {
  id: '22222222-2222-4222-8222-222222222222',
  project_id: project.id,
  snapshot_id: snapshot.id,
  parent_branch_id: null,
  label: '降价分支',
  seed: 20260811,
  variables: { 竞争者降价: true },
  forced_actions: [],
  created_at: '2026-08-11T00:01:00Z',
}

function run(state: SandboxRun['state'], completedRounds: number): SandboxRun {
  return {
    id: '33333333-3333-4333-8333-333333333333',
    project_id: project.id,
    branch_id: branch.id,
    state,
    requested_rounds: 3,
    completed_rounds: completedRounds,
    action_budget: 15,
    actions_used: completedRounds * 5,
    current_state_sha256: String(completedRounds).repeat(64),
    created_at: '2026-08-11T00:02:00Z',
    updated_at: '2026-08-11T00:02:00Z',
    completed_at: state === 'completed' ? '2026-08-11T00:03:00Z' : null,
    rounds: Array.from({ length: completedRounds }, (_, index) => ({
      id: `round-${index + 1}`,
      run_id: '33333333-3333-4333-8333-333333333333',
      ordinal: index + 1,
      actions: [],
      outcomes: [{
        actor_id: 'actor_1',
        summary: `第${index + 1}轮形成新的渠道选择。`,
        resource_changes: {},
        relationship_changes: {},
        location_change: null,
        momentum_change: 1,
        confidence: 0.72,
      }],
      assumptions: ['只依据快照'],
      evidence: [],
      state_before_sha256: 'b'.repeat(64),
      state_after_sha256: 'c'.repeat(64),
      created_at: '2026-08-11T00:02:00Z',
    })),
  }
}

const report: SandboxReport = {
  run_id: run('completed', 3).id,
  branch_id: branch.id,
  snapshot_sha256: snapshot.snapshot_sha256,
  state: 'completed',
  disclaimer: '以下均为受约束的剧情假设，不是历史事实、现实预测或正式故事设定。',
  conclusions: [{
    round_number: 3,
    actor_id: 'actor_1',
    statement: '第三轮形成新的渠道选择。',
    assumptions: ['只依据快照'],
    evidence: [],
    confidence: 0.72,
    impact_chain: ['观察', '动量+1', '改变下一轮选择'],
    counterexample: '若现实约束改变，本结论可能不成立。',
  }],
  final_scores: { total_momentum: 5 },
}

const candidate: SandboxCandidate = {
  id: '44444444-4444-4444-8444-444444444444',
  project_id: project.id,
  run_id: report.run_id,
  target_chapter_id: null,
  source_round: 3,
  kind: 'chapter_outline',
  title: '沙盘章纲候选',
  content: { beats: ['第三轮形成新的渠道选择。'] },
  state: 'candidate',
  created_at: '2026-08-11T00:04:00Z',
  updated_at: '2026-08-11T00:04:00Z',
  decided_at: null,
}

const empty: SandboxWorkspace = { snapshots: [], branches: [], runs: [], candidates: [] }

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('NarrativeSandboxDialog', () => {
  it('runs the local branch workflow and keeps results behind a candidate approval gate', async () => {
    vi.spyOn(api, 'listSandboxTemplates').mockResolvedValue([template])
    vi.spyOn(api, 'getSandboxWorkspace')
      .mockResolvedValueOnce(empty)
      .mockResolvedValueOnce({ ...empty, snapshots: [snapshot] })
      .mockResolvedValueOnce({ ...empty, snapshots: [snapshot], branches: [branch] })
    vi.spyOn(api, 'createSandboxSnapshot').mockResolvedValue(snapshot)
    vi.spyOn(api, 'createSandboxBranch').mockResolvedValue(branch)
    vi.spyOn(api, 'createSandboxRun').mockResolvedValue(run('ready', 0))
    vi.spyOn(api, 'advanceSandboxRun')
      .mockResolvedValueOnce(run('running', 1))
      .mockResolvedValueOnce(run('running', 2))
      .mockResolvedValueOnce(run('completed', 3))
    vi.spyOn(api, 'getSandboxReport').mockResolvedValue(report)
    vi.spyOn(api, 'createSandboxCandidate').mockResolvedValue(candidate)
    vi.spyOn(api, 'decideSandboxCandidate').mockResolvedValue({
      ...candidate,
      state: 'approved',
      decided_at: '2026-08-11T00:05:00Z',
    })
    const user = userEvent.setup()

    render(<NarrativeSandboxDialog project={project} onClose={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: /都市商战 · 首单与渠道/ }))
    expect(screen.getByLabelText('不可变快照')).toHaveValue(snapshot.id)
    await user.clear(screen.getByLabelText('分支名'))
    await user.type(screen.getByLabelText('分支名'), '降价分支')
    await user.click(screen.getByRole('button', { name: '创建隔离分支' }))
    await user.click(screen.getByRole('button', { name: '建立受约束推演' }))
    await user.click(screen.getByRole('button', { name: '连续推演' }))

    expect(await screen.findByRole('heading', { name: '每条结论都有假设、证据、置信度与反例' })).toBeVisible()
    expect(screen.getByText(report.disclaimer)).toBeVisible()
    expect(api.advanceSandboxRun).toHaveBeenCalledTimes(3)
    await user.click(screen.getByRole('button', { name: '形成章纲候选' }))
    expect(await screen.findByText('章纲候选 · candidate')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '批准为创作参考' }))

    await waitFor(() => expect(screen.getByText('章纲候选 · approved')).toBeVisible())
    expect(api.decideSandboxCandidate).toHaveBeenCalledWith(candidate.id, 'approve')
    expect(screen.getByRole('heading', { name: '批准也不会直接写正文、事实或时间线' })).toBeVisible()
  })

  it('supports cancelling a durable run before the next round', async () => {
    const ready = run('ready', 0)
    vi.spyOn(api, 'listSandboxTemplates').mockResolvedValue([template])
    vi.spyOn(api, 'getSandboxWorkspace').mockResolvedValue({
      ...empty,
      snapshots: [snapshot],
      branches: [branch],
      runs: [ready],
    })
    vi.spyOn(api, 'cancelSandboxRun').mockResolvedValue({ ...ready, state: 'cancelled' })
    const user = userEvent.setup()

    render(<NarrativeSandboxDialog project={project} onClose={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: '取消' }))

    expect(api.cancelSandboxRun).toHaveBeenCalledWith(ready.id)
    expect(await screen.findByText(/已取消 · 0\/3 轮/)).toBeVisible()
  })
})
