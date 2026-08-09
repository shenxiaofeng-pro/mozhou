import { invoke, isTauri } from '@tauri-apps/api/core'
import { afterEach, expect, it, vi } from 'vitest'

import { api } from './api'

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
