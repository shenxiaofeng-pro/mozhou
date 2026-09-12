import type {
  BookBlueprintContent,
  CreativePlanImpactPreview,
  DirectorPlanningSnapshot,
  PlanRebaseCandidate,
} from '@mozhou/contracts'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api } from '../api'
import { PlanRebaseWorkbench } from './PlanRebaseWorkbench'

const content: BookBlueprintContent = {
  title: '闽北春潮',
  genre: 'urban_rebirth',
  rebirth_year: 1998,
  rebirth_location: '福建南平',
  target_audience: '现实创业读者',
  core_selling_points: ['产业改命'],
  core_desire: '先保住父亲的工作',
  divergence_point: '提前拿到停产名单',
  long_term_promise: '改变家族与城市产业路线',
  ending_direction: '建立产业联盟',
  protagonist_arc: '从救家到担责',
  resource_growth: '信息差到组织信用',
  relationship_design: '重构父子与商业盟友关系',
}

const impact: CreativePlanImpactPreview = {
  project_id: 'project-1',
  current_dependency: {
    schema_version: 1,
    topic: { id: 'topic-1', revision: 2, content_sha256: 'a'.repeat(64) },
    writing_pattern_profile: { id: 'profile-1', revision: 0, content_sha256: 'b'.repeat(64) },
    writing_pattern_source_availability: 'source_verified',
    base_blueprint: { id: 'blueprint-1', revision: 4, content_sha256: 'c'.repeat(64) },
    subject_sha256: 'd'.repeat(64),
  },
  current_dependency_fingerprint_sha256: 'e'.repeat(64),
  reasons: ['writing_pattern_profile_dependency_changed'],
  affected_blueprint_fields: ['core_desire', 'long_term_promise'],
  locked_blueprint_fields: ['title'],
  targets: [{
    kind: 'book_blueprint', id: 'blueprint-1', revision: 4, locked: false,
    state: 'stale', stale_reasons: ['writing_pattern_profile_dependency_changed'],
  }],
  approved_chapter_count: 8,
  can_rebase: true,
}

const candidate: PlanRebaseCandidate = {
  id: 'candidate-1',
  project_id: 'project-1',
  state: 'candidate',
  revision: 0,
  based_on_dependency_fingerprint_sha256: 'f'.repeat(64),
  target_dependency_fingerprint_sha256: impact.current_dependency_fingerprint_sha256,
  impact,
  book_blueprint: {
    id: 'blueprint-1',
    expected_revision: 4,
    content,
    locks: {
      title: true,
      genre: false,
      rebirth_year: false,
      rebirth_location: false,
      target_audience: false,
      core_selling_points: false,
      core_desire: false,
      divergence_point: false,
      long_term_promise: false,
      ending_direction: false,
      protagonist_arc: false,
      resource_growth: false,
      relationship_design: false,
    },
  },
  volume_plans: [],
  rolling_chapter_plans: [],
  created_at: '2026-09-12T00:00:00Z',
  updated_at: '2026-09-12T00:00:00Z',
  adopted_at: null,
}

const planning: DirectorPlanningSnapshot = {
  book_blueprint: null,
  volume_plans: [],
  rolling_chapter_plans: [],
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('PlanRebaseWorkbench', () => {
  beforeEach(() => {
    vi.spyOn(api, 'getCreativeContextImpact').mockResolvedValue(impact)
    vi.spyOn(api, 'createPlanRebaseCandidate').mockResolvedValue(candidate)
    vi.spyOn(api, 'getPlanRebaseCandidate').mockResolvedValue(candidate)
  })

  it('keeps locked fields, lets the author edit an isolated candidate and adopts explicitly', async () => {
    const user = userEvent.setup()
    const updated: PlanRebaseCandidate = {
      ...candidate,
      revision: 1,
      book_blueprint: {
        ...candidate.book_blueprint!,
        content: { ...content, core_desire: '保住父亲，也争回自己的选择权' },
      },
    }
    const update = vi.spyOn(api, 'updatePlanRebaseCandidate').mockResolvedValue(updated)
    const adopt = vi.spyOn(api, 'adoptPlanRebaseCandidate').mockResolvedValue({
      candidate: { ...updated, state: 'adopted', adopted_at: '2026-09-12T01:00:00Z' },
      planning,
    })
    const onAdopted = vi.fn()

    render(<PlanRebaseWorkbench projectId="project-1" active onAdopted={onAdopted} />)

    expect(await screen.findByRole('heading', { name: '安全更新全书计划' })).toBeVisible()
    expect(screen.getAllByText('启用的写作模式或其可验证状态发生变化')).not.toHaveLength(0)
    expect(screen.queryByText('writing_pattern_profile_dependency_changed')).not.toBeInTheDocument()
    expect(screen.getByText('8 章已定稿正文不会改动')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '生成重基候选' }))

    const title = await screen.findByRole('textbox', { name: /书名/ })
    expect(screen.getByText('逐项核对后再采用').closest('header')).toHaveFocus()
    expect(title).toHaveAttribute('readonly')
    expect(screen.getByText('锁定保留')).toBeVisible()
    const desire = screen.getByRole('textbox', { name: /核心欲望/ })
    await user.clear(desire)
    await user.type(desire, '保住父亲，也争回自己的选择权')
    await user.click(screen.getByRole('button', { name: '保存候选修改' }))

    expect(update).toHaveBeenCalledWith('project-1', 'candidate-1', expect.objectContaining({
      expected_revision: 0,
      book_blueprint_content: expect.objectContaining({ core_desire: '保住父亲，也争回自己的选择权' }),
    }))
    await user.click(screen.getByRole('button', { name: '确认采用重基计划' }))
    expect(adopt).toHaveBeenCalledWith('project-1', 'candidate-1', expect.objectContaining({
      expected_revision: 1,
      expected_dependency_fingerprint_sha256: impact.current_dependency_fingerprint_sha256,
    }))
    expect(onAdopted).toHaveBeenCalledWith(planning)
  })

  it('preserves unsaved author input and refreshes server state after a 409', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'updatePlanRebaseCandidate').mockRejectedValue(
      new ApiError('候选已变化', 409, 'rebase_candidate_changed'),
    )
    render(<PlanRebaseWorkbench projectId="project-1" active onAdopted={vi.fn()} />)

    await user.click(await screen.findByRole('button', { name: '生成重基候选' }))
    const desire = await screen.findByRole('textbox', { name: /核心欲望/ })
    await user.clear(desire)
    await user.type(desire, '这是我不想丢失的修改')
    await user.click(screen.getByRole('button', { name: '保存候选修改' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('你的输入仍在')
    expect(desire).toHaveValue('这是我不想丢失的修改')
    await waitFor(() => {
      expect(api.getCreativeContextImpact).toHaveBeenCalledTimes(2)
      expect(api.getPlanRebaseCandidate).toHaveBeenCalledWith('project-1', 'candidate-1')
    })
  })
})
