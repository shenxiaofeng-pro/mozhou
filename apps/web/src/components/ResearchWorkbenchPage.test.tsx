import type { Job, Project, ResearchPreview, ResearchSession } from '@mozhou/contracts'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api'
import { ResearchWorkbenchPage } from './ResearchWorkbenchPage'

const project: Project = {
  id: 'project-1', title: '南平新局', genre: 'urban_rebirth', rebirth_year: 1992,
  rebirth_location: '南平', chapter_target_words: 3000, safety_buffer_chapters: 3,
  created_at: '2026-08-11T00:00:00Z', updated_at: '2026-08-11T00:00:00Z',
}

const preview: ResearchPreview = {
  source_set_sha256: 'a'.repeat(64),
  sources: [{ source_document_id: null, label: '临时粘贴资料', source_format: 'paste', character_count: 18, content_sha256: 'b'.repeat(64) }],
  character_count: 18, estimated_calls: 1, estimated_input_tokens: 20, estimated_output_tokens: 100,
  estimated_cost_microusd: null, profile_id: null, profile_name: '本地规则', provider: 'local', model: 'research-rules-v1',
  requires_external_confirmation: false, data_types: ['研究问题', '来源原文'], content_scope: '1 份来源，共 18 字符',
}

const session: ResearchSession = {
  id: 'session-1', project_id: project.id, title: '纸价研究', question: '1992 年纸价如何？',
  era_start: 1992, era_end: 1992, region: '南平', material_type: '行业资料', mode: 'local',
  state: 'ready', source_set_sha256: preview.source_set_sha256, job_id: null, invalid_ai_findings: 0,
  finding_count: 0, candidate_count: 0, created_at: '2026-08-11T00:00:00Z', updated_at: '2026-08-11T00:00:00Z',
}

describe('ResearchWorkbenchPage', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks() })

  it('previews a frozen local source set before creating an isolated research task', async () => {
    vi.spyOn(api, 'listSourceDocuments').mockResolvedValue([])
    vi.spyOn(api, 'listResearchSessions').mockResolvedValue([])
    const inspect = vi.spyOn(api, 'previewResearch').mockResolvedValue(preview)
    const submit = vi.spyOn(api, 'submitResearch').mockResolvedValue({ session, job: {} as Job })

    render(<ResearchWorkbenchPage project={project} onBack={vi.fn()} onSourceCardsChanged={vi.fn()} />)
    await screen.findByText('尚无研究任务')
    fireEvent.change(screen.getByLabelText('研究问题'), { target: { value: '1992 年纸价如何？' } })
    fireEvent.change(screen.getByLabelText('或粘贴本地资料（最多 20 万字）'), { target: { value: '1992 年纸张每令约 18 元。' } })
    fireEvent.click(screen.getByRole('button', { name: '预览范围与费用' }))

    await screen.findByText('1 份来源，共 18 字符')
    expect(inspect).toHaveBeenCalledWith(project.id, expect.objectContaining({
      question: '1992 年纸价如何？', mode: 'local', pasted_text: '1992 年纸张每令约 18 元。',
    }))
    fireEvent.click(screen.getByRole('button', { name: '创建可恢复研究任务' }))

    await waitFor(() => expect(submit).toHaveBeenCalledWith(project.id, expect.objectContaining({
      expected_source_set_sha256: preview.source_set_sha256,
      confirm_external_processing: true,
    })))
    expect((await screen.findAllByText('纸价研究')).length).toBe(2)
    expect(screen.getByText(/只有逐条批准的证据卡才进入 AI 上下文/)).toBeInTheDocument()
  })

  it('uses worldbuilding research defaults for a fantasy project', async () => {
    vi.spyOn(api, 'listSourceDocuments').mockResolvedValue([])
    vi.spyOn(api, 'listResearchSessions').mockResolvedValue([])
    const fantasyProject: Project = {
      ...project,
      genre: 'eastern_fantasy',
      rebirth_year: 728,
      rebirth_location: '九州·云泽',
    }

    render(<ResearchWorkbenchPage project={fantasyProject} onBack={vi.fn()} onSourceCardsChanged={vi.fn()} />)

    await screen.findByText('尚无研究任务')
    expect(screen.getByLabelText('资料类型')).toHaveValue('世界设定 / 神话资料')
    expect(screen.getByLabelText('研究问题')).toHaveAttribute(
      'placeholder',
      '例：云泽灵脉枯竭会怎样改变宗门资源与修炼代价？',
    )
    expect(screen.getByText('全局参考资料')).toBeInTheDocument()
  })
})
