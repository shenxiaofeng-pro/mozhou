import type {
  AiStatus,
  Job,
  TopicDecisionCandidate,
  TopicDecisionCandidateSet,
  TopicDecisionContent,
  TopicDecisionField,
  TopicDecisionOutboundPreview,
  Workspace,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { useEffect, useState } from 'react'

import { ApiError, api } from '../api'
import { ModelSettingsPanel } from './ModelSettingsPanel'

interface TopicDecisionWorkbenchProps {
  workspace: WorkspaceSummary
  onWorkspaceChanged: (workspace: Workspace | WorkspaceSummary) => void
  onContinue: () => void
  onClose: () => void
  onOpenTaskCenter: () => void
}

interface TopicFieldDefinition {
  field: TopicDecisionField
  label: string
  prompt: string
  list?: boolean
  compact?: boolean
  maxLength: number
}

const topicFields: TopicFieldDefinition[] = [
  { field: 'target_platform', label: '首发平台', prompt: '例如：番茄、起点、晋江；写清平台调性与篇幅预期。', compact: true, maxLength: 120 },
  { field: 'target_audience', label: '目标读者', prompt: '谁会持续追更？年龄、阅读偏好、爽点期待是什么？', maxLength: 500 },
  { field: 'subgenre', label: '细分题材', prompt: '例如：东方玄幻·宗门经营，或都市重生·实业创业。', compact: true, maxLength: 120 },
  { field: 'premise', label: '一句话命题', prompt: '主角是谁、遇到什么变化、要完成什么高难目标？', maxLength: 3000 },
  { field: 'core_desire', label: '核心欲望', prompt: '主角最深的渴望是什么？它为什么足以推动长篇？', maxLength: 1200 },
  { field: 'long_term_promise', label: '长期追更承诺', prompt: '读者每隔一段时间能持续获得什么升级、变化或回报？', maxLength: 1500 },
  { field: 'first_three_chapter_promise', label: '前三章承诺', prompt: '前三章分别用什么钩子，让读者看见题材、能力与主冲突？', maxLength: 1500 },
  { field: 'constraints', label: '必须遵守', prompt: '每行一条，最多 20 条；例如：主角能力有明确代价。', list: true, maxLength: 10000 },
  { field: 'forbidden_elements', label: '明确不要', prompt: '每行一条，最多 20 条；例如：不写系统面板、不靠降智反派。', list: true, maxLength: 10000 },
  { field: 'reference_purpose', label: '参考作品怎么用', prompt: '只写要借鉴的抽象功能：节奏、钩子类型、资源循环等，不复制桥段。', maxLength: 1200 },
  { field: 'reality_anchor', label: '现实／世界锚点', prompt: '历史、地域、行业或世界规则中，哪些事实必须可信且稳定？', maxLength: 1500 },
  { field: 'first_ten_chapter_goal', label: '前十章目标', prompt: '第十章结束时，主角、资源、关系与主线必须推进到哪里？', maxLength: 1500 },
]

const fieldLabels = Object.fromEntries(
  topicFields.map(({ field, label }) => [field, label]),
) as Record<TopicDecisionField, string>

const terminalJobStates = new Set(['failed', 'interrupted', 'cancelled'])

function displayFieldValue(content: TopicDecisionContent, field: TopicDecisionField): string {
  const value = content[field]
  return Array.isArray(value) ? value.join('\n') : value
}

function updateFieldValue(
  content: TopicDecisionContent,
  field: TopicDecisionField,
  rawValue: string,
): TopicDecisionContent {
  if (field === 'constraints' || field === 'forbidden_elements') {
    return {
      ...content,
      [field]: rawValue.split('\n').slice(0, 20),
    }
  }
  return { ...content, [field]: rawValue }
}

function normalizeContent(content: TopicDecisionContent): TopicDecisionContent {
  return {
    ...content,
    constraints: content.constraints.map((item) => item.trim()).filter(Boolean),
    forbidden_elements: content.forbidden_elements.map((item) => item.trim()).filter(Boolean),
  }
}

function sameFieldValue(
  left: TopicDecisionContent,
  right: TopicDecisionContent,
  field: TopicDecisionField,
): boolean {
  return displayFieldValue(left, field) === displayFieldValue(right, field)
}

function formatCost(value: number | null): string {
  return value === null ? '当前模型未配置价格' : `$${(value / 1_000_000).toFixed(4)}`
}

function initialSelections(result: TopicDecisionCandidateSet, locks: Record<TopicDecisionField, boolean>) {
  return Object.fromEntries(result.candidates.map((candidate) => [
    candidate.id,
    candidate.changed_fields.filter((field) => !locks[field]),
  ])) as Record<string, TopicDecisionField[]>
}

function nextActionCopy(nextAction: WorkspaceSummary['next_action']): string {
  if (nextAction === 'review_topic_changes') return '选题已改动，需要你重新确认后再更新下游计划。'
  if (nextAction === 'plan_book') return '选题已确认，下一步可以让总导演搭建全书蓝图。'
  if (nextAction === 'review_downstream_plans') return '选题已确认，但已有计划需要复核。'
  if (nextAction === 'continue_writing') return '选题与计划都已就绪，可以回到正文继续写。'
  return '先由你定方向；AI 只提供候选，不会替你确认。'
}

function CandidateCard({
  candidate,
  selectedFields,
  rejectionReason,
  locks,
  disabled,
  onToggleField,
  onApply,
  onReasonChange,
  onReject,
}: {
  candidate: TopicDecisionCandidate
  selectedFields: TopicDecisionField[]
  rejectionReason: string
  locks: Record<TopicDecisionField, boolean>
  disabled: boolean
  onToggleField: (field: TopicDecisionField) => void
  onApply: () => void
  onReasonChange: (value: string) => void
  onReject: () => void
}) {
  const candidateDisabled = disabled || candidate.state !== 'candidate'
  return (
    <article className="topic-candidate-card" data-state={candidate.state}>
      <header>
        <div>
          <small>方案 {candidate.ordinal}</small>
          <h3>{candidate.label}</h3>
        </div>
        <span>{candidate.state === 'selected' ? '已采用过' : candidate.state === 'rejected' ? '已记录不采用' : '待比较'}</span>
      </header>
      <p className="topic-candidate-rationale">{candidate.rationale}</p>
      <div className="topic-candidate-fields">
        {candidate.changed_fields.map((field) => (
          <label key={field} data-locked={locks[field]}>
            <span>
              <input
                type="checkbox"
                checked={selectedFields.includes(field)}
                disabled={candidateDisabled || locks[field]}
                onChange={() => onToggleField(field)}
              />
              <strong>{fieldLabels[field]}</strong>
              {locks[field] ? <em>已锁定</em> : null}
            </span>
            <output>{displayFieldValue(candidate.content, field) || '（这个方案没有填写）'}</output>
          </label>
        ))}
      </div>
      {candidate.risks.length > 0 ? (
        <details>
          <summary>查看风险提醒（{candidate.risks.length}）</summary>
          <ul>{candidate.risks.map((risk) => <li key={risk}>{risk}</li>)}</ul>
        </details>
      ) : null}
      <button
        className="topic-candidate-apply"
        type="button"
        disabled={candidateDisabled || selectedFields.length === 0}
        onClick={onApply}
      >
        并入勾选字段（不会确认）
      </button>
      <div className="topic-candidate-reject">
        <label>
          不采用原因
          <textarea
            value={rejectionReason}
            rows={2}
            maxLength={600}
            placeholder="例如：开篇承诺太慢、核心欲望不够具体"
            disabled={candidateDisabled}
            onChange={(event) => onReasonChange(event.target.value)}
          />
        </label>
        <button
          type="button"
          disabled={candidateDisabled || rejectionReason.trim().length === 0}
          onClick={onReject}
        >
          记录不采用
        </button>
      </div>
    </article>
  )
}

export function TopicDecisionWorkbench({
  workspace,
  onWorkspaceChanged,
  onContinue,
  onClose,
  onOpenTaskCenter,
}: TopicDecisionWorkbenchProps) {
  const initialTopic = workspace.topic_decision
  const [topic, setTopic] = useState(initialTopic)
  const [draft, setDraft] = useState<TopicDecisionContent | null>(initialTopic?.content ?? null)
  const [locks, setLocks] = useState<Record<TopicDecisionField, boolean> | null>(initialTopic?.locks ?? null)
  const [restoreLocks] = useState<Record<TopicDecisionField, boolean>>(
    initialTopic?.locks ?? {} as Record<TopicDecisionField, boolean>,
  )
  const [authorIntent, setAuthorIntent] = useState('')
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [regenerationField, setRegenerationField] = useState<TopicDecisionField>('premise')
  const [preview, setPreview] = useState<TopicDecisionOutboundPreview | null>(null)
  const [externalConfirmed, setExternalConfirmed] = useState(false)
  const [activeJob, setActiveJob] = useState<Job | null>(null)
  const [candidateSet, setCandidateSet] = useState<TopicDecisionCandidateSet | null>(null)
  const [candidateSelections, setCandidateSelections] = useState<Record<string, TopicDecisionField[]>>({})
  const [rejectionReasons, setRejectionReasons] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const activeJobId = activeJob?.id
  const activeJobState = activeJob?.state

  useEffect(() => {
    let active = true
    const restore = async () => {
      const [statusResult, jobsResult] = await Promise.allSettled([
        api.getAiStatus(),
        api.listJobs(workspace.project.id),
      ])
      if (!active) return
      if (statusResult.status === 'fulfilled') {
        setAiStatus(statusResult.value)
      } else {
        setError(statusResult.reason instanceof Error ? statusResult.reason.message : '无法读取 AI 模型状态')
      }
      if (jobsResult.status !== 'fulfilled') return
      const latestTopicJob = jobsResult.value.find((job) => job.kind === 'topic_decision')
      if (!latestTopicJob) return
      if (latestTopicJob.state === 'succeeded') {
        try {
          const result = await api.getTopicDecisionCandidates(latestTopicJob.id)
          if (!active) return
          setCandidateSet((current) => current ?? result)
          setCandidateSelections((current) => Object.keys(current).length > 0
            ? current
            : initialSelections(result, restoreLocks))
          setRejectionReasons((current) => Object.keys(current).length > 0
            ? current
            : Object.fromEntries(result.candidates.map((candidate) => [candidate.id, candidate.rejection_reason ?? ''])))
        } catch {
          // The job remains available in Task Center when no candidate artifact can be restored.
        }
      } else if (latestTopicJob.state !== 'cancelled') {
        setActiveJob((current) => current ?? latestTopicJob)
      }
    }
    void restore()
    return () => {
      active = false
    }
  }, [restoreLocks, workspace.project.id])

  useEffect(() => {
    if (!activeJobId || !activeJobState || terminalJobStates.has(activeJobState)) return undefined
    let stopped = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const job = await api.getJob(activeJobId)
        if (stopped) return
        setActiveJob(job)
        if (job.state === 'succeeded') {
          const result = await api.getTopicDecisionCandidates(job.id)
          if (stopped) return
          setCandidateSet(result)
          setCandidateSelections(initialSelections(result, locks ?? topic?.locks ?? {} as Record<TopicDecisionField, boolean>))
          setRejectionReasons(Object.fromEntries(result.candidates.map((candidate) => [
            candidate.id,
            candidate.rejection_reason ?? '',
          ])))
          setActiveJob(null)
          setExternalConfirmed(false)
          setNotice(result.target_field
            ? `已生成 3 个“${fieldLabels[result.target_field]}”局部方案。`
            : '已生成 3 个选题方案，请逐字段比较。')
          return
        }
        if (terminalJobStates.has(job.state)) {
          setError(job.error_message ?? '选题任务已中断，可重试或去任务中心查看。')
          return
        }
        timer = window.setTimeout(poll, 700)
      } catch (caught) {
        if (!stopped) setError(caught instanceof Error ? caught.message : '无法读取选题任务')
      }
    }
    void poll()
    return () => {
      stopped = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [activeJobId, activeJobState, locks, topic?.locks])

  if (!topic || !draft || !locks) {
    return (
      <main className="topic-workbench topic-workbench-missing">
        <div>
          <span aria-hidden="true">墨</span>
          <h1>这本书还没有选题单</h1>
          <p>旧作品不会被阻断，你仍可以回到原来的创作台继续写作。</p>
          <button type="button" onClick={onContinue}>返回创作台</button>
        </div>
      </main>
    )
  }

  const currentTopic = topic
  const currentDraft = draft
  const currentLocks = locks
  const normalizedDraft = normalizeContent(draft)
  const invalidListField = topicFields.find(({ field, list }) => (
    list && (draft[field] as string[]).some((item) => item.length > 500)
  ))

  const changedFields = topicFields
    .filter(({ field }) => !sameFieldValue(normalizedDraft, topic.content, field))
    .map(({ field }) => field)
  const lockUpdates = Object.fromEntries(topicFields
    .filter(({ field }) => locks[field] !== topic.locks[field])
    .map(({ field }) => [field, locks[field]])) as Partial<Record<TopicDecisionField, boolean>>
  const hasLockUpdates = Object.keys(lockUpdates).length > 0
  const hasUnsavedChanges = changedFields.length > 0 || hasLockUpdates
  const missingFields = topicFields.filter(({ field }) => {
    const value = normalizedDraft[field]
    return Array.isArray(value) ? value.length === 0 : value.trim().length === 0
  })
  const candidateIsStale = candidateSet !== null && candidateSet.based_on_revision !== topic.revision
  const availableRegenerationFields = topicFields.filter(({ field }) => !locks[field])
  const effectiveRegenerationField = availableRegenerationFields.some(({ field }) => field === regenerationField)
    ? regenerationField
    : availableRegenerationFields[0]?.field ?? null
  const isCurrentConfirmation = topic.status === 'confirmed' && topic.confirmed_revision === topic.revision
  const progress = activeJob && activeJob.progress_total > 0
    ? Math.round((activeJob.progress_current / activeJob.progress_total) * 100)
    : 0

  async function refreshWorkspace() {
    const refreshed = await api.getProjectSummary(workspace.project.id)
    if (refreshed.topic_decision) {
      setTopic(refreshed.topic_decision)
      setDraft(refreshed.topic_decision.content)
      setLocks(refreshed.topic_decision.locks)
    }
    onWorkspaceChanged(refreshed)
    return refreshed
  }

  async function recoverConflict(caught: unknown) {
    if (!(caught instanceof ApiError) || caught.status !== 409) return false
    await refreshWorkspace()
    setCandidateSet(null)
    setPreview(null)
    setExternalConfirmed(false)
    setError('选题已在别处更新，已为你载入最新版本；请检查后再继续。')
    return true
  }

  async function saveDraft() {
    if (!hasUnsavedChanges || invalidListField) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await api.updateTopicDecision(workspace.project.id, {
        content: normalizeContent(currentDraft),
        changed_fields: changedFields,
        lock_updates: lockUpdates,
        rejection_reason_updates: {},
        expected_revision: currentTopic.revision,
      })
      await refreshWorkspace()
      setCandidateSet(null)
      setPreview(null)
      setExternalConfirmed(false)
      setNotice('选题草稿和字段锁定已保存。')
    } catch (caught) {
      if (!await recoverConflict(caught)) {
        setError(caught instanceof Error ? caught.message : '保存选题失败')
      }
    } finally {
      setBusy(false)
    }
  }

  function candidateRequest(confirm: boolean) {
    return {
      expected_revision: currentTopic.revision,
      author_intent: authorIntent.trim(),
      confirm_external_processing: confirm,
      max_estimated_cost_microusd: confirm ? preview?.estimated_cost_microusd ?? null : null,
    }
  }

  async function showCandidatePreview(targetField: TopicDecisionField | null) {
    if (hasUnsavedChanges) return
    setBusy(true)
    setError(null)
    setNotice(null)
    setPreview(null)
    setExternalConfirmed(false)
    try {
      const nextPreview = targetField
        ? await api.previewTopicDecisionRegeneration(workspace.project.id, {
          ...candidateRequest(false),
          target_field: targetField,
        })
        : await api.previewTopicDecisionCandidates(workspace.project.id, candidateRequest(false))
      setPreview(nextPreview)
    } catch (caught) {
      if (!await recoverConflict(caught)) {
        setError(caught instanceof Error ? caught.message : '无法预览 AI 选题范围')
      }
    } finally {
      setBusy(false)
    }
  }

  async function startCandidateJob() {
    if (!preview || !externalConfirmed || hasUnsavedChanges) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const job = preview.mode === 'field_regeneration' && preview.target_field
        ? await api.startTopicDecisionRegenerationJob(workspace.project.id, {
          ...candidateRequest(true),
          target_field: preview.target_field,
        })
        : await api.startTopicDecisionCandidateJob(workspace.project.id, candidateRequest(true))
      setCandidateSet(null)
      setActiveJob(job)
      setPreview(null)
    } catch (caught) {
      if (!await recoverConflict(caught)) {
        setError(caught instanceof Error ? caught.message : '无法启动 AI 选题任务')
      }
    } finally {
      setBusy(false)
    }
  }

  async function applyCandidate(candidate: TopicDecisionCandidate) {
    const selectedFields = candidateSelections[candidate.id] ?? []
    if (selectedFields.length === 0 || candidateIsStale || candidate.state !== 'candidate' || !candidateSet) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const candidateJobId = candidateSet.job_id
      await api.selectTopicDecisionCandidate(workspace.project.id, {
        job_id: candidateJobId,
        candidate_id: candidate.id,
        selected_fields: selectedFields,
        expected_revision: currentTopic.revision,
      })
      await refreshWorkspace()
      const updatedSet = await api.getTopicDecisionCandidates(candidateJobId)
      setCandidateSet(updatedSet)
      setCandidateSelections((current) => ({
        ...initialSelections(updatedSet, currentLocks),
        ...Object.fromEntries(Object.entries(current).filter(([candidateId]) => (
          updatedSet.candidates.some((item) => item.id === candidateId && item.state === 'candidate')
        ))),
      }))
      setRejectionReasons((current) => ({
        ...Object.fromEntries(updatedSet.candidates.map((item) => [item.id, item.rejection_reason ?? ''])),
        ...current,
      }))
      setPreview(null)
      setNotice(`已把“${candidate.label}”的 ${selectedFields.length} 项并入草稿，尚未确认选题。`)
    } catch (caught) {
      if (!await recoverConflict(caught)) {
        setError(caught instanceof Error ? caught.message : '无法采用候选字段')
      }
    } finally {
      setBusy(false)
    }
  }

  async function rejectCandidate(candidate: TopicDecisionCandidate) {
    const reason = rejectionReasons[candidate.id]?.trim() ?? ''
    if (!reason || !candidateSet || candidateIsStale || candidate.state !== 'candidate') return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await api.rejectTopicDecisionCandidate(workspace.project.id, {
        job_id: candidateSet.job_id,
        candidate_id: candidate.id,
        reason,
        expected_revision: currentTopic.revision,
      })
      const updatedSet = await api.getTopicDecisionCandidates(candidateSet.job_id)
      setCandidateSet(updatedSet)
      setCandidateSelections(initialSelections(updatedSet, currentLocks))
      setRejectionReasons((current) => ({ ...current, [candidate.id]: reason }))
      setNotice(`已记录“${candidate.label}”不采用的原因。`)
    } catch (caught) {
      if (!await recoverConflict(caught)) {
        setError(caught instanceof Error ? caught.message : '无法记录不采用原因')
      }
    } finally {
      setBusy(false)
    }
  }

  async function confirmTopic() {
    if (hasUnsavedChanges || isCurrentConfirmation) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await api.confirmTopicDecision(workspace.project.id, { expected_revision: currentTopic.revision })
      await refreshWorkspace()
      setNotice('选题已由你确认，正在进入全书规划。')
      onContinue()
    } catch (caught) {
      if (!await recoverConflict(caught)) {
        setError(caught instanceof Error ? caught.message : '确认选题失败')
      }
    } finally {
      setBusy(false)
    }
  }

  async function cancelJob() {
    if (!activeJob) return
    setBusy(true)
    setError(null)
    try {
      setActiveJob(await api.cancelJob(activeJob.id))
      setNotice('已请求停止选题任务；已有草稿不会改变。')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '无法停止任务')
    } finally {
      setBusy(false)
    }
  }

  async function retryJob() {
    if (!activeJob) return
    setBusy(true)
    setError(null)
    try {
      setActiveJob(await api.retryJob(activeJob.id))
      setNotice('已从断点重试选题任务。')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '无法重试任务')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="topic-workbench">
      <header className="topic-workbench-bar">
        <div className="topic-workbench-brand">
          <span aria-hidden="true">墨</span>
          <div><small>墨舟 · 选题会</small><strong>{workspace.project.title}</strong></div>
        </div>
        <div className="topic-workbench-actions">
          <button type="button" onClick={onOpenTaskCenter}>任务中心</button>
          {workspace.next_action !== 'confirm_topic' && workspace.next_action !== 'review_topic_changes' ? (
            <button type="button" onClick={onContinue}>返回创作台</button>
          ) : null}
          <button type="button" onClick={onClose}>返回书架</button>
        </div>
      </header>

      <section className="topic-workbench-hero" aria-labelledby="topic-workbench-title">
        <div>
          <p>EDITORIAL DECISION / REVISION {topic.revision}</p>
          <h1 id="topic-workbench-title">你定方向，AI 提方案</h1>
          <span>{nextActionCopy(workspace.next_action)}</span>
        </div>
        <dl>
          <div><dt>选题状态</dt><dd>{isCurrentConfirmation ? '已确认' : topic.status === 'pending_reconfirmation' ? '待复核' : '草稿'}</dd></div>
          <div><dt>已锁字段</dt><dd>{topicFields.filter(({ field }) => locks[field]).length} / {topicFields.length}</dd></div>
          <div><dt>AI 采用来源</dt><dd>{topic.source_candidate_ids.length}</dd></div>
        </dl>
      </section>

      <div className="topic-workbench-layout">
        <nav className="topic-stage-rail" aria-label="选题四阶段">
          <p>四阶段主流程</p>
          <ol>
            <li data-active="true" data-complete={!hasUnsavedChanges && missingFields.length === 0}>
              <a href="#topic-stage-draft"><span>01</span><strong>人工定方向</strong><small>先写清不可让渡的判断</small></a>
            </li>
            <li data-complete={candidateSet !== null || topic.source_job_id !== null}>
              <a href="#topic-stage-ai"><span>02</span><strong>AI 出候选</strong><small>预览范围和费用后才外发</small></a>
            </li>
            <li data-complete={topic.source_candidate_ids.length > 0}>
              <a href="#topic-stage-compare"><span>03</span><strong>逐字段取舍</strong><small>只并入你勾选的内容</small></a>
            </li>
            <li data-complete={isCurrentConfirmation}>
              <a href="#topic-stage-confirm"><span>04</span><strong>人工确认</strong><small>确认后才进入全书规划</small></a>
            </li>
          </ol>
          <blockquote>AI 候选永远停在候选区，不能越过作者确认直接进入正文。</blockquote>
        </nav>

        <div className="topic-workbench-content">
          {notice ? <p className="topic-status topic-status-success" role="status">{notice}</p> : null}
          {error ? <p className="topic-status topic-status-error" role="alert">{error}</p> : null}

          <section id="topic-stage-draft" className="topic-stage topic-draft-stage" aria-labelledby="topic-draft-heading">
            <header>
              <div><small>STAGE 01 · HUMAN DECISION</small><h2 id="topic-draft-heading">先写你的选题判断</h2></div>
              <span>{hasUnsavedChanges ? `${changedFields.length} 项内容待保存` : '已与服务端同步'}</span>
            </header>
            <p className="topic-stage-intro">字段右侧的“锁定”表示 AI 后续不能改这一项。你可以全程手写，也可以只把难想的部分交给 AI。</p>
            <div className="topic-field-grid">
              {topicFields.map(({ field, label, prompt, compact, maxLength }) => (
                <label key={field} className={compact ? 'topic-field topic-field-compact' : 'topic-field'} data-locked={locks[field]}>
                  <span>
                    <strong>{label}</strong>
                    <button
                      type="button"
                      aria-pressed={locks[field]}
                      aria-label={`${locks[field] ? '取消锁定' : '锁定'}${label}`}
                      onClick={() => setLocks((current) => current ? { ...current, [field]: !current[field] } : current)}
                    >
                      {locks[field] ? '已锁定' : '锁定'}
                    </button>
                  </span>
                  <textarea
                    aria-label={label}
                    value={displayFieldValue(draft, field)}
                    rows={compact ? 2 : 4}
                    maxLength={maxLength}
                    readOnly={locks[field]}
                    placeholder={prompt}
                    onChange={(event) => setDraft((current) => current ? updateFieldValue(current, field, event.target.value) : current)}
                  />
                  <small>{prompt}</small>
                </label>
              ))}
            </div>
            {invalidListField ? <p className="topic-inline-warning" role="alert">“{invalidListField.label}”中有一条超过 500 字，请拆成更短的条目后保存。</p> : null}
            <footer>
              <span>{hasUnsavedChanges ? '保存后，AI 才会读取这一版。' : `版本 ${topic.revision} · 可以生成候选。`}</span>
              <button type="button" disabled={busy || !hasUnsavedChanges || invalidListField !== undefined} onClick={() => { void saveDraft() }}>保存选题草稿</button>
            </footer>
          </section>

          <section id="topic-stage-ai" className="topic-stage topic-ai-stage" aria-labelledby="topic-ai-heading">
            <header>
              <div><small>STAGE 02 · AI PROPOSALS</small><h2 id="topic-ai-heading">让 AI 提三种方案</h2></div>
              <span>{aiStatus?.configured ? `${aiStatus.profile_name ?? aiStatus.provider} · ${aiStatus.model}` : '模型尚未配置'}</span>
            </header>
            {aiStatus && !aiStatus.configured ? (
              <div className="topic-ai-setup">
                <div><strong>先接入你的 AI 模型</strong><p>配置只保存在本机；密钥不会写进作品或导出包。</p></div>
                <button type="button" onClick={() => setSettingsOpen(true)}>打开模型线路台</button>
              </div>
            ) : null}
            <label className="topic-author-intent">
              这轮特别想让 AI 解决什么？
              <textarea
                value={authorIntent}
                rows={3}
                maxLength={1000}
                placeholder="例如：前三章要更强兑现，但不要系统；参考东方玄幻的资源循环，不参考人物关系。"
                onChange={(event) => {
                  setAuthorIntent(event.target.value)
                  setPreview(null)
                  setExternalConfirmed(false)
                }}
              />
            </label>
            <div className="topic-ai-actions">
              <button
                type="button"
                disabled={busy || hasUnsavedChanges || activeJob !== null || aiStatus?.configured !== true}
                onClick={() => { void showCandidatePreview(null) }}
              >
                预览完整选题候选
              </button>
              <label>
                只重生成一个未锁字段
                <select
                value={effectiveRegenerationField ?? ''}
                  disabled={availableRegenerationFields.length === 0}
                  onChange={(event) => {
                    setRegenerationField(event.target.value as TopicDecisionField)
                    setPreview(null)
                    setExternalConfirmed(false)
                  }}
                >
                  {availableRegenerationFields.map(({ field, label }) => <option key={field} value={field}>{label}</option>)}
                </select>
              </label>
              <button
                type="button"
                disabled={busy || hasUnsavedChanges || activeJob !== null || availableRegenerationFields.length === 0 || aiStatus?.configured !== true}
                onClick={() => { if (effectiveRegenerationField) void showCandidatePreview(effectiveRegenerationField) }}
              >
                预览局部候选
              </button>
            </div>
            {hasUnsavedChanges ? <p className="topic-inline-warning">请先保存 Stage 01 的修改，避免 AI 读取旧版本。</p> : null}

            {preview ? (
              <aside className="topic-outbound-preview" aria-label="AI 外发范围与费用">
                <header>
                  <div><small>发送前确认</small><h3>{preview.mode === 'full' ? '3 个完整选题方案' : `3 个“${fieldLabels[preview.target_field ?? regenerationField]}”方案`}</h3></div>
                  <strong>{formatCost(preview.estimated_cost_microusd)}</strong>
                </header>
                <dl>
                  <div><dt>模型</dt><dd>{preview.profile_name} · {preview.model}</dd></div>
                  <div><dt>内容范围</dt><dd>{preview.content_scope}</dd></div>
                  <div><dt>数据类型</dt><dd>{preview.data_types.join('、')}</dd></div>
                  <div><dt>预计调用</dt><dd>{preview.estimated_calls} 次 · 约 {preview.character_count.toLocaleString()} 字符</dd></div>
                </dl>
                <label className="topic-external-confirmation">
                  <input
                    type="checkbox"
                    checked={externalConfirmed}
                    onChange={(event) => setExternalConfirmed(event.target.checked)}
                  />
                  我已检查以上范围，并确认把这一版选题信息发送给当前 AI 服务。
                </label>
                <button type="button" disabled={busy || !externalConfirmed} onClick={() => { void startCandidateJob() }}>
                  确认外发并生成 3 个候选
                </button>
              </aside>
            ) : null}

            {activeJob ? (
              <aside className="topic-job-status" aria-live="polite">
                <header><div><small>AI 正在工作</small><h3>{activeJob.current_step || '正在生成选题候选'}</h3></div><strong>{progress}%</strong></header>
                <progress max={100} value={progress}>{progress}%</progress>
                <p>{activeJob.completed_calls} / {activeJob.estimated_calls} 次调用 · 原选题草稿保持不变</p>
                <div>
                  {terminalJobStates.has(activeJob.state) ? (
                    <button type="button" disabled={busy} onClick={() => { void retryJob() }}>从断点重试</button>
                  ) : (
                    <button type="button" disabled={busy} onClick={() => { void cancelJob() }}>停止任务</button>
                  )}
                  <button type="button" onClick={onOpenTaskCenter}>去任务中心</button>
                </div>
              </aside>
            ) : null}
          </section>

          <section id="topic-stage-compare" className="topic-stage topic-compare-stage" aria-labelledby="topic-compare-heading">
            <header>
              <div><small>STAGE 03 · FIELD-BY-FIELD REVIEW</small><h2 id="topic-compare-heading">并排比较，只拿有用的部分</h2></div>
              <span>{candidateSet ? `${candidateSet.candidates.length} 个候选` : '等待候选'}</span>
            </header>
            {!candidateSet ? (
              <div className="topic-empty-candidates"><strong>候选区还是空的</strong><p>你可以直接手写并确认；需要 AI 时，先在 Stage 02 查看外发范围和费用。</p></div>
            ) : (
              <>
                {candidateIsStale ? (
                  <p className="topic-inline-warning" role="alert">这些候选基于旧版本 {candidateSet.based_on_revision}，当前已是版本 {topic.revision}。为了避免覆盖新判断，现已禁止采用；请重新生成。</p>
                ) : null}
                <p className="topic-stage-intro">勾选需要的字段再并入草稿。每次采用都会形成新版本，但不会替你确认选题；锁定字段不能被候选覆盖。</p>
                <div className="topic-candidate-grid">
                  {candidateSet.candidates.map((candidate) => (
                    <CandidateCard
                      key={candidate.id}
                      candidate={candidate}
                      selectedFields={candidateSelections[candidate.id] ?? []}
                      rejectionReason={rejectionReasons[candidate.id] ?? ''}
                      locks={locks}
                      disabled={busy || candidateIsStale}
                      onToggleField={(field) => setCandidateSelections((current) => ({
                        ...current,
                        [candidate.id]: (current[candidate.id] ?? []).includes(field)
                          ? (current[candidate.id] ?? []).filter((item) => item !== field)
                          : [...(current[candidate.id] ?? []), field],
                      }))}
                      onApply={() => { void applyCandidate(candidate) }}
                      onReasonChange={(value) => setRejectionReasons((current) => ({ ...current, [candidate.id]: value }))}
                      onReject={() => { void rejectCandidate(candidate) }}
                    />
                  ))}
                </div>
              </>
            )}
          </section>

          <section id="topic-stage-confirm" className="topic-stage topic-confirm-stage" aria-labelledby="topic-confirm-heading">
            <header>
              <div><small>STAGE 04 · AUTHOR SIGN-OFF</small><h2 id="topic-confirm-heading">最后由你确认选题</h2></div>
              <span>{isCurrentConfirmation ? '已签字' : '等待作者'}</span>
            </header>
            <div className="topic-confirm-summary">
              <p><strong>{draft.premise || '一句话命题尚未填写'}</strong></p>
              <dl>
                <div><dt>平台 / 读者</dt><dd>{draft.target_platform || '未填写'} · {draft.target_audience || '未填写'}</dd></div>
                <div><dt>核心欲望</dt><dd>{draft.core_desire || '未填写'}</dd></div>
                <div><dt>前三章</dt><dd>{draft.first_three_chapter_promise || '未填写'}</dd></div>
                <div><dt>前十章</dt><dd>{draft.first_ten_chapter_goal || '未填写'}</dd></div>
              </dl>
            </div>
            {hasUnsavedChanges ? <p className="topic-inline-warning">还有未保存修改。先保存，再由你确认当前版本。</p> : null}
            {!hasUnsavedChanges && missingFields.length > 0 ? (
              <p className="topic-inline-warning">确认前还要补齐：{missingFields.map(({ label }) => label).join('、')}。</p>
            ) : null}
            <footer>
              <p>确认只代表“用这份选题进入规划”，不会自动生成或覆盖正文。</p>
              {isCurrentConfirmation ? (
                <button type="button" className="topic-continue-action" onClick={onContinue}>进入创作台</button>
              ) : (
                <button
                  type="button"
                  className="topic-confirm-action"
                  disabled={busy || hasUnsavedChanges || missingFields.length > 0}
                  onClick={() => { void confirmTopic() }}
                >
                  确认选题，进入全书规划
                </button>
              )}
            </footer>
          </section>
        </div>
      </div>
      <ModelSettingsPanel
        open={settingsOpen}
        status={aiStatus}
        onClose={() => setSettingsOpen(false)}
        onStatusChanged={(status) => {
          setAiStatus(status)
          setError(null)
        }}
      />
    </main>
  )
}
