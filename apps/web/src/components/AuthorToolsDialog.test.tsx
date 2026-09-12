import type { AuthorIdea, Chapter, Project, WritingCalendar } from '@mozhou/contracts'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
  afterEach(() => { cleanup(); vi.restoreAllMocks() })

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

  it('keeps the latest seven days prominent and compresses the previous 35 days', async () => {
    const days: WritingCalendar['days'] = Array.from({ length: 42 }, (_, index) => {
      const date = new Date(Date.UTC(2026, 6, index + 1)).toISOString().slice(0, 10)
      const netCharacters = index === 10 ? -280 : index === 41 ? 1200 : index % 5 === 0 ? 800 : 0
      return { date, net_characters: netCharacters, target_characters: 1000, met_goal: netCharacters >= 1000 }
    })
    vi.spyOn(api, 'getWritingCalendar').mockResolvedValue({
      project_id: project.id,
      timezone: 'Asia/Shanghai',
      days,
      total_net_characters: 5_720,
      streak_days: 3,
    })

    const onClose = vi.fn()
    const onAdjustGoal = vi.fn()
    render(<AuthorToolsDialog project={project} chapter={chapter} initialTab="calendar" selection={null} onClose={onClose} onAdjustGoal={onAdjustGoal} />)

    expect(await screen.findByRole('heading', { name: '码字节奏' })).toBeInTheDocument()
    const today = screen.getByText('今日字数变化').parentElement!
    expect(within(today).getByText('+1,200')).toBeInTheDocument()
    expect(screen.getByText('达标天数')).toBeInTheDocument()
    expect(screen.getByText('近42天变化')).toBeInTheDocument()
    const currentWeek = screen.getByRole('region', { name: '近 7 天' })
    const history = screen.getByRole('region', { name: '过去 35 天' })
    expect(within(currentWeek).getAllByRole('listitem')).toHaveLength(7)
    expect(within(history).getAllByRole('listitem')).toHaveLength(35)
    expect(within(currentWeek).getByText('今天')).toBeInTheDocument()
    expect(screen.getByRole('listitem', { name: /7月11日 以修改为主/ })).toHaveAttribute('data-negative', 'true')
    expect(screen.getByRole('listitem', { name: /8月11日 已达目标/ })).toHaveAttribute('data-today', 'true')
    fireEvent.click(screen.getByRole('button', { name: '回到正文写作' }))
    expect(onClose).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByRole('button', { name: '调整日目标' }))
    expect(onAdjustGoal).toHaveBeenCalledOnce()
  })

  it('moves focus into the dialog, closes with Escape, and restores focus', async () => {
    vi.spyOn(api, 'listAuthorIdeas').mockResolvedValue([])
    const trigger = document.createElement('button')
    trigger.textContent = '打开作者工具'
    document.body.append(trigger)
    trigger.focus()
    const onClose = vi.fn()

    const { unmount } = render(<AuthorToolsDialog project={project} chapter={chapter} initialTab="ideas" selection={null} onClose={onClose} />)
    const close = await screen.findByRole('button', { name: '关闭' })
    await waitFor(() => expect(close).toHaveFocus())
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
    unmount()
    expect(trigger).toHaveFocus()
    trigger.remove()
  })

  it('exposes tabs and loading state while a tool is being read', async () => {
    let finishLoading!: (ideas: AuthorIdea[]) => void
    vi.spyOn(api, 'listAuthorIdeas').mockReturnValue(new Promise((resolve) => { finishLoading = resolve }))

    render(<AuthorToolsDialog project={project} chapter={chapter} initialTab="ideas" selection={null} onClose={vi.fn()} />)

    expect(screen.getByRole('tablist', { name: '作者工具分类' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '灵感箱' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel', { name: '灵感箱' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('正在读取灵感箱…')
    finishLoading([])
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
  })
})
