import type {
  AuthorNextAction,
  AuthorNextActionKind,
  AuthorWorkflowStage,
} from '@mozhou/contracts'

export type AuthorWorkflowStep = 'book' | 'plan' | 'candidate' | 'review'
export type AuthorActionOperation = 'topic' | 'director' | 'production' | 'manuscript' | 'create' | 'final'

export interface AuthorWorkflowStepDefinition {
  id: AuthorWorkflowStep
  label: string
  shortLabel: string
  description: string
}

export interface AuthorActionPresentation {
  label: string
  detail: string
  operation: AuthorActionOperation
  disabled: boolean
}

export const AUTHOR_WORKFLOW_STEPS: readonly AuthorWorkflowStepDefinition[] = [
  {
    id: 'book',
    label: '选题与整书',
    shortLabel: '整书',
    description: '确定读者、承诺、卷向与结局',
  },
  {
    id: 'plan',
    label: '当前章计划',
    shortLabel: '章纲',
    description: '钩子、变化、回报与章尾悬念',
  },
  {
    id: 'candidate',
    label: 'AI 候选',
    shortLabel: '候选',
    description: 'AI 主写，结果仍与正文隔离',
  },
  {
    id: 'review',
    label: '审校定稿',
    shortLabel: '定稿',
    description: '作者调整、确认 Canon，再进入下一章',
  },
] as const

export function workflowStepForStage(stage: AuthorWorkflowStage | null | undefined): AuthorWorkflowStep {
  if (stage === 'topic' || stage === 'book') return 'book'
  if (stage === 'candidate') return 'candidate'
  if (stage === 'review' || stage === 'feedback' || stage === 'complete') return 'review'
  return 'plan'
}

export function stageForWorkflowStep(step: AuthorWorkflowStep): AuthorWorkflowStage {
  const stages: Record<AuthorWorkflowStep, AuthorWorkflowStage> = {
    book: 'book',
    plan: 'plan',
    candidate: 'candidate',
    review: 'review',
  }
  return stages[step]
}

export function presentAuthorAction(action: AuthorNextAction | null | undefined): AuthorActionPresentation {
  if (!action) {
    return {
      label: '打开本章计划',
      detail: '先确认这一章会改变什么，再让 AI 写候选。',
      operation: 'production',
      disabled: false,
    }
  }

  const chapter = action.chapter_number ? `第 ${action.chapter_number} 章` : '当前章节'
  const presentations: Record<AuthorNextActionKind, Omit<AuthorActionPresentation, 'disabled'>> = {
    confirm_topic: {
      label: '确认选题方向',
      detail: '先由你确定题材、读者与长期承诺。',
      operation: 'topic',
    },
    review_topic_changes: {
      label: '复核选题变更',
      detail: '选题有新调整，确认后再更新后续计划。',
      operation: 'topic',
    },
    plan_book: {
      label: '生成整书规划候选',
      detail: '让 AI 提供卷向与结局方案，由你选择和调整。',
      operation: 'director',
    },
    review_downstream_plans: {
      label: '复核受影响的计划',
      detail: '选题或写作模式已变化，已定稿正文不会被改动。',
      operation: 'director',
    },
    plan_chapter: {
      label: `规划${chapter}`,
      detail: '补齐本章钩子、状态变化、情绪回报和悬念。',
      operation: 'production',
    },
    generate_chapter_candidate: {
      label: `生成${chapter}候选`,
      detail: 'AI 将主写完整候选，采用前不会覆盖正文。',
      operation: 'production',
    },
    continue_chapter_draft: {
      label: `继续调整${chapter}`,
      detail: '回到正文，保留你的修改并准备审校。',
      operation: 'manuscript',
    },
    review_chapter: {
      label: `审校并定稿${chapter}`,
      detail: '检查问题单与正文，最终定稿仍由你确认。',
      operation: 'director',
    },
    review_canon_reconciliation: {
      label: action.blocked ? '正在整理定稿变化' : `确认${chapter}事实与偏好`,
      detail: action.blocked
        ? '后台正在从最终正文提取候选事实，完成后可确认。'
        : '接受或拒绝候选事实与写作偏好，再补齐后续计划。',
      operation: 'director',
    },
    review_rolling_plan: {
      label: '确认后续章节计划',
      detail: '审阅 AI 补出的 3–5 章计划，采用后才进入正式章纲。',
      operation: 'director',
    },
    create_next_chapter: {
      label: action.chapter_number ? `创建第 ${action.chapter_number} 章` : '创建下一章',
      detail: '按已确认的滚动计划建立下一章，不生成正文。',
      operation: 'create',
    },
    project_complete: {
      label: '查看最后定稿',
      detail: '当前计划已经完成；可回看定稿或继续扩写整书计划。',
      operation: 'final',
    },
  }

  return { ...presentations[action.kind], disabled: action.blocked }
}
