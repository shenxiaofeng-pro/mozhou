import type {
  CraftPatternAsset,
  CraftPatternAssetSummary,
  TopicDecisionField,
  WritingPatternProfilePreview,
  WritingPatternProfileVersion,
  WritingPatternRecipePreview,
  WritingPatternRecipeSeries,
  WritingPatternRecipeSummary,
  WritingPatternRecipeVersion,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api } from '../api'
import { WritingPatternRecipePage } from './WritingPatternRecipePage'

const projectId = '05f14cb8-d0ed-4489-bc20-31c44c1efbba'
const assetId = '62c9d281-9194-4e5e-b358-f022d30c479e'
const recipeId = '7a60a41d-29d2-4bbb-ae7c-acd307ee6d43'
const recipeVersionId = '9bd0ea8e-90ed-46f8-9a20-64d599e8b174'
const sha = (value: string) => value.repeat(64)
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

const workspace: WorkspaceSummary = {
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
  topic_decision: {
    id: 'topic-1',
    project_id: projectId,
    content: {
      target_platform: '番茄小说',
      target_audience: '喜欢实业升级的读者',
      subgenre: '都市重生',
      premise: '工程师回到九八年救活纸厂。',
      core_desire: '改变家庭命运。',
      long_term_promise: '逐卷完成产业升级。',
      first_three_chapter_promise: '危机、小胜、新债。',
      constraints: ['产业细节可信'],
      forbidden_elements: ['不复制参考作品人物'],
      reference_purpose: '学习钩子与兑现。',
      reality_anchor: '九十年代闽北工业。',
      first_ten_chapter_goal: '保住第一条产线。',
    },
    status: 'confirmed',
    locks: Object.fromEntries(topicFields.map((field) => [field, false])) as Record<TopicDecisionField, boolean>,
    field_versions: Object.fromEntries(topicFields.map((field) => [field, 1])) as Record<TopicDecisionField, number>,
    rejection_reasons: {},
    source_template_id: null,
    source_job_id: null,
    source_candidate_ids: [],
    revision: 4,
    confirmed_revision: 4,
    plan_stale: false,
    created_at: '2026-09-11T00:00:00Z',
    updated_at: '2026-09-11T00:00:00Z',
  },
  next_action: 'plan_book',
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

const assetSummary: CraftPatternAssetSummary = {
  id: assetId,
  series_id: '8c9c8235-56f1-41a8-bbe6-dce61912acd2',
  asset_type: 'stage',
  version: 1,
  content_sha256: sha('a'),
  lifecycle_state: 'active',
  lifecycle_revision: 0,
  source_work_ids: ['work-1'],
  source_segment_ids: ['segment-1'],
  source_asset_version_ids: [],
  title: '开局阶段·危机钩子',
  summary: '用倒计时把核心欲望压进第一个选择。',
  provider: 'openai',
  model: 'fixture-model',
  prompt_version: 'craft-pattern-v2',
  created_at: '2026-09-11T00:00:00Z',
  updated_at: '2026-09-11T00:00:00Z',
}

const assetDetail: CraftPatternAsset = {
  ...assetSummary,
  schema_version: 2,
  source_job_id: null,
  author_focus: '开篇钩子',
  craft_items: [{
    dimension: 'hook_mechanics',
    name: '危机倒计时',
    observation: '先给出不可拖延的损失。',
    transferable_rule: '在主角第一次选择前建立清晰倒计时。',
    adaptation_risk: '必须重写人物、事件和场景组织。',
    evidence: [{
      id: 'evidence-1',
      work_id: 'work-1',
      work_title: '作者自有旧稿',
      segment_id: 'segment-1',
      stage_label: '第 1 阶段',
      chapter_label: '第 1 章',
      absolute_start_char: 0,
      absolute_end_char: 80,
      evidence_summary: '危机在首次行动前完成倒计时建立。',
      evidence_sha256: sha('e'),
      confidence: 0.92,
    }],
  }],
}

const recipePreview: WritingPatternRecipePreview = {
  name: '回到九八年的南平·写作配方',
  description: '',
  expected_topic_revision: 4,
  expected_latest_version: null,
  sources: [{
    entry_key: sha('1'),
    asset_version_id: assetId,
    asset_series_id: assetSummary.series_id,
    asset_version: 1,
    asset_content_sha256: assetSummary.content_sha256,
    asset_type: 'stage',
    dimension: 'hook_mechanics',
    pattern_name: '危机倒计时',
    transferable_rule: '在主角第一次选择前建立清晰倒计时。',
    adaptation_risk: '必须重写人物、事件和场景组织。',
    purpose: 'learn',
    strategy: 'transform',
    weight: 60,
    applicable_stages: ['startup'],
    chapter_start: null,
    chapter_end: null,
    note: '',
    source_work_fingerprints: [{ basis: 'content_sha256', identity_sha256: sha('w') }],
    source_snapshot_sha256: sha('s'),
  }],
  conflicts: [],
  decisions: [],
  unresolved_conflict_count: 0,
  source_asset_count: 1,
  source_work_count: 1,
  safety_basis: 'source_verified',
  source_snapshot_sha256: sha('s'),
  recipe_content_sha256: sha('r'),
  preview_sha256: sha('p'),
}

const savedVersion: WritingPatternRecipeVersion = {
  id: recipeVersionId,
  recipe_id: recipeId,
  version: 1,
  name: recipePreview.name,
  description: '',
  source_asset_count: 1,
  source_work_count: 1,
  safety_basis: 'source_verified',
  source_snapshot_sha256: sha('s'),
  content_sha256: sha('r'),
  created_at: '2026-09-12T00:00:00Z',
  sources: recipePreview.sources,
  conflicts: [],
  conflict_decisions: [],
}

const recipeSummary: WritingPatternRecipeSummary = {
  id: recipeId,
  lifecycle_state: 'active',
  lifecycle_revision: 0,
  latest_version: savedVersion,
  created_at: '2026-09-12T00:00:00Z',
  updated_at: '2026-09-12T00:00:00Z',
}

const recipeSeries: WritingPatternRecipeSeries = {
  id: recipeId,
  lifecycle_state: 'active',
  lifecycle_revision: 0,
  versions: [savedVersion],
  created_at: '2026-09-12T00:00:00Z',
  updated_at: '2026-09-12T00:00:00Z',
}

const profilePreview: WritingPatternProfilePreview = {
  recipe_version_id: recipeVersionId,
  recipe_content_sha256: sha('r'),
  topic_decision_version_id: 'topic-version-1',
  topic_revision: 4,
  topic_content_sha256: sha('t'),
  safety_basis: 'source_verified',
  model_safe_profile: {
    schema_version: 1,
    compiler_version: 'recipe-v1',
    topic_revision: 4,
    topic_content_sha256: sha('t'),
    recipe_content_sha256: sha('r'),
    safety_basis: 'source_verified',
    rules: [{
      source_content_sha256: sha('a'),
      dimension: 'hook_mechanics',
      name: '危机倒计时',
      transferable_rule: '在主角第一次选择前建立清晰倒计时。',
      adaptation_risk: '必须重写人物、事件和场景组织。',
      purpose: 'learn',
      strategy: 'transform',
      weight_basis_points: 10_000,
      applicable_stages: ['startup'],
      chapter_start: null,
      chapter_end: null,
    }],
  },
  conflicts: [],
  decisions: [],
  excluded_entry_keys: [],
  source_snapshot_sha256: sha('s'),
  profile_fingerprint_sha256: sha('f'),
  preview_sha256: sha('q'),
}

const activeProfile: WritingPatternProfileVersion = {
  id: 'a12c3d45-6789-4abc-8def-1234567890ab',
  project_id: projectId,
  recipe_version_id: recipeVersionId,
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
  model_safe_profile: profilePreview.model_safe_profile,
  conflicts: [],
  decisions: [],
  excluded_entry_keys: [],
}

describe('WritingPatternRecipePage', () => {
  beforeEach(() => {
    vi.spyOn(api, 'listReferenceCraftAssets').mockResolvedValue([assetSummary])
    vi.spyOn(api, 'listWritingPatternRecipes').mockResolvedValue({ items: [], total: 0, limit: 30, offset: 0 })
    vi.spyOn(api, 'listWritingPatternProfiles').mockResolvedValue([])
    vi.spyOn(api, 'getReferenceCraftAsset').mockResolvedValue(assetDetail)
    vi.spyOn(api, 'previewWritingPatternRecipe').mockResolvedValue(recipePreview)
    vi.spyOn(api, 'createWritingPatternRecipe').mockResolvedValue(savedVersion)
    vi.spyOn(api, 'getWritingPatternRecipe').mockResolvedValue(recipeSeries)
    vi.spyOn(api, 'getWritingPatternRecipeVersion').mockResolvedValue(savedVersion)
    vi.spyOn(api, 'previewWritingPatternRecipeReuse').mockResolvedValue(profilePreview)
    vi.spyOn(api, 'reuseWritingPatternRecipe').mockResolvedValue(activeProfile)
    vi.spyOn(api, 'updateWritingPatternRecipeLifecycle').mockResolvedValue(recipeSeries)
    vi.spyOn(api, 'updateWritingPatternProfileLifecycle').mockResolvedValue(activeProfile)
    vi.spyOn(api, 'getPatternOriginalityGate').mockResolvedValue({
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
    })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('requires asset detail before selecting a craft item and never copies evidence into the recipe request', async () => {
    const user = userEvent.setup()
    render(<WritingPatternRecipePage workspace={workspace} onBack={vi.fn()} />)

    expect(await screen.findByText('开局阶段·危机钩子')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '加入配方' })).not.toBeInTheDocument()

    await user.click(screen.getByText('查看技法与来源证据'))
    const addButton = await screen.findByRole('button', { name: '加入配方' })
    await user.click(addButton)

    const matrix = screen.getByRole('region', { name: '来源矩阵' })
    expect(within(matrix).getByText('危机倒计时')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '编译配方预览' }))

    await waitFor(() => expect(api.previewWritingPatternRecipe).toHaveBeenCalledTimes(1))
    const request = vi.mocked(api.previewWritingPatternRecipe).mock.calls[0][1]
    expect(request.entries[0]).toEqual({
      asset_version_id: assetId,
      asset_content_sha256: sha('a'),
      dimension: 'hook_mechanics',
      pattern_name: '危机倒计时',
      purpose: 'learn',
      strategy: 'transform',
      weight: 60,
      applicable_stages: ['startup'],
      chapter_start: null,
      chapter_end: null,
      note: '',
    })
    expect(JSON.stringify(request)).not.toMatch(/observation|evidence|work_title|chapter_label|absolute_start_char|raw/)

    await user.click(await screen.findByRole('button', { name: '保存为全局配方' }))
    await waitFor(() => expect(api.createWritingPatternRecipe).toHaveBeenCalledWith(
      projectId,
      expect.objectContaining({ expected_preview_sha256: sha('p') }),
    ))
    expect(await screen.findByText('配方第 1 版已保存，全局库可以复用。')).toBeInTheDocument()
  })

  it('requires every compiler conflict to be resolved and recompiled before saving', async () => {
    const user = userEvent.setup()
    const secondItem = {
      ...assetDetail.craft_items[0],
      name: '先胜后压',
      transferable_rule: '先兑现一个小目标，再立刻提高下一步代价。',
      evidence: [{ ...assetDetail.craft_items[0].evidence[0], id: 'evidence-2' }],
    }
    vi.mocked(api.getReferenceCraftAsset).mockResolvedValue({
      ...assetDetail,
      craft_items: [assetDetail.craft_items[0], secondItem],
    })
    const secondSource = {
      ...recipePreview.sources[0],
      entry_key: sha('2'),
      pattern_name: '先胜后压',
      transferable_rule: secondItem.transferable_rule,
    }
    const unresolved: WritingPatternRecipePreview = {
      ...recipePreview,
      sources: [recipePreview.sources[0], secondSource],
      conflicts: [{
        conflict_key: sha('c'),
        dimension: 'hook_mechanics',
        applicable_stage: 'startup',
        entry_keys: [sha('1'), sha('2')],
        reason: 'competing_preserve_rules',
      }],
      unresolved_conflict_count: 1,
    }
    const resolved: WritingPatternRecipePreview = {
      ...unresolved,
      decisions: [{ conflict_key: sha('c'), resolution: 'choose_source', chosen_entry_key: sha('1') }],
      unresolved_conflict_count: 0,
      preview_sha256: sha('z'),
    }
    vi.mocked(api.previewWritingPatternRecipe)
      .mockResolvedValueOnce(unresolved)
      .mockResolvedValueOnce(resolved)

    render(<WritingPatternRecipePage workspace={workspace} onBack={vi.fn()} />)
    await user.click(await screen.findByText('查看技法与来源证据'))
    const addButtons = await screen.findAllByRole('button', { name: '加入配方' })
    await user.click(addButtons[0])
    await user.click(addButtons[1])
    await user.selectOptions(screen.getAllByLabelText('使用方式')[0], 'preserve_function')
    await user.selectOptions(screen.getAllByLabelText('使用方式')[1], 'preserve_function')
    await user.click(screen.getByRole('button', { name: '编译配方预览' }))

    expect(await screen.findByText('同一阶段有多条需要保留的规则')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存为全局配方' })).toBeDisabled()
    await user.click(screen.getByRole('radio', { name: '只采用一条来源规则' }))
    await user.selectOptions(screen.getByLabelText('选择保留的来源'), sha('1'))
    await user.click(screen.getByRole('button', { name: '重新编译冲突决定' }))

    await waitFor(() => expect(api.previewWritingPatternRecipe).toHaveBeenLastCalledWith(
      projectId,
      expect.objectContaining({
        conflict_decisions: [{
          conflict_key: sha('c'),
          resolution: 'choose_source',
          chosen_entry_key: sha('1'),
        }],
      }),
    ))
    expect(await screen.findByText('规则已稳定，可以保存为不可变版本。')).toBeInTheDocument()
  })

  it('opens a global immutable version before reuse and manages the project profile lifecycle', async () => {
    const user = userEvent.setup()
    vi.mocked(api.listWritingPatternRecipes).mockResolvedValue({ items: [recipeSummary], total: 1, limit: 30, offset: 0 })
    vi.mocked(api.updateWritingPatternProfileLifecycle).mockResolvedValue({
      ...activeProfile,
      lifecycle_state: 'archived',
      lifecycle_revision: 1,
      is_current: false,
    })

    render(<WritingPatternRecipePage workspace={workspace} onBack={vi.fn()} />)

    expect(await screen.findByText('全局配方版本库')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '查看配方版本' }))
    await user.click(await screen.findByRole('button', { name: '查看第 1 版' }))
    expect(await screen.findByText('在主角第一次选择前建立清晰倒计时。')).toBeInTheDocument()
    expect(screen.queryByText('先给出不可拖延的损失。')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '预览装入当前作品' }))
    expect(await screen.findByText('即将生成项目模式快照')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '确认装入为当前模式' }))

    expect(await screen.findByText('当前写作模式')).toBeInTheDocument()
    expect(screen.getByText('模式快照 ffffffffff')).toBeInTheDocument()
    expect(api.reuseWritingPatternRecipe).toHaveBeenCalledWith(projectId, recipeVersionId, {
      expected_recipe_content_sha256: sha('r'),
      expected_topic_revision: 4,
      expected_preview_sha256: sha('q'),
    })

    await user.click(screen.getByRole('button', { name: '归档当前模式' }))
    expect(await screen.findByText('模式快照已归档；后续创作不会使用它。')).toBeInTheDocument()
    expect(api.updateWritingPatternProfileLifecycle).toHaveBeenCalledWith(projectId, activeProfile.id, {
      state: 'archived',
      expected_lifecycle_revision: 0,
    })
  })

  it('creates a new immutable version without overwriting the inspected global version', async () => {
    const user = userEvent.setup()
    vi.mocked(api.listWritingPatternRecipes).mockResolvedValue({ items: [recipeSummary], total: 1, limit: 30, offset: 0 })
    vi.spyOn(api, 'previewWritingPatternRecipeVersion').mockResolvedValue({
      ...recipePreview,
      expected_latest_version: 1,
    })
    vi.spyOn(api, 'createWritingPatternRecipeVersion').mockResolvedValue({ ...savedVersion, version: 2 })

    render(<WritingPatternRecipePage workspace={workspace} onBack={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: '查看配方版本' }))
    await user.click(await screen.findByRole('button', { name: '查看第 1 版' }))
    await user.click(await screen.findByRole('button', { name: '基于第 1 版编配新版本' }))
    expect(within(screen.getByRole('region', { name: '来源矩阵' })).getByText('危机倒计时')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '编译第 2 版预览' }))
    await user.click(await screen.findByRole('button', { name: '保存为第 2 版' }))

    expect(api.createWritingPatternRecipeVersion).toHaveBeenCalledWith(projectId, recipeId, expect.objectContaining({
      expected_latest_version: 1,
      expected_preview_sha256: sha('p'),
    }))
    expect(await screen.findByText('配方第 2 版已保存，旧版本保持不变。')).toBeInTheDocument()
  })

  it('keeps the local matrix but invalidates a preview after a 409 conflict', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createWritingPatternRecipe).mockRejectedValue(
      new ApiError('配方预览条件已变化，请重新预览', 409, 'preview_changed'),
    )

    render(<WritingPatternRecipePage workspace={workspace} onBack={vi.fn()} />)
    await user.click(await screen.findByText('查看技法与来源证据'))
    await user.click(await screen.findByRole('button', { name: '加入配方' }))
    await user.click(screen.getByRole('button', { name: '编译配方预览' }))
    await user.click(await screen.findByRole('button', { name: '保存为全局配方' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('来源矩阵已保留，请重新编译预览')
    expect(within(screen.getByRole('region', { name: '来源矩阵' })).getByText('危机倒计时')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存为全局配方' })).toBeDisabled()
  })
})
