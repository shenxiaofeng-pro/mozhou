import type { AuthorNextAction } from '@mozhou/contracts'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthorWorkflowRail } from './AuthorWorkflowRail'

const action: AuthorNextAction = {
  kind: 'generate_chapter_candidate',
  target_view: 'writing',
  target_stage: 'candidate',
  chapter_id: 'chapter-2',
  chapter_number: 2,
  last_approved_chapter_id: 'chapter-1',
  reconciliation_id: null,
  rolling_plan_id: null,
  rolling_plan_replenishment_id: null,
  blocked: false,
}

afterEach(cleanup)

describe('AuthorWorkflowRail', () => {
  it('shows one server-selected primary action and four named stages', () => {
    render(
      <AuthorWorkflowRail
        action={action}
        activeStage="candidate"
        busy={false}
        onSelectStage={() => undefined}
        onPrimaryAction={() => undefined}
        onOpenLastApproved={() => undefined}
      />,
    )

    expect(screen.getByRole('navigation', { name: '四阶段创作流程' })).toBeVisible()
    expect(screen.getAllByRole('listitem')).toHaveLength(4)
    expect(screen.getByRole('button', { name: '生成第 2 章候选' })).toBeVisible()
    expect(screen.getByRole('button', { name: /3，AI 候选/ })).toHaveAttribute('aria-current', 'step')
  })

  it('supports stage navigation and the secondary approved-chapter action', () => {
    const selectStage = vi.fn()
    const openLastApproved = vi.fn()
    render(
      <AuthorWorkflowRail
        action={action}
        activeStage="candidate"
        busy={false}
        onSelectStage={selectStage}
        onPrimaryAction={() => undefined}
        onOpenLastApproved={openLastApproved}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /4，审校定稿/ }))
    fireEvent.click(screen.getByRole('button', { name: '查看上一已定稿' }))

    expect(selectStage).toHaveBeenCalledWith('review')
    expect(openLastApproved).toHaveBeenCalledWith('chapter-1')
  })
})
