import type { ManuscriptImportPreview, Workspace } from '@mozhou/contracts'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api'
import { ManuscriptImportDialog } from './ManuscriptImportDialog'

const preview: ManuscriptImportPreview = {
  source_filename: '旧稿.txt',
  source_format: 'txt',
  source_sha256: 'a'.repeat(64),
  source_encoding: 'gb18030',
  encoding_confidence: 0.92,
  inferred_project_title: '旧城再起',
  volumes: [{
    client_id: 'volume-1',
    title: '第一卷',
    chapters: [{
      client_id: 'chapter-1',
      title: '醒来',
      content: '一九九二年的雨。',
      heading_confidence: 0.88,
      warnings: [],
    }],
  }],
  unrecognized_text: '作者按：旧稿整理。',
  warnings: ['encoding_confirmation_required'],
  total_characters: 18,
  chapter_count: 1,
}

describe('ManuscriptImportDialog', () => {
  afterEach(() => vi.restoreAllMocks())

  it('keeps preview local, lets the author correct the tree, then writes once on confirmation', async () => {
    vi.spyOn(api, 'previewManuscript').mockResolvedValue(preview)
    const restored = { project: { title: '南平新局' } } as Workspace
    const confirm = vi.spyOn(api, 'confirmManuscriptImport').mockResolvedValue(restored)
    const imported = vi.fn()

    render(<ManuscriptImportDialog onClose={vi.fn()} onImported={imported} />)
    const file = new File(['旧稿'], '旧稿.txt', { type: 'text/plain' })
    fireEvent.change(screen.getByLabelText('选择 TXT、Markdown、DOCX 或 EPUB 稿件'), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: '识别卷章结构' }))

    expect(await screen.findByDisplayValue('旧城再起')).toBeInTheDocument()
    expect(confirm).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '确认并创建作品' })).toBeDisabled()

    fireEvent.change(screen.getByDisplayValue('旧城再起'), { target: { value: '南平新局' } })
    fireEvent.change(screen.getByLabelText('第 1 卷标题'), { target: { value: '闽北风云' } })
    fireEvent.change(screen.getByLabelText('第 1 卷第 1 章标题'), { target: { value: '回到九二' } })
    fireEvent.click(screen.getByLabelText('我已检查目录与正文预览'))
    fireEvent.click(screen.getByRole('button', { name: '确认并创建作品' }))

    await waitFor(() => expect(confirm).toHaveBeenCalledWith(expect.objectContaining({
      title: '南平新局',
      unrecognized_action: 'prepend_first_chapter',
      confirm_warnings: true,
      volumes: [expect.objectContaining({
        title: '闽北风云',
        chapters: [expect.objectContaining({ title: '回到九二' })],
      })],
    })))
    expect(imported).toHaveBeenCalledWith(restored)
  })
})
