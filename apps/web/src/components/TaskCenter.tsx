import type {
  Chapter,
  ChapterSummary,
  Job,
  JobArtifactContent,
  JobDetail,
  JobKind,
  JobState,
  Workspace,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { useEffect, useMemo, useState } from 'react'

import { ApiError, api } from '../api'

interface TaskCenterProps {
  projectId: string
  chapters: ChapterSummary[]
  open: boolean
  onClose: () => void
  onChapterChanged: (chapter: Chapter) => void
  onWorkspaceChanged: (workspace: Workspace | WorkspaceSummary) => void
  onOpenReferenceLibrary: () => void
  onOpenWritingPatterns?: () => void
  onOpenChapterProduction?: (chapterId: string | null) => void
}

const kindLabels: Record<JobKind, string> = {
  chapter_brief: 'AI 章纲',
  chapter_draft: '完整章节候选',
  reference_segment_map: '参考区段分析',
  reference_book_reduce: '单书结构归纳',
  reference_fusion: '多书六维合成',
  review: 'AI 审校',
  sandbox_ai_round: 'AI 剧情沙盘',
  research_extraction: '资料研究',
  comic_season_plan: '漫剧季方案',
  comic_episode_script: '漫剧单集剧本',
  topic_decision: '选题候选',
  pattern_adaptation: '写作模式原创迁移',
}

const stateLabels: Record<JobState, string> = {
  queued: '排队中',
  running: '执行中',
  pause_requested: '正在停止',
  cancelled: '已取消',
  succeeded: '已完成',
  failed: '失败',
  interrupted: '已中断',
}

const activeStates = new Set<JobState>(['queued', 'running', 'pause_requested'])
const retryableStates = new Set<JobState>(['failed', 'interrupted', 'cancelled'])
const craftPatternWorkflows = new Set(['craft_pattern_analysis_v2', 'craft_pattern_fusion_v2'])
const chapterProductionWorkflows = new Set([
  'chapter_production_outline',
  'chapter_production_draft',
  'chapter_production_rewrite',
  'chapter_production_review',
])

function isChapterProductionJob(job: Pick<Job, 'kind' | 'workflow'>): boolean {
  return chapterProductionWorkflows.has(job.workflow)
    || (['chapter_brief', 'chapter_draft'].includes(job.kind) && job.workflow === '')
}

function needsFreshPreflight(job: Pick<Job, 'kind' | 'workflow'>): boolean {
  return craftPatternWorkflows.has(job.workflow) || job.kind === 'pattern_adaptation'
}

function jobLabel(job: Pick<Job, 'kind' | 'workflow'>): string {
  if (job.workflow === 'chapter_production_outline') return '本章章纲候选'
  if (job.workflow === 'chapter_production_draft') return '本章正文候选'
  if (job.workflow === 'chapter_production_rewrite') return '候选局部改写'
  if (job.workflow === 'chapter_production_review') return '候选七维审校'
  if (job.workflow === 'canon_reconciliation_v1') return '定稿事实与偏好整理'
  if (job.workflow === 'craft_pattern_analysis_v2') return '单书写作模式拆解'
  if (job.workflow === 'craft_pattern_fusion_v2') return '多书模式融合'
  return kindLabels[job.kind]
}

export function TaskCenter({
  projectId,
  open,
  onClose,
  onWorkspaceChanged,
  onOpenReferenceLibrary,
  onOpenWritingPatterns = () => undefined,
  onOpenChapterProduction = () => undefined,
}: TaskCenterProps) {
  const [jobs, setJobs] = useState<Job[]>([])
  const [selected, setSelected] = useState<JobDetail | null>(null)
  const [artifact, setArtifact] = useState<JobArtifactContent | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [resubmissionJobIds, setResubmissionJobIds] = useState<Set<string>>(() => new Set())
  const activeCount = useMemo(
    () => jobs.filter((job) => activeStates.has(job.state)).length,
    [jobs],
  )
  const usageSummary = useMemo(() => {
    if (!selected) return null
    const inputTokens = selected.attempts.reduce(
      (total, attempt) => total + (attempt.input_tokens ?? 0),
      0,
    )
    const outputTokens = selected.attempts.reduce(
      (total, attempt) => total + (attempt.output_tokens ?? 0),
      0,
    )
    const durationMs = selected.attempts.reduce(
      (total, attempt) => total + (attempt.duration_ms ?? 0),
      0,
    )
    const estimatedCost = selected.attempts.reduce(
      (total, attempt) => total + (attempt.estimated_cost_microusd ?? 0),
      0,
    )
    return {
      inputTokens,
      outputTokens,
      durationMs,
      estimatedCost,
      hasUsage: selected.attempts.some(
        (attempt) => attempt.input_tokens !== null || attempt.output_tokens !== null,
      ),
      hasCost: selected.attempts.some((attempt) => attempt.estimated_cost_microusd !== null),
    }
  }, [selected])
  useEffect(() => {
    let stopped = false
    let timer: number | undefined
    const refresh = async () => {
      try {
        const nextJobs = await api.listJobs(projectId)
        if (stopped) return
        setJobs(nextJobs)
        timer = window.setTimeout(
          refresh,
          nextJobs.some((job) => activeStates.has(job.state)) ? 700 : 3000,
        )
      } catch (caught) {
        if (!stopped && open) {
          setError(caught instanceof Error ? caught.message : '读取任务列表失败')
        }
        timer = window.setTimeout(refresh, 3000)
      }
    }
    void refresh()
    return () => {
      stopped = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [open, projectId])

  useEffect(() => {
    if (!open) return undefined
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose, open])

  async function inspectJob(job: Job) {
    setError(null)
    setArtifact(null)
    try {
      setSelected(await api.getJob(job.id))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '读取任务详情失败')
    }
  }

  function replaceJob(updated: Job) {
    setJobs((current) => current.map((job) => job.id === updated.id ? updated : job))
    setSelected((current) => current?.id === updated.id ? { ...current, ...updated } : current)
  }

  async function cancelJob(job: Job) {
    setBusyAction(`cancel:${job.id}`)
    setError(null)
    try {
      replaceJob(await api.cancelJob(job.id))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '取消任务失败')
    } finally {
      setBusyAction(null)
    }
  }

  async function retryJob(job: Job) {
    setBusyAction(`retry:${job.id}`)
    setError(null)
    try {
      replaceJob(await api.retryJob(job.id))
    } catch (caught) {
      if (
        needsFreshPreflight(job)
        && caught instanceof ApiError
        && caught.status === 409
      ) {
        setResubmissionJobIds((current) => new Set(current).add(job.id))
        setError(job.kind === 'pattern_adaptation'
          ? '原预检依据已过期，请回到写作配方重新预检后提交。'
          : '原预检依据已过期，请回到拆书库重新预检后提交。')
      } else {
        setError(caught instanceof Error ? caught.message : '重试任务失败')
      }
    } finally {
      setBusyAction(null)
    }
  }

  function openFreshPreflight(job: Job) {
    onClose()
    if (job.kind === 'pattern_adaptation') onOpenWritingPatterns()
    else onOpenReferenceLibrary()
  }

  async function viewArtifact(artifactId: string) {
    setBusyAction(`artifact:${artifactId}`)
    setError(null)
    try {
      setArtifact(await api.getJobArtifact(artifactId))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '读取任务产物失败')
    } finally {
      setBusyAction(null)
    }
  }

  async function continueResult(job: Job) {
    setBusyAction(`result:${job.id}`)
    setError(null)
    try {
      if (isChapterProductionJob(job)) {
        onClose()
        onOpenChapterProduction(job.chapter_id)
        return
      }
      if (selected?.id !== job.id) {
        setSelected(await api.getJob(job.id))
        setArtifact(null)
      }
      if (job.kind === 'reference_fusion') {
        if (craftPatternWorkflows.has(job.workflow)) {
          onClose()
          onOpenReferenceLibrary()
        } else {
          onWorkspaceChanged(await api.getProjectSummary(projectId))
        }
      } else if (job.kind === 'pattern_adaptation') {
        onClose()
        onOpenWritingPatterns()
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '读取任务结果失败')
    } finally {
      setBusyAction(null)
    }
  }

  return (
    <>
      <button
        className="task-center-backdrop"
        type="button"
        tabIndex={-1}
        aria-label="关闭任务中心背景"
        data-open={open}
        onClick={onClose}
        hidden={!open}
      />
      <aside
        className="task-center"
        role="dialog"
        aria-modal="true"
        aria-labelledby="task-center-title"
        data-open={open}
        hidden={!open}
      >
        <header>
          <div><small>JOB RUNTIME</small><h2 id="task-center-title">任务中心</h2></div>
          <button type="button" aria-label="关闭任务中心" onClick={onClose}>×</button>
        </header>
        <p className="task-center-summary">
          {activeCount > 0 ? `${activeCount} 个任务仍在执行；退出应用后进度仍会保留。` : '当前没有执行中的任务。'}
        </p>
        {error ? <p className="task-center-error" role="alert">{error}</p> : null}
        <div className="task-center-body">
          <section className="task-list" aria-label="作品任务列表">
            {jobs.length > 0 ? jobs.map((job) => (
              <article key={job.id} data-state={job.state} data-selected={selected?.id === job.id}>
                <button type="button" className="task-main" onClick={() => { void inspectJob(job) }}>
                  <span>{jobLabel(job)}</span>
                  <strong>{job.error_message || job.current_step || stateLabels[job.state]}</strong>
                  <small>{stateLabels[job.state]} · {job.progress_current}/{job.progress_total || '—'}</small>
                  <progress value={job.progress_current} max={Math.max(job.progress_total, 1)} />
                </button>
                <div>
                  {activeStates.has(job.state) ? (
                    <button
                      type="button"
                      onClick={() => { void cancelJob(job) }}
                      disabled={busyAction === `cancel:${job.id}`}
                    >停止</button>
                  ) : null}
                  {retryableStates.has(job.state) && needsFreshPreflight(job) && (
                    job.error_code === 'restored_requires_resubmission'
                    || resubmissionJobIds.has(job.id)
                  ) ? (
                    <button
                      type="button"
                      onClick={() => openFreshPreflight(job)}
                    >重新预检</button>
                  ) : retryableStates.has(job.state) ? (
                    <button
                      type="button"
                      onClick={() => { void retryJob(job) }}
                      disabled={busyAction === `retry:${job.id}`}
                    >从断点继续</button>
                  ) : null}
                  {job.state === 'succeeded' && (isChapterProductionJob(job) || ['reference_fusion', 'pattern_adaptation'].includes(job.kind)) ? (
                    <button
                      type="button"
                      onClick={() => { void continueResult(job) }}
                      disabled={busyAction === `result:${job.id}`}
                    >{isChapterProductionJob(job) ? '回到单章生产台' : job.kind === 'pattern_adaptation' ? '查看三套候选' : craftPatternWorkflows.has(job.workflow) ? '查看模式素材' : '继续采用'}</button>
                  ) : null}
                </div>
              </article>
            )) : <p className="task-list-empty">还没有 AI 后台任务。</p>}
          </section>

          {selected ? (
            <section className="task-detail" aria-label="任务详情">
              <header><span>{jobLabel(selected)}</span><strong>{stateLabels[selected.state]}</strong></header>
              <dl>
                <div><dt>模型</dt><dd>{selected.provider} · {selected.model}</dd></div>
                <div><dt>调用</dt><dd>{selected.completed_calls} / 预计 {selected.estimated_calls}</dd></div>
                <div><dt>任务块</dt><dd>{selected.chunks.filter((chunk) => chunk.state === 'succeeded').length} / {selected.chunks.length}</dd></div>
                {usageSummary?.hasUsage ? (
                  <div><dt>Token</dt><dd>{usageSummary.inputTokens.toLocaleString()} 入 / {usageSummary.outputTokens.toLocaleString()} 出</dd></div>
                ) : null}
                {usageSummary && selected.attempts.length > 0 ? (
                  <div><dt>耗时</dt><dd>{(usageSummary.durationMs / 1000).toFixed(1)} 秒</dd></div>
                ) : null}
                {usageSummary?.hasCost ? (
                  <div><dt>估算费用</dt><dd>约 ${(usageSummary.estimatedCost / 1_000_000).toFixed(4)}</dd></div>
                ) : null}
              </dl>
              {selected.error_message ? <p className="task-detail-error">{selected.error_message}</p> : null}
              <div className="task-artifacts">
                <strong>不可变产物</strong>
                {selected.artifacts.length > 0 ? selected.artifacts.map((item) => (
                  <button
                    type="button"
                    key={item.id}
                    onClick={() => { void viewArtifact(item.id) }}
                    disabled={busyAction === `artifact:${item.id}`}
                  >{item.kind} · {item.payload_sha256.slice(0, 8)}</button>
                )) : <span>任务完成块尚无产物</span>}
              </div>
              {artifact ? (
                <details className="task-artifact-preview" open>
                  <summary>{artifact.kind} · {artifact.content_type}</summary>
                  <pre>{artifact.payload}</pre>
                </details>
              ) : null}
            </section>
          ) : null}
        </div>
      </aside>
    </>
  )
}
