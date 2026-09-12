import type {
  BookBlueprintContent,
  BookBlueprintField,
  CreativePlanImpactPreview,
  Genre,
  PlanRebaseCandidate,
  RollingChapterPlanContent,
  VolumePlanContent,
} from '@mozhou/contracts'
import type { ChangeEvent } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { ApiError, api } from '../api'
import { genreOptions } from '../genre'

interface PlanRebaseWorkbenchProps {
  projectId: string
  active: boolean
  onAdopted: (planning: Awaited<ReturnType<typeof api.adoptPlanRebaseCandidate>>['planning']) => void | Promise<void>
}

interface RebaseDraft {
  bookBlueprint: BookBlueprintContent | null
  volumePlans: Array<{ id: string; content: VolumePlanContent }>
  rollingPlans: Array<{ id: string; content: RollingChapterPlanContent }>
}

const blueprintFields: Array<{ field: BookBlueprintField; label: string; multiline?: boolean }> = [
  { field: 'title', label: '书名' },
  { field: 'genre', label: '题材' },
  { field: 'rebirth_year', label: '故事纪年' },
  { field: 'rebirth_location', label: '起始地域' },
  { field: 'target_audience', label: '目标读者', multiline: true },
  { field: 'core_selling_points', label: '核心卖点', multiline: true },
  { field: 'core_desire', label: '核心欲望', multiline: true },
  { field: 'divergence_point', label: '故事引爆点', multiline: true },
  { field: 'long_term_promise', label: '长线承诺', multiline: true },
  { field: 'ending_direction', label: '结局方向', multiline: true },
  { field: 'protagonist_arc', label: '主角成长弧', multiline: true },
  { field: 'resource_growth', label: '资源成长线', multiline: true },
  { field: 'relationship_design', label: '人物关系设计', multiline: true },
]

const volumeFields: Array<{ field: keyof VolumePlanContent; label: string; multiline?: boolean }> = [
  { field: 'volume_number', label: '卷序' },
  { field: 'title', label: '卷名' },
  { field: 'direction', label: '本卷方向', multiline: true },
  { field: 'central_conflict', label: '核心冲突', multiline: true },
  { field: 'state_goal', label: '状态目标', multiline: true },
  { field: 'resource_goal', label: '资源目标', multiline: true },
  { field: 'emotional_payoff', label: '情绪回报', multiline: true },
  { field: 'climax', label: '高潮', multiline: true },
  { field: 'verification', label: '验证标准', multiline: true },
]

const rollingFields: Array<{ field: Exclude<keyof RollingChapterPlanContent, 'scene_beats'>; label: string; multiline?: boolean }> = [
  { field: 'chapter_number', label: '章节序号' },
  { field: 'title', label: '章节标题' },
  { field: 'reader_promise', label: '读者承诺', multiline: true },
  { field: 'opening_hook', label: '开篇钩子', multiline: true },
  { field: 'state_change', label: '状态变化', multiline: true },
  { field: 'resource_change', label: '资源变化', multiline: true },
  { field: 'emotional_payoff', label: '情绪回报', multiline: true },
  { field: 'ending_cliffhanger', label: '结尾悬念', multiline: true },
  { field: 'verification', label: '验证标准', multiline: true },
]

const targetLabels = {
  book_blueprint: '整书蓝图',
  volume_plan: '卷纲',
  rolling_plan: '滚动章纲',
} as const

function copyDraft(candidate: PlanRebaseCandidate): RebaseDraft {
  return {
    bookBlueprint: candidate.book_blueprint ? structuredClone(candidate.book_blueprint.content) : null,
    volumePlans: candidate.volume_plans.map((plan) => ({ id: plan.id, content: structuredClone(plan.content) })),
    rollingPlans: candidate.rolling_chapter_plans.map((plan) => ({ id: plan.id, content: structuredClone(plan.content) })),
  }
}

function candidateDraft(candidate: PlanRebaseCandidate): RebaseDraft {
  return {
    bookBlueprint: candidate.book_blueprint?.content ?? null,
    volumePlans: candidate.volume_plans.map(({ id, content }) => ({ id, content })),
    rollingPlans: candidate.rolling_chapter_plans.map(({ id, content }) => ({ id, content })),
  }
}

function sameDraft(left: RebaseDraft | null, right: RebaseDraft | null): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}

function blueprintValue(content: BookBlueprintContent, field: BookBlueprintField): string {
  const value = content[field]
  return Array.isArray(value) ? value.join('\n') : String(value)
}

function updateBlueprint(
  content: BookBlueprintContent,
  field: BookBlueprintField,
  raw: string,
): BookBlueprintContent {
  if (field === 'core_selling_points') {
    return { ...content, core_selling_points: raw.split('\n').map((item) => item.trim()).filter(Boolean) }
  }
  if (field === 'rebirth_year') return { ...content, rebirth_year: Number(raw) }
  if (field === 'genre') return { ...content, genre: raw as Genre }
  return { ...content, [field]: raw }
}

function simpleValue(value: string | number): string {
  return String(value)
}

function idempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `plan-rebase-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function dependencyReasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    legacy_dependency_snapshot: '旧计划尚未绑定可验证的创作依赖',
    topic_dependency_changed: '已确认的选题发生变化',
    writing_pattern_profile_dependency_changed: '启用的写作模式或其可验证状态发生变化',
    base_blueprint_dependency_changed: '整书蓝图版本发生变化',
    creative_context_dependency_changed: '创作依赖快照发生变化',
  }
  return labels[reason] ?? reason
}

function conflictMessage(code: string | null, preservesInput = true): string {
  if (code === 'context_blocked') return '当前创作上下文仍有阻断，请先处理阻断项再生成候选。'
  if (code === 'plan_rebase_not_required') return '计划已与最新创作依赖同步，无需再次生成候选。'
  if (code === 'plan_rebase_unavailable') return '当前还没有可安全更新的整书蓝图。'
  if (code === 'rebase_candidate_not_editable') return '这份候选已结束，不能再编辑或采用。'
  if (code === 'creative_context_dependency_changed') {
    return `选题或写作模式刚刚变化；影响清单已刷新${preservesInput ? '，你的输入仍在，请核对后再次保存' : '，请重新生成候选'}。`
  }
  if (code === 'locked_blueprint_field' || code === 'locked_volume_plan' || code === 'locked_rolling_plan') {
    return '锁定内容已在其他位置变化；最新锁定状态已刷新，你的输入仍在，请核对后再次保存。'
  }
  return `计划或候选已在其他位置更新；最新状态已刷新${preservesInput ? '，你的输入仍在，请核对后再次保存' : '，请重新生成候选'}。`
}

export function PlanRebaseWorkbench({ projectId, active, onAdopted }: PlanRebaseWorkbenchProps) {
  const [impactResult, setImpactResult] = useState<{ projectId: string; value: CreativePlanImpactPreview } | null>(null)
  const [candidate, setCandidate] = useState<PlanRebaseCandidate | null>(null)
  const [draft, setDraft] = useState<RebaseDraft | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const candidateHeadingRef = useRef<HTMLDivElement>(null)
  const focusCandidateAfterCreate = useRef(false)
  const impact = impactResult?.projectId === projectId ? impactResult.value : null
  const loading = active && impact === null && error === null
  const baseline = candidate ? candidateDraft(candidate) : null
  const dirty = !sameDraft(draft, baseline)
  const editable = candidate?.state === 'candidate'

  useEffect(() => {
    if (!active) return undefined
    let current = true
    api.getCreativeContextImpact(projectId).then((value) => {
      if (current) setImpactResult({ projectId, value })
    }).catch((caught: unknown) => {
      if (current) setError(caught instanceof Error ? caught.message : '无法读取计划影响')
    })
    return () => { current = false }
  }, [active, projectId])

  useEffect(() => {
    if (!candidate || !focusCandidateAfterCreate.current) return
    focusCandidateAfterCreate.current = false
    candidateHeadingRef.current?.focus()
  }, [candidate])

  async function refreshAfterConflict(candidateId: string) {
    const [nextImpact, nextCandidate] = await Promise.all([
      api.getCreativeContextImpact(projectId),
      api.getPlanRebaseCandidate(projectId, candidateId),
    ])
    setImpactResult({ projectId, value: nextImpact })
    setCandidate(nextCandidate)
  }

  async function createCandidate() {
    if (!impact?.can_rebase || busy) return
    setBusy(true)
    setError(null)
    setSuccess(null)
    try {
      const created = await api.createPlanRebaseCandidate(projectId, {
        expected_dependency_fingerprint_sha256: impact.current_dependency_fingerprint_sha256,
      })
      focusCandidateAfterCreate.current = true
      setCandidate(created)
      setDraft(copyDraft(created))
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        try {
          const refreshed = await api.getCreativeContextImpact(projectId)
          setImpactResult({ projectId, value: refreshed })
          setError(conflictMessage(caught.code, false))
        } catch (refreshError) {
          setError(refreshError instanceof Error ? refreshError.message : '计划影响刷新失败')
        }
      } else {
        setError(caught instanceof Error ? caught.message : '无法生成重基候选')
      }
    } finally {
      setBusy(false)
    }
  }

  async function saveCandidate() {
    if (!candidate || !draft || !editable || !dirty || busy) return
    setBusy(true)
    setError(null)
    setSuccess(null)
    try {
      const updated = await api.updatePlanRebaseCandidate(projectId, candidate.id, {
        expected_revision: candidate.revision,
        ...(draft.bookBlueprint ? { book_blueprint_content: draft.bookBlueprint } : {}),
        volume_plans: draft.volumePlans,
        rolling_chapter_plans: draft.rollingPlans,
      })
      setCandidate(updated)
      setDraft(copyDraft(updated))
      setSuccess('候选修改已保存，正式计划尚未改变。')
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        try {
          await refreshAfterConflict(candidate.id)
          setError(conflictMessage(caught.code))
        } catch (refreshError) {
          setError(refreshError instanceof Error ? refreshError.message : '冲突后刷新失败；你的输入仍在。')
        }
      } else {
        setError(caught instanceof Error ? caught.message : '候选修改保存失败')
      }
    } finally {
      setBusy(false)
    }
  }

  async function adoptCandidate() {
    if (!candidate || !impact || !editable || dirty || busy) return
    setBusy(true)
    setError(null)
    setSuccess(null)
    try {
      const result = await api.adoptPlanRebaseCandidate(projectId, candidate.id, {
        expected_revision: candidate.revision,
        expected_dependency_fingerprint_sha256: impact.current_dependency_fingerprint_sha256,
        idempotency_key: idempotencyKey(),
      })
      setCandidate(result.candidate)
      setDraft(copyDraft(result.candidate))
      setSuccess('重基计划已采用；已定稿正文保持不变。')
      await onAdopted(result.planning)
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        try {
          await refreshAfterConflict(candidate.id)
          setError(conflictMessage(caught.code))
        } catch (refreshError) {
          setError(refreshError instanceof Error ? refreshError.message : '冲突后刷新失败')
        }
      } else {
        setError(caught instanceof Error ? caught.message : '重基计划采用失败')
      }
    } finally {
      setBusy(false)
    }
  }

  const affectedLabels = useMemo(() => (
    impact?.affected_blueprint_fields.map((field) => blueprintFields.find((item) => item.field === field)?.label ?? field) ?? []
  ), [impact?.affected_blueprint_fields])

  if (!active) return null

  return (
    <section className="plan-rebase-workbench" aria-labelledby="plan-rebase-title">
      <header>
        <div>
          <small>PLAN REBASE</small>
          <h4 id="plan-rebase-title">安全更新全书计划</h4>
        </div>
        <span data-state={candidate?.state ?? (impact?.can_rebase ? 'ready' : 'current')}>
          {candidate?.state === 'adopted' ? '已采用' : candidate ? '候选未采用' : impact?.can_rebase ? '等待生成候选' : '无需更新'}
        </span>
      </header>

      {loading ? <p className="plan-rebase-status" role="status">正在核对选题、写作模式与计划版本…</p> : null}
      {impact ? (
        <>
          <div className="plan-rebase-impact">
            <div>
              <strong>计划为什么需要更新</strong>
              {impact.reasons.length > 0
                ? <ul>{impact.reasons.map((reason) => <li key={reason}>{dependencyReasonLabel(reason)}</li>)}</ul>
                : <p>当前计划已绑定最新选题与写作模式。</p>}
            </div>
            <div>
              <strong>会影响什么</strong>
              <p>{affectedLabels.length > 0 ? affectedLabels.join('、') : '没有待更新的蓝图字段'}</p>
              <p>{impact.targets.filter((target) => target.state === 'stale').length} 份计划待复核</p>
            </div>
            <div className="plan-rebase-safety">
              <strong>{impact.approved_chapter_count} 章已定稿正文不会改动</strong>
              <span>锁定字段与整份锁定计划会原样保留；只有最后“确认采用”才会替换正式计划。</span>
            </div>
          </div>
          {impact.targets.length > 0 ? (
            <ul className="plan-rebase-targets" aria-label="受影响计划">
              {impact.targets.map((target) => (
                <li key={`${target.kind}:${target.id}`} data-state={target.state}>
                  <strong>{targetLabels[target.kind]}</strong>
                  <span>{target.locked ? '整份锁定保留' : target.state === 'stale' ? '等待复核' : target.state === 'legacy' ? '旧版计划' : '已同步'}</span>
                  {target.stale_reasons.length ? <small>{target.stale_reasons.map(dependencyReasonLabel).join('；')}</small> : null}
                </li>
              ))}
            </ul>
          ) : null}
          {!candidate && impact.can_rebase ? (
            <button className="plan-rebase-primary" type="button" disabled={busy} onClick={() => { void createCandidate() }}>
              {busy ? '正在生成…' : '生成重基候选'}
            </button>
          ) : null}
          {!impact.can_rebase && impact.reasons.length > 0 ? (
            <p className="plan-rebase-blocked" role="status">当前依赖仍有阻断，请先按上方原因处理，再重新核对。</p>
          ) : null}
        </>
      ) : null}

      {candidate && draft ? (
        <div className="plan-rebase-candidate" aria-label="计划重基候选">
          <header ref={candidateHeadingRef} tabIndex={-1}>
            <div><small>候选 · 尚未写入正式计划</small><strong>逐项核对后再采用</strong></div>
            <span>{dirty ? '有未保存修改' : '候选已保存'}</span>
          </header>
          {candidate.book_blueprint && draft.bookBlueprint ? (
            <details open>
              <summary>整书蓝图 <small>{impact?.locked_blueprint_fields.length ?? 0} 项锁定保留</small></summary>
              <div className="plan-rebase-fields">
                {blueprintFields.map(({ field, label, multiline }) => {
                  const locked = candidate.book_blueprint?.locks[field] ?? false
                  const value = blueprintValue(draft.bookBlueprint!, field)
                  return (
                    <label key={field} data-locked={locked}>
                      <span>{label}{locked ? <em>锁定保留</em> : null}</span>
                      {field === 'genre' ? (
                        <select
                          aria-label={`${label}${locked ? '（锁定）' : ''}`}
                          value={draft.bookBlueprint!.genre}
                          disabled={busy || !editable || locked}
                          onChange={(event) => setDraft((current) => current?.bookBlueprint ? ({
                            ...current,
                            bookBlueprint: updateBlueprint(current.bookBlueprint, field, event.target.value),
                          }) : current)}
                        >
                          {genreOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                        </select>
                      ) : multiline ? (
                        <textarea
                          aria-label={`${label}${locked ? '（锁定）' : ''}`}
                          value={value}
                          rows={3}
                          readOnly={busy || !editable || locked}
                          onChange={(event) => setDraft((current) => current?.bookBlueprint ? ({
                            ...current,
                            bookBlueprint: updateBlueprint(current.bookBlueprint, field, event.target.value),
                          }) : current)}
                        />
                      ) : (
                        <input
                          aria-label={`${label}${locked ? '（锁定）' : ''}`}
                          type={field === 'rebirth_year' ? 'number' : 'text'}
                          value={value}
                          readOnly={busy || !editable || locked}
                          onChange={(event) => setDraft((current) => current?.bookBlueprint ? ({
                            ...current,
                            bookBlueprint: updateBlueprint(current.bookBlueprint, field, event.target.value),
                          }) : current)}
                        />
                      )}
                    </label>
                  )
                })}
              </div>
            </details>
          ) : null}

          {candidate.volume_plans.map((plan, index) => {
            const current = draft.volumePlans[index]
            if (!current) return null
            return (
              <details key={plan.id}>
                <summary>第 {current.content.volume_number} 卷 · {current.content.title} <small>{plan.locked ? '整份锁定保留' : '可编辑候选'}</small></summary>
                <div className="plan-rebase-fields">
                  {volumeFields.map(({ field, label, multiline }) => {
                    const value = current.content[field]
                    const controlProps = {
                      'aria-label': `${label}${plan.locked ? '（锁定）' : ''}`,
                      value: simpleValue(value),
                      readOnly: busy || !editable || plan.locked,
                      onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setDraft((previous) => {
                        if (!previous) return previous
                        return {
                          ...previous,
                          volumePlans: previous.volumePlans.map((item) => item.id === plan.id ? {
                            ...item,
                            content: { ...item.content, [field]: field === 'volume_number' ? Number(event.target.value) : event.target.value },
                          } : item),
                        }
                      }),
                    }
                    return <label key={field} data-locked={plan.locked}><span>{label}{plan.locked ? <em>锁定保留</em> : null}</span>{multiline ? <textarea {...controlProps} rows={3} /> : <input {...controlProps} type={field === 'volume_number' ? 'number' : 'text'} />}</label>
                  })}
                </div>
              </details>
            )
          })}

          {candidate.rolling_chapter_plans.map((plan, index) => {
            const current = draft.rollingPlans[index]
            if (!current) return null
            return (
              <details key={plan.id}>
                <summary>第 {current.content.chapter_number} 章 · {current.content.title} <small>{plan.locked ? '整份锁定保留' : '可编辑候选'}</small></summary>
                <div className="plan-rebase-fields">
                  {rollingFields.map(({ field, label, multiline }) => {
                    const value = current.content[field]
                    const update = (raw: string) => setDraft((previous) => {
                      if (!previous) return previous
                      return {
                        ...previous,
                        rollingPlans: previous.rollingPlans.map((item) => item.id === plan.id ? {
                          ...item,
                          content: { ...item.content, [field]: field === 'chapter_number' ? Number(raw) : raw },
                        } : item),
                      }
                    })
                    return (
                      <label key={field} data-locked={plan.locked}>
                        <span>{label}{plan.locked ? <em>锁定保留</em> : null}</span>
                        {multiline ? (
                          <textarea aria-label={`${label}${plan.locked ? '（锁定）' : ''}`} value={simpleValue(value)} rows={3} readOnly={busy || !editable || plan.locked} onChange={(event) => update(event.target.value)} />
                        ) : (
                          <input aria-label={`${label}${plan.locked ? '（锁定）' : ''}`} value={simpleValue(value)} type={field === 'chapter_number' ? 'number' : 'text'} readOnly={busy || !editable || plan.locked} onChange={(event) => update(event.target.value)} />
                        )}
                      </label>
                    )
                  })}
                  {current.content.scene_beats.map((beat, beatIndex) => (
                    <fieldset key={beat.ordinal} disabled={busy || !editable || plan.locked}>
                      <legend>场景 {beat.ordinal}</legend>
                      {(['summary', 'state_change', 'resource_change', 'emotional_turn', 'verification'] as const).map((field) => (
                        <label key={field}>
                          <span>{{ summary: '场景动作', state_change: '状态变化', resource_change: '资源变化', emotional_turn: '情绪转折', verification: '验证' }[field]}</span>
                          <textarea
                            aria-label={`场景 ${beat.ordinal} · ${{ summary: '场景动作', state_change: '状态变化', resource_change: '资源变化', emotional_turn: '情绪转折', verification: '验证' }[field]}`}
                            value={beat[field]}
                            rows={2}
                            onChange={(event) => setDraft((previous) => {
                              if (!previous) return previous
                              return {
                                ...previous,
                                rollingPlans: previous.rollingPlans.map((item) => item.id === plan.id ? {
                                  ...item,
                                  content: {
                                    ...item.content,
                                    scene_beats: item.content.scene_beats.map((itemBeat, itemIndex) => itemIndex === beatIndex ? { ...itemBeat, [field]: event.target.value } : itemBeat),
                                  },
                                } : item),
                              }
                            })}
                          />
                        </label>
                      ))}
                    </fieldset>
                  ))}
                </div>
              </details>
            )
          })}

          <footer>
            <button type="button" onClick={() => candidate && setDraft(copyDraft(candidate))} disabled={busy || !dirty}>撤销未保存修改</button>
            <button type="button" onClick={() => { void saveCandidate() }} disabled={busy || !editable || !dirty}>保存候选修改</button>
            <button className="plan-rebase-primary" type="button" onClick={() => { void adoptCandidate() }} disabled={busy || !editable || dirty}>
              确认采用重基计划
            </button>
          </footer>
          {dirty ? <p className="plan-rebase-hint">先保存候选修改，再确认采用；正式计划现在仍未改变。</p> : null}
        </div>
      ) : null}

      {success ? <p className="plan-rebase-success" role="status">{success}</p> : null}
      {error ? <p className="plan-rebase-error" role="alert">{error}</p> : null}
    </section>
  )
}
