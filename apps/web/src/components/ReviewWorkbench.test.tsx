import type {
  Chapter,
  ChapterVersion,
  Job,
  JobDetail,
  ReviewFinding,
  ReviewJobResult,
  ReviewOutboundPreview,
  TextChangeSet,
} from '@mozhou/contracts'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api'
import { ReviewWorkbench } from './ReviewWorkbench'

const body = '他掏出智能手机，点开微信。院外一片寂静。'

const chapter: Chapter = {
  id: '19c7daae-21f2-42f6-9520-daec63e4a726',
  project_id: '05f14cb8-d0ed-4489-bc20-31c44c1efbba',
  volume_number: 1,
  chapter_number: 3,
  title: '第三章 寻路',
  content: body,
  reader_promise: '主角找到第一条生路',
  opening_hook: '父亲的工牌被收走',
  state_change: '主角决定进入竹木生意',
  emotional_payoff: '父子第一次并肩',
  ending_cliffhanger: '名单上出现另一个熟悉名字',
  status: 'drafted',
  revision: 4,
  updated_at: '2026-08-11T00:00:00Z',
}

function finding(
  id: string,
  excerpt: string,
  replacement: string,
  dimension: ReviewFinding['dimension'] = 'realism',
): ReviewFinding {
  const start = body.indexOf(excerpt)
  return {
    id,
    project_id: chapter.project_id,
    chapter_id: chapter.id,
    chapter_revision: chapter.revision,
    review_job_id: 'review-job',
    dimension,
    severity: 'critical',
    code: `test_${id}`,
    title: '正文与 1998 年现实条件冲突',
    evidence: [{
      kind: 'body',
      chapter_id: chapter.id,
      start_char: start,
      end_char: start + excerpt.length,
      excerpt,
      source_type: null,
      source_id: null,
      label: '本章正文原句',
    }],
    explanation: '该物件在故事年代尚未普及。',
    suggestion: '改为当时可用的通信方式。',
    suggested_replacement: replacement,
    confidence: 0.96,
    dedupe_key: `dedupe-${id}`,
    state: 'open',
    created_at: '2026-08-11T00:00:00Z',
  }
}

const phoneFinding = finding('finding-phone', '智能手机', '传呼机')
const silenceFinding = finding('finding-silence', '一片寂静', '只剩虫鸣', 'style')

function version(overrides: Partial<ChapterVersion> = {}): ChapterVersion {
  return {
    id: 'version-current',
    chapter_id: chapter.id,
    version_number: 3,
    chapter_revision: chapter.revision,
    content: body,
    content_sha256: 'current-sha',
    source: 'manual_save',
    source_id: null,
    parent_version_id: 'version-old',
    is_candidate: false,
    created_at: '2026-08-11T00:00:00Z',
    ...overrides,
  }
}

function changeSet(): TextChangeSet {
  return {
    id: 'change-set',
    chapter_id: chapter.id,
    base_chapter_revision: chapter.revision,
    base_content_sha256: 'current-sha',
    title: '审校局部修改',
    state: 'candidate',
    revision: 0,
    changes: [
      {
        id: 'change-phone',
        change_set_id: 'change-set',
        ordinal: 1,
        start_char: body.indexOf('智能手机'),
        end_char: body.indexOf('智能手机') + '智能手机'.length,
        original_text: '智能手机',
        replacement_text: '传呼机',
        rationale: '符合 1998 年通信条件',
        review_finding_id: phoneFinding.id,
        selected: null,
        applied_replacement: null,
      },
      {
        id: 'change-silence',
        change_set_id: 'change-set',
        ordinal: 2,
        start_char: body.indexOf('一片寂静'),
        end_char: body.indexOf('一片寂静') + '一片寂静'.length,
        original_text: '一片寂静',
        replacement_text: '只剩虫鸣',
        rationale: '增加可感知细节',
        review_finding_id: silenceFinding.id,
        selected: null,
        applied_replacement: null,
      },
    ],
    created_at: '2026-08-11T00:00:00Z',
    updated_at: '2026-08-11T00:00:00Z',
  }
}

function reviewJob(state: Job['state'] = 'queued'): JobDetail {
  return {
    id: 'review-job',
    project_id: chapter.project_id,
    chapter_id: chapter.id,
    parent_job_id: null,
    kind: 'review',
    workflow: 'chapter_review',
    state,
    idempotency_key: 'review-key',
    progress_current: state === 'succeeded' ? 7 : 0,
    progress_total: 7,
    current_step: '',
    estimated_calls: 5,
    completed_calls: state === 'succeeded' ? 4 : 0,
    provider: 'openai_compatible',
    provider_profile_id: null,
    model: 'review-test',
    lease_owner: null,
    lease_expires_at: null,
    heartbeat_at: null,
    error_code: null,
    error_message: null,
    created_at: '2026-08-11T00:00:00Z',
    updated_at: '2026-08-11T00:00:00Z',
    started_at: null,
    completed_at: state === 'succeeded' ? '2026-08-11T00:00:01Z' : null,
    chunks: [],
    attempts: [],
    artifacts: [],
    events: [],
  }
}

function preview(): ReviewOutboundPreview {
  return {
    profile_id: null,
    profile_name: '审校测试线路',
    provider: 'openai_compatible',
    model: 'review-test',
    dimensions: ['continuity', 'serial_rhythm', 'character', 'realism', 'rebirth_logic', 'style', 'format'],
    local_dimensions: ['continuity', 'serial_rhythm'],
    external_dimensions: ['character', 'realism', 'rebirth_logic', 'style', 'format'],
    data_types: ['本章正文', '近三章正文', '正式事实'],
    content_scope: '本章与最近 3 章的冻结审校上下文',
    character_count: 3200,
    estimated_input_tokens: 1800,
    estimated_output_tokens: 3000,
    estimated_calls: 5,
    estimated_cost_microusd: 42_000,
    context_sha256: 'context-sha',
  }
}

function result(): ReviewJobResult {
  return {
    job_id: 'review-job',
    project_id: chapter.project_id,
    chapter_id: chapter.id,
    chapter_revision: chapter.revision,
    window_size: 3,
    outcomes: [
      { dimension: 'continuity', state: 'succeeded', finding_count: 0, error_code: null, error_message: null },
      { dimension: 'realism', state: 'failed', finding_count: 0, error_code: 'provider_unavailable', error_message: '模型服务暂时不可用' },
      { dimension: 'style', state: 'succeeded', finding_count: 1, error_code: null, error_message: null },
    ],
    findings: [silenceFinding],
  }
}

function mockEmptyHistory() {
  vi.spyOn(api, 'listReviewFindings').mockResolvedValue([])
  vi.spyOn(api, 'listChapterVersions').mockResolvedValue([version()])
  vi.spyOn(api, 'listTextChangeSets').mockResolvedValue([])
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('ReviewWorkbench', () => {
  it('requires an outbound preview, retains successful dimensions and prepares a failed dimension rerun', async () => {
    mockEmptyHistory()
    vi.spyOn(api, 'previewChapterReview').mockResolvedValue(preview())
    const start = vi.spyOn(api, 'startChapterReviewJob').mockResolvedValue(reviewJob())
    vi.spyOn(api, 'getJob').mockResolvedValue(reviewJob('succeeded'))
    vi.spyOn(api, 'getChapterReviewJobResult').mockResolvedValue(result())
    vi.spyOn(api, 'listReviewFindings').mockResolvedValueOnce([]).mockResolvedValue([silenceFinding])
    const user = userEvent.setup()

    render(<ReviewWorkbench chapter={chapter} canReview onChapterUpdated={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: /七维审校/ }))
    await user.click(screen.getByRole('button', { name: '查看审校范围与费用' }))

    expect(start).not.toHaveBeenCalled()
    expect(await screen.findByText('本章与最近 3 章的冻结审校上下文')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '确认范围并开始审校' }))
    expect(start).toHaveBeenCalledWith(chapter.id, expect.objectContaining({
      confirm_external_processing: true,
      max_estimated_cost_microusd: 42_000,
      dimensions: preview().dimensions,
    }))

    expect(await screen.findByText('正文与 1998 年现实条件冲突')).toBeVisible()
    expect(screen.getByText('一片寂静')).toBeVisible()
    expect(screen.getByText('0 项')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '准备单独重跑' }))
    await user.click(screen.getByRole('button', { name: '查看审校范围与费用' }))
    expect(api.previewChapterReview).toHaveBeenLastCalledWith(chapter.id, expect.objectContaining({
      dimensions: ['realism'],
      parent_job_id: 'review-job',
    }))
  })

  it('applies only selected changes and preserves the author-edited replacement', async () => {
    vi.spyOn(api, 'listReviewFindings').mockResolvedValue([phoneFinding, silenceFinding])
    vi.spyOn(api, 'listChapterVersions').mockResolvedValue([version()])
    vi.spyOn(api, 'listTextChangeSets').mockResolvedValue([])
    const created = changeSet()
    vi.spyOn(api, 'createTextChangeSet').mockResolvedValue(created)
    const apply = vi.spyOn(api, 'applyTextChangeSet').mockResolvedValue({
      ...chapter,
      content: body.replace('智能手机', '传呼机和公用电话'),
      revision: chapter.revision + 1,
    })
    const updated = vi.fn()
    const user = userEvent.setup()

    render(<ReviewWorkbench chapter={chapter} canReview onChapterUpdated={updated} />)
    await user.click(screen.getByRole('button', { name: /七维审校/ }))
    const findingSelectors = await screen.findAllByLabelText('加入局部变更集')
    await user.click(findingSelectors[0])
    await user.click(findingSelectors[1])
    await user.click(screen.getByRole('button', { name: '生成局部变更集' }))

    await user.click(screen.getByLabelText('采用第 2 处修改'))
    const replacement = screen.getByLabelText('第 1 处替换文本')
    await user.clear(replacement)
    await user.type(replacement, '传呼机和公用电话')
    await user.click(screen.getByRole('button', { name: '应用所选并创建新版本' }))

    expect(apply).toHaveBeenCalledWith(created.id, {
      selected_change_ids: ['change-phone'],
      edited_replacements: { 'change-phone': '传呼机和公用电话' },
      expected_set_revision: 0,
      expected_chapter_revision: chapter.revision,
    })
    expect(updated).toHaveBeenCalledWith(expect.objectContaining({ revision: chapter.revision + 1 }))
  })

  it('requires a second click to roll back and creates a new chapter revision', async () => {
    const oldVersion = version({
      id: 'version-old',
      version_number: 2,
      chapter_revision: 3,
      content: '旧稿正文',
      content_sha256: 'old-sha',
      parent_version_id: null,
    })
    vi.spyOn(api, 'listReviewFindings').mockResolvedValue([])
    vi.spyOn(api, 'listChapterVersions').mockResolvedValue([version(), oldVersion])
    vi.spyOn(api, 'listTextChangeSets').mockResolvedValue([])
    const rollback = vi.spyOn(api, 'rollbackChapterVersion').mockResolvedValue({
      ...chapter,
      content: oldVersion.content,
      revision: chapter.revision + 1,
    })
    const updated = vi.fn()
    const user = userEvent.setup()

    render(<ReviewWorkbench chapter={chapter} canReview onChapterUpdated={updated} />)
    await user.click(screen.getByRole('button', { name: /七维审校/ }))
    const firstStep = await screen.findByRole('button', { name: '回滚到此版本' })
    await user.click(firstStep)
    expect(rollback).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: '确认回滚为新版本' }))

    expect(rollback).toHaveBeenCalledWith(chapter.id, oldVersion.id, {
      expected_revision: chapter.revision,
    })
    expect(updated).toHaveBeenCalledWith(expect.objectContaining({
      content: oldVersion.content,
      revision: chapter.revision + 1,
    }))
  })
})
