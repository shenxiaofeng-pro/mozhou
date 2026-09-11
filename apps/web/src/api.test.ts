import { invoke, isTauri } from '@tauri-apps/api/core'
import type { PreviewWritingPatternRecipeInput } from '@mozhou/contracts'
import { afterEach, expect, it, vi } from 'vitest'

import { aiCredentialStore, ApiError, api } from './api'

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
  isTauri: vi.fn(),
}))

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('uses the loopback sidecar address and in-memory session token returned by Tauri', async () => {
  const sessionToken = 'a'.repeat(64)
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8765')
  vi.mocked(isTauri).mockReturnValue(true)
  vi.mocked(invoke).mockResolvedValue({
    baseUrl: 'http://127.0.0.1:54321',
    sessionToken,
  })
  const request = vi.fn().mockResolvedValue(
    new Response(JSON.stringify([]), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', request)

  await api.listProjects()

  expect(invoke).toHaveBeenCalledWith('api_connection')
  expect(request).toHaveBeenCalledWith('http://127.0.0.1:54321/api/projects', expect.any(Object))
  const requestInit = request.mock.calls[0][1] as RequestInit
  expect(new Headers(requestInit.headers).get('X-Mozhou-Session-Token')).toBe(sessionToken)
})

it('keeps multiple browser fallback credentials only in the current module session', async () => {
  vi.mocked(isTauri).mockReturnValue(false)
  const activate = vi.spyOn(api, 'activateAiProfile').mockResolvedValue({
    configured: true,
    provider: 'openai_compatible',
    model: 'fixture',
    key_source: 'runtime',
    profile_id: null,
    profile_name: null,
  })
  const firstProfile = '3a3f708a-2599-4ad7-8de0-413331897de3'
  const secondProfile = 'f31777af-41b0-46cf-aea4-9e2a3f5ffb48'

  await aiCredentialStore.storeAndActivate(firstProfile, 'first-session-fixture')
  await aiCredentialStore.storeAndActivate(secondProfile, 'second-session-fixture')
  await aiCredentialStore.activateSaved(firstProfile)

  expect(activate).toHaveBeenNthCalledWith(1, firstProfile, 'first-session-fixture')
  expect(activate).toHaveBeenNthCalledWith(2, secondProfile, 'second-session-fixture')
  expect(activate).toHaveBeenNthCalledWith(3, firstProfile, 'first-session-fixture')
  expect(await aiCredentialStore.status(firstProfile)).toEqual({
    profileId: firstProfile,
    stored: true,
    active: true,
  })
  expect(await aiCredentialStore.status(secondProfile)).toEqual({
    profileId: secondProfile,
    stored: true,
    active: false,
  })
})

it('updates a reference application lifecycle with its independent revision', async () => {
  vi.mocked(isTauri).mockReturnValue(false)
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8765')
  const request = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ lifecycle_state: 'draft', lifecycle_revision: 3 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', request)

  await api.updateReferenceApplicationLifecycle('project id', 'application/id', {
    lifecycle_state: 'draft',
    expected_lifecycle_revision: 2,
  })

  expect(request).toHaveBeenCalledWith(
    'http://127.0.0.1:8765/api/projects/project%20id/reference-pattern-applications/application%2Fid/lifecycle',
    expect.objectContaining({
      method: 'PATCH',
      body: JSON.stringify({
        lifecycle_state: 'draft',
        expected_lifecycle_revision: 2,
      }),
    }),
  )
})

it('starts topic candidates only after forwarding the explicit external-processing confirmation', async () => {
  vi.mocked(isTauri).mockReturnValue(false)
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8765')
  const request = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ id: 'job-1', kind: 'topic_decision' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', request)

  await api.startTopicDecisionCandidateJob('project id', {
    expected_revision: 4,
    author_intent: '更强调开篇兑现',
    confirm_external_processing: true,
    max_estimated_cost_microusd: 12_345,
  })

  expect(request).toHaveBeenCalledWith(
    'http://127.0.0.1:8765/api/projects/project%20id/topic-decision/candidate-jobs',
    expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({
        expected_revision: 4,
        author_intent: '更强调开篇兑现',
        confirm_external_processing: true,
        max_estimated_cost_microusd: 12_345,
      }),
    }),
  )
})

it('sends only the author-selected topic fields when adopting a candidate', async () => {
  vi.mocked(isTauri).mockReturnValue(false)
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8765')
  const request = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ id: 'topic-1', revision: 5 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', request)

  await api.selectTopicDecisionCandidate('project/id', {
    job_id: 'job-1',
    candidate_id: 'candidate-2',
    selected_fields: ['premise', 'core_desire'],
    expected_revision: 4,
  })

  expect(request).toHaveBeenCalledWith(
    'http://127.0.0.1:8765/api/projects/project%2Fid/topic-decision/candidate-selection',
    expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({
        job_id: 'job-1',
        candidate_id: 'candidate-2',
        selected_fields: ['premise', 'core_desire'],
        expected_revision: 4,
      }),
    }),
  )
})

it('keeps raw reference analysis separate from persisted-asset fusion', async () => {
  vi.mocked(isTauri).mockReturnValue(false)
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8765')
  const request = vi.fn().mockImplementation(async () => (
    new Response(JSON.stringify({ id: 'job-1' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  ))
  vi.stubGlobal('fetch', request)

  await api.startCraftPatternAnalysisJob('project/id', {
    selected_segment_ids: ['segment-1'],
    author_focus: '章末钩子',
    expected_preflight_sha256: 'analysis-fingerprint',
    confirm_external_processing: true,
    confirm_unknown_cost: false,
    max_estimated_cost_microusd: 30_000,
  })
  await api.startCraftPatternFusionJob('project/id', {
    selected_asset_version_ids: ['stage-1', 'book-2'],
    author_focus: '融合升级与兑现节奏',
    expected_preflight_sha256: 'fusion-fingerprint',
    confirm_external_processing: true,
    confirm_unknown_cost: false,
    max_estimated_cost_microusd: 12_000,
  })

  expect(request).toHaveBeenNthCalledWith(
    1,
    'http://127.0.0.1:8765/api/projects/project%2Fid/craft-pattern-analysis-jobs',
    expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({
        selected_segment_ids: ['segment-1'],
        author_focus: '章末钩子',
        expected_preflight_sha256: 'analysis-fingerprint',
        confirm_external_processing: true,
        confirm_unknown_cost: false,
        max_estimated_cost_microusd: 30_000,
      }),
    }),
  )
  expect(request).toHaveBeenNthCalledWith(
    2,
    'http://127.0.0.1:8765/api/projects/project%2Fid/craft-pattern-fusion-jobs',
    expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({
        selected_asset_version_ids: ['stage-1', 'book-2'],
        author_focus: '融合升级与兑现节奏',
        expected_preflight_sha256: 'fusion-fingerprint',
        confirm_external_processing: true,
        confirm_unknown_cost: false,
        max_estimated_cost_microusd: 12_000,
      }),
    }),
  )
})

it('updates a craft asset lifecycle with its project-link revision', async () => {
  vi.mocked(isTauri).mockReturnValue(false)
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8765')
  const request = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ id: 'asset-1', lifecycle_state: 'archived', lifecycle_revision: 5 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', request)

  await api.updateCraftPatternLifecycle('project id', 'asset/id', {
    state: 'archived',
    expected_lifecycle_revision: 4,
  })

  expect(request).toHaveBeenCalledWith(
    'http://127.0.0.1:8765/api/projects/project%20id/reference-craft-assets/asset%2Fid/lifecycle',
    expect.objectContaining({
      method: 'PATCH',
      body: JSON.stringify({ state: 'archived', expected_lifecycle_revision: 4 }),
    }),
  )
})

it('discovers immutable craft assets globally and loads unlinked detail without project scoping', async () => {
  vi.mocked(isTauri).mockReturnValue(false)
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8765')
  const request = vi.fn().mockImplementation(async () => (
    new Response(JSON.stringify({ items: [], total: 0, limit: 50, offset: 0 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  ))
  vi.stubGlobal('fetch', request)

  await api.listGlobalReferenceCraftAssets({
    for_project_id: 'project id',
    asset_type: 'book_evolution',
    work_id: 'work/id',
    limit: 50,
    offset: 100,
  })
  await api.getReferenceCraftAsset('asset/id')

  expect(request).toHaveBeenNthCalledWith(
    1,
    'http://127.0.0.1:8765/api/reference-craft-assets?for_project_id=project+id&asset_type=book_evolution&work_id=work%2Fid&limit=50&offset=100',
    expect.objectContaining({ headers: expect.any(Headers) }),
  )
  expect(request).toHaveBeenNthCalledWith(
    2,
    'http://127.0.0.1:8765/api/reference-craft-assets/asset%2Fid',
    expect.objectContaining({ headers: expect.any(Headers) }),
  )
})

it('previews and saves a writing-pattern recipe with only immutable abstract source selectors', async () => {
  vi.mocked(isTauri).mockReturnValue(false)
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8765')
  const request = vi.fn().mockImplementation(async () => (
    new Response(JSON.stringify({ preview_sha256: 'p'.repeat(64) }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  ))
  vi.stubGlobal('fetch', request)
  const input: PreviewWritingPatternRecipeInput = {
    name: '钩子与兑现配方',
    description: '学习开篇承诺，避开同构人物关系。',
    expected_topic_revision: 4,
    entries: [{
      asset_version_id: '62c9d281-9194-4e5e-b358-f022d30c479e',
      asset_content_sha256: 'a'.repeat(64),
      dimension: 'hook_mechanics',
      pattern_name: '危机倒计时',
      purpose: 'learn',
      strategy: 'transform',
      weight: 70,
      applicable_stages: ['startup', 'chapter_brief'],
      chapter_start: null,
      chapter_end: null,
      note: '保留功能，不复制事件。',
    }],
    conflict_decisions: [],
  }

  await api.previewWritingPatternRecipe('project/id', input)
  await api.createWritingPatternRecipe('project/id', {
    ...input,
    expected_preview_sha256: 'p'.repeat(64),
  })

  expect(request).toHaveBeenNthCalledWith(
    1,
    'http://127.0.0.1:8765/api/projects/project%2Fid/writing-pattern-recipes/preview',
    expect.objectContaining({ method: 'POST', body: JSON.stringify(input) }),
  )
  const serialized = JSON.stringify((request.mock.calls[1][1] as RequestInit).body)
  expect(serialized).not.toMatch(/observation|evidence|work_title|chapter_label|absolute_start_char|raw_text/)
})

it('keeps the structured writing-pattern conflict code for safe recovery', async () => {
  vi.mocked(isTauri).mockReturnValue(false)
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8765')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
    new Response(JSON.stringify({
      detail: { code: 'preview_changed', message: '配方预览条件已变化，请重新预览' },
    }), {
      status: 409,
      headers: { 'Content-Type': 'application/json' },
    }),
  ))

  const caught = await api.listWritingPatternRecipes().catch((error: unknown) => error)

  expect(caught).toBeInstanceOf(ApiError)
  expect(caught).toMatchObject({
    status: 409,
    code: 'preview_changed',
    message: '配方预览条件已变化，请重新预览',
  })
})

it('routes immutable recipe versions, reuse previews, and lifecycle revisions explicitly', async () => {
  vi.mocked(isTauri).mockReturnValue(false)
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8765')
  const request = vi.fn().mockImplementation(async () => (
    new Response(JSON.stringify({ items: [], versions: [], rules: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  ))
  vi.stubGlobal('fetch', request)
  const recipeInput: PreviewWritingPatternRecipeInput = {
    name: '稳定配方',
    description: '',
    expected_topic_revision: 7,
    entries: [{
      asset_version_id: '62c9d281-9194-4e5e-b358-f022d30c479e',
      asset_content_sha256: 'a'.repeat(64),
      dimension: 'scene_design',
      pattern_name: '场景状态翻转',
      purpose: 'learn',
      strategy: 'transform',
      weight: 80,
      applicable_stages: ['chapter_brief'],
      chapter_start: null,
      chapter_end: null,
      note: '',
    }],
    conflict_decisions: [],
  }

  await api.previewWritingPatternRecipeVersion('project/id', 'recipe/id', {
    ...recipeInput,
    expected_latest_version: 2,
  })
  await api.createWritingPatternRecipeVersion('project/id', 'recipe/id', {
    ...recipeInput,
    expected_latest_version: 2,
    expected_preview_sha256: 'p'.repeat(64),
  })
  await api.getWritingPatternRecipe('recipe/id')
  await api.getWritingPatternRecipeVersion('version/id')
  await api.updateWritingPatternRecipeLifecycle('recipe/id', {
    state: 'archived',
    expected_lifecycle_revision: 3,
  })
  await api.previewWritingPatternRecipeReuse('project/id', 'version/id', {
    expected_recipe_content_sha256: 'r'.repeat(64),
    expected_topic_revision: 7,
  })
  await api.reuseWritingPatternRecipe('project/id', 'version/id', {
    expected_recipe_content_sha256: 'r'.repeat(64),
    expected_topic_revision: 7,
    expected_preview_sha256: 'q'.repeat(64),
  })
  await api.listWritingPatternProfiles('project/id')
  await api.getActiveWritingPatternProfile('project/id')
  await api.getWritingPatternProfile('project/id', 'profile/id')
  await api.updateWritingPatternProfileLifecycle('project/id', 'profile/id', {
    state: 'active',
    expected_lifecycle_revision: 4,
  })

  expect(request).toHaveBeenNthCalledWith(
    1,
    'http://127.0.0.1:8765/api/projects/project%2Fid/writing-pattern-recipes/recipe%2Fid/versions/preview',
    expect.objectContaining({ method: 'POST', body: expect.stringContaining('"expected_latest_version":2') }),
  )
  expect(request).toHaveBeenNthCalledWith(
    5,
    'http://127.0.0.1:8765/api/writing-pattern-recipes/recipe%2Fid/lifecycle',
    expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ state: 'archived', expected_lifecycle_revision: 3 }) }),
  )
  expect(request).toHaveBeenNthCalledWith(
    7,
    'http://127.0.0.1:8765/api/projects/project%2Fid/writing-pattern-recipes/version%2Fid/reuse',
    expect.objectContaining({ method: 'POST', body: expect.stringContaining('"expected_preview_sha256"') }),
  )
  expect(request).toHaveBeenNthCalledWith(
    11,
    'http://127.0.0.1:8765/api/projects/project%2Fid/writing-pattern-profiles/profile%2Fid/lifecycle',
    expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ state: 'active', expected_lifecycle_revision: 4 }) }),
  )
})

it('keeps pattern adaptation preflight, candidates, adoption, and originality on explicit safe routes', async () => {
  vi.mocked(isTauri).mockReturnValue(false)
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8765')
  const request = vi.fn().mockImplementation(async () => (
    new Response(JSON.stringify({ id: 'fixture' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  ))
  vi.stubGlobal('fetch', request)
  const safeInput = {
    profile_version_id: 'profile-version-id-0000000000000000',
    expected_profile_fingerprint_sha256: 'f'.repeat(64),
    expected_topic_revision: 4,
    expected_topic_content_sha256: 't'.repeat(64),
    expected_base_blueprint_revision: null,
    expected_base_blueprint_content_sha256: null,
    author_intent: '把人物关系彻底重构，给出三条真正不同的整书路线。',
    provider_profile_id: null,
  }

  await api.previewPatternAdaptation('project/id', safeInput)
  await api.startPatternAdaptation('project/id', {
    ...safeInput,
    expected_preview_sha256: 'p'.repeat(64),
    confirm_external_processing: true,
    max_estimated_cost_microusd: 12_345,
  })
  await api.getPatternAdaptationResult('project/id', 'job/id')
  await api.editPatternAdaptationCandidate('project/id', 'candidate/id', {
    blueprint: {
      title: '自有新故事', genre: 'urban_rebirth', rebirth_year: 1998,
      rebirth_location: '南平', target_audience: '成长向读者',
      core_selling_points: ['产业升级'], core_desire: '改变家庭命运',
      divergence_point: '接下一张订单', long_term_promise: '建立产业网络',
      ending_direction: '完成共同富裕', protagonist_arc: '学会信任伙伴',
      resource_growth: '订单到产业链', relationship_design: '由对立到合作',
    },
    key_scene_sequence: ['危机', '选择', '代价'],
    transformation_notes: ['人物关系重构'],
    changed_fields: ['relationship_design'],
    expected_revision: 0,
    expected_content_sha256: 'c'.repeat(64),
  })
  await api.adoptPatternAdaptationCandidate('project/id', 'candidate/id', {
    expected_candidate_revision: 1,
    expected_candidate_content_sha256: 'd'.repeat(64),
    expected_profile_fingerprint_sha256: 'f'.repeat(64),
    expected_recipe_content_sha256: 'r'.repeat(64),
    expected_topic_revision: 4,
    expected_topic_content_sha256: 't'.repeat(64),
    expected_base_blueprint_revision: null,
    expected_base_blueprint_content_sha256: null,
    idempotency_key: 'adopt-candidate-idempotency',
  })
  await api.runPatternOriginalityCheck('project/id', {
    expected_blueprint_revision: 0,
    expected_blueprint_content_sha256: 'b'.repeat(64),
    expected_profile_fingerprint_sha256: 'f'.repeat(64),
    expected_recipe_content_sha256: 'r'.repeat(64),
  })
  await api.getPatternOriginalityReport('report/id')
  await api.viewPatternOriginalityReport('report/id')
  await api.acknowledgePatternOriginalityReport('report/id')

  expect(request).toHaveBeenNthCalledWith(
    1,
    'http://127.0.0.1:8765/api/projects/project%2Fid/pattern-adaptations/preview',
    expect.objectContaining({ method: 'POST', body: JSON.stringify(safeInput) }),
  )
  expect(request).toHaveBeenNthCalledWith(
    3,
    'http://127.0.0.1:8765/api/projects/project%2Fid/pattern-adaptation-jobs/job%2Fid/result',
    expect.any(Object),
  )
  expect(request).toHaveBeenNthCalledWith(
    4,
    'http://127.0.0.1:8765/api/projects/project%2Fid/pattern-adaptation-candidates/candidate%2Fid',
    expect.objectContaining({ method: 'PATCH' }),
  )
  expect(request).toHaveBeenNthCalledWith(
    5,
    'http://127.0.0.1:8765/api/projects/project%2Fid/pattern-adaptation-candidates/candidate%2Fid/adopt',
    expect.objectContaining({ method: 'POST' }),
  )
  expect(request).toHaveBeenNthCalledWith(
    6,
    'http://127.0.0.1:8765/api/projects/project%2Fid/pattern-originality-checks',
    expect.objectContaining({ method: 'POST' }),
  )
  expect(request).toHaveBeenNthCalledWith(
    9,
    'http://127.0.0.1:8765/api/pattern-originality-reports/report%2Fid/acknowledgements',
    expect.objectContaining({ method: 'POST' }),
  )
  expect(JSON.stringify(request.mock.calls.map((call) => (call[1] as RequestInit).body))).not.toMatch(
    /observation|evidence|work_title|chapter_label|absolute_start_char|raw_text/,
  )
})

it('loads the persisted project originality gate after refresh', async () => {
  vi.mocked(isTauri).mockReturnValue(false)
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8765')
  const request = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ state: 'needs_check', requires_check: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', request)

  await api.getPatternOriginalityGate('project/id')

  expect(request).toHaveBeenCalledWith(
    'http://127.0.0.1:8765/api/projects/project%2Fid/pattern-originality-gate',
    expect.any(Object),
  )
})
