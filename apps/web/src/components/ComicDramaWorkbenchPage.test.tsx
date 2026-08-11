import type { ChapterSummary, ComicWorkspace, Project } from '@mozhou/contracts'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api'
import { ComicDramaWorkbenchPage } from './ComicDramaWorkbenchPage'

const project: Project = {
  id: '05f14cb8-d0ed-4489-bc20-31c44c1efbba',
  title: '回到九八年的南平',
  genre: 'urban_rebirth',
  rebirth_year: 1998,
  rebirth_location: '福建南平',
  chapter_target_words: 3000,
  safety_buffer_chapters: 3,
  created_at: '2026-08-11T00:00:00Z',
  updated_at: '2026-08-11T00:00:00Z',
}

const chapter: ChapterSummary = {
  id: '19c7daae-21f2-42f6-9520-daec63e4a726',
  project_id: project.id,
  volume_id: null,
  volume_number: 1,
  chapter_number: 1,
  sort_key: 1024,
  title: '第一章 停产通知',
  reader_promise: '',
  opening_hook: '',
  state_change: '',
  emotional_payoff: '',
  ending_cliffhanger: '',
  status: 'drafted',
  revision: 1,
  updated_at: '2026-08-11T00:00:00Z',
  has_content: true,
  content_characters: 1200,
}

const comicWorkspace: ComicWorkspace = {
  project: {
    id: '3b49d2c4-17b1-4774-8457-31674e9d9de1',
    project_id: project.id,
    title: '旧厂新生·第一季',
    source_chapter_ids: [chapter.id],
    source_snapshot_sha256: 'a'.repeat(64),
    episode_target_count: 8,
    episode_duration_seconds: 90,
    aspect_ratio: '9:16',
    art_style: '写实国漫',
    adaptation_mode: 'balanced',
    narration_preference: '少量旁白',
    author_requirements: '',
    state: 'draft',
    season_revision: 0,
    created_at: '2026-08-11T00:00:00Z',
    updated_at: '2026-08-11T00:00:00Z',
  },
  episodes: [],
  versions: [],
  scenes: [],
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('ComicDramaWorkbenchPage', () => {
  it('creates an isolated comic project from a continuous chapter range', async () => {
    vi.spyOn(api, 'listComicProjects').mockResolvedValue([])
    const create = vi.spyOn(api, 'createComicProject').mockResolvedValue(comicWorkspace)
    vi.spyOn(api, 'getComicAudit').mockResolvedValue([])
    vi.spyOn(api, 'getComicAssets').mockResolvedValue([])
    const user = userEvent.setup()

    render(
      <ComicDramaWorkbenchPage
        project={project}
        chapters={[chapter]}
        onBack={vi.fn()}
        onOpenTaskCenter={vi.fn()}
      />,
    )

    expect(await screen.findByRole('heading', { name: '先圈定一段连续小说剧情' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: '建立漫剧改编季' }))

    await waitFor(() => expect(create).toHaveBeenCalledWith(project.id, expect.objectContaining({
      source_chapter_ids: [chapter.id],
      episode_target_count: 8,
      aspect_ratio: '9:16',
      adaptation_mode: 'balanced',
    })))
    expect(await screen.findByRole('heading', { name: comicWorkspace.project.title })).toBeVisible()
    expect(screen.getByRole('button', { name: '预览季方案范围与费用' })).toBeVisible()
  })
})
