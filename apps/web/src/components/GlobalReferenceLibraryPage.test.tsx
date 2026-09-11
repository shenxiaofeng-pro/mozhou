import type {
  CraftPatternAsset,
  CraftPatternAssetSummary,
  ReferenceFilePreview,
  ReferenceWork,
  SourceDocument,
} from '@mozhou/contracts'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
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

const craftAssetSummary: CraftPatternAssetSummary = {
  id: '62c9d281-9194-4e5e-b358-f022d30c479e',
  series_id: '7a60a41d-29d2-4bbb-ae7c-acd307ee6d43',
  asset_type: 'book_evolution',
  version: 2,
  content_sha256: 'e'.repeat(64),
  lifecycle_state: null,
  lifecycle_revision: null,
  source_work_ids: [work.id],
  source_segment_ids: [work.segments[0].id],
  source_asset_version_ids: ['9bd0ea8e-90ed-46f8-9a20-64d599e8b174'],
  title: '旧稿·钩子兑现演变',
  summary: '小胜先兑现核心欲望，再把结果转成下一阶段的更高压力。',
  provider: 'openai',
  model: 'gpt-5.6',
  prompt_version: 'craft-pattern-v2',
  created_at: '2026-09-11T00:00:00Z',
  updated_at: '2026-09-11T00:00:00Z',
}

const craftAsset: CraftPatternAsset = {
  ...craftAssetSummary,
  schema_version: 2,
  source_job_id: null,
  author_focus: '中期兑现节奏',
  craft_items: [{
    dimension: 'promise_payoff_cadence',
    name: '兑现后加码',
    observation: '每次兑现都会引出更高层级的承诺。',
    transferable_rule: '让阶段结果改变下一阶段的行动条件。',
    adaptation_risk: '必须重写事件、人物与场景顺序。',
    evidence: [{
      id: 'be68d64c-3ae7-48fd-bac4-1ac36b52b629',
      work_id: work.id,
      work_title: work.title,
      segment_id: work.segments[0].id,
      stage_label: '第 1 阶段',
      chapter_label: '第 1 章',
      absolute_start_char: 0,
      absolute_end_char: 8,
      evidence_summary: '开局小目标兑现后，立即出现更高层压力。',
      evidence_sha256: 'f'.repeat(64),
      confidence: 0.91,
    }],
  }],
}

beforeEach(() => {
  vi.spyOn(api, 'listReferenceWorks').mockResolvedValue([work])
  vi.spyOn(api, 'listSourceDocuments').mockResolvedValue([])
  vi.spyOn(api, 'listGlobalReferenceCraftAssets').mockResolvedValue({
    items: [],
    total: 0,
    limit: 50,
    offset: 0,
  })
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

  it('explains raw, cache, retained-asset, and running-job impact before purge', async () => {
    vi.spyOn(api, 'getReferenceWorkImpact').mockResolvedValue({
      work,
      projects: [project],
      cache_entries: 7,
      retained_craft_asset_count: 3,
      affected_craft_job_count: 2,
    })
    const purge = vi.spyOn(api, 'purgeReferenceWork')
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()

    render(
      <GlobalReferenceLibraryPage
        projects={[project]}
        activeProjectId={project.id}
        onBack={vi.fn()}
        onProjectAssetsChanged={vi.fn()}
      />,
    )

    await user.click(await screen.findByRole('button', { name: '查看影响并清理' }))
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('原文、区段与 7 项缓存会删除'))
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('3 张抽象模式素材及其证据哈希会保留'))
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('2 个运行中拆解任务会停止或失效'))
    expect(purge).not.toHaveBeenCalled()
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

  it('opens evidence for an unlinked immutable asset before installing it into a project', async () => {
    vi.mocked(api.listGlobalReferenceCraftAssets).mockResolvedValue({
      items: [craftAssetSummary],
      total: 1,
      limit: 50,
      offset: 0,
    })
    const getDetail = vi.spyOn(api, 'getReferenceCraftAsset').mockResolvedValue(craftAsset)
    const reuse = vi.spyOn(api, 'reuseReferenceCraftAsset').mockResolvedValue({
      ...craftAsset,
      lifecycle_state: 'active',
      lifecycle_revision: 0,
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

    expect(await screen.findByRole('heading', { name: craftAsset.title })).toBeVisible()
    expect(screen.getByText('未装入当前作品')).toBeVisible()
    expect(getDetail).not.toHaveBeenCalled()
    await user.click(screen.getByText('查看技法与来源证据'))
    await screen.findByText(craftAsset.craft_items[0].observation)
    await user.click(screen.getByText('查看 1 条来源证据'))
    expect(screen.getByText('开局小目标兑现后，立即出现更高层压力。')).toBeVisible()
    expect(getDetail).toHaveBeenCalledWith(craftAsset.id)

    await user.click(screen.getByRole('button', { name: `装入《${project.title}》` }))
    expect(reuse).toHaveBeenCalledWith(project.id, craftAsset.id)
    expect(changed).toHaveBeenCalledWith(project.id)
    expect(await screen.findByRole('status')).toHaveTextContent('可在拆书库中选择它参与后续融合')
  })

  it('opens an immutable parent card that is outside the current global page', async () => {
    const parentSummary: CraftPatternAssetSummary = {
      ...craftAssetSummary,
      id: craftAssetSummary.source_asset_version_ids[0],
      series_id: 'f8d0f40f-8994-4b24-a5af-3b0e17155131',
      asset_type: 'stage',
      version: 1,
      content_sha256: '1'.repeat(64),
      source_asset_version_ids: [],
      title: '旧稿·第 1 阶段',
      summary: '第一阶段用小目标兑现建立主角行动信用。',
    }
    const parentDetail: CraftPatternAsset = {
      ...craftAsset,
      ...parentSummary,
      schema_version: 2,
      source_job_id: null,
      author_focus: '开局兑现',
    }
    vi.mocked(api.listGlobalReferenceCraftAssets).mockResolvedValue({
      items: [craftAssetSummary],
      total: 51,
      limit: 50,
      offset: 0,
    })
    const getDetail = vi.spyOn(api, 'getReferenceCraftAsset').mockImplementation(async (assetId) => (
      assetId === parentSummary.id ? parentDetail : craftAsset
    ))
    const user = userEvent.setup()

    render(
      <GlobalReferenceLibraryPage
        projects={[project]}
        activeProjectId={project.id}
        onBack={vi.fn()}
        onProjectAssetsChanged={vi.fn()}
      />,
    )

    const childHeading = await screen.findByRole('heading', { name: craftAsset.title })
    const childCard = childHeading.closest('.craft-asset-card')
    expect(childCard).not.toBeNull()
    await user.click(within(childCard as HTMLElement).getByText('查看技法与来源证据'))
    await user.click(await within(childCard as HTMLElement).findByRole('button', {
      name: `查看来源素材 ${parentSummary.id.slice(0, 8)}`,
    }))

    const previewPanel = await screen.findByRole('complementary', { name: '来源素材预览' })
    expect(within(previewPanel).getByRole('heading', { name: parentSummary.title })).toBeVisible()
    expect(within(previewPanel).getByText(parentSummary.summary)).toBeVisible()
    expect(getDetail).toHaveBeenNthCalledWith(1, craftAsset.id)
    expect(getDetail).toHaveBeenNthCalledWith(2, parentSummary.id)
  })
})
