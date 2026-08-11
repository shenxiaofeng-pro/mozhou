import type { AuthorIdea, Chapter, Project } from '@mozhou/contracts'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api'
import { AuthorToolsDialog } from './AuthorToolsDialog'

const project: Project = {
  id: 'project-1', title: '南平新局', genre: 'urban_rebirth', rebirth_year: 1992,
  rebirth_location: '南平', chapter_target_words: 3000, safety_buffer_chapters: 3,
  created_at: '2026-08-11T00:00:00Z', updated_at: '2026-08-11T00:00:00Z',
}
const chapter: Chapter = {
  id: 'chapter-1', project_id: project.id, volume_number: 1, chapter_number: 1, title: '回到九二',
  content: '列车驶入南平站。', reader_promise: '', opening_hook: '', state_change: '', emotional_payoff: '',
  ending_cliffhanger: '', status: 'drafted', revision: 1, updated_at: '2026-08-11T00:00:00Z',
}

function idea(status: AuthorIdea['status'] = 'inbox'): AuthorIdea {
  return {
    id: 'idea-1', project_id: project.id, title: '纸厂首单', content: '先用小额现金试单。', tags: ['资源'],
    status, target_kind: status === 'planned' ? 'chapter_brief' : null, target_id: null, revision: status === 'planned' ? 1 : 0,
    created_at: '2026-08-11T00:00:00Z', updated_at: '2026-08-11T00:00:00Z',
  }
}

describe('AuthorToolsDialog', () => {
  afterEach(() => vi.restoreAllMocks())

  it('keeps a new idea isolated and only marks its intended candidate type', async () => {
    vi.spyOn(api, 'listAuthorIdeas').mockResolvedValue([])
    const create = vi.spyOn(api, 'createAuthorIdea').mockResolvedValue(idea())
    const prepare = vi.spyOn(api, 'prepareAuthorIdea').mockResolvedValue(idea('planned'))

    render(<AuthorToolsDialog project={project} chapter={chapter} initialTab="ideas" selection={null} onClose={vi.fn()} />)
    await screen.findByText('“准备为候选”只标记用途，不会直接改章纲、资料卡或人物账本。')
    fireEvent.change(screen.getByPlaceholderText('一句话标题'), { target: { value: '纸厂首单' } })
    fireEvent.change(screen.getByPlaceholderText('人物、桥段、资料线索……'), { target: { value: '先用小额现金试单。' } })
    fireEvent.change(screen.getByPlaceholderText('标签，用逗号分隔'), { target: { value: '资源，首单' } })
    fireEvent.click(screen.getByRole('button', { name: '收进灵感箱' }))

    await waitFor(() => expect(create).toHaveBeenCalledWith({
      project_id: project.id, title: '纸厂首单', content: '先用小额现金试单。', tags: ['资源', '首单'],
    }))
    fireEvent.click(await screen.findByRole('button', { name: '准备为章纲候选' }))
    await waitFor(() => expect(prepare).toHaveBeenCalledWith('idea-1', 'chapter_brief', 0))
    expect(await screen.findByText('已准备：chapter_brief')).toBeInTheDocument()
  })
})
