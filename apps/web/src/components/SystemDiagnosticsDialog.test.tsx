import type { DiagnosticSummary } from '@mozhou/contracts'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api'
import { SystemDiagnosticsDialog } from './SystemDiagnosticsDialog'

const summary: DiagnosticSummary = {
  generated_at: '2026-08-11T00:00:00+00:00',
  app_version: '0.1.0',
  schema_version: 15,
  operating_system: 'Darwin',
  architecture: 'arm64',
  python_version: '3.14.5',
  database_bytes: 4 * 1024 * 1024,
  free_disk_bytes: 32 * 1024 * 1024 * 1024,
  counts: { projects: 2, chapters: 100, jobs: 9 },
  checks: [
    { key: 'database_integrity', status: 'ok', message: '数据库完整性检查通过' },
    { key: 'free_disk', status: 'ok', message: '可用磁盘空间充足' },
    { key: 'schema_compatibility', status: 'ok', message: '数据库结构版本与应用一致' },
  ],
}

describe('SystemDiagnosticsDialog', () => {
  afterEach(() => vi.restoreAllMocks())

  it('shows read-only health checks and closes with Escape', async () => {
    vi.spyOn(api, 'getDiagnostics').mockResolvedValue(summary)
    const close = vi.fn()
    render(<SystemDiagnosticsDialog onClose={close} />)

    expect(await screen.findByText('数据库完整性检查通过')).toBeInTheDocument()
    expect(screen.getByText('100')).toBeInTheDocument()
    expect(screen.getByText('32.0 GiB')).toBeInTheDocument()
    expect(screen.getByText(/不含书名、正文、资料原文/)).toBeInTheDocument()

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(close).toHaveBeenCalledTimes(1)
  })
})
