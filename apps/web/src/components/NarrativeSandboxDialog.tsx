import type {
  Job,
  Project,
  SandboxAiPreview,
  SandboxCandidate,
  SandboxComparison,
  SandboxInterview,
  SandboxReport,
  SandboxRun,
  SandboxTemplate,
  SandboxVariableValue,
  SandboxWorkspace,
} from '@mozhou/contracts'
import { useEffect, useMemo, useState } from 'react'

import { api } from '../api'

interface NarrativeSandboxDialogProps {
  project: Project
  onClose: () => void
}

const emptyWorkspace: SandboxWorkspace = {
  snapshots: [],
  branches: [],
  runs: [],
  candidates: [],
}

const stateLabels: Record<SandboxRun['state'], string> = {
  ready: '等待推演',
  running: '可继续',
  completed: '已完成',
  cancelled: '已取消',
  budget_exhausted: '预算已用完',
}

function parseVariableValue(value: string): SandboxVariableValue {
  const normalized = value.trim()
  if (normalized === 'true' || normalized === '是') return true
  if (normalized === 'false' || normalized === '否') return false
  if (/^-?\d+$/.test(normalized)) return Number(normalized)
  return normalized
}

function mergeRun(workspace: SandboxWorkspace, run: SandboxRun): SandboxWorkspace {
  return {
    ...workspace,
    runs: [run, ...workspace.runs.filter((item) => item.id !== run.id)],
  }
}

function mergeCandidate(
  workspace: SandboxWorkspace,
  candidate: SandboxCandidate,
): SandboxWorkspace {
  return {
    ...workspace,
    candidates: [
      candidate,
      ...workspace.candidates.filter((item) => item.id !== candidate.id),
    ],
  }
}

export function NarrativeSandboxDialog({ project, onClose }: NarrativeSandboxDialogProps) {
  const [templates, setTemplates] = useState<SandboxTemplate[]>([])
  const [workspace, setWorkspace] = useState<SandboxWorkspace>(emptyWorkspace)
  const [selectedSnapshotId, setSelectedSnapshotId] = useState('')
  const [selectedBranchId, setSelectedBranchId] = useState('')
  const [activeRunId, setActiveRunId] = useState('')
  const [branchLabel, setBranchLabel] = useState('新变量分支')
  const [variableName, setVariableName] = useState('竞争者降价')
  const [variableValue, setVariableValue] = useState('true')
  const [requestedRounds, setRequestedRounds] = useState(3)
  const [executionMode, setExecutionMode] = useState<'rules' | 'ai'>('rules')
  const [aiPreview, setAiPreview] = useState<SandboxAiPreview | null>(null)
  const [aiConfirmed, setAiConfirmed] = useState(false)
  const [aiJob, setAiJob] = useState<Job | null>(null)
  const [report, setReport] = useState<SandboxReport | null>(null)
  const [interview, setInterview] = useState<SandboxInterview | null>(null)
  const [comparison, setComparison] = useState<SandboxComparison | null>(null)
  const [comparisonRunIds, setComparisonRunIds] = useState<string[]>([])
  const [busy, setBusy] = useState<string | null>('loading')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    Promise.all([
      api.listSandboxTemplates(),
      api.getSandboxWorkspace(project.id),
      api.listJobs(project.id).catch(() => []),
    ])
      .then(([nextTemplates, nextWorkspace, jobs]) => {
        if (!active) return
        setTemplates(nextTemplates)
        setWorkspace(nextWorkspace)
        setSelectedSnapshotId(nextWorkspace.snapshots[0]?.id ?? '')
        setSelectedBranchId(nextWorkspace.branches[0]?.id ?? '')
        setActiveRunId(nextWorkspace.runs[0]?.id ?? '')
        setAiJob(jobs.find((job) => job.kind === 'sandbox_ai_round') ?? null)
        setBusy(null)
      })
      .catch((failure: unknown) => {
        if (!active) return
        setError(failure instanceof Error ? failure.message : '无法打开剧情沙盘')
        setBusy(null)
      })
    return () => {
      active = false
    }
  }, [project.id])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  const activeRun = workspace.runs.find((run) => run.id === activeRunId) ?? null
  const selectedBranch = workspace.branches.find((branch) => branch.id === selectedBranchId)
    ?? null
  const selectedSnapshot = workspace.snapshots.find(
    (snapshot) => snapshot.id === selectedSnapshotId,
  ) ?? workspace.snapshots.find((snapshot) => snapshot.id === selectedBranch?.snapshot_id) ?? null
  const activeSnapshot = useMemo(() => {
    const branch = workspace.branches.find((item) => item.id === activeRun?.branch_id)
    return workspace.snapshots.find((item) => item.id === branch?.snapshot_id) ?? null
  }, [activeRun?.branch_id, workspace.branches, workspace.snapshots])

  const refresh = async () => {
    const nextWorkspace = await api.getSandboxWorkspace(project.id)
    setWorkspace(nextWorkspace)
    return nextWorkspace
  }

  const createSnapshot = async (template: SandboxTemplate) => {
    setBusy(`snapshot:${template.id}`)
    setError(null)
    try {
      const snapshot = await api.createSandboxSnapshot(project.id, {
        label: `${template.label} · ${project.rebirth_year}`,
        template_id: template.id,
      })
      const nextWorkspace = await refresh()
      setSelectedSnapshotId(snapshot.id)
      setSelectedBranchId('')
      setActiveRunId('')
      setReport(null)
      setInterview(null)
      const firstVariable = Object.entries(template.suggested_variables)[0]
      if (firstVariable) {
        setVariableName(firstVariable[0])
        setVariableValue(String(firstVariable[1]))
      }
      setWorkspace(nextWorkspace)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '快照创建失败')
    } finally {
      setBusy(null)
    }
  }

  const createBranch = async () => {
    if (!selectedSnapshot) return
    setBusy('branch')
    setError(null)
    try {
      const variables = variableName.trim()
        ? { [variableName.trim()]: parseVariableValue(variableValue) }
        : {}
      const branch = await api.createSandboxBranch(selectedSnapshot.id, {
        label: branchLabel.trim() || '未命名分支',
        seed: 20260811 + workspace.branches.length,
        variables,
        forced_actions: [],
      })
      await refresh()
      setSelectedBranchId(branch.id)
      setActiveRunId('')
      setReport(null)
      setInterview(null)
      setComparison(null)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '分支创建失败')
    } finally {
      setBusy(null)
    }
  }

  const createRun = async () => {
    if (!selectedBranch) return
    const snapshot = workspace.snapshots.find(
      (item) => item.id === selectedBranch.snapshot_id,
    )
    if (!snapshot) return
    setBusy('run')
    setError(null)
    try {
      const run = await api.createSandboxRun(
        selectedBranch.id,
        requestedRounds,
        snapshot.actor_count * requestedRounds,
        executionMode,
      )
      setWorkspace((current) => mergeRun(current, run))
      setActiveRunId(run.id)
      setReport(null)
      setInterview(null)
      setAiPreview(null)
      setAiConfirmed(false)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '推演创建失败')
    } finally {
      setBusy(null)
    }
  }

  const advance = async (run: SandboxRun, allRounds = false) => {
    setBusy(allRounds ? 'advance-all' : 'advance')
    setError(null)
    try {
      let current = run
      do {
        current = await api.advanceSandboxRun(current.id)
        setWorkspace((value) => mergeRun(value, current))
      } while (allRounds && (current.state === 'ready' || current.state === 'running'))
      if (current.state === 'completed' || current.state === 'budget_exhausted') {
        setReport(await api.getSandboxReport(current.id))
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '推演推进失败')
    } finally {
      setBusy(null)
    }
  }

  const waitForAiJob = async (jobId: string) => {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const detail = await api.getJob(jobId)
      setAiJob(detail)
      if (['succeeded', 'failed', 'cancelled', 'interrupted'].includes(detail.state)) {
        if (detail.state === 'succeeded') {
          const current = await api.getSandboxRun(activeRunId)
          setWorkspace((value) => mergeRun(value, current))
          setReport(await api.getSandboxReport(current.id))
          setAiPreview(null)
          setAiConfirmed(false)
        } else if (detail.error_message) {
          setError(detail.error_message)
        }
        return
      }
      await new Promise((resolve) => window.setTimeout(resolve, 250))
    }
    setError('AI 沙盘仍在后台运行，可在任务中心继续查看或取消')
  }

  const previewAiRound = async (run: SandboxRun) => {
    setBusy('ai-preview')
    setError(null)
    try {
      setAiPreview(await api.previewSandboxAiRound(run.id))
      setAiConfirmed(false)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'AI 沙盘预览失败')
    } finally {
      setBusy(null)
    }
  }

  const submitAiRound = async (run: SandboxRun) => {
    if (!aiPreview || !aiConfirmed) return
    setBusy('ai-submit')
    setError(null)
    try {
      const job = await api.submitSandboxAiRound(run.id, {
        expected_state_sha256: aiPreview.state_sha256,
        confirm_external_processing: true,
        max_estimated_cost_microusd: aiPreview.estimated_cost_microusd,
      })
      setAiJob(job)
      setBusy(null)
      await waitForAiJob(job.id)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'AI 沙盘任务提交失败')
    } finally {
      setBusy(null)
    }
  }

  const cancelAiJob = async () => {
    if (!aiJob) return
    setBusy('ai-cancel')
    setError(null)
    try {
      setAiJob(await api.cancelJob(aiJob.id))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'AI 沙盘任务取消失败')
    } finally {
      setBusy(null)
    }
  }

  const retryAiJob = async () => {
    if (!aiJob) return
    setBusy('ai-retry')
    setError(null)
    try {
      const job = await api.retryJob(aiJob.id)
      setAiJob(job)
      setBusy(null)
      await waitForAiJob(job.id)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'AI 沙盘任务重试失败')
    } finally {
      setBusy(null)
    }
  }

  const cancel = async (run: SandboxRun) => {
    setBusy('cancel')
    setError(null)
    try {
      const cancelled = await api.cancelSandboxRun(run.id)
      setWorkspace((current) => mergeRun(current, cancelled))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '取消失败')
    } finally {
      setBusy(null)
    }
  }

  const replay = async (run: SandboxRun) => {
    setBusy('replay')
    setError(null)
    try {
      const nextRun = await api.replaySandboxRun(run.id)
      setWorkspace((current) => mergeRun(current, nextRun))
      setActiveRunId(nextRun.id)
      setReport(null)
      setInterview(null)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '重放创建失败')
    } finally {
      setBusy(null)
    }
  }

  const loadRun = async (run: SandboxRun) => {
    setActiveRunId(run.id)
    setReport(null)
    setInterview(null)
    if (run.rounds.length > 0) {
      try {
        setReport(await api.getSandboxReport(run.id))
      } catch (failure) {
        setError(failure instanceof Error ? failure.message : '影响报告读取失败')
      }
    }
  }

  const loadInterview = async (actorId: string) => {
    if (!activeRun) return
    setBusy(`interview:${actorId}`)
    setError(null)
    try {
      setInterview(await api.getSandboxInterview(activeRun.id, actorId))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '角色采访生成失败')
    } finally {
      setBusy(null)
    }
  }

  const createCandidate = async (kind: 'chapter_outline' | 'fact_change') => {
    if (!activeRun || activeRun.completed_rounds === 0) return
    setBusy(`candidate:${kind}`)
    setError(null)
    try {
      const candidate = await api.createSandboxCandidate(activeRun.id, {
        kind,
        source_round: activeRun.completed_rounds,
        title: kind === 'chapter_outline' ? '沙盘章纲候选' : '沙盘事实变更候选',
      })
      setWorkspace((current) => mergeCandidate(current, candidate))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '候选创建失败')
    } finally {
      setBusy(null)
    }
  }

  const decideCandidate = async (
    candidate: SandboxCandidate,
    decision: 'approve' | 'reject',
  ) => {
    setBusy(`candidate:${candidate.id}`)
    setError(null)
    try {
      const decided = await api.decideSandboxCandidate(candidate.id, decision)
      setWorkspace((current) => mergeCandidate(current, decided))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '候选处理失败')
    } finally {
      setBusy(null)
    }
  }

  const compare = async () => {
    setBusy('compare')
    setError(null)
    try {
      setComparison(await api.compareSandboxRuns(project.id, comparisonRunIds))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '分支比较失败')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="sandbox-dialog-backdrop" role="presentation">
      <section
        className="sandbox-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="sandbox-dialog-title"
      >
        <header>
          <div>
            <p>NARRATIVE SANDBOX / 剧情沙盘</p>
            <h2 id="sandbox-dialog-title">《{project.title}》的假设试验场</h2>
          </div>
          <button type="button" aria-label="关闭剧情沙盘" onClick={onClose}>×</button>
        </header>

        {error ? <p className="sandbox-error" role="alert">{error}</p> : null}
        {busy === 'loading' ? (
          <p className="sandbox-loading" role="status">正在读取本地沙盘…</p>
        ) : (
          <div className="sandbox-content">
            <aside className="sandbox-rail">
              <section aria-labelledby="sandbox-snapshot-title">
                <p>01 / FREEZE</p>
                <h3 id="sandbox-snapshot-title">冻结正式世界</h3>
                <div className="sandbox-template-list">
                  {templates.map((template) => (
                    <button
                      type="button"
                      key={template.id}
                      disabled={busy !== null}
                      onClick={() => { void createSnapshot(template) }}
                    >
                      <strong>{template.label}</strong>
                      <span>{template.actors.length} 方 · {template.description}</span>
                    </button>
                  ))}
                </div>
                {workspace.snapshots.length > 0 ? (
                  <label>不可变快照
                    <select
                      value={selectedSnapshot?.id ?? ''}
                      onChange={(event) => {
                        setSelectedSnapshotId(event.target.value)
                        setSelectedBranchId('')
                      }}
                    >
                      {workspace.snapshots.map((snapshot) => (
                        <option key={snapshot.id} value={snapshot.id}>
                          {snapshot.label} · {snapshot.actor_count} 方
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
                {selectedSnapshot ? (
                  <dl className="sandbox-source-counts">
                    <div><dt>正式事实</dt><dd>{selectedSnapshot.source_counts.fact ?? 0}</dd></div>
                    <div><dt>双时间线</dt><dd>{(selectedSnapshot.source_counts.timeline_original ?? 0) + (selectedSnapshot.source_counts.timeline_novel ?? 0)}</dd></div>
                    <div><dt>现实资料</dt><dd>{selectedSnapshot.source_counts.reality ?? 0}</dd></div>
                  </dl>
                ) : null}
              </section>

              <section aria-labelledby="sandbox-branch-title">
                <p>02 / BRANCH</p>
                <h3 id="sandbox-branch-title">注入一个变量</h3>
                <label>分支名<input value={branchLabel} onChange={(event) => setBranchLabel(event.target.value)} /></label>
                <div className="sandbox-variable-row">
                  <label>变量<input value={variableName} onChange={(event) => setVariableName(event.target.value)} /></label>
                  <label>取值<input value={variableValue} onChange={(event) => setVariableValue(event.target.value)} /></label>
                </div>
                <button type="button" disabled={!selectedSnapshot || busy !== null} onClick={() => { void createBranch() }}>
                  {busy === 'branch' ? '正在分叉…' : '创建隔离分支'}
                </button>
                {workspace.branches.length > 0 ? (
                  <label>当前分支
                    <select value={selectedBranch?.id ?? ''} onChange={(event) => setSelectedBranchId(event.target.value)}>
                      <option value="">选择分支</option>
                      {workspace.branches
                        .filter((branch) => !selectedSnapshot || branch.snapshot_id === selectedSnapshot.id)
                        .map((branch) => <option key={branch.id} value={branch.id}>{branch.label}</option>)}
                    </select>
                  </label>
                ) : null}
              </section>

              <section aria-labelledby="sandbox-run-title">
                <p>03 / SIMULATE</p>
                <h3 id="sandbox-run-title">运行 3–10 轮</h3>
                <label>轮数
                  <input
                    type="number"
                    min={3}
                    max={10}
                    value={requestedRounds}
                    onChange={(event) => setRequestedRounds(Number(event.target.value))}
                  />
                </label>
                <label>推演模式
                  <select
                    value={executionMode}
                    onChange={(event) => setExecutionMode(event.target.value as 'rules' | 'ai')}
                  >
                    <option value="rules">本地规则 · 零费用</option>
                    <option value="ai">AI 提议 + 规则裁决</option>
                  </select>
                </label>
                <button type="button" disabled={!selectedBranch || busy !== null} onClick={() => { void createRun() }}>
                  {busy === 'run' ? '正在建立运行…' : '建立受约束推演'}
                </button>
              </section>
            </aside>

            <div className="sandbox-stage">
              <section className="sandbox-runs" aria-labelledby="sandbox-runs-title">
                <header>
                  <div><p>RUNS / 运行记录</p><h3 id="sandbox-runs-title">分支互不污染，可按种子重放</h3></div>
                  <button type="button" disabled={comparisonRunIds.length < 2 || busy !== null} onClick={() => { void compare() }}>
                    比较已选分支
                  </button>
                </header>
                {workspace.runs.length === 0 ? (
                  <p className="sandbox-empty">先冻结世界、创建变量分支，再建立推演。</p>
                ) : (
                  <ul>
                    {workspace.runs.map((run) => {
                      const branch = workspace.branches.find((item) => item.id === run.branch_id)
                      return (
                        <li key={run.id} data-active={run.id === activeRunId}>
                          <input
                            type="checkbox"
                            aria-label={`选择运行 ${run.id.slice(0, 8)} 进行比较`}
                            checked={comparisonRunIds.includes(run.id)}
                            onChange={(event) => setComparisonRunIds((current) => (
                              event.target.checked
                                ? [...current, run.id].slice(-6)
                                : current.filter((id) => id !== run.id)
                            ))}
                          />
                          <button type="button" onClick={() => { void loadRun(run) }}>
                            <strong>{branch?.label ?? '未知分支'}</strong>
                            <span>{run.execution_mode === 'ai' ? 'AI + 规则' : '本地规则'} · {stateLabels[run.state]} · {run.completed_rounds}/{run.requested_rounds} 轮 · {run.actions_used}/{run.action_budget} 行动</span>
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                )}
              </section>

              {comparison ? (
                <section className="sandbox-comparison" aria-labelledby="sandbox-comparison-title">
                  <p>BRANCH DELTA / 分支差异</p>
                  <h3 id="sandbox-comparison-title">{comparison.comparable ? '同一快照，可直接比较' : '快照不同，不可直接比较'}</h3>
                  {comparison.differences.length > 0 ? (
                    <ul>{comparison.differences.map((item) => <li key={item}>{item}</li>)}</ul>
                  ) : <span>当前聚合分数一致，可继续比较逐轮行动。</span>}
                </section>
              ) : null}

              {activeRun ? (
                <section className="sandbox-active-run" aria-labelledby="sandbox-active-title">
                  <header>
                    <div>
                      <p>ACTIVE RUN / 当前推演</p>
                      <h3 id="sandbox-active-title">{stateLabels[activeRun.state]} · {activeRun.current_state_sha256.slice(0, 12)}</h3>
                    </div>
                    <div>
                      {(activeRun.state === 'ready' || activeRun.state === 'running') ? (
                        <>
                          <button type="button" disabled={busy !== null} onClick={() => { void cancel(activeRun) }}>取消</button>
                          {activeRun.execution_mode === 'ai' ? (
                            <button type="button" disabled={busy !== null} onClick={() => { void previewAiRound(activeRun) }}>
                              {busy === 'ai-preview' ? '正在计算范围…' : '预览 AI 本轮'}
                            </button>
                          ) : (
                            <>
                              <button type="button" disabled={busy !== null} onClick={() => { void advance(activeRun) }}>推进一轮</button>
                              <button type="button" disabled={busy !== null} onClick={() => { void advance(activeRun, true) }}>连续推演</button>
                            </>
                          )}
                        </>
                      ) : (
                        <button type="button" disabled={busy !== null} onClick={() => { void replay(activeRun) }}>同种子重放</button>
                      )}
                    </div>
                  </header>
                  <div className="sandbox-rounds">
                    {activeRun.rounds.map((roundItem) => (
                      <article key={roundItem.id}>
                        <header><strong>第 {roundItem.ordinal} 轮 · {roundItem.origin === 'ai' ? '模型提议 / 规则裁决' : '本地规则'}</strong><span>{roundItem.state_after_sha256.slice(0, 10)}</span></header>
                        <ul>{roundItem.outcomes.map((outcome) => <li key={outcome.actor_id}>{outcome.summary}</li>)}</ul>
                        {(roundItem.rejected_proposals?.length ?? 0) > 0 ? (
                          <small>{roundItem.rejected_proposals?.length} 个模型行动被规则拒绝并安全回退</small>
                        ) : null}
                      </article>
                    ))}
                  </div>
                </section>
              ) : null}

              {aiPreview && activeRun?.execution_mode === 'ai' ? (
                <section className="sandbox-ai-preview" aria-labelledby="sandbox-ai-preview-title">
                  <p>OUTBOUND PREVIEW / 外发确认</p>
                  <h3 id="sandbox-ai-preview-title">第 {aiPreview.round_number} 轮只发送冻结沙盘摘要</h3>
                  <dl>
                    <div><dt>线路</dt><dd>{aiPreview.profile_name} · {aiPreview.model}</dd></div>
                    <div><dt>范围</dt><dd>{aiPreview.content_scope}</dd></div>
                    <div><dt>字符 / Token</dt><dd>{aiPreview.character_count} 字符 · 约 {aiPreview.estimated_input_tokens + aiPreview.estimated_output_tokens} Token</dd></div>
                    <div><dt>预计费用</dt><dd>{aiPreview.estimated_cost_microusd === null ? '线路未配置单价' : `约 $${(aiPreview.estimated_cost_microusd / 1_000_000).toFixed(6)}`}</dd></div>
                  </dl>
                  <p>发送：{aiPreview.data_types.join('、')}。模型只提议，服务端仍逐项检查知识、位置、能力、资源和预算。</p>
                  <label className="sandbox-ai-confirm">
                    <input type="checkbox" checked={aiConfirmed} onChange={(event) => setAiConfirmed(event.target.checked)} />
                    我确认把以上范围发送给当前模型，并接受本次费用上限
                  </label>
                  <button type="button" disabled={!aiConfirmed || busy !== null} onClick={() => { void submitAiRound(activeRun) }}>
                    {busy === 'ai-submit' ? '正在创建可恢复任务…' : '确认并推进一轮'}
                  </button>
                </section>
              ) : null}

              {aiJob ? (
                <section className="sandbox-ai-job" aria-live="polite">
                  <p>AI JOB / 可恢复任务</p>
                  <h3>{aiJob.state} · {aiJob.current_step || '等待后台执行'}</h3>
                  <span>{aiJob.progress_current}/{aiJob.progress_total} · 已完成 {aiJob.completed_calls}/{aiJob.estimated_calls} 次模型调用</span>
                  {['queued', 'running', 'pause_requested'].includes(aiJob.state) ? (
                    <button type="button" disabled={busy !== null || aiJob.state === 'pause_requested'} onClick={() => { void cancelAiJob() }}>取消任务</button>
                  ) : null}
                  {['failed', 'cancelled', 'interrupted'].includes(aiJob.state) ? (
                    <button type="button" disabled={busy !== null} onClick={() => { void retryAiJob() }}>重试并复用已付费结果</button>
                  ) : null}
                </section>
              ) : null}

              {report && activeRun ? (
                <section className="sandbox-report" aria-labelledby="sandbox-report-title">
                  <header>
                    <div><p>IMPACT REPORT / 影响报告</p><h3 id="sandbox-report-title">每条结论都有假设、证据、置信度与反例</h3></div>
                    <div>
                      <button type="button" disabled={busy !== null} onClick={() => { void createCandidate('chapter_outline') }}>形成章纲候选</button>
                      <button type="button" disabled={busy !== null} onClick={() => { void createCandidate('fact_change') }}>形成事实变更候选</button>
                    </div>
                  </header>
                  <aside>{report.disclaimer}</aside>
                  <ol>
                    {report.conclusions.slice(-Math.min(report.conclusions.length, 10)).map((conclusion, index) => (
                      <li key={`${conclusion.round_number}:${conclusion.actor_id}:${index}`}>
                        <strong>R{conclusion.round_number} · {conclusion.actor_id} · {Math.round(conclusion.confidence * 100)}%</strong>
                        <p>{conclusion.statement}</p>
                        <span>{conclusion.impact_chain.join(' → ')}</span>
                        <small>反例：{conclusion.counterexample}</small>
                      </li>
                    ))}
                  </ol>
                  {activeSnapshot ? (
                    <div className="sandbox-interview-actions">
                      <strong>角色采访</strong>
                      {activeSnapshot.actors.map((actor) => (
                        <button key={actor.id} type="button" disabled={busy !== null} onClick={() => { void loadInterview(actor.id) }}>{actor.name}</button>
                      ))}
                    </div>
                  ) : null}
                </section>
              ) : null}

              {interview ? (
                <section className="sandbox-interview" aria-labelledby="sandbox-interview-title">
                  <p>ROLE INTERVIEW / 角色采访</p>
                  <h3 id="sandbox-interview-title">{interview.actor_name}：只回答快照内知道的事</h3>
                  <aside>{interview.disclaimer}</aside>
                  <dl>{interview.answers.map((answer) => <div key={answer.question}><dt>{answer.question}</dt><dd>{answer.answer}</dd></div>)}</dl>
                </section>
              ) : null}

              {workspace.candidates.length > 0 ? (
                <section className="sandbox-candidates" aria-labelledby="sandbox-candidates-title">
                  <p>APPROVAL GATE / 候选批准门</p>
                  <h3 id="sandbox-candidates-title">批准也不会直接写正文、事实或时间线</h3>
                  <ul>
                    {workspace.candidates.map((candidate) => (
                      <li key={candidate.id}>
                        <div><strong>{candidate.title}</strong><span>{candidate.kind === 'chapter_outline' ? '章纲候选' : '事实变更候选'} · {candidate.state}</span></div>
                        {candidate.state === 'candidate' ? (
                          <div>
                            <button type="button" disabled={busy !== null} onClick={() => { void decideCandidate(candidate, 'reject') }}>拒绝</button>
                            <button type="button" disabled={busy !== null} onClick={() => { void decideCandidate(candidate, 'approve') }}>批准为创作参考</button>
                          </div>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </div>
          </div>
        )}

        <footer>
          <span>规则模式零外发；AI 模式逐轮确认费用，模型提议与正式正文永久隔离</span>
          <button type="button" onClick={onClose}>返回作品书架</button>
        </footer>
      </section>
    </div>
  )
}
