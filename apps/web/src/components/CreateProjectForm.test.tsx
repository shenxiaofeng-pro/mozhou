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
    })
    expect(onCreated).toHaveBeenCalledWith(created)
  })
})
