import type { BetaEvaluationReport, Project } from '@mozhou/contracts'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api'
import { BetaEvaluationDialog } from './BetaEvaluationDialog'

const project: Project = {
  id: '05f14cb8-d0ed-4489-bc20-31c44c1efbba',
  title: '闽北新局',
  genre: 'urban_rebirth',
  rebirth_year: 2008,
  rebirth_location: '福建南平',
  chapter_target_words: 3000,
  safety_buffer_chapters: 3,
  created_at: '2026-08-11T00:00:00Z',
  updated_at: '2026-08-11T00:00:00Z',
}

const report: BetaEvaluationReport = {
  format: 'mozhou-closed-beta-report',
  format_version: 2,
  generated_at: '2026-08-11T00:00:00Z',
  project_id: project.id,
  template_ids: ['urban-rebirth', 'reality-anchor'],
  milestones: [
    { key: 'project', label: '建立或导入作品', completed: true, evidence_count: 1 },
    { key: 'ten_chapters', label: '连续完成至少十章正文', completed: false, evidence_count: 3 },
  ],
  metrics: {
    chapter_count: 3,
    written_chapter_count: 3,
    approved_chapter_count: 2,
    ai_candidate_count: 2,
    ai_applied_count: 1,
    ai_adoption_rate: 0.5,
    mean_manual_modification_ratio: 0.25,
    mean_ai_text_retention_rate: 0.75,
    manual_adjustment_type_counts: {
      accepted_as_is: 0,
      light_edit: 1,
      substantial_edit: 0,
      rewrite: 0,
      partial_adoption: 0,
    },
    longest_consecutive_written_chapters: 3,
    ten_chapter_sequence_completed: false,
    review_finding_count: 4,
    review_accepted_count: 3,
    review_acceptance_rate: 0.75,
    median_seconds_to_approved_chapter: 600,
    estimated_cost_microusd: 125000,
    failed_or_interrupted_jobs: 1,
    recovered_retry_jobs: 1,
    retry_recovery_rate: 1,
    open_critical_findings: 0,
    originality_blocked_count: 1,
  },
  subjective_ratings: [
    { category: 'ai_quality', context: 'writing', response_count: 2, mean_rating: 4 },
  ],
  feedback: [],
  privacy_notice: '报告不含作品名、正文、Prompt、文件路径或密钥。',
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('BetaEvaluationDialog', () => {
  it('shows local milestones and saves author feedback without automatic upload', async () => {
    const close = vi.fn()
    const getReport = vi.spyOn(api, 'getBetaReport').mockResolvedValue(report)
    const createFeedback = vi.spyOn(api, 'createBetaFeedback').mockResolvedValue({
      id: 'feedback-1',
      project_id: project.id,
      category: 'usability',
      context: 'writing',
      rating: 5,
      note: '这条流程已经顺畅。',
      created_at: '2026-08-11T00:01:00Z',
    })
    const user = userEvent.setup()

    render(<BetaEvaluationDialog project={project} onClose={close} />)

    expect(await screen.findByRole('heading', { name: `《${project.title}》十章闭环` })).toBeVisible()
    expect(screen.getByText('候选采用率').nextElementSibling).toHaveTextContent('50%')
    expect(screen.getByText('AI 正文保留率').nextElementSibling).toHaveTextContent('75%')
    expect(screen.getByText('最长连续完成').nextElementSibling).toHaveTextContent('3 章')
    expect(screen.getByRole('heading', { name: '作者主观评分' })).toBeVisible()
    expect(screen.getByText('4.0 / 5（2 次）')).toBeVisible()
    await user.selectOptions(screen.getByLabelText('评分'), '5')
    await user.type(screen.getByLabelText('具体反馈（可选）'), '这条流程已经顺畅。')
    await user.click(screen.getByRole('button', { name: '保存反馈' }))

    await waitFor(() => {
      expect(createFeedback).toHaveBeenCalledWith(project.id, {
        category: 'usability',
        context: 'writing',
        rating: 5,
        note: '这条流程已经顺畅。',
      })
    })
    expect(getReport).toHaveBeenCalledTimes(2)
    expect(close).not.toHaveBeenCalled()
  })

  it('exports an explicitly requested redacted report and records only the event', async () => {
    vi.spyOn(api, 'getBetaReport').mockResolvedValue(report)
    const recordEvent = vi.spyOn(api, 'recordBetaEvent').mockResolvedValue(undefined)
    const objectUrl = vi.fn(() => 'blob:beta-report')
    const revokeUrl = vi.fn()
    vi.stubGlobal('URL', { createObjectURL: objectUrl, revokeObjectURL: revokeUrl })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const user = userEvent.setup()

    render(<BetaEvaluationDialog project={project} onClose={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: '导出脱敏封测报告' }))

    expect(objectUrl).toHaveBeenCalledOnce()
    expect(click).toHaveBeenCalledOnce()
    expect(revokeUrl).toHaveBeenCalledWith('blob:beta-report')
    expect(recordEvent).toHaveBeenCalledWith(project.id, 'report_export')
  })
})
