import type { SerialDashboard } from '@mozhou/contracts'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api'
import { SerialWorkspaceDialog } from './SerialWorkspaceDialog'

const dashboard: SerialDashboard = {
  project_id: 'project-1',
  goal: {
    project_id: 'project-1',
    goal_date: '2026-08-11',
    target_characters: 6000,
    actual_characters: 3200,
    revision: 1,
    updated_at: '2026-08-11T00:00:00+00:00',
  },
  total_characters: 300_000,
  chapter_count: 100,
  planned_chapters: 5,
  drafted_chapters: 3,
  reviewing_chapters: 2,
  approved_chapters: 90,
  stockpile_chapters: 95,
  pending_review_chapters: 3,
  ready_to_publish_chapters: 90,
}

describe('SerialWorkspaceDialog', () => {
  afterEach(() => vi.restoreAllMocks())

  it('focuses global search and opens a matching chapter', async () => {
    vi.spyOn(api, 'getSerialDashboard').mockResolvedValue(dashboard)
    const search = vi.spyOn(api, 'searchWorkspace').mockResolvedValue([{
      kind: 'chapter',
      id: 'chapter-9',
      title: '第九章 竹海订单',
      snippet: '第一笔竹海订单终于落地。',
      chapter_id: 'chapter-9',
    }])
    const openChapter = vi.fn().mockResolvedValue(undefined)
    const close = vi.fn()
    render(
      <SerialWorkspaceDialog
        projectId="project-1"
        initialMode="search"
        onClose={close}
        onOpenChapter={openChapter}
      />,
    )

    const input = screen.getByLabelText('搜索章节正文、人物、资源与伏笔')
    await waitFor(() => expect(input).toHaveFocus())
    fireEvent.change(input, { target: { value: '竹海订单' } })
    fireEvent.click(screen.getByRole('button', { name: '搜索' }))

    expect(await screen.findByText('第一笔竹海订单终于落地。')).toBeInTheDocument()
    expect(search).toHaveBeenCalledWith('project-1', '竹海订单')
    fireEvent.click(screen.getByRole('button', { name: '打开章节' }))
    await waitFor(() => expect(openChapter).toHaveBeenCalledWith('chapter-9'))
    expect(close).toHaveBeenCalled()
  })
})
