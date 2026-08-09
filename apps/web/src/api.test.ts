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

it('uses the loopback sidecar address returned by Tauri', async () => {
  vi.mocked(isTauri).mockReturnValue(true)
  vi.mocked(invoke).mockResolvedValue('http://127.0.0.1:54321')
  const request = vi.fn().mockResolvedValue(
    new Response(JSON.stringify([]), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', request)

  await api.listProjects()

  expect(invoke).toHaveBeenCalledWith('api_base_url')
  expect(request).toHaveBeenCalledWith('http://127.0.0.1:54321/api/projects', expect.any(Object))
})
