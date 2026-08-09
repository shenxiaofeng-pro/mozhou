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
