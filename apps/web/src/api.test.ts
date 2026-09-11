import { invoke, isTauri } from '@tauri-apps/api/core'
import { afterEach, expect, it, vi } from 'vitest'

import { aiCredentialStore, api } from './api'

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
