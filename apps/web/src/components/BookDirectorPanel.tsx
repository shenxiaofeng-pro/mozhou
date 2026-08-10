import type {
  AiChapterBriefProposal,
  BookBlueprintContent,
  BookBlueprintField,
  Chapter,
  DirectorChapterPipelineResult,
  DirectorExpansionProposal,
  DirectorFieldProposal,
  DirectorOutboundPreview,
  DirectorPipelineStage,
  DirectorPlanningSnapshot,
  DirectorRegenerationImpact,
  DirectorStartupProposalSet,
  GenerationRun,
  Job,
  Project,
  RollingChapterPlan,
  RollingChapterPlanContent,
  VolumePlan,
  VolumePlanContent,
  Workspace,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { useEffect, useState } from 'react'

import { api } from '../api'

interface BookDirectorPanelProps {
  project: Project
  workspace: WorkspaceSummary
  chapter: Chapter
  canUseChapter: boolean
  onWorkspaceChanged: (workspace: Workspace | WorkspaceSummary) => void
  onAdoptBrief: (proposal: AiChapterBriefProposal) => void
  onDraftGenerated: (run: GenerationRun) => void
}

type DirectorTask = 'startup' | 'expansion' | 'field' | 'pipeline'

const blueprintFields: Array<{
  field: BookBlueprintField
  label: string
  multiline?: boolean
}> = [
  { field: 'title', label: '书名' },
  { field: 'genre', label: '题材' },
  { field: 'rebirth_year', label: '重生年份' },
  { field: 'rebirth_location', label: '重生地点' },
  { field: 'target_audience', label: '目标读者', multiline: true },
  { field: 'core_selling_points', label: '核心卖点（每行一条）', multiline: true },
  { field: 'core_desire', label: '核心欲望', multiline: true },
  { field: 'divergence_point', label: '重生分歧点', multiline: true },
  { field: 'long_term_promise', label: '长线承诺', multiline: true },
  { field: 'ending_direction', label: '结局方向', multiline: true },
  { field: 'protagonist_arc', label: '主角成长弧', multiline: true },
  { field: 'resource_growth', label: '资源成长线', multiline: true },
  { field: 'relationship_design', label: '人物关系设计', multiline: true },
]

const stageLabels: Record<DirectorPipelineStage, string> = {
  context: '组装上下文',
  brief: '设计章纲',
  pre_review: '写前审查',
  draft: '生成候选稿',
}

function displayBlueprintValue(content: BookBlueprintContent, field: BookBlueprintField): string {
  const value = content[field]
  return Array.isArray(value) ? value.join('\n') : String(value)
}

function updateBlueprintValue(
  content: BookBlueprintContent,
  field: BookBlueprintField,
  rawValue: string,
): BookBlueprintContent {
  if (field === 'rebirth_year') return { ...content, rebirth_year: Number(rawValue) }
  if (field === 'core_selling_points') {
    return {
      ...content,
      core_selling_points: rawValue.split('\n').map((item) => item.trim()).filter(Boolean),
    }
  }
  if (field === 'genre') {
    return { ...content, genre: rawValue === 'historical_rebirth' ? 'historical_rebirth' : 'urban_rebirth' }
  }
  return { ...content, [field]: rawValue }
}

function previewCost(preview: DirectorOutboundPreview): string {
  if (preview.estimated_cost_microusd === null) return '未配置价格'
  return `$${(preview.estimated_cost_microusd / 1_000_000).toFixed(4)}`
}

export function BookDirectorPanel({
  project,
  workspace,
  chapter,
  canUseChapter,
  onWorkspaceChanged,
  onAdoptBrief,
  onDraftGenerated,
}: BookDirectorPanelProps) {
  const initialSnapshot: DirectorPlanningSnapshot = {
    book_blueprint: workspace.book_blueprint,
    volume_plans: workspace.volume_plans,
    rolling_chapter_plans: workspace.rolling_chapter_plans,
  }
  const [snapshot, setSnapshot] = useState(initialSnapshot)
  const [idea, setIdea] = useState('')
  const [realityAnchor, setRealityAnchor] = useState('')
  const [authorIntent, setAuthorIntent] = useState('')
  const [startupResult, setStartupResult] = useState<DirectorStartupProposalSet | null>(null)
  const [expansionResult, setExpansionResult] = useState<DirectorExpansionProposal | null>(null)
  const [fieldResult, setFieldResult] = useState<DirectorFieldProposal | null>(null)
  const [pipelineResult, setPipelineResult] = useState<DirectorChapterPipelineResult | null>(null)
  const [preview, setPreview] = useState<DirectorOutboundPreview | null>(null)
  const [previewTask, setPreviewTask] = useState<DirectorTask | null>(null)
  const [activeJob, setActiveJob] = useState<Job | null>(null)
  const [activeTask, setActiveTask] = useState<DirectorTask | null>(null)
  const [pendingPipelineRerun, setPendingPipelineRerun] = useState<{
    rerunFrom: DirectorPipelineStage
    parentJobId: string | null
  }>({ rerunFrom: 'context', parentJobId: null })
  const [fieldTarget, setFieldTarget] = useState<BookBlueprintField>('core_desire')
  const [impact, setImpact] = useState<DirectorRegenerationImpact | null>(null)
  const [blueprintDraft, setBlueprintDraft] = useState<BookBlueprintContent | null>(
    initialSnapshot.book_blueprint?.content ?? null,
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const activeJobId = activeJob?.id
  const activeJobState = activeJob?.state
  useEffect(() => {
    if (!activeJobId || !activeJobState || !activeTask) return undefined
    if (['failed', 'interrupted', 'cancelled'].includes(activeJobState)) return undefined
    let stopped = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const job = await api.getJob(activeJobId)
        if (stopped) return
        setActiveJob(job)
        if (job.state === 'succeeded') {
          if (activeTask === 'startup') setStartupResult(await api.getDirectorStartupResult(job.id))
          if (activeTask === 'expansion') setExpansionResult(await api.getDirectorExpansionResult(job.id))
          if (activeTask === 'field') setFieldResult(await api.getDirectorFieldResult(job.id))
          if (activeTask === 'pipeline') setPipelineResult(await api.getDirectorPipelineResult(job.id))
          if (!stopped) {
            setActiveJob(null)
            setActiveTask(null)
          }
          return
        }
        if (['failed', 'interrupted', 'cancelled'].includes(job.state)) {
          setError(job.error_message ?? '任务已中断，可从断点继续。')
          return
        }
        timer = window.setTimeout(poll, 700)
      } catch (caught) {
        if (!stopped) setError(caught instanceof Error ? caught.message : '无法读取总导演任务')
      }
    }
    void poll()
    return () => {
      stopped = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [activeJobId, activeJobState, activeTask])

  async function refreshWorkspace(nextSnapshot?: DirectorPlanningSnapshot) {
    if (nextSnapshot) setSnapshot(nextSnapshot)
    const refreshed = await api.getProjectSummary(project.id)
    onWorkspaceChanged(refreshed)
  }

  function startupInput(confirm: boolean) {
    return {
      idea,
      reality_anchor: realityAnchor,
      candidate_count: 3,
      confirm_external_processing: confirm,
      max_estimated_cost_microusd: confirm ? preview?.estimated_cost_microusd ?? null : null,
    }
  }

  function expansionInput(confirm: boolean) {
    return {
      expected_revision: snapshot.book_blueprint?.revision ?? 0,
      author_intent: authorIntent,
      chapter_count: 5,
      confirm_external_processing: confirm,
      max_estimated_cost_microusd: confirm ? preview?.estimated_cost_microusd ?? null : null,
    }
  }

  function fieldInput(confirm: boolean) {
    return {
      target_field: fieldTarget,
      expected_revision: snapshot.book_blueprint?.revision ?? 0,
      author_intent: authorIntent,
      confirm_external_processing: confirm,
      max_estimated_cost_microusd: confirm ? preview?.estimated_cost_microusd ?? null : null,
    }
  }

  function pipelineInput(
    confirm: boolean,
    rerunFrom: DirectorPipelineStage = 'context',
    parentJobId: string | null = null,
  ) {
    return {
      expected_revision: chapter.revision,
      author_intent: authorIntent,
      context_token_budget: 24_000,
      confirm_external_processing: confirm,
      max_estimated_cost_microusd: confirm ? preview?.estimated_cost_microusd ?? null : null,
      rerun_from: rerunFrom,
      parent_job_id: parentJobId,
    }
  }

  async function showPreview(task: DirectorTask) {
    setBusy(true)
    setError(null)
    setPreview(null)
    setPreviewTask(null)
    try {
      let result: DirectorOutboundPreview
      if (task === 'startup') result = await api.previewDirectorStartup(project.id, startupInput(false))
      else if (task === 'expansion') result = await api.previewDirectorExpansion(project.id, expansionInput(false))
      else if (task === 'field') {
        setImpact(await api.getDirectorRegenerationImpact(project.id, fieldTarget))
        result = await api.previewDirectorField(project.id, fieldInput(false))
      } else {
        setPendingPipelineRerun({ rerunFrom: 'context', parentJobId: null })
        result = await api.previewDirectorPipeline(chapter.id, pipelineInput(false))
      }
      setPreview(result)
      setPreviewTask(task)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '无法预览外发范围')
    } finally {
      setBusy(false)
    }
  }

  async function confirmPreview() {
    if (!preview || !previewTask) return
    setBusy(true)
    setError(null)
    try {
      let job: Job
      if (previewTask === 'startup') job = await api.startDirectorStartupJob(project.id, startupInput(true))
      else if (previewTask === 'expansion') job = await api.startDirectorExpansionJob(project.id, expansionInput(true))
      else if (previewTask === 'field') job = await api.startDirectorFieldJob(project.id, fieldInput(true))
      else job = await api.startDirectorPipelineJob(
        chapter.id,
        pipelineInput(true, pendingPipelineRerun.rerunFrom, pendingPipelineRerun.parentJobId),
      )
      setActiveTask(previewTask)
      setActiveJob(job)
      setPreview(null)
      setPreviewTask(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '无法启动总导演任务')
    } finally {
      setBusy(false)
    }
  }

  async function selectCandidate(candidateId: string) {
    if (!startupResult) return
    setBusy(true)
    setError(null)
    try {
      const blueprint = await api.selectDirectorStartupCandidate(project.id, {
        job_id: startupResult.job_id,
        candidate_id: candidateId,
        expected_blueprint_revision: snapshot.book_blueprint?.revision ?? null,
      })
      setSnapshot({ book_blueprint: blueprint, volume_plans: [], rolling_chapter_plans: [] })
      setBlueprintDraft(blueprint.content)
      setStartupResult(null)
      await refreshWorkspace()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '开书方向采用失败')
    } finally {
      setBusy(false)
    }
  }

  async function saveBlueprint(lockUpdates: Partial<Record<BookBlueprintField, boolean>> = {}) {
    const blueprint = snapshot.book_blueprint
    if (!blueprint || !blueprintDraft) return
    const changedFields = blueprintFields
      .map(({ field }) => field)
      .filter((field) => displayBlueprintValue(blueprint.content, field) !== displayBlueprintValue(blueprintDraft, field))
    if (changedFields.length === 0 && Object.keys(lockUpdates).length === 0) return
    setBusy(true)
    setError(null)
    try {
      const updated = await api.updateBookBlueprint(project.id, {
        content: blueprintDraft,
        changed_fields: changedFields,
        lock_updates: lockUpdates,
        expected_revision: blueprint.revision,
      })
      setSnapshot((current) => ({ ...current, book_blueprint: updated }))
      setBlueprintDraft(updated.content)
      setPreview(null)
      setPreviewTask(null)
      await refreshWorkspace()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '整书蓝图保存失败')
    } finally {
      setBusy(false)
    }
  }

  async function applyExpansion() {
    const blueprint = snapshot.book_blueprint
    if (!blueprint || !expansionResult) return
    setBusy(true)
    setError(null)
    try {
      const updated = await api.applyDirectorExpansion(project.id, {
        job_id: expansionResult.job_id,
        expected_revision: blueprint.revision,
      })
      setExpansionResult(null)
      setSnapshot(updated)
      setBlueprintDraft(updated.book_blueprint?.content ?? null)
      await refreshWorkspace(updated)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '整书计划采用失败')
    } finally {
      setBusy(false)
    }
  }

  async function applyField() {
    const blueprint = snapshot.book_blueprint
    if (!blueprint || !fieldResult) return
    setBusy(true)
    setError(null)
    try {
      const updated = await api.applyDirectorField(project.id, {
        job_id: fieldResult.job_id,
        expected_revision: blueprint.revision,
      })
      setSnapshot((current) => ({ ...current, book_blueprint: updated }))
      setBlueprintDraft(updated.content)
      setFieldResult(null)
      setImpact(null)
      await refreshWorkspace()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '字段候选采用失败')
    } finally {
      setBusy(false)
    }
  }

  async function cancelJob() {
    if (!activeJob) return
    try {
      setActiveJob(await api.cancelJob(activeJob.id))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '停止任务失败')
    }
  }

  async function retryJob() {
    if (!activeJob) return
    try {
      setError(null)
      setActiveJob(await api.retryJob(activeJob.id))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '从断点继续失败')
    }
  }

  async function rerunPipeline(stage: DirectorPipelineStage) {
    if (!pipelineResult) return
    setBusy(true)
    setError(null)
    try {
      const input = pipelineInput(false, stage, pipelineResult.job_id)
      const nextPreview = await api.previewDirectorPipeline(chapter.id, input)
      setPendingPipelineRerun({ rerunFrom: stage, parentJobId: pipelineResult.job_id })
      setPreview(nextPreview)
      setPreviewTask('pipeline')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '无法预览分阶段重跑')
    } finally {
      setBusy(false)
    }
  }

  const blueprint = snapshot.book_blueprint
  const hasLockedField = blueprint ? Object.values(blueprint.locks).some(Boolean) : false

  return (
    <section className="book-director" aria-labelledby="book-director-title">
      <header>
        <div>
          <p>BOOK DIRECTOR</p>
          <h3 id="book-director-title">从一句创意到可写的整书路线</h3>
        </div>
        <span data-ready={Boolean(blueprint)}>{blueprint ? `蓝图 v${blueprint.revision}` : '尚未开书'}</span>
      </header>

      {!blueprint ? (
        <div className="director-startup">
          <label>
            一句话创意
            <textarea
              value={idea}
              onChange={(event) => { setIdea(event.target.value); setPreview(null) }}
              maxLength={3000}
              rows={4}
              placeholder="例：1998 年回到南平，从一家濒临倒闭的木竹厂开始，改变家族和城市的命运。"
            />
          </label>
          <label>
            现实锚点（可选）
            <textarea
              value={realityAnchor}
              onChange={(event) => { setRealityAnchor(event.target.value); setPreview(null) }}
              maxLength={1500}
              rows={2}
              placeholder="地点、年代、行业或你已确认的现实材料。"
            />
          </label>
          <button type="button" onClick={() => { void showPreview('startup') }} disabled={busy || idea.trim().length === 0}>
            {busy ? '正在准备…' : '生成 3 个差异化开书方案'}
          </button>
        </div>
      ) : (
        <>
          <details className="blueprint-editor" open={blueprint.plan_stale || blueprint.stale_fields.length > 0}>
            <summary>
              <span>整书蓝图</span>
              <small>{hasLockedField ? '含锁定字段' : '可继续编辑'} · {blueprint.plan_stale ? '计划待更新' : '计划已同步'}</small>
            </summary>
            {blueprint.stale_fields.length > 0 ? (
              <p className="director-warning">待联动复核：{blueprint.stale_fields.map((field) => blueprintFields.find((item) => item.field === field)?.label ?? field).join('、')}</p>
            ) : null}
            <div className="blueprint-grid">
              {blueprintDraft ? blueprintFields.map(({ field, label, multiline }) => (
                <label key={field} data-locked={blueprint.locks[field]}>
                  <span>{label}</span>
                  {field === 'genre' ? (
                    <select
                      value={blueprintDraft.genre}
                      disabled={blueprint.locks[field]}
                      onChange={(event) => setBlueprintDraft(updateBlueprintValue(blueprintDraft, field, event.target.value))}
                    >
                      <option value="historical_rebirth">历史重生</option>
                      <option value="urban_rebirth">都市重生</option>
                    </select>
                  ) : multiline ? (
                    <textarea
                      value={displayBlueprintValue(blueprintDraft, field)}
                      readOnly={blueprint.locks[field]}
                      rows={3}
                      onChange={(event) => setBlueprintDraft(updateBlueprintValue(blueprintDraft, field, event.target.value))}
                    />
                  ) : (
                    <input
                      type={field === 'rebirth_year' ? 'number' : 'text'}
                      value={displayBlueprintValue(blueprintDraft, field)}
                      readOnly={blueprint.locks[field]}
                      onChange={(event) => setBlueprintDraft(updateBlueprintValue(blueprintDraft, field, event.target.value))}
                    />
                  )}
                  <button
                    type="button"
                    className="blueprint-lock"
                    onClick={() => { void saveBlueprint({ [field]: !blueprint.locks[field] }) }}
                    disabled={busy}
                    aria-label={`${blueprint.locks[field] ? '解锁' : '锁定'}${label}`}
                  >{blueprint.locks[field] ? '已锁定' : '锁定'}</button>
                </label>
              )) : null}
            </div>
            <button type="button" onClick={() => { void saveBlueprint() }} disabled={busy}>保存蓝图修改</button>
          </details>

          <div className="director-command-row">
            <label>
              本次导演意图（可选）
              <textarea
                value={authorIntent}
                onChange={(event) => {
                  setAuthorIntent(event.target.value)
                  setPreview(null)
                  setPreviewTask(null)
                }}
                rows={2}
                maxLength={1000}
              />
            </label>
            <button type="button" onClick={() => { void showPreview('expansion') }} disabled={busy || blueprint.stale_fields.length > 0}>
              {snapshot.volume_plans.length > 0 ? '重新展开卷纲与未来 5 章' : '展开卷纲与未来 5 章'}
            </button>
            <div className="field-regenerator">
              <select value={fieldTarget} onChange={(event) => {
                setFieldTarget(event.target.value as BookBlueprintField)
                setImpact(null)
                setPreview(null)
                setPreviewTask(null)
              }}>
                {blueprintFields.map(({ field, label }) => <option key={field} value={field}>{label}</option>)}
              </select>
              <button type="button" onClick={() => { void showPreview('field') }} disabled={busy || blueprint.locks[fieldTarget]}>
                只重生成这一项
              </button>
            </div>
            <button type="button" className="pipeline-action" onClick={() => { void showPreview('pipeline') }} disabled={busy || !canUseChapter || blueprint.plan_stale}>
              一键跑完：上下文 → 章纲 → 写前审查 → 候选稿
            </button>
          </div>
        </>
      )}

      {preview ? (
        <article className="director-outbound" aria-label="总导演外发确认">
          <div><strong>发送前确认</strong><span>{preview.profile_name} · {preview.model}</span></div>
          <p>{preview.content_scope}</p>
          <p>{preview.character_count.toLocaleString()} 字符 · {preview.estimated_calls} 次模型调用 · 估算 {previewCost(preview)}</p>
          <p>数据类型：{preview.data_types.join('、')}</p>
          {impact ? <p>联动影响：{impact.downstream_affected.join('、') || '无'}{impact.locked_conflicts.length ? `；锁定冲突：${impact.locked_conflicts.join('、')}` : ''}</p> : null}
          <div>
            <button type="button" onClick={() => { void confirmPreview() }} disabled={busy || Boolean(impact?.locked_conflicts.length)}>确认外发并启动</button>
            <button type="button" className="quiet-action" onClick={() => { setPreview(null); setPreviewTask(null) }}>取消</button>
          </div>
        </article>
      ) : null}

      {activeJob ? (
        <div className="director-job" role="status" aria-live="polite">
          <div><strong>{activeJob.current_step || '已进入本地任务队列'}</strong><span>{activeJob.progress_current} / {activeJob.progress_total}</span></div>
          <progress value={activeJob.progress_current} max={Math.max(activeJob.progress_total, 1)} />
          {['queued', 'running', 'pause_requested'].includes(activeJob.state)
            ? <button type="button" onClick={() => { void cancelJob() }}>停止任务</button>
            : <button type="button" onClick={() => { void retryJob() }}>从断点继续</button>}
        </div>
      ) : null}

      {startupResult ? (
        <div className="startup-candidates" aria-label="开书候选方案">
          {startupResult.candidates.map((candidate) => (
            <article key={candidate.id}>
              <small>方案 {candidate.ordinal}</small>
              <h4>{candidate.label}</h4>
              <strong>{candidate.blueprint.title}</strong>
              <p>{candidate.blueprint.core_desire}</p>
              <p>{candidate.why_distinct}</p>
              <ul>{candidate.blueprint.core_selling_points.map((item) => <li key={item}>{item}</li>)}</ul>
              {candidate.risks.length ? <p className="director-warning">风险：{candidate.risks.join('、')}</p> : null}
              <button type="button" onClick={() => { void selectCandidate(candidate.id) }} disabled={busy}>采用这个方向</button>
            </article>
          ))}
        </div>
      ) : null}

      {fieldResult ? (
        <article className="field-proposal">
          <strong>单字段候选 · {fieldResult.target_field}</strong>
          <p>{Array.isArray(fieldResult.value) ? fieldResult.value.join('、') : fieldResult.value}</p>
          <small>{fieldResult.rationale}</small>
          <button type="button" onClick={() => { void applyField() }} disabled={busy}>采用这项修改</button>
        </article>
      ) : null}

      {expansionResult ? (
        <article className="expansion-proposal">
          <h4>整书展开候选</h4>
          <p>{expansionResult.why_writeable}</p>
          <div><strong>{expansionResult.volumes.length} 卷</strong><span>{expansionResult.chapters.length} 章滚动计划</span><span>{expansionResult.entities.length} 个人物/资源</span></div>
          {expansionResult.risk_notes.length ? <p className="director-warning">风险：{expansionResult.risk_notes.join('、')}</p> : null}
          <button type="button" onClick={() => { void applyExpansion() }} disabled={busy}>采用并创建可编辑计划</button>
        </article>
      ) : null}

      {snapshot.volume_plans.length > 0 ? (
        <details className="director-plans">
          <summary>卷纲与未来 3–5 章 <small>每项可编辑、锁定和验证</small></summary>
          {snapshot.volume_plans.map((plan) => (
            <VolumePlanEditor key={`${plan.id}:${plan.revision}`} plan={plan} projectId={project.id} onSaved={(updated) => {
              setSnapshot((current) => ({ ...current, volume_plans: current.volume_plans.map((item) => item.id === updated.id ? updated : item) }))
              setPreview(null)
              setPreviewTask(null)
              void refreshWorkspace()
            }} />
          ))}
          {snapshot.rolling_chapter_plans.map((plan) => (
            <RollingPlanEditor key={`${plan.id}:${plan.revision}`} plan={plan} projectId={project.id} onSaved={(updated) => {
              setSnapshot((current) => ({ ...current, rolling_chapter_plans: current.rolling_chapter_plans.map((item) => item.id === updated.id ? updated : item) }))
              setPreview(null)
              setPreviewTask(null)
              void refreshWorkspace()
            }} />
          ))}
        </details>
      ) : null}

      {pipelineResult ? (
        <article className="pipeline-result">
          <header><strong>单章候选链已完成</strong><span>{pipelineResult.completed_stages.map((stage) => stageLabels[stage]).join(' → ')}</span></header>
          <h4>{pipelineResult.brief.title}</h4>
          <p>{pipelineResult.brief.opening_hook}</p>
          <p>写前审查：{pipelineResult.pre_review.passed ? '通过' : '需复核'}，{pipelineResult.pre_review.findings.length} 条提示</p>
          <div>
            <button type="button" onClick={() => onAdoptBrief(pipelineResult.brief)}>送入章纲编辑区</button>
            <button type="button" onClick={() => onDraftGenerated(pipelineResult.draft)}>送入正文候选区</button>
          </div>
          <div className="pipeline-rerun">
            {(['brief', 'pre_review', 'draft'] as DirectorPipelineStage[]).map((stage) => (
              <button type="button" key={stage} onClick={() => { void rerunPipeline(stage) }} disabled={busy}>从“{stageLabels[stage]}”重跑</button>
            ))}
          </div>
        </article>
      ) : null}

      {error ? <p className="ai-coauthor-error" role="alert">{error}</p> : null}
    </section>
  )
}

function VolumePlanEditor({
  plan,
  projectId,
  onSaved,
}: {
  plan: VolumePlan
  projectId: string
  onSaved: (updated: VolumePlan) => void
}) {
  const [draft, setDraft] = useState(plan)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function save(locked = draft.locked) {
    const content: VolumePlanContent = {
      volume_number: draft.volume_number,
      title: draft.title,
      direction: draft.direction,
      central_conflict: draft.central_conflict,
      state_goal: draft.state_goal,
      resource_goal: draft.resource_goal,
      emotional_payoff: draft.emotional_payoff,
      climax: draft.climax,
      verification: draft.verification,
    }
    setSaving(true)
    setError(null)
    try {
      onSaved(await api.updateDirectorVolumePlan(projectId, plan.id, { content, locked, expected_revision: plan.revision }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '卷纲保存失败')
    } finally {
      setSaving(false)
    }
  }
  return (
    <article className="plan-editor">
      <header><strong>第 {plan.volume_number} 卷</strong><button type="button" onClick={() => { void save(!plan.locked) }} disabled={saving}>{plan.locked ? '已锁定' : '锁定'}</button></header>
      <input aria-label={`第 ${plan.volume_number} 卷标题`} value={draft.title} readOnly={plan.locked} onChange={(event) => setDraft({ ...draft, title: event.target.value })} />
      <textarea aria-label={`第 ${plan.volume_number} 卷方向`} value={draft.direction} readOnly={plan.locked} rows={2} onChange={(event) => setDraft({ ...draft, direction: event.target.value })} />
      <textarea aria-label={`第 ${plan.volume_number} 卷核心冲突`} value={draft.central_conflict} readOnly={plan.locked} rows={2} onChange={(event) => setDraft({ ...draft, central_conflict: event.target.value })} />
      <button type="button" onClick={() => { void save() }} disabled={saving || plan.locked}>保存卷纲</button>
      {error ? <p role="alert">{error}</p> : null}
    </article>
  )
}

function RollingPlanEditor({
  plan,
  projectId,
  onSaved,
}: {
  plan: RollingChapterPlan
  projectId: string
  onSaved: (updated: RollingChapterPlan) => void
}) {
  const [draft, setDraft] = useState(plan)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function save(locked = draft.locked) {
    const content: RollingChapterPlanContent = {
      chapter_number: draft.chapter_number,
      title: draft.title,
      reader_promise: draft.reader_promise,
      opening_hook: draft.opening_hook,
      state_change: draft.state_change,
      resource_change: draft.resource_change,
      emotional_payoff: draft.emotional_payoff,
      ending_cliffhanger: draft.ending_cliffhanger,
      verification: draft.verification,
      scene_beats: draft.scene_beats,
    }
    setSaving(true)
    setError(null)
    try {
      onSaved(await api.updateDirectorRollingPlan(projectId, plan.id, { content, locked, expected_revision: plan.revision }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '滚动章纲保存失败')
    } finally {
      setSaving(false)
    }
  }
  return (
    <article className="plan-editor rolling">
      <header><strong>第 {plan.chapter_number} 章</strong><button type="button" onClick={() => { void save(!plan.locked) }} disabled={saving}>{plan.locked ? '已锁定' : '锁定'}</button></header>
      <input aria-label={`第 ${plan.chapter_number} 章标题`} value={draft.title} readOnly={plan.locked} onChange={(event) => setDraft({ ...draft, title: event.target.value })} />
      <textarea aria-label={`第 ${plan.chapter_number} 章读者承诺`} value={draft.reader_promise} readOnly={plan.locked} rows={2} onChange={(event) => setDraft({ ...draft, reader_promise: event.target.value })} />
      <textarea aria-label={`第 ${plan.chapter_number} 章钩子`} value={draft.opening_hook} readOnly={plan.locked} rows={2} onChange={(event) => setDraft({ ...draft, opening_hook: event.target.value })} />
      <textarea aria-label={`第 ${plan.chapter_number} 章状态变化`} value={draft.state_change} readOnly={plan.locked} rows={2} onChange={(event) => setDraft({ ...draft, state_change: event.target.value })} />
      <textarea aria-label={`第 ${plan.chapter_number} 章章尾悬念`} value={draft.ending_cliffhanger} readOnly={plan.locked} rows={2} onChange={(event) => setDraft({ ...draft, ending_cliffhanger: event.target.value })} />
      <button type="button" onClick={() => { void save() }} disabled={saving || plan.locked}>保存滚动章纲</button>
      {error ? <p role="alert">{error}</p> : null}
    </article>
  )
}
