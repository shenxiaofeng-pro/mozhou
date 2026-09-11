import type {
  AdoptPatternAdaptationResult,
  PatternAdaptationAdoption,
  BookBlueprintContent,
  BookBlueprintField,
  Genre,
  Job,
  PatternAdaptationCandidate,
  PatternAdaptationPreflight,
  PatternAdaptationPreflightInput,
  PatternAdaptationProposal,
  PatternDistinctAxis,
  PatternOriginalityReport,
  PatternOriginalityGateState,
  WritingPatternProfileVersion,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { useEffect, useState } from 'react'

import { ApiError, api } from '../api'
import { genreOptions, getStoryAnchorLabels } from '../genre'

interface PatternAdaptationWorkbenchProps {
  workspace: WorkspaceSummary
  profile: WritingPatternProfileVersion | null
  onWorkspaceChanged?: (workspace: WorkspaceSummary) => void
}

const blueprintFields: Array<{ field: BookBlueprintField; label: string; multiline?: boolean }> = [
  { field: 'title', label: '书名' },
  { field: 'genre', label: '题材' },
  { field: 'rebirth_year', label: '时代年份' },
  { field: 'rebirth_location', label: '时代地点' },
  { field: 'target_audience', label: '目标读者', multiline: true },
  { field: 'core_selling_points', label: '核心卖点（每行一条）', multiline: true },
  { field: 'core_desire', label: '核心欲望', multiline: true },
  { field: 'divergence_point', label: '故事分歧点', multiline: true },
  { field: 'long_term_promise', label: '长线承诺', multiline: true },
  { field: 'ending_direction', label: '结局方向', multiline: true },
  { field: 'protagonist_arc', label: '主角成长弧', multiline: true },
  { field: 'resource_growth', label: '资源成长线', multiline: true },
  { field: 'relationship_design', label: '人物关系设计', multiline: true },
]

const axisLabels: Record<PatternDistinctAxis, string> = {
  core_conflict: '核心冲突',
  character_relationships: '人物关系',
  resource_progression: '资源成长',
  scene_organization: '场景组织',
  ending: '结局方向',
}

const riskLabels = { low: '低风险', medium: '中风险', high: '高风险' } as const

function shortHash(value: string): string {
  return value.slice(0, 10)
}

function formatCost(value: number | null): string {
  return value === null ? '费用未知' : `US$ ${(value / 1_000_000).toFixed(4)}`
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`)
      .join(',')}}`
  }
  return JSON.stringify(value)
}

async function blueprintContentSha256(content: BookBlueprintContent): Promise<string> {
  const bytes = new TextEncoder().encode(canonicalJson(content))
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

function adaptationErrorMessage(error: ApiError): string {
  const messages: Record<string, string> = {
    topic_not_confirmed: '当前选题尚未确认，暂时不能生成整书候选。',
    topic_changed: '选题已经变化。作者意图已保留，请重新预检。',
    profile_unavailable: '当前写作模式不可用，请先恢复或重新装入。',
    profile_changed: '写作模式已经变化。作者意图已保留，请重新预检。',
    recipe_changed: '写作配方已经变化，请重新预检。',
    base_blueprint_changed: '整书蓝图已经变化，请重新预检。',
    preview_changed: '预检依据已经变化，请重新预检后提交。',
    cost_unavailable: '当前远程模型没有费用配置，系统不会启动任务。',
    cost_limit_required: '请填写允许启动的预估费用上限。',
    estimated_cost_exceeds_limit: '最新预估费用超过允许启动的上限，请重新确认。',
    external_processing_not_confirmed: '请先确认把已净化的抽象创作资料发送给当前模型线路。',
    candidate_changed: '候选已在其他位置更新，请刷新结果后继续。',
    proposal_stale: '候选基于旧版选题、配方或蓝图，不能采用，请重新预检。',
    locked_field: '调整触及作者锁定的蓝图字段，已阻止保存。',
    relationships_must_be_rebuilt: '人物关系仍与原蓝图一致，请完成重构后再保存。',
    declared_fields_do_not_match: '候选修改范围已变化，请重新打开候选编辑。',
    guard_dependencies_changed: '蓝图或配方已经变化，请重新运行原创性检查。',
    high_risk_cannot_be_acknowledged: '高风险方案不能手动确认通过，请调整蓝图后重跑检查。',
    report_must_be_viewed: '请先查看完整风险报告，再确认中风险方案。',
  }
  return error.code ? messages[error.code] ?? error.message : error.message
}

function updateBlueprintField(
  content: BookBlueprintContent,
  field: BookBlueprintField,
  rawValue: string,
): BookBlueprintContent {
  if (field === 'genre') return { ...content, genre: rawValue as Genre }
  if (field === 'rebirth_year') return { ...content, rebirth_year: Number(rawValue) }
  if (field === 'core_selling_points') {
    return { ...content, core_selling_points: rawValue.split('\n').map((item) => item.trim()).filter(Boolean) }
  }
  return { ...content, [field]: rawValue }
}

function displayBlueprintField(content: BookBlueprintContent, field: BookBlueprintField): string {
  const value = content[field]
  return Array.isArray(value) ? value.join('\n') : String(value)
}

function changedBlueprintFields(
  before: BookBlueprintContent,
  after: BookBlueprintContent,
): BookBlueprintField[] {
  return blueprintFields
    .map(({ field }) => field)
    .filter((field) => JSON.stringify(before[field]) !== JSON.stringify(after[field]))
}

function CandidateEditor({
  candidate,
  lockedFields,
  busy,
  onCancel,
  onSave,
}: {
  candidate: PatternAdaptationCandidate
  lockedFields: Set<BookBlueprintField>
  busy: boolean
  onCancel: () => void
  onSave: (blueprint: BookBlueprintContent, scenes: string[], notes: string[]) => void
}) {
  const [blueprint, setBlueprint] = useState(candidate.current_version.blueprint)
  const [scenes, setScenes] = useState(candidate.current_version.key_scene_sequence.join('\n'))
  const [notes, setNotes] = useState(candidate.current_version.transformation_notes.join('\n'))
  const anchors = getStoryAnchorLabels(blueprint.genre)

  function fieldLabel(field: BookBlueprintField, fallback: string): string {
    if (field === 'rebirth_year') return anchors.year
    if (field === 'rebirth_location') return anchors.location
    if (field === 'divergence_point') return anchors.divergence
    return fallback
  }

  const sceneItems = scenes.split('\n').map((item) => item.trim()).filter(Boolean)
  const noteItems = notes.split('\n').map((item) => item.trim()).filter(Boolean)
  const hasChanges = changedBlueprintFields(candidate.current_version.blueprint, blueprint).length > 0
    || JSON.stringify(sceneItems) !== JSON.stringify(candidate.current_version.key_scene_sequence)
    || JSON.stringify(noteItems) !== JSON.stringify(candidate.current_version.transformation_notes)
  const valid = sceneItems.length >= 3 && sceneItems.length <= 8 && noteItems.length >= 1 && noteItems.length <= 8

  return (
    <div className="adaptation-candidate-editor">
      <p className="adaptation-editor-note">只调整你的新故事。带“已锁定”的字段来自作者锁定，不能改动。</p>
      <div className="adaptation-blueprint-fields">
        {blueprintFields.map(({ field, label, multiline }) => {
          const locked = lockedFields.has(field)
          const resolvedLabel = fieldLabel(field, label)
          if (field === 'genre') {
            return (
              <label key={field}>{resolvedLabel}{locked ? ' · 已锁定' : ''}
                <select disabled={locked || busy} value={blueprint.genre} onChange={(event) => setBlueprint(updateBlueprintField(blueprint, field, event.target.value))}>
                  {genreOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
            )
          }
          if (!multiline && field !== 'rebirth_year') {
            return <label key={field}>{resolvedLabel}{locked ? ' · 已锁定' : ''}<input disabled={locked || busy} value={displayBlueprintField(blueprint, field)} onChange={(event) => setBlueprint(updateBlueprintField(blueprint, field, event.target.value))} /></label>
          }
          if (field === 'rebirth_year') {
            return <label key={field}>{resolvedLabel}{locked ? ' · 已锁定' : ''}<input type="number" disabled={locked || busy} value={blueprint.rebirth_year} onChange={(event) => setBlueprint(updateBlueprintField(blueprint, field, event.target.value))} /></label>
          }
          return <label key={field}>{resolvedLabel}{locked ? ' · 已锁定' : ''}<textarea rows={3} disabled={locked || busy} value={displayBlueprintField(blueprint, field)} onChange={(event) => setBlueprint(updateBlueprintField(blueprint, field, event.target.value))} /></label>
        })}
      </div>
      <label>关键场景顺序（每行一个，3–8 个）<textarea rows={5} disabled={busy} value={scenes} onChange={(event) => setScenes(event.target.value)} /></label>
      <label>转化说明（每行一个，1–8 条）<textarea rows={4} disabled={busy} value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
      {!valid ? <p className="recipe-field-error" role="alert">请填写 3–8 个关键场景和 1–8 条转化说明。</p> : null}
      <div className="adaptation-editor-actions">
        <button type="button" disabled={busy} onClick={onCancel}>取消调整</button>
        <button type="button" disabled={busy || !valid || !hasChanges} onClick={() => onSave(blueprint, sceneItems, noteItems)}>保存候选调整</button>
      </div>
    </div>
  )
}

export function PatternAdaptationWorkbench({
  workspace,
  profile,
  onWorkspaceChanged,
}: PatternAdaptationWorkbenchProps) {
  const profileReady = profile?.lifecycle_state === 'active' && profile.is_current
  const [authorIntent, setAuthorIntent] = useState('')
  const [preflightInput, setPreflightInput] = useState<PatternAdaptationPreflightInput | null>(null)
  const [preflight, setPreflight] = useState<PatternAdaptationPreflight | null>(null)
  const [confirmedExternal, setConfirmedExternal] = useState(false)
  const [costLimit, setCostLimit] = useState('')
  const [job, setJob] = useState<Job | null>(null)
  const [proposal, setProposal] = useState<PatternAdaptationProposal | null>(null)
  const [editingCandidateId, setEditingCandidateId] = useState<string | null>(null)
  const [adoption, setAdoption] = useState<PatternAdaptationAdoption | null>(null)
  const gateKey = `${workspace.project.id}:${workspace.book_blueprint?.revision ?? 'none'}`
  const [gateResult, setGateResult] = useState<{
    key: string
    state: PatternOriginalityGateState | null
  } | null>(null)
  const [gateReload, setGateReload] = useState(0)
  const [report, setReport] = useState<PatternOriginalityReport | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const gateResolved = gateResult?.key === gateKey
  const gate = gateResolved ? gateResult.state : null
  const gateLoading = !gateResolved
  const candidateLockedFields = new Set<BookBlueprintField>(
    preflight?.locked_fields ?? blueprintFields.filter(({ field }) => workspace.book_blueprint?.locks[field]).map(({ field }) => field),
  )

  useEffect(() => {
    let active = true
    api.getPatternOriginalityGate(workspace.project.id)
      .then((state) => {
        if (!active) return
        setGateResult({ key: gateKey, state })
        setAdoption(state.adoption)
        setReport(state.report_is_current ? state.latest_report : null)
      })
      .catch((caught: unknown) => {
        if (!active) return
        setGateResult({ key: gateKey, state: null })
        setError(caught instanceof Error ? caught.message : '无法恢复当前原创性门禁')
      })
    return () => { active = false }
  }, [gateKey, gateReload, workspace.project.id])

  useEffect(() => {
    if (!job || ['succeeded', 'failed', 'interrupted', 'cancelled'].includes(job.state)) return undefined
    let stopped = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const current = await api.getJob(job.id)
        if (stopped) return
        setJob(current)
        if (current.state === 'succeeded') {
          setProposal(await api.getPatternAdaptationResult(workspace.project.id, current.id))
          return
        }
        if (['failed', 'interrupted', 'cancelled'].includes(current.state)) {
          setError(current.error_message ?? '候选任务未完成，请重新预检后再试。')
          return
        }
        timer = window.setTimeout(poll, 700)
      } catch (caught) {
        if (!stopped) setError(caught instanceof Error ? caught.message : '无法读取候选任务')
      }
    }
    timer = window.setTimeout(poll, 400)
    return () => {
      stopped = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [job, workspace.project.id])

  function invalidatePreflight() {
    setPreflight(null)
    setPreflightInput(null)
    setConfirmedExternal(false)
    setCostLimit('')
  }

  function reportError(caught: unknown, fallback: string, invalidate = false) {
    if (invalidate) invalidatePreflight()
    setError(caught instanceof ApiError ? adaptationErrorMessage(caught) : caught instanceof Error ? caught.message : fallback)
  }

  async function previewAdaptation() {
    if (!profileReady || !profile) return
    setBusy('preflight')
    setError(null)
    setNotice(null)
    try {
      const currentBlueprint = workspace.book_blueprint
      const input: PatternAdaptationPreflightInput = {
        profile_version_id: profile.id,
        expected_profile_fingerprint_sha256: profile.profile_fingerprint_sha256,
        expected_topic_revision: profile.topic_revision,
        expected_topic_content_sha256: profile.topic_content_sha256,
        expected_base_blueprint_revision: currentBlueprint?.revision ?? null,
        expected_base_blueprint_content_sha256: currentBlueprint
          ? await blueprintContentSha256(currentBlueprint.content)
          : null,
        author_intent: authorIntent.trim(),
        provider_profile_id: null,
      }
      const result = await api.previewPatternAdaptation(workspace.project.id, input)
      setPreflightInput(input)
      setPreflight(result)
      setConfirmedExternal(false)
      setCostLimit(result.estimated_cost_microusd === null ? '' : (result.estimated_cost_microusd / 1_000_000).toFixed(4))
    } catch (caught) {
      reportError(caught, '无法预检原创迁移任务', true)
    } finally {
      setBusy(null)
    }
  }

  async function loadResult(jobId: string) {
    const result = await api.getPatternAdaptationResult(workspace.project.id, jobId)
    setProposal(result)
    if (result.result_state !== 'available') {
      setError('这组候选依赖已经变化，请保留作者意图并重新预检。')
    }
  }

  async function submitAdaptation() {
    if (!preflight || !preflightInput || !confirmedExternal || preflight.cost_status === 'unavailable') return
    setBusy('submit')
    setError(null)
    setNotice(null)
    try {
      const maxCost = preflight.cost_status === 'known' ? Math.round(Number(costLimit) * 1_000_000) : null
      const created = await api.startPatternAdaptation(workspace.project.id, {
        ...preflightInput,
        expected_preview_sha256: preflight.preview_sha256,
        confirm_external_processing: true,
        max_estimated_cost_microusd: maxCost,
      })
      setJob(created)
      if (created.state === 'succeeded') await loadResult(created.id)
      else setNotice('候选任务已创建；完成后会在这里展开三套方案。')
    } catch (caught) {
      reportError(caught, '无法创建原创迁移任务', caught instanceof ApiError && caught.status === 409)
    } finally {
      setBusy(null)
    }
  }

  async function saveCandidate(
    candidate: PatternAdaptationCandidate,
    blueprint: BookBlueprintContent,
    scenes: string[],
    notes: string[],
  ) {
    const changed = changedBlueprintFields(candidate.current_version.blueprint, blueprint)
    setBusy(`edit:${candidate.id}`)
    setError(null)
    try {
      const updated = await api.editPatternAdaptationCandidate(workspace.project.id, candidate.id, {
        blueprint,
        key_scene_sequence: scenes,
        transformation_notes: notes,
        changed_fields: changed,
        expected_revision: candidate.current_version.revision,
        expected_content_sha256: candidate.current_version.content_sha256,
      })
      setProposal((current) => current ? {
        ...current,
        candidates: current.candidates.map((item) => item.id === updated.id ? updated : item),
      } : current)
      setEditingCandidateId(null)
      setNotice('候选调整已保存为新修订；另外两套候选保持不变。')
    } catch (caught) {
      reportError(caught, '无法保存候选调整')
    } finally {
      setBusy(null)
    }
  }

  async function adoptAndCheck(candidate: PatternAdaptationCandidate) {
    if (!proposal) return
    setBusy(`adopt:${candidate.id}`)
    setError(null)
    setNotice(null)
    setReport(null)
    let completedAdoption: AdoptPatternAdaptationResult | null = null
    try {
      const result = await api.adoptPatternAdaptationCandidate(workspace.project.id, candidate.id, {
        expected_candidate_revision: candidate.current_version.revision,
        expected_candidate_content_sha256: candidate.current_version.content_sha256,
        expected_profile_fingerprint_sha256: proposal.profile_fingerprint_sha256,
        expected_recipe_content_sha256: proposal.recipe_content_sha256,
        expected_topic_revision: proposal.topic_revision,
        expected_topic_content_sha256: proposal.topic_content_sha256,
        expected_base_blueprint_revision: proposal.base_blueprint_revision,
        expected_base_blueprint_content_sha256: proposal.base_blueprint_content_sha256,
        idempotency_key: `pattern-adopt:${candidate.id}:${candidate.current_version.id}`,
      })
      completedAdoption = result
      setAdoption(result.adoption)
      if (gateKey) {
        setGateResult({
          key: gateKey,
          state: {
            project_id: workspace.project.id,
            state: 'needs_check',
            reason: 'originality_check_required',
            requires_check: true,
            adoption: result.adoption,
            blueprint_id: result.blueprint.id,
            blueprint_revision: result.adoption.blueprint_revision,
            blueprint_content_sha256: result.adoption.blueprint_content_sha256,
            latest_report: null,
            report_is_current: false,
          },
        })
      }
      if (onWorkspaceChanged) {
        onWorkspaceChanged(await api.getProjectSummary(workspace.project.id))
      }
      const checked = await api.runPatternOriginalityCheck(workspace.project.id, {
        expected_blueprint_revision: result.adoption.blueprint_revision,
        expected_blueprint_content_sha256: result.adoption.blueprint_content_sha256,
        expected_profile_fingerprint_sha256: result.adoption.profile_fingerprint_sha256,
        expected_recipe_content_sha256: result.adoption.recipe_content_sha256,
      })
      setReport(checked)
      syncGateWithReport(checked, result.adoption)
    } catch (caught) {
      reportError(caught, completedAdoption ? '候选已采用，但原创性检查尚未完成，请重试检查。' : '无法采用候选')
    } finally {
      setBusy(null)
    }
  }

  function syncGateWithReport(
    nextReport: PatternOriginalityReport,
    nextAdoption: PatternAdaptationAdoption | null = adoption,
  ) {
    if (!gateKey) return
    setGateResult((current) => ({
      key: gateKey,
      state: {
        project_id: workspace.project.id,
        state: nextReport.status === 'blocked'
          ? 'blocked'
          : nextReport.status === 'review_required' ? 'review_required' : nextReport.status === 'passed' ? 'passed' : 'needs_check',
        reason: nextReport.status,
        requires_check: nextReport.status !== 'passed',
        adoption: nextAdoption ?? current?.state?.adoption ?? null,
        blueprint_id: nextReport.blueprint_id,
        blueprint_revision: nextReport.blueprint_revision,
        blueprint_content_sha256: nextReport.blueprint_content_sha256,
        latest_report: nextReport,
        report_is_current: true,
      },
    }))
  }

  async function runCurrentOriginalityCheck() {
    if (!adoption) return
    const blueprintRevision = gate?.blueprint_revision ?? adoption.blueprint_revision
    const blueprintHash = gate?.blueprint_content_sha256 ?? adoption.blueprint_content_sha256
    if (blueprintRevision === null || blueprintHash === null) {
      setError('无法读取当前实际蓝图版本，请刷新工作台后重试。')
      return
    }
    setBusy('check')
    setError(null)
    try {
      const checked = await api.runPatternOriginalityCheck(workspace.project.id, {
        expected_blueprint_revision: blueprintRevision,
        expected_blueprint_content_sha256: blueprintHash,
        expected_profile_fingerprint_sha256: adoption.profile_fingerprint_sha256,
        expected_recipe_content_sha256: adoption.recipe_content_sha256,
      })
      setReport(checked)
      syncGateWithReport(checked)
    } catch (caught) {
      reportError(caught, '无法重新运行原创性检查')
    } finally {
      setBusy(null)
    }
  }

  async function viewReport() {
    if (!report) return
    setBusy('view-report')
    setError(null)
    try {
      const viewed = await api.viewPatternOriginalityReport(report.id)
      setReport(viewed)
      syncGateWithReport(viewed)
    } catch (caught) {
      reportError(caught, '无法打开完整原创性报告')
    } finally {
      setBusy(null)
    }
  }

  async function acknowledgeReport() {
    if (!report || report.risk_level !== 'medium' || !report.viewed_at) return
    setBusy('ack-report')
    setError(null)
    try {
      const acknowledged = await api.acknowledgePatternOriginalityReport(report.id)
      setReport(acknowledged)
      syncGateWithReport(acknowledged)
      setNotice('中风险项已由作者查看并确认。后续规划可以使用这版蓝图。')
    } catch (caught) {
      reportError(caught, '无法确认原创改编')
    } finally {
      setBusy(null)
    }
  }

  const canSubmit = confirmedExternal
    && preflight !== null
    && preflight.cost_status !== 'unavailable'
    && (preflight.cost_status !== 'known' || (Number(costLimit) >= (preflight.estimated_cost_microusd ?? 0) / 1_000_000))

  return (
    <section className="adaptation-workbench" aria-labelledby="adaptation-heading">
      <header className="adaptation-heading">
        <div><small>05 / ADAPT</small><h2 id="adaptation-heading">把模式迁移成你的原创蓝图</h2></div>
        <span>{profileReady && profile ? `当前模式 ${shortHash(profile.profile_fingerprint_sha256)}` : '当前无可用模式'}</span>
      </header>
      <p className="adaptation-lead">你给方向，AI 主写三套结构明显不同的整书候选；任何候选都不会自动覆盖蓝图。</p>
      {gateLoading ? <p className="recipe-page-notice" role="status">正在恢复实际蓝图的原创性门禁…</p> : null}
      {gateResolved && gate === null ? (
        <div className="adaptation-stale" role="alert">
          <strong>暂时无法读取实际蓝图门禁</strong>
          <p>为避免把已采用蓝图误当成未采用，恢复成功前不会启动新的迁移。</p>
          <button type="button" onClick={() => { setError(null); setGateResult(null); setGateReload((value) => value + 1) }}>重新读取</button>
        </div>
      ) : null}
      {gate && gate.state !== 'needs_adaptation' && gate.state !== 'legacy' ? (
        <div className="adaptation-gate-summary" role="status" data-state={gate.state}>
          <strong>{gate.state === 'passed'
            ? '当前实际蓝图已通过原创性门禁'
            : gate.state === 'review_required'
              ? '当前实际蓝图等待作者确认'
              : gate.state === 'blocked'
                ? '当前实际蓝图被高风险阻断'
                : gate.state === 'stale'
                  ? '蓝图已调整，旧检查报告已过期'
                  : '蓝图已采用，等待原创性检查'}</strong>
          <span>{gate.state === 'stale' ? '请按当前蓝图版本重新运行检查。' : '这里显示的是刷新后恢复的实际状态。'}</span>
        </div>
      ) : null}
      {error ? <p className="agent-error" role="alert">{error}</p> : null}
      {notice ? <p className="recipe-page-notice" role="status">{notice}</p> : null}

      {!profileReady || !profile ? (
        <div className="adaptation-gate" role="note">
          <strong>新建迁移前，请启用与当前选题一致的项目模式</strong>
          <p>已采用蓝图和原创性门禁仍会在下方恢复；归档模式不会绕过已有检查。</p>
        </div>
      ) : <div className="adaptation-intent-panel">
        <label htmlFor="adaptation-author-intent">这次迁移最想改变什么</label>
        <textarea
          id="adaptation-author-intent"
          rows={4}
          maxLength={1000}
          value={authorIntent}
          placeholder="例如：保留逆境开局的功能，但把人物关系、资源路径和关键场景顺序全部重构。不要粘贴参考作品原文。"
          onChange={(event) => { setAuthorIntent(event.target.value); invalidatePreflight() }}
        />
        <small>{authorIntent.length}/1000 · 只写你希望新故事如何变化，不要粘贴参考原文或书名。</small>
        <button type="button" disabled={busy !== null || gateLoading || gate === null || authorIntent.trim().length === 0} onClick={() => { void previewAdaptation() }}>预览范围与费用</button>
      </div>}

      {profileReady && profile && preflight ? (
        <section className="adaptation-preflight" aria-label="候选任务预检">
          <header><div><small>发送前确认</small><h3>{preflight.content_scope}</h3></div><strong>{formatCost(preflight.estimated_cost_microusd)}</strong></header>
          <dl>
            <div><dt>模型线路</dt><dd>{preflight.provider_profile_name} · {preflight.model}</dd></div>
            <div><dt>预计用量</dt><dd>{preflight.estimated_input_tokens.toLocaleString('zh-CN')} 输入 / {preflight.estimated_output_tokens.toLocaleString('zh-CN')} 输出 token</dd></div>
            <div><dt>安全依据</dt><dd>{preflight.source_availability === 'source_verified' ? '来源可核验' : '仅抽象模式'}</dd></div>
            <div><dt>人物关系</dt><dd>默认重构，不沿用旧关系</dd></div>
          </dl>
          <div className="adaptation-scope-list" aria-label="将发送的数据类型">
            {preflight.data_types.map((item) => <span key={item}>{item}</span>)}
          </div>
          <p className="adaptation-safe-note">不会发送参考书原文、书名、证据句或来源坐标。只发送已确认选题、抽象规则、当前蓝图和你的迁移意图。</p>
          {preflight.locked_fields.length > 0 ? <p>作者锁定：{preflight.locked_fields.map((field) => blueprintFields.find((item) => item.field === field)?.label ?? field).join('、')}</p> : null}
          {preflight.cost_status === 'unavailable' ? (
            <p className="agent-error" role="alert">费用未知：当前远程模型未配置价格，系统不会启动任务。请先在模型设置中补齐价格。</p>
          ) : (
            <>
              {preflight.cost_status === 'known' ? (
                <label>允许启动的预估费用上限（US$）
                  <input type="number" min={(preflight.estimated_cost_microusd ?? 0) / 1_000_000} step="0.0001" value={costLimit} onChange={(event) => setCostLimit(event.target.value)} />
                  <small>只用于决定是否启动；实际费用按模型服务商 token 用量，可能有偏差。</small>
                </label>
              ) : <p>当前线路为本地免费调用，仍需确认抽象资料范围。</p>}
              <label className="adaptation-confirm">
                <input aria-label="确认发送上述抽象创作资料" type="checkbox" checked={confirmedExternal} onChange={(event) => setConfirmedExternal(event.target.checked)} />
                <span><strong>确认发送上述抽象创作资料</strong><small>生成结果只进入候选区，不会自动采用。</small></span>
              </label>
            </>
          )}
          <button type="button" disabled={busy !== null || !canSubmit} onClick={() => { void submitAdaptation() }}>生成 3 套候选</button>
        </section>
      ) : null}

      {profileReady && profile && job && !proposal ? (
        <section className="adaptation-job" aria-live="polite">
          <strong>{job.state === 'succeeded' ? '正在展开候选…' : job.current_step || '正在生成三套候选…'}</strong>
          <span>{job.progress_current}/{job.progress_total}</span>
        </section>
      ) : null}

      {profileReady && profile && proposal ? (
        <section className="adaptation-comparison" role="region" aria-label="三套原创迁移候选">
          <header><div><small>COMPARE 3 WAYS</small><h3>三套结构路线并排比较</h3></div><span>所有方案都只是候选 · 作者确认后才采用</span></header>
          {proposal.result_state !== 'available' || proposal.candidates.length !== 3 ? (
            <div className="adaptation-stale" role="alert">
              <strong>候选基于旧版依赖</strong>
              <p>{proposal.stale_reason ?? '选题、配方或蓝图已经变化。'}</p>
              <button type="button" onClick={() => { setProposal(null); setJob(null); invalidatePreflight() }}>重新预检</button>
            </div>
          ) : (
            <div className="adaptation-candidate-grid">
              {proposal.candidates.map((candidate) => (
                <article key={candidate.id} className="adaptation-candidate" data-ordinal={candidate.ordinal}>
                  <header><span>候选 {candidate.ordinal}/3</span><small>{candidate.current_version.source === 'author_edit' ? `作者修订 ${candidate.current_version.revision}` : 'AI 候选'}</small></header>
                  <h4>{candidate.label}</h4>
                  <p>{candidate.why_distinct}</p>
                  <div className="adaptation-axis-list">{candidate.distinct_axes.map((axis) => <span key={axis}>{axisLabels[axis]}</span>)}</div>
                  <dl className="adaptation-candidate-core">
                    <div><dt>核心冲突</dt><dd>{candidate.current_version.blueprint.divergence_point}</dd></div>
                    <div><dt>人物关系</dt><dd>{candidate.current_version.blueprint.relationship_design}</dd></div>
                    <div><dt>资源成长</dt><dd>{candidate.current_version.blueprint.resource_growth}</dd></div>
                    <div><dt>结局方向</dt><dd>{candidate.current_version.blueprint.ending_direction}</dd></div>
                  </dl>
                  <details><summary>查看关键场景与转化说明</summary>
                    <ol>{candidate.current_version.key_scene_sequence.map((scene) => <li key={scene}>{scene}</li>)}</ol>
                    <ul>{candidate.current_version.transformation_notes.map((note) => <li key={note}>{note}</li>)}</ul>
                  </details>
                  {candidate.risk_hypotheses.length > 0 ? <p className="adaptation-hypothesis">待核对：{candidate.risk_hypotheses.join('；')}</p> : null}
                  {editingCandidateId === candidate.id ? (
                    <CandidateEditor
                      candidate={candidate}
                      lockedFields={candidateLockedFields}
                      busy={busy === `edit:${candidate.id}`}
                      onCancel={() => setEditingCandidateId(null)}
                      onSave={(nextBlueprint, scenes, notes) => { void saveCandidate(candidate, nextBlueprint, scenes, notes) }}
                    />
                  ) : (
                    <div className="adaptation-candidate-actions">
                      <button type="button" disabled={busy !== null || adoption !== null} onClick={() => setEditingCandidateId(candidate.id)}>调整此候选</button>
                      <button type="button" disabled={busy !== null || adoption !== null} onClick={() => { void adoptAndCheck(candidate) }}>{adoption?.candidate_id === candidate.id ? '已采用，等待门禁' : adoption ? '原候选已过期' : '采用并检查原创性'}</button>
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}
        </section>
      ) : null}

      {adoption && !report ? (
        <section className="adaptation-originality" role="status">
          <h3>{gate?.state === 'stale' ? '蓝图已调整，旧检查报告已过期' : '蓝图已采用，原创性检查尚未完成'}</h3>
          <p>{gate?.state === 'stale' ? '系统会按当前实际蓝图的最新版本重跑，不会沿用采用时的旧指纹。' : '在检查通过前，请不要让后续规划使用这版蓝图。'}</p>
          <button type="button" disabled={busy !== null} onClick={() => { void runCurrentOriginalityCheck() }}>{busy === 'check' ? '正在检查…' : '重新运行检查'}</button>
        </section>
      ) : null}

      {report ? (
        <section className="adaptation-originality" data-risk={report.risk_level} aria-labelledby="adaptation-report-heading">
          <header><div><small>实际蓝图原创性报告</small><h3 id="adaptation-report-heading">{riskLabels[report.risk_level]} · {report.score} 分</h3></div><strong>{report.status === 'passed' ? '原创性检查已通过' : report.status === 'blocked' ? '已阻断' : '需要作者确认'}</strong></header>
          <p>{report.risk_level === 'high'
            ? '结构组合与来源模式过于接近。必须调整蓝图并重新检查，不能手动放行。'
            : report.risk_level === 'medium'
              ? '先阅读完整报告，确认人物关系、因果链和场景顺序已经完成原创重构。'
              : '未发现需要阻断的结构组合风险。'}</p>
          <dl><div><dt>检查阈值</dt><dd>{report.threshold_version}</dd></div><div><dt>检查依据</dt><dd>{report.source_availability === 'source_verified' ? '来源可核验' : '仅抽象依据，风险下限为中等'}</dd></div></dl>
          {!report.viewed_at ? <button type="button" disabled={busy !== null} onClick={() => { void viewReport() }}>查看完整风险报告</button> : (
            <div className="adaptation-findings">
              <h4>风险项</h4>
              {report.findings.length === 0 ? <p>没有发现需要单列的风险项。</p> : report.findings.map((finding) => (
                <article key={finding.id}><strong>{finding.score} 分 · {finding.signal}</strong><p>{finding.summary}</p><small>验证指纹 {shortHash(finding.evidence_sha256)}</small></article>
              ))}
            </div>
          )}
          {report.risk_level === 'medium' && report.status === 'review_required' && report.viewed_at ? (
            <button type="button" disabled={busy !== null} onClick={() => { void acknowledgeReport() }}>确认已完成原创改编</button>
          ) : null}
          {report.risk_level === 'high' ? <p className="adaptation-hard-stop" role="alert">高风险不能确认通过。请编辑当前实际蓝图并按最新版本重跑检查，或重新预检生成新的三套候选。</p> : null}
        </section>
      ) : null}
    </section>
  )
}
