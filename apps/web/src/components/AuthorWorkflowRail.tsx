import type { AuthorNextAction, AuthorWorkflowStage } from '@mozhou/contracts'

import {
  AUTHOR_WORKFLOW_STEPS,
  presentAuthorAction,
  stageForWorkflowStep,
  workflowStepForStage,
} from '../authorWorkflow'

interface AuthorWorkflowRailProps {
  action: AuthorNextAction | null | undefined
  activeStage: AuthorWorkflowStage
  busy: boolean
  nextActionRecovery?: string | null
  onSelectStage: (stage: AuthorWorkflowStage) => void
  onPrimaryAction: () => void
  onRefreshNextAction?: () => void
  onOpenLastApproved: (chapterId: string) => void
}

export function AuthorWorkflowRail({
  action,
  activeStage,
  busy,
  nextActionRecovery = null,
  onSelectStage,
  onPrimaryAction,
  onRefreshNextAction = () => undefined,
  onOpenLastApproved,
}: AuthorWorkflowRailProps) {
  const currentStep = workflowStepForStage(activeStage)
  const recommendation = presentAuthorAction(action)

  return (
    <aside className="author-workflow-rail" aria-label="本章创作流程">
      <header>
        <p>AUTHOR ROUTE</p>
        <h2>这一章，现在做什么</h2>
        <span>你定方向与定稿，AI 负责主写候选。</span>
      </header>

      <nav aria-label="四阶段创作流程">
        <ol>
          {AUTHOR_WORKFLOW_STEPS.map((step, index) => {
            const selected = step.id === currentStep
            return (
              <li key={step.id} data-current={selected}>
                <button
                  type="button"
                  aria-current={selected ? 'step' : undefined}
                  aria-label={`${index + 1}，${step.label}：${step.description}`}
                  disabled={busy}
                  onClick={() => onSelectStage(stageForWorkflowStep(step.id))}
                >
                  <span aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
                  <strong>
                    <span className="author-stage-full">{step.label}</span>
                    <span className="author-stage-short">{step.shortLabel}</span>
                  </strong>
                  <small>{step.description}</small>
                </button>
              </li>
            )
          })}
        </ol>
      </nav>

      <section className="author-next-action" aria-labelledby="author-next-action-title">
        <p>{nextActionRecovery ? '下一步状态待同步' : '服务端建议的唯一下一步'}</p>
        <h3 id="author-next-action-title">{nextActionRecovery ? '章节已创建' : recommendation.label}</h3>
        <span role={nextActionRecovery ? 'alert' : undefined}>{nextActionRecovery ?? recommendation.detail}</span>
        <button
          type="button"
          disabled={busy || (!nextActionRecovery && recommendation.disabled)}
          onClick={nextActionRecovery ? onRefreshNextAction : onPrimaryAction}
        >
          {busy
            ? nextActionRecovery ? '正在刷新下一步…' : '正在处理下一步…'
            : nextActionRecovery ? '刷新下一步' : recommendation.label}
        </button>
        {!nextActionRecovery && recommendation.disabled ? <small role="status">整理完成后，这里会自动变为可确认。</small> : null}
      </section>

      {action?.last_approved_chapter_id && action.last_approved_chapter_id !== action.chapter_id ? (
        <button
          className="author-last-approved"
          type="button"
          aria-label="查看上一已定稿"
          disabled={busy}
          onClick={() => onOpenLastApproved(action.last_approved_chapter_id!)}
        >
          <span>次操作</span>
          <strong>查看上一已定稿</strong>
        </button>
      ) : null}
    </aside>
  )
}
