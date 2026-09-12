import type { AuthorNextAction } from '@mozhou/contracts'
import { describe, expect, it } from 'vitest'

import {
  presentAuthorAction,
  stageForWorkflowStep,
  workflowStepForStage,
} from './authorWorkflow'

function action(overrides: Partial<AuthorNextAction>): AuthorNextAction {
  return {
    kind: 'plan_chapter',
    target_view: 'writing',
    target_stage: 'plan',
    chapter_id: 'chapter-2',
    chapter_number: 2,
    last_approved_chapter_id: 'chapter-1',
    reconciliation_id: null,
    rolling_plan_id: null,
    rolling_plan_replenishment_id: null,
    blocked: false,
    ...overrides,
  }
}

describe('author workflow presentation', () => {
  it('collapses server stages into the four author-visible stages', () => {
    expect(workflowStepForStage('topic')).toBe('book')
    expect(workflowStepForStage('feedback')).toBe('review')
    expect(workflowStepForStage('complete')).toBe('review')
    expect(stageForWorkflowStep('candidate')).toBe('candidate')
  })

  it('maps the suggested chapter candidate to the isolated AI production desk', () => {
    expect(presentAuthorAction(action({ kind: 'generate_chapter_candidate', target_stage: 'candidate' }))).toEqual({
      label: '生成第 2 章候选',
      detail: 'AI 将主写完整候选，采用前不会覆盖正文。',
      operation: 'production',
      disabled: false,
    })
  })

  it('keeps a pending reconciliation visible but disabled', () => {
    const presentation = presentAuthorAction(action({
      kind: 'review_canon_reconciliation',
      target_stage: 'feedback',
      blocked: true,
    }))
    expect(presentation.label).toBe('正在整理定稿变化')
    expect(presentation.disabled).toBe(true)
  })
})
