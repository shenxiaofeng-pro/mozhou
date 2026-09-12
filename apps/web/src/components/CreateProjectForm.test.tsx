import type { BetaTemplate, Workspace } from '@mozhou/contracts'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api'
import { CreateProjectForm } from './CreateProjectForm'

const template: BetaTemplate = {
  id: 'historical-rebirth',
  label: '历史重生 · 山河改写',
  genre: 'historical_rebirth',
  suggested_title: '烽火归途',
  rebirth_year: 1937,
  rebirth_location: '福建南平',
  idea_prompt: '一个熟知后世转折的人回到危局前夜。',
  reality_anchor: '地方地理、交通、组织能力和制度必须有来源。',
  first_ten_chapter_goal: '建立生存压力并兑现一次小胜。',
}

const fantasyTemplate: BetaTemplate = {
  id: 'eastern-fantasy',
  label: '东方玄幻 · 万山问道',
  genre: 'eastern_fantasy',
  suggested_title: '万山问道',
  rebirth_year: 728,
  rebirth_location: '九州·云泽',
  idea_prompt: '力量会吞噬记忆。',
  reality_anchor: '境界、资源和力量代价必须一致。',
  first_ten_chapter_goal: '建立代价规则并完成第一次受限突破。',
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('CreateProjectForm closed beta templates', () => {
  it('prefills an editable project anchor and submits the selected genre', async () => {
    vi.spyOn(api, 'listBetaTemplates').mockResolvedValue([template])
    const created = { project: { id: 'project-1' } } as Workspace
    const createProject = vi.spyOn(api, 'createProject').mockResolvedValue(created)
    const onCreated = vi.fn()
    const user = userEvent.setup()

    render(<CreateProjectForm onCreated={onCreated} />)
    await user.click(await screen.findByRole('button', { name: /历史重生 · 山河改写/ }))

    expect(screen.getByLabelText('作品名')).toHaveValue('烽火归途')
    expect(screen.getByLabelText('重生年份')).toHaveValue(1937)
    expect(screen.getByLabelText('重生地点')).toHaveValue('福建南平')
    expect(screen.getByLabelText('一句话选题（可稍后完善）')).toHaveValue(template.idea_prompt)
    expect(screen.getByText('建立生存压力并兑现一次小胜。')).toBeVisible()
    await user.clear(screen.getByLabelText('作品名'))
    await user.type(screen.getByLabelText('作品名'), '南平烽火')
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    expect(createProject).toHaveBeenCalledWith({
      title: '南平烽火',
      genre: 'historical_rebirth',
      rebirth_year: 1937,
      rebirth_location: '福建南平',
      chapter_target_words: 3000,
      safety_buffer_chapters: 3,
      template_id: template.id,
      topic_seed: template.idea_prompt,
    })
    expect(onCreated).toHaveBeenCalledWith(created)
  })

  it('uses story anchor language and fantasy defaults for non-rebirth genres', async () => {
    vi.spyOn(api, 'listBetaTemplates').mockResolvedValue([template, fantasyTemplate])
    const created = { project: { id: 'fantasy-project' } } as Workspace
    const createProject = vi.spyOn(api, 'createProject').mockResolvedValue(created)
    const user = userEvent.setup()

    render(<CreateProjectForm onCreated={vi.fn()} />)
    await screen.findByRole('button', { name: /东方玄幻 · 万山问道/ })
    await user.click(screen.getByRole('radio', { name: '东方玄幻' }))

    expect(screen.getByLabelText('故事纪年')).toHaveValue(728)
    expect(screen.getByLabelText('起始地域')).toHaveValue('九州·云泽')
    expect(screen.queryByText('重生年份')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('作品名'), '云泽问道')
    await user.click(screen.getByRole('button', { name: '创建作品并进入工作台' }))

    expect(createProject).toHaveBeenCalledWith(expect.objectContaining({
      title: '云泽问道',
      genre: 'eastern_fantasy',
      rebirth_year: 728,
      rebirth_location: '九州·云泽',
      template_id: null,
      topic_seed: '',
    }))
  })
})
