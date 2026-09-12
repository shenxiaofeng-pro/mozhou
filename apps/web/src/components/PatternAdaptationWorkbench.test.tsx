import type {
  AdoptPatternAdaptationResult,
  BookBlueprintField,
  Job,
  PatternAdaptationCandidate,
  PatternAdaptationPreflight,
  PatternAdaptationProposal,
  PatternOriginalityGateState,
  PatternOriginalityReport,
  WritingPatternProfileVersion,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api } from '../api'
import { PatternAdaptationWorkbench } from './PatternAdaptationWorkbench'

const projectId = '05f14cb8-d0ed-4489-bc20-31c44c1efbba'
const profileId = 'a12c3d45-6789-4abc-8def-1234567890ab'
const sha = (value: string) => value.repeat(64)
const blueprintFields: BookBlueprintField[] = [
  'title', 'genre', 'rebirth_year', 'rebirth_location', 'target_audience',
  'core_selling_points', 'core_desire', 'divergence_point', 'long_term_promise',
  'ending_direction', 'protagonist_arc', 'resource_growth', 'relationship_design',
]

const blueprint = {
  title: '回到九八年',
  genre: 'urban_rebirth' as const,
  rebirth_year: 1998,
  rebirth_location: '福建南平',
  target_audience: '喜欢产业成长的读者',
  core_selling_points: ['真实产业升级'],
  core_desire: '保住家人与工厂',
  divergence_point: '接下一张即将违约的订单',
  long_term_promise: '建立竹木产业网',
  ending_direction: '让家人与工人共享成果',
  protagonist_arc: '从独断走向信任',
  resource_growth: '订单、现金流和渠道逐步扩张',
  relationship_design: '父子冲突后重新协作',
}

const workspace: WorkspaceSummary = {
  project: {
    id: projectId, title: '回到九八年的南平', genre: 'urban_rebirth',
    rebirth_year: 1998, rebirth_location: '福建南平', chapter_target_words: 3000,
    safety_buffer_chapters: 3, created_at: '2026-09-11T00:00:00Z', updated_at: '2026-09-11T00:00:00Z',
  },
  chapters: [],
  topic_decision: null,
  next_action: 'plan_book',
  book_blueprint: null,
  volume_plans: [], rolling_chapter_plans: [], timeline_events: [], story_facts: [], fact_change_sets: [],
  future_knowledge: [], story_entities: [], story_threads: [], source_cards: [], reference_works: [],
  reference_pattern_cards: [], reference_pattern_applications: [], continuity_issues: [], resume_card: null,
}

const profile: WritingPatternProfileVersion = {
  id: profileId,
  project_id: projectId,
  recipe_version_id: '9bd0ea8e-90ed-46f8-9a20-64d599e8b174',
  recipe_content_sha256: sha('r'),
  topic_revision: 4,
  topic_content_sha256: sha('t'),
  safety_basis: 'source_verified',
  profile_fingerprint_sha256: sha('f'),
  lifecycle_state: 'active',
  lifecycle_revision: 0,
  is_current: true,
  created_at: '2026-09-12T00:00:00Z',
  updated_at: '2026-09-12T00:00:00Z',
  topic_decision_version_id: 'topic-version-1',
  compiler_version: 'recipe-v1',
  source_snapshot_sha256: sha('s'),
  model_safe_profile: {
    schema_version: 1,
    compiler_version: 'recipe-v1',
    topic_revision: 4,
    topic_content_sha256: sha('t'),
    recipe_content_sha256: sha('r'),
    safety_basis: 'source_verified',
    rules: [],
  },
  conflicts: [], decisions: [], excluded_entry_keys: [],
}

const preflight: PatternAdaptationPreflight = {
  profile_version_id: profileId,
  profile_fingerprint_sha256: sha('f'),
  recipe_version_id: profile.recipe_version_id,
  recipe_content_sha256: sha('r'),
  source_availability: 'source_verified',
  topic_decision_version_id: 'topic-version-1',
  topic_revision: 4,
  topic_content_sha256: sha('t'),
  base_blueprint_id: null,
  base_blueprint_revision: null,
  base_blueprint_content_sha256: null,
  dependency_fingerprint_sha256: sha('d'),
  safe_context_sha256: sha('c'),
  lock_snapshot_sha256: sha('l'),
  provider: 'openai_compatible',
  provider_profile_id: 'b12c3d45-6789-4abc-8def-1234567890ab',
  provider_profile_name: '创作线路',
  provider_profile_revision: 2,
  model: 'fixture-model',
  estimated_input_tokens: 2400,
  estimated_output_tokens: 12000,
  estimated_calls: 1,
  estimated_cost_microusd: 12_500,
  cost_status: 'known',
  data_types: ['已确认选题', '抽象写作模式', '作者意图', '字段锁'],
  content_scope: '生成 3 套隔离的整书蓝图候选，不自动采用',
  locked_fields: [],
  relationship_mode: 'rebuild_by_default',
  preview_sha256: sha('p'),
}

function candidate(ordinal: number): PatternAdaptationCandidate {
  const labels = ['家庭信任线', '产业竞速线', '地方共同体线']
  return {
    id: `candidate-${ordinal}`,
    proposal_id: 'proposal-1',
    ordinal,
    label: labels[ordinal - 1],
    why_distinct: ordinal === 1 ? '用父子信任危机启动主线。' : ordinal === 2 ? '用窗口期竞争启动主线。' : '用工人共同选择启动主线。',
    distinct_axes: ordinal === 1
      ? ['core_conflict', 'character_relationships']
      : ordinal === 2 ? ['core_conflict', 'resource_progression'] : ['character_relationships', 'scene_organization'],
    risk_hypotheses: ['需要核对九八年的产业条件'],
    current_version: {
      id: `candidate-version-${ordinal}`,
      candidate_id: `candidate-${ordinal}`,
      revision: 0,
      blueprint: { ...blueprint, title: `${blueprint.title}·方案${ordinal}` },
      key_scene_sequence: ['订单违约', '关系破裂', '抢回渠道'],
      transformation_notes: ['人物关系重新组织'],
      content_sha256: String(ordinal).repeat(64),
      changed_fields: blueprintFields,
      source: 'model',
      created_at: '2026-09-12T00:00:00Z',
    },
    created_at: '2026-09-12T00:00:00Z',
    updated_at: '2026-09-12T00:00:00Z',
  }
}

const proposal: PatternAdaptationProposal = {
  id: 'proposal-1', job_id: 'job-1', project_id: projectId,
  profile_version_id: profileId, profile_fingerprint_sha256: sha('f'),
  recipe_version_id: profile.recipe_version_id, recipe_content_sha256: sha('r'),
  topic_decision_version_id: 'topic-version-1', topic_revision: 4, topic_content_sha256: sha('t'),
  base_blueprint_id: null, base_blueprint_revision: null, base_blueprint_content_sha256: null,
  dependency_fingerprint_sha256: sha('d'), safe_context_sha256: sha('c'), lock_snapshot_sha256: sha('l'),
  provider: 'openai_compatible', provider_profile_id: preflight.provider_profile_id,
  provider_profile_revision: 2, model: 'fixture-model', input_cost_microusd_per_million: 100,
  output_cost_microusd_per_million: 200, result_state: 'available', stale_reason: null,
  candidates: [candidate(1), candidate(2), candidate(3)],
  created_at: '2026-09-12T00:00:00Z', updated_at: '2026-09-12T00:00:00Z',
}

const job: Job = {
  id: 'job-1', project_id: projectId, chapter_id: null, parent_job_id: null,
  kind: 'pattern_adaptation', workflow: 'pattern_adaptation', state: 'succeeded',
  idempotency_key: 'job-key', progress_current: 1, progress_total: 1,
  current_step: '3 套原创迁移方案已生成', estimated_calls: 1, completed_calls: 1,
  provider: 'openai_compatible', provider_profile_id: preflight.provider_profile_id,
  model: 'fixture-model', lease_owner: null, lease_expires_at: null, heartbeat_at: null,
  error_code: null, error_message: null, created_at: '2026-09-12T00:00:00Z',
  updated_at: '2026-09-12T00:00:00Z', started_at: '2026-09-12T00:00:00Z', completed_at: '2026-09-12T00:00:01Z',
}

const adoption: AdoptPatternAdaptationResult = {
  adoption: {
    id: 'adoption-1', project_id: projectId, proposal_id: proposal.id, candidate_id: 'candidate-1',
    candidate_version_id: 'candidate-version-1', blueprint_id: 'blueprint-1', blueprint_revision: 0,
    blueprint_content_sha256: sha('b'), profile_fingerprint_sha256: sha('f'), recipe_content_sha256: sha('r'),
    created_at: '2026-09-12T00:00:02Z',
  },
  blueprint: {
    id: 'blueprint-1', project_id: projectId, idea: '救活家庭工厂', content: candidate(1).current_version.blueprint,
    locks: Object.fromEntries(blueprintFields.map((field) => [field, false])) as Record<BookBlueprintField, boolean>,
    field_versions: Object.fromEntries(blueprintFields.map((field) => [field, 1])) as Record<BookBlueprintField, number>,
    stale_fields: [], plan_stale: true, source_candidate_id: 'candidate-1', revision: 0,
    created_at: '2026-09-12T00:00:02Z', updated_at: '2026-09-12T00:00:02Z',
  },
  originality_status: 'needs_check',
}

const mediumReport: PatternOriginalityReport = {
  id: 'report-1', project_id: projectId, adoption_id: 'adoption-1', profile_fingerprint_sha256: sha('f'),
  recipe_content_sha256: sha('r'), blueprint_id: 'blueprint-1', blueprint_revision: 0,
  blueprint_content_sha256: sha('b'), candidate_version_id: 'candidate-version-1',
  candidate_content_sha256: sha('1'), risk_level: 'medium', status: 'review_required', score: 58,
  threshold_version: 'writing-pattern-originality-v1', input_sha256: sha('i'), source_availability: 'source_verified',
  findings: [{ id: 'finding-1', ordinal: 0, signal: 'relationship_function', score: 58,
    summary: '人物功能组合与多条抽象规则接近，需要作者确认已完成重构。',
    source_fingerprint_sha256: sha('x'), evidence_sha256: sha('e') }],
  viewed_at: null, acknowledged_at: null, created_at: '2026-09-12T00:00:03Z',
}

const emptyGate: PatternOriginalityGateState = {
  project_id: projectId,
  state: 'needs_adaptation',
  reason: 'adaptation_not_adopted',
  requires_check: true,
  adoption: null,
  blueprint_id: null,
  blueprint_revision: null,
  blueprint_content_sha256: null,
  latest_report: null,
  report_is_current: false,
}

describe('PatternAdaptationWorkbench', () => {
  beforeEach(() => {
    vi.spyOn(api, 'getPatternOriginalityGate').mockResolvedValue(emptyGate)
    vi.spyOn(api, 'previewPatternAdaptation').mockResolvedValue(preflight)
    vi.spyOn(api, 'startPatternAdaptation').mockResolvedValue(job)
    vi.spyOn(api, 'getPatternAdaptationResult').mockResolvedValue(proposal)
    vi.spyOn(api, 'editPatternAdaptationCandidate').mockImplementation(async (_project, _candidate, input) => ({
      ...candidate(1),
      current_version: { ...candidate(1).current_version, ...input, revision: 1, content_sha256: sha('u'), source: 'author_edit' },
    }))
    vi.spyOn(api, 'adoptPatternAdaptationCandidate').mockResolvedValue(adoption)
    vi.spyOn(api, 'runPatternOriginalityCheck').mockResolvedValue(mediumReport)
    vi.spyOn(api, 'viewPatternOriginalityReport').mockResolvedValue({ ...mediumReport, viewed_at: '2026-09-12T00:00:04Z' })
    vi.spyOn(api, 'acknowledgePatternOriginalityReport').mockResolvedValue({
      ...mediumReport, status: 'passed', viewed_at: '2026-09-12T00:00:04Z', acknowledged_at: '2026-09-12T00:00:05Z',
    })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('previews safe external scope, compares exactly three isolated candidates, edits, adopts, then requires viewing a medium report before acknowledgement', async () => {
    const user = userEvent.setup()
    render(<PatternAdaptationWorkbench workspace={workspace} profile={profile} />)

    await user.type(screen.getByLabelText('这次迁移最想改变什么'), '强化产业窗口期，并重构所有人物关系。')
    await user.click(screen.getByRole('button', { name: '预览范围与费用' }))

    await waitFor(() => expect(api.previewPatternAdaptation).toHaveBeenCalledWith(projectId, expect.objectContaining({
      profile_version_id: profileId,
      expected_profile_fingerprint_sha256: sha('f'),
      expected_topic_revision: 4,
      expected_topic_content_sha256: sha('t'),
      expected_base_blueprint_revision: null,
      expected_base_blueprint_content_sha256: null,
      author_intent: '强化产业窗口期，并重构所有人物关系。',
    })))
    expect(JSON.stringify(vi.mocked(api.previewPatternAdaptation).mock.calls[0][1])).not.toMatch(
      /observation|evidence|work_title|chapter_label|absolute_start_char|raw_text/,
    )
    expect(await screen.findByText('生成 3 套隔离的整书蓝图候选，不自动采用')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '生成 3 套候选' })).toBeDisabled()
    await user.click(screen.getByLabelText('确认发送上述抽象创作资料'))
    await user.click(screen.getByRole('button', { name: '生成 3 套候选' }))

    const comparison = await screen.findByRole('region', { name: '三套原创迁移候选' })
    expect(within(comparison).getAllByText(/候选 \d\/3/)).toHaveLength(3)
    expect(within(comparison).getByText('家庭信任线')).toBeInTheDocument()
    expect(within(comparison).getByText('产业竞速线')).toBeInTheDocument()
    expect(within(comparison).getByText('地方共同体线')).toBeInTheDocument()
    expect(comparison).toHaveTextContent('所有方案都只是候选')
    expect(comparison).not.toHaveTextContent('作者自有旧稿')
    expect(comparison).not.toHaveTextContent('危机在首次行动前完成倒计时建立')

    await user.click(within(comparison).getAllByRole('button', { name: '调整此候选' })[0])
    const relationship = within(comparison).getByLabelText('人物关系设计')
    await user.clear(relationship)
    await user.type(relationship, '父子从互不信任到共同承担风险，竞争者转为行业盟友。')
    await user.click(within(comparison).getByRole('button', { name: '保存候选调整' }))
    await waitFor(() => expect(api.editPatternAdaptationCandidate).toHaveBeenCalledWith(
      projectId,
      'candidate-1',
      expect.objectContaining({ changed_fields: ['relationship_design'], expected_revision: 0 }),
    ))

    await user.click(within(comparison).getAllByRole('button', { name: '采用并检查原创性' })[0])
    expect(await screen.findByText('中风险 · 58 分')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '确认已完成原创改编' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '查看完整风险报告' }))
    expect(await screen.findByText('人物功能组合与多条抽象规则接近，需要作者确认已完成重构。')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '确认已完成原创改编' }))
    expect(await screen.findByText('原创性检查已通过')).toBeInTheDocument()
  })

  it('refuses to start a remote task when pricing is unavailable', async () => {
    const user = userEvent.setup()
    vi.mocked(api.previewPatternAdaptation).mockResolvedValue({
      ...preflight,
      estimated_cost_microusd: null,
      cost_status: 'unavailable',
    })

    render(<PatternAdaptationWorkbench workspace={workspace} profile={profile} />)
    await user.type(screen.getByLabelText('这次迁移最想改变什么'), '重构人物关系。')
    await user.click(screen.getByRole('button', { name: '预览范围与费用' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('费用未知')
    expect(screen.queryByLabelText('确认发送上述抽象创作资料')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '生成 3 套候选' })).toBeDisabled()
    expect(api.startPatternAdaptation).not.toHaveBeenCalled()
  })

  it('hard-blocks a high-risk adopted blueprint and offers no acknowledgement escape hatch', async () => {
    const user = userEvent.setup()
    const highReport: PatternOriginalityReport = {
      ...mediumReport,
      risk_level: 'high',
      status: 'blocked',
      score: 82,
      findings: [{ ...mediumReport.findings[0], score: 82 }],
    }
    vi.mocked(api.runPatternOriginalityCheck).mockResolvedValue(highReport)
    vi.mocked(api.viewPatternOriginalityReport).mockResolvedValue({
      ...highReport,
      viewed_at: '2026-09-12T00:00:04Z',
    })

    render(<PatternAdaptationWorkbench workspace={workspace} profile={profile} />)
    await user.type(screen.getByLabelText('这次迁移最想改变什么'), '彻底改变场景顺序。')
    await user.click(screen.getByRole('button', { name: '预览范围与费用' }))
    await user.click(await screen.findByLabelText('确认发送上述抽象创作资料'))
    await user.click(screen.getByRole('button', { name: '生成 3 套候选' }))
    const comparison = await screen.findByRole('region', { name: '三套原创迁移候选' })
    await user.click(within(comparison).getAllByRole('button', { name: '采用并检查原创性' })[0])

    expect(await screen.findByText('高风险 · 82 分')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('编辑当前实际蓝图并按最新版本重跑检查')
    await user.click(screen.getByRole('button', { name: '查看完整风险报告' }))
    expect(await screen.findByText(highReport.findings[0].summary)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '确认已完成原创改编' })).not.toBeInTheDocument()
    expect(within(comparison).getAllByRole('button', { name: /已采用，等待门禁|原候选已过期/ })).toHaveLength(3)
    expect(api.acknowledgePatternOriginalityReport).not.toHaveBeenCalled()
  })

  it('keeps author intent but removes stale confirmation after a 409', async () => {
    const user = userEvent.setup()
    vi.mocked(api.startPatternAdaptation).mockRejectedValue(
      new ApiError('预览条件已变化', 409, 'preview_changed'),
    )

    render(<PatternAdaptationWorkbench workspace={workspace} profile={profile} />)
    const intent = screen.getByLabelText('这次迁移最想改变什么')
    await user.type(intent, '把结局改成共同成长。')
    await user.click(screen.getByRole('button', { name: '预览范围与费用' }))
    await user.click(await screen.findByLabelText('确认发送上述抽象创作资料'))
    await user.click(screen.getByRole('button', { name: '生成 3 套候选' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('请重新预检后提交')
    expect(intent).toHaveValue('把结局改成共同成长。')
    expect(screen.queryByLabelText('确认发送上述抽象创作资料')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '预览范围与费用' })).toBeEnabled()
  })

  it('restores a current medium-risk gate after refresh and still requires an explicit report view', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getPatternOriginalityGate).mockResolvedValue({
      project_id: projectId,
      state: 'review_required',
      reason: 'medium_risk_requires_acknowledgement',
      requires_check: true,
      adoption: adoption.adoption,
      blueprint_id: adoption.adoption.blueprint_id,
      blueprint_revision: adoption.adoption.blueprint_revision,
      blueprint_content_sha256: adoption.adoption.blueprint_content_sha256,
      latest_report: mediumReport,
      report_is_current: true,
    })

    render(<PatternAdaptationWorkbench workspace={workspace} profile={profile} />)

    expect(await screen.findByText('当前实际蓝图等待作者确认')).toBeInTheDocument()
    expect(screen.getByText('中风险 · 58 分')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '确认已完成原创改编' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '查看完整风险报告' }))
    await user.click(await screen.findByRole('button', { name: '确认已完成原创改编' }))
    expect(await screen.findByText('原创性检查已通过')).toBeInTheDocument()
  })

  it('reruns a stale gate against the latest actual blueprint rather than the adopted snapshot', async () => {
    const user = userEvent.setup()
    const currentBlueprintHash = sha('z')
    vi.mocked(api.getPatternOriginalityGate).mockResolvedValue({
      project_id: projectId,
      state: 'stale',
      reason: 'blueprint_changed_after_report',
      requires_check: true,
      adoption: adoption.adoption,
      blueprint_id: adoption.adoption.blueprint_id,
      blueprint_revision: 7,
      blueprint_content_sha256: currentBlueprintHash,
      latest_report: mediumReport,
      report_is_current: false,
    })

    render(<PatternAdaptationWorkbench workspace={workspace} profile={profile} />)

    expect(await screen.findAllByText('蓝图已调整，旧检查报告已过期')).toHaveLength(2)
    expect(screen.queryByText('中风险 · 58 分')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '重新运行检查' }))

    await waitFor(() => expect(api.runPatternOriginalityCheck).toHaveBeenCalledWith(projectId, {
      expected_blueprint_revision: 7,
      expected_blueprint_content_sha256: currentBlueprintHash,
      expected_profile_fingerprint_sha256: adoption.adoption.profile_fingerprint_sha256,
      expected_recipe_content_sha256: adoption.adoption.recipe_content_sha256,
    }))
  })

  it('keeps an existing originality gate visible when its source profile is archived', async () => {
    vi.mocked(api.getPatternOriginalityGate).mockResolvedValue({
      project_id: projectId,
      state: 'review_required',
      reason: 'medium_risk_requires_acknowledgement',
      requires_check: true,
      adoption: adoption.adoption,
      blueprint_id: adoption.adoption.blueprint_id,
      blueprint_revision: adoption.adoption.blueprint_revision,
      blueprint_content_sha256: adoption.adoption.blueprint_content_sha256,
      latest_report: mediumReport,
      report_is_current: true,
    })

    render(<PatternAdaptationWorkbench workspace={workspace} profile={{ ...profile, lifecycle_state: 'archived' }} />)

    expect(await screen.findByText('当前实际蓝图等待作者确认')).toBeInTheDocument()
    expect(screen.getByText('中风险 · 58 分')).toBeInTheDocument()
    expect(screen.getByText(/归档模式不会绕过已有检查/)).toBeInTheDocument()
    expect(screen.queryByLabelText('这次迁移最想改变什么')).not.toBeInTheDocument()
  })
})
