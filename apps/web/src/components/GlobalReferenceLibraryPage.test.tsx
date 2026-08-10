import type { ReferenceFilePreview, ReferenceWork, SourceDocument } from '@mozhou/contracts'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api'
import { GlobalReferenceLibraryPage } from './GlobalReferenceLibraryPage'

const project = {
  id: '05f14cb8-d0ed-4489-bc20-31c44c1efbba',
  title: '回到九八年的南平',
  genre: 'urban_rebirth' as const,
  rebirth_year: 1998,
  rebirth_location: '福建南平',
  chapter_target_words: 3000,
  safety_buffer_chapters: 3,
  created_at: '2026-08-08T00:00:00Z',
  updated_at: '2026-08-08T00:00:00Z',
}

const work: ReferenceWork = {
  id: 'd74f1a42-b881-4ffd-ab4c-13eeb0ef21d9',
  project_id: null,
  project_ids: [],
  title: '自有旧稿',
  source_filename: '旧稿.txt',
  source_format: 'txt',
  rights_basis: 'self_owned',
  total_characters: 8,
  segment_target_characters: 500_000,
  content_sha256: 'a'.repeat(64),
  source_sha256: 'b'.repeat(64),
  source_encoding: 'utf-8',
  encoding_confidence: 1,
  import_state: 'ready',
  duplicate_of_id: null,
  source_spans: [],
  segments: [{
    id: '7e4dbbc5-af7d-40a5-a8ee-69322bc8b667',
    reference_work_id: 'd74f1a42-b881-4ffd-ab4c-13eeb0ef21d9',
    ordinal: 0,
    start_char: 0,
    end_char: 8,
    character_count: 8,
    chapter_start: '第一章',
    chapter_end: '第一章',
    created_at: '2026-08-08T00:00:00Z',
  }],
  created_at: '2026-08-08T00:00:00Z',
  updated_at: '2026-08-08T00:00:00Z',
}

const preview: ReferenceFilePreview = {
  source_filename: '旧稿.txt',
  source_format: 'txt',
  source_encoding: 'utf-8',
  encoding_confidence: 1,
  import_state: 'ready',
  source_sha256: 'b'.repeat(64),
  content_sha256: 'a'.repeat(64),
  total_characters: 8,
  page_count: 0,
  preview: '第一章\n旧城醒来。',
  warnings: [],
  source_spans: [],
}

beforeEach(() => {
  vi.spyOn(api, 'listReferenceWorks').mockResolvedValue([work])
  vi.spyOn(api, 'listSourceDocuments').mockResolvedValue([])
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('GlobalReferenceLibraryPage', () => {
  it('previews a local file before importing it into the global reference library', async () => {
    const previewFile = vi.spyOn(api, 'previewReferenceFile').mockResolvedValue(preview)
    const importFile = vi.spyOn(api, 'importReferenceFile').mockResolvedValue(work)
    const user = userEvent.setup()

    render(
      <GlobalReferenceLibraryPage
        projects={[project]}
        activeProjectId={project.id}
        onBack={vi.fn()}
        onProjectAssetsChanged={vi.fn()}
      />,
    )

    const file = new File(['第一章\n旧城醒来。'], '旧稿.txt', { type: 'text/plain' })
    await user.upload(await screen.findByLabelText('全局资料文件'), file)
    await user.click(screen.getByRole('button', { name: '检测编码与安全内容' }))

    expect(await screen.findByText(/来源护照 · utf-8/)).toBeVisible()
    expect(screen.getByText((_, element) => (
      element?.tagName === 'PRE' && element.textContent === '第一章\n旧城醒来。'
    ))).toBeVisible()
    await user.click(screen.getByRole('button', { name: '收入全局拆书库' }))

    expect(previewFile).toHaveBeenCalledWith(file)
    expect(importFile).toHaveBeenCalledWith(file, expect.objectContaining({
      title: '旧稿',
      expected_source_sha256: preview.source_sha256,
      confirm_preview: true,
    }))
    expect(await screen.findByRole('status')).toHaveTextContent('已进入全局拆书库')
    expect(screen.getByLabelText('全局资料文件')).toHaveValue('')
  })

  it('links and unlinks one global reference work without deleting its raw asset', async () => {
    const linkedWork = { ...work, project_id: project.id, project_ids: [project.id] }
    const link = vi.spyOn(api, 'linkReferenceWork').mockResolvedValue(linkedWork)
    const unlink = vi.spyOn(api, 'unlinkReferenceWork').mockResolvedValue(undefined)
    vi.mocked(api.listReferenceWorks)
      .mockResolvedValueOnce([work])
      .mockResolvedValueOnce([linkedWork])
      .mockResolvedValueOnce([work])
    const changed = vi.fn()
    const user = userEvent.setup()

    render(
      <GlobalReferenceLibraryPage
        projects={[project]}
        activeProjectId={project.id}
        onBack={vi.fn()}
        onProjectAssetsChanged={changed}
      />,
    )

    await user.click(await screen.findByRole('button', { name: '装入目标作品' }))
    await waitFor(() => expect(link).toHaveBeenCalledWith(project.id, work.id))
    expect(await screen.findByRole('button', { name: '从目标作品卸下' })).toBeVisible()

    await user.click(screen.getByRole('button', { name: '从目标作品卸下' }))
    await waitFor(() => expect(unlink).toHaveBeenCalledWith(project.id, work.id))
    expect(await screen.findByText('尚未装入作品')).toBeVisible()
    expect(changed).toHaveBeenCalledTimes(2)
  })

  it('shows global reality documents with their source passport', async () => {
    const document: SourceDocument = {
      id: '749992ad-2318-4f12-96b1-fba79adc0967',
      title: '九八年南平物价资料',
      source_filename: '物价.pdf',
      source_format: 'pdf',
      source_sha256: 'c'.repeat(64),
      content_sha256: 'd'.repeat(64),
      source_encoding: 'pdf-text',
      encoding_confidence: 1,
      import_state: 'ready',
      duplicate_of_id: null,
      source_spans: [{ page_number: 1, start_char: 0, end_char: 120 }],
      total_characters: 120,
      created_at: '2026-08-08T00:00:00Z',
      updated_at: '2026-08-08T00:00:00Z',
    }
    vi.mocked(api.listSourceDocuments).mockResolvedValue([document])
    const apply = vi.spyOn(api, 'applySourceDocument').mockResolvedValue({
      id: 'f772595c-9032-4838-9784-f5fa229ea66d',
      project_id: project.id,
      source_kind: 'historical_record',
      title: document.title,
      source_reference: '作者本地资料',
      applicable_year_start: 1998,
      applicable_year_end: 1998,
      confidence: 'medium',
      excerpt: '早市物价记录',
      source_document_id: document.id,
      source_date: null,
      page_number_start: 1,
      page_number_end: 1,
      start_char: 0,
      end_char: 6,
      confirmed: false,
      revision: 0,
      created_at: '2026-08-08T00:00:00Z',
      updated_at: '2026-08-08T00:00:00Z',
    })
    const changed = vi.fn()
    const user = userEvent.setup()

    render(
      <GlobalReferenceLibraryPage
        projects={[project]}
        activeProjectId={project.id}
        onBack={vi.fn()}
        onProjectAssetsChanged={changed}
      />,
    )

    expect(await screen.findByRole('heading', { name: document.title })).toBeVisible()
    expect(screen.getByText(/1 个页码来源/)).toBeVisible()
    expect(screen.getByText(document.content_sha256.slice(0, 12))).toBeVisible()
    await user.click(screen.getByRole('button', { name: '为目标作品生成候选卡' }))
    expect(apply).toHaveBeenCalledWith(project.id, document.id, expect.objectContaining({
      title: document.title,
      applicable_year_start: 1998,
      applicable_year_end: 1998,
    }), undefined)
    expect(changed).toHaveBeenCalledWith(project.id)
  })
})
