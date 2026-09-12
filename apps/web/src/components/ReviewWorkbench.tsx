import type {
  Chapter,
  ChapterVersion,
  Job,
  ReviewChapterInput,
  ReviewDimension,
  ReviewFinding,
  ReviewJobResult,
  ReviewOutboundPreview,
  TextChangeSet,
} from '@mozhou/contracts'
import { creativeContextCanSubmit } from '@mozhou/contracts'
import { useEffect, useMemo, useState } from 'react'

import { api } from '../api'
import { ContextPacketPanel } from './ContextPacketPanel'

interface ReviewWorkbenchProps {
  chapter: Chapter
  canReview: boolean
  onChapterUpdated: (chapter: Chapter) => void
}

const dimensions: Array<{ id: ReviewDimension; label: string; local: boolean }> = [
  { id: 'continuity', label: '连续性', local: true },
  { id: 'serial_rhythm', label: '连载节奏', local: true },
  { id: 'character', label: '人物', local: false },
  { id: 'realism', label: '现实性', local: false },
  { id: 'rebirth_logic', label: '世界机制 / 重生逻辑', local: false },
  { id: 'style', label: '文风', local: false },
  { id: 'format', label: '格式', local: false },
]

const dimensionLabels = Object.fromEntries(
  dimensions.map((dimension) => [dimension.id, dimension.label]),
) as Record<ReviewDimension, string>

const severityLabels = {
  critical: '严重',
  warning: '警告',
  info: '提示',
} as const

const versionSourceLabels = {
  initial: '初始版本',
  manual_save: '作者保存',
  generation_candidate: 'AI 候选',
  generation_apply: '采用 AI 候选',
  change_set_apply: '应用局部修改',
  rollback: '回滚生成',
} as const

const terminalStates = new Set(['succeeded', 'failed', 'cancelled', 'interrupted'])

function money(microusd: number | null): string {
  return microusd === null ? '价格未知' : `$${(microusd / 1_000_000).toFixed(4)}`
}

export function ReviewWorkbench({
  chapter,
  canReview,
  onChapterUpdated,
}: ReviewWorkbenchProps) {
  const [open, setOpen] = useState(false)
  const [selectedDimensions, setSelectedDimensions] = useState<ReviewDimension[]>(
    () => dimensions.map((dimension) => dimension.id),
  )
  const [windowSize, setWindowSize] = useState<3 | 10>(3)
  const [preview, setPreview] = useState<ReviewOutboundPreview | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [result, setResult] = useState<ReviewJobResult | null>(null)
  const [findings, setFindings] = useState<ReviewFinding[]>([])
  const [versions, setVersions] = useState<ChapterVersion[]>([])
  const [changeSets, setChangeSets] = useState<TextChangeSet[]>([])
  const [selectedFindingIds, setSelectedFindingIds] = useState<string[]>([])
  const [activeChangeSet, setActiveChangeSet] = useState<TextChangeSet | null>(null)
  const [selectedChangeIds, setSelectedChangeIds] = useState<string[]>([])
  const [editedReplacements, setEditedReplacements] = useState<Record<string, string>>({})
  const [rollbackTarget, setRollbackTarget] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const running = job !== null && !terminalStates.has(job.state)
  const latestOfficialVersion = versions.find((version) => !version.is_candidate) ?? null
  const applicableFindings = useMemo(
    () => findings.filter((finding) => (
      finding.state === 'open'
      && finding.chapter_revision === chapter.revision
      && finding.suggested_replacement !== null
      && finding.evidence.some((evidence) => evidence.kind === 'body' && evidence.chapter_id === chapter.id)
    )),
    [chapter.id, chapter.revision, findings],
  )

  useEffect(() => {
    if (open) void loadHistory()
    // History is refreshed whenever the disclosure opens. The parent remounts this
    // workbench on a chapter revision change, invalidating every confirmation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    if (!job || terminalStates.has(job.state)) return
    const jobId = job.id
    let active = true
    let timer: number | undefined

    async function poll() {
      try {
        const current = await api.getJob(jobId)
        if (!active) return
        if (terminalStates.has(current.state)) {
          const reviewResult = await api.getChapterReviewJobResult(current.id)
          if (!active) return
          setJob(current)
          setResult(reviewResult)
          await loadHistory()
          return
        }
        setJob(current)
        timer = window.setTimeout(() => { void poll() }, 700)
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : '审校任务状态读取失败')
      }
    }

    void poll()
    return () => {
      active = false
      if (timer !== undefined) window.clearTimeout(timer)
    }
    // loadHistory is deliberately bound to the current chapter props.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, job?.state])

  async function loadHistory() {
    try {
      const [currentFindings, currentVersions, currentChangeSets] = await Promise.all([
        api.listReviewFindings(chapter.id, chapter.revision),
        api.listChapterVersions(chapter.id),
        api.listTextChangeSets(chapter.id),
      ])
      setFindings(currentFindings)
      setVersions(currentVersions)
      setChangeSets(currentChangeSets)
      const candidate = currentChangeSets.find((item) => item.state === 'candidate') ?? null
      setActiveChangeSet(candidate)
      if (candidate) {
        setSelectedChangeIds(candidate.changes.map((change) => change.id))
        setEditedReplacements(Object.fromEntries(
          candidate.changes.map((change) => [change.id, change.replacement_text]),
        ))
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '审校历史读取失败')
    }
  }

  function input(confirm: boolean): ReviewChapterInput {
    return {
      expected_revision: chapter.revision,
      window_size: windowSize,
      dimensions: selectedDimensions,
      confirm_external_processing: confirm,
      max_estimated_cost_microusd: preview?.estimated_cost_microusd ?? null,
      parent_job_id: result?.job_id ?? null,
    }
  }

  function toggleDimension(dimension: ReviewDimension) {
    setSelectedDimensions((current) => (
      current.includes(dimension)
        ? current.filter((item) => item !== dimension)
        : dimensions.map((item) => item.id).filter((item) => [...current, dimension].includes(item))
    ))
    setPreview(null)
    setResult(null)
  }

  async function createPreview() {
    if (!selectedDimensions.length) return
    setBusy(true)
    setError(null)
    try {
      setPreview(await api.previewChapterReview(chapter.id, input(false)))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '审校预览失败')
    } finally {
      setBusy(false)
    }
  }

  async function startReview() {
    if (!preview) return
    const contextPacket = preview.context_packet
    if (contextPacket && !creativeContextCanSubmit(contextPacket)) return
    setBusy(true)
    setError(null)
    try {
      const queued = await api.startChapterReviewJob(chapter.id, input(true))
      setJob(queued)
      setResult(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '审校任务提交失败')
    } finally {
      setBusy(false)
    }
  }

  async function stopReview() {
    if (!job || !running) return
    setBusy(true)
    try {
      setJob(await api.cancelJob(job.id))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '停止审校失败')
    } finally {
      setBusy(false)
    }
  }

  function prepareDimensionRerun(dimension: ReviewDimension) {
    setSelectedDimensions([dimension])
    setPreview(null)
    setJob(null)
    setError(null)
  }

  function toggleFinding(id: string) {
    setSelectedFindingIds((current) => (
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id]
    ))
  }

  async function createChangeSet() {
    if (!selectedFindingIds.length) return
    setBusy(true)
    setError(null)
    try {
      const created = await api.createTextChangeSet(chapter.id, {
        finding_ids: selectedFindingIds,
      })
      setActiveChangeSet(created)
      setSelectedChangeIds(created.changes.map((change) => change.id))
      setEditedReplacements(Object.fromEntries(
        created.changes.map((change) => [change.id, change.replacement_text]),
      ))
      setChangeSets((current) => [created, ...current.filter((item) => item.id !== created.id)])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '局部变更集创建失败')
    } finally {
      setBusy(false)
    }
  }

  function toggleChange(id: string) {
    setSelectedChangeIds((current) => (
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id]
    ))
  }

  const previewContextPacket = preview
    ? preview.context_packet
    : null

  async function applyChangeSet() {
    if (!activeChangeSet || !selectedChangeIds.length) return
    setBusy(true)
    setError(null)
    try {
      const updated = await api.applyTextChangeSet(activeChangeSet.id, {
        selected_change_ids: selectedChangeIds,
        edited_replacements: Object.fromEntries(
          selectedChangeIds.map((id) => [
            id,
            editedReplacements[id]
              ?? activeChangeSet.changes.find((change) => change.id === id)?.replacement_text
              ?? '',
          ]),
        ),
        expected_set_revision: activeChangeSet.revision,
        expected_chapter_revision: chapter.revision,
      })
      onChapterUpdated(updated)
      setActiveChangeSet(null)
      setSelectedFindingIds([])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '局部修改应用失败')
    } finally {
      setBusy(false)
    }
  }

  async function rejectChangeSet() {
    if (!activeChangeSet) return
    setBusy(true)
    setError(null)
    try {
      const rejected = await api.rejectTextChangeSet(activeChangeSet.id, {
        expected_revision: activeChangeSet.revision,
      })
      setChangeSets((current) => current.map((item) => item.id === rejected.id ? rejected : item))
      setActiveChangeSet(null)
      await loadHistory()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '变更集拒绝失败')
    } finally {
      setBusy(false)
    }
  }

  async function rollbackVersion(versionId: string) {
    if (rollbackTarget !== versionId) {
      setRollbackTarget(versionId)
      return
    }
    setBusy(true)
    setError(null)
    try {
      const updated = await api.rollbackChapterVersion(chapter.id, versionId, {
        expected_revision: chapter.revision,
      })
      onChapterUpdated(updated)
      setRollbackTarget(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '版本回滚失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="review-workbench" data-open={open}>
      <button
        className="review-workbench-trigger"
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span><small>多 Agent 审校</small><strong>七维审校 · 局部改稿 · 版本回滚</strong></span>
        <b aria-hidden="true">{open ? '−' : '＋'}</b>
      </button>
      {open ? (
        <div className="review-workbench-body">
          <div className="review-scope-row">
            <div className="review-dimensions" role="group" aria-label="审校维度">
              {dimensions.map((dimension) => (
                <label key={dimension.id}>
                  <input
                    type="checkbox"
                    checked={selectedDimensions.includes(dimension.id)}
                    disabled={running}
                    onChange={() => toggleDimension(dimension.id)}
                  />
                  <span>{dimension.label}<small>{dimension.local ? '本地' : '模型'}</small></span>
                </label>
              ))}
            </div>
            <label className="review-window-select">
              连续范围
              <select
                value={windowSize}
                disabled={running}
                onChange={(event) => {
                  setWindowSize(Number(event.target.value) as 3 | 10)
                  setPreview(null)
                }}
              >
                <option value={3}>最近 3 章</option>
                <option value={10}>最近 10 章</option>
              </select>
            </label>
          </div>

          {!preview ? (
            <button
              className="review-primary"
              type="button"
              disabled={!canReview || busy || running || selectedDimensions.length === 0}
              onClick={() => { void createPreview() }}
            >查看审校范围与费用</button>
          ) : (
            <div className="review-preview">
              <div><strong>{preview.profile_name}</strong><span>{preview.model}</span></div>
              <p>{preview.content_scope}</p>
              <dl>
                <div>
                  <dt>{preview.external_dimensions.length ? '外发字符' : '本地上下文'}</dt>
                  <dd>{preview.character_count.toLocaleString('zh-CN')}</dd>
                </div>
                <div><dt>模型调用</dt><dd>{preview.estimated_calls}</dd></div>
                <div>
                  <dt>预计费用</dt>
                  <dd>{preview.external_dimensions.length ? money(preview.estimated_cost_microusd) : '不产生费用'}</dd>
                </div>
              </dl>
              <small>
                本地：{preview.local_dimensions.map((item) => dimensionLabels[item]).join('、') || '无'}；
                外发：{preview.external_dimensions.map((item) => dimensionLabels[item]).join('、') || '无'}。
                审校只生成问题与候选修改，不直接改正文或 Canon。
              </small>
              {previewContextPacket ? <ContextPacketPanel packet={previewContextPacket} /> : null}
              <div className="review-actions">
                <button type="button" onClick={() => setPreview(null)}>返回调整</button>
                <button
                  className="review-primary"
                  type="button"
                  disabled={busy || running || Boolean(previewContextPacket && !creativeContextCanSubmit(previewContextPacket))}
                  onClick={() => { void startReview() }}
                >
                  确认范围并开始审校
                </button>
              </div>
            </div>
          )}

          {job ? (
            <div className="review-job" role="status">
              <div><strong>{running ? '七维审校进行中' : '本轮审校已停止'}</strong><span>{job.progress_current}/{job.progress_total}</span></div>
              <progress value={job.progress_current} max={Math.max(job.progress_total, 1)} />
              <p>{job.current_step || (job.error_message ?? '等待任务运行')}</p>
              {running ? <button type="button" disabled={busy} onClick={() => { void stopReview() }}>停止后续审校</button> : null}
            </div>
          ) : null}

          {result ? (
            <div className="review-outcomes">
              {result.outcomes.map((outcome) => (
                <div key={outcome.dimension} data-state={outcome.state}>
                  <span>{dimensionLabels[outcome.dimension]}</span>
                  <strong>{outcome.state === 'succeeded' ? `${outcome.finding_count} 项` : '失败'}</strong>
                  {outcome.state === 'failed' ? (
                    <button type="button" onClick={() => prepareDimensionRerun(outcome.dimension)}>准备单独重跑</button>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}

          {findings.length ? (
            <div className="review-findings">
              <div className="review-section-heading"><strong>有证据的问题</strong><span>{findings.length} 项</span></div>
              {findings.map((finding) => {
                const applicable = applicableFindings.some((item) => item.id === finding.id)
                return (
                  <article key={finding.id} data-severity={finding.severity}>
                    <header>
                      <span>{dimensionLabels[finding.dimension]} · {severityLabels[finding.severity]}</span>
                      <strong>{finding.title}</strong>
                      <small>置信度 {Math.round(finding.confidence * 100)}%</small>
                    </header>
                    {finding.evidence.map((evidence, index) => (
                      <blockquote key={`${finding.id}:${index}`}>
                        {evidence.excerpt ?? evidence.label}
                        <cite>{evidence.label}</cite>
                      </blockquote>
                    ))}
                    <p>{finding.explanation}</p>
                    <div className="review-suggestion"><span>建议</span>{finding.suggestion}</div>
                    {applicable ? (
                      <label className="review-select-finding">
                        <input
                          type="checkbox"
                          checked={selectedFindingIds.includes(finding.id)}
                          onChange={() => toggleFinding(finding.id)}
                        />加入局部变更集
                      </label>
                    ) : <small>该问题只提供判断依据，不具备安全的局部替换。</small>}
                  </article>
                )
              })}
              <button className="review-primary" type="button" disabled={busy || !selectedFindingIds.length} onClick={() => { void createChangeSet() }}>
                生成局部变更集
              </button>
            </div>
          ) : null}

          {activeChangeSet ? (
            <div className="review-change-set">
              <div className="review-section-heading"><strong>{activeChangeSet.title}</strong><span>基于 revision {activeChangeSet.base_chapter_revision}</span></div>
              {activeChangeSet.changes.map((change) => (
                <article key={change.id}>
                  <label>
                    <input type="checkbox" checked={selectedChangeIds.includes(change.id)} onChange={() => toggleChange(change.id)} />
                    采用第 {change.ordinal} 处修改
                  </label>
                  <div className="review-diff"><del>{change.original_text}</del><span>→</span></div>
                  <textarea
                    aria-label={`第 ${change.ordinal} 处替换文本`}
                    value={editedReplacements[change.id] ?? change.replacement_text}
                    rows={3}
                    maxLength={4000}
                    onChange={(event) => setEditedReplacements((current) => ({ ...current, [change.id]: event.target.value }))}
                  />
                </article>
              ))}
              <p>只会应用勾选项；作者编辑后的替换文本会进入新版本，未选项不会改动正文。</p>
              <div className="review-actions">
                <button type="button" disabled={busy} onClick={() => { void rejectChangeSet() }}>拒绝整组</button>
                <button className="review-primary" type="button" disabled={busy || !selectedChangeIds.length} onClick={() => { void applyChangeSet() }}>应用所选并创建新版本</button>
              </div>
            </div>
          ) : null}

          <div className="review-versions">
            <div className="review-section-heading"><strong>章节版本</strong><span>{versions.length} 个</span></div>
            {versions.slice(0, 12).map((version) => (
              <article key={version.id} data-candidate={version.is_candidate}>
                <div>
                  <strong>V{version.version_number} · {versionSourceLabels[version.source]}</strong>
                  <small>revision {version.chapter_revision} · {version.content.length.toLocaleString('zh-CN')} 字</small>
                </div>
                <p>{version.content.slice(0, 90) || '空白初始稿'}{version.content.length > 90 ? '…' : ''}</p>
                {!version.is_candidate && version.id !== latestOfficialVersion?.id ? (
                  <button
                    type="button"
                    disabled={busy}
                    data-confirming={rollbackTarget === version.id}
                    onClick={() => { void rollbackVersion(version.id) }}
                  >{rollbackTarget === version.id ? '确认回滚为新版本' : '回滚到此版本'}</button>
                ) : null}
              </article>
            ))}
          </div>

          {changeSets.length > 0 ? <small className="review-history-note">已保留 {changeSets.length} 个文本变更集及其部分接受记录。</small> : null}
          {!canReview ? <p className="brief-hint">正文保存完成且非空后才能开始审校。</p> : null}
          {error ? <p className="review-error" role="alert">{error}</p> : null}
        </div>
      ) : null}
    </section>
  )
}
