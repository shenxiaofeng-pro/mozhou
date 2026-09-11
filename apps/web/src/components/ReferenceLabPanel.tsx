import type {
  BlueprintDimensionState,
  BlueprintEntityKind,
  BlueprintRelationshipState,
  Job,
  OriginalityReport,
  ReferenceApplicationLifecycleState,
  ReferenceFilePreview,
  ReferencePatternApplication,
  ReferencePatternCard,
  ReferencePatternDimension,
  ReferenceBlueprintState,
  ReferenceRightsBasis,
  SceneOriginalityCheck,
  Workspace,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { useEffect, useMemo, useState } from 'react'

import { ApiError, api } from '../api'

interface ReferenceLabPanelProps {
  workspace: WorkspaceSummary
  onWorkspaceChanged: (workspace: Workspace | WorkspaceSummary) => void
}

const MAX_FILE_BYTES = 25 * 1024 * 1024
const DEFAULT_SEGMENT_CHARACTERS = 500_000

const rightsLabels: Record<ReferenceRightsBasis, string> = {
  self_owned: '作者自有',
  authorized: '已经授权',
  public_domain: '公版作品',
}

const dimensionLabels = [
  ['era', '时代'],
  ['core_desire', '核心欲望'],
  ['conflict_causality', '冲突因果'],
  ['resource_system', '资源体系'],
  ['key_scene_sequence', '关键场景顺序'],
  ['ending', '结局'],
] as const

const lifecycleLabels: Record<ReferenceApplicationLifecycleState, string> = {
  active: '使用中',
  draft: '已暂停',
  archived: '已归档',
}

function formatWan(value: number) {
  return value % 10_000 === 0 ? `${value / 10_000} 万` : value.toLocaleString('zh-CN')
}

export function ReferenceLabPanel({ workspace, onWorkspaceChanged }: ReferenceLabPanelProps) {
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [rightsBasis, setRightsBasis] = useState<ReferenceRightsBasis>('self_owned')
  const [segmentCharacters, setSegmentCharacters] = useState(DEFAULT_SEGMENT_CHARACTERS)
  const [filePreview, setFilePreview] = useState<ReferenceFilePreview | null>(null)
  const [isPreviewing, setIsPreviewing] = useState(false)
  const [confirmedUncertainEncoding, setConfirmedUncertainEncoding] = useState(false)
  const [selectedSegments, setSelectedSegments] = useState<Set<string>>(() => new Set())
  const [isImporting, setIsImporting] = useState(false)
  const [authorFocus, setAuthorFocus] = useState('')
  const [confirmedExternalProcessing, setConfirmedExternalProcessing] = useState(false)
  const [analysisJob, setAnalysisJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const analysisJobId = analysisJob?.id
  const analysisJobState = analysisJob?.state
  const isAnalyzing = analysisJob !== null
    && ['queued', 'running', 'pause_requested'].includes(analysisJob.state)

  useEffect(() => {
    let ignored = false
    void api.listJobs(workspace.project.id).then((jobs) => {
      if (ignored) return
      const recoverable = jobs.find((job) => (
        job.kind === 'reference_fusion' && job.state !== 'succeeded'
      ))
      if (recoverable) {
        setAnalysisJob(recoverable)
        if (recoverable.error_message) setError(recoverable.error_message)
      }
    }).catch(() => undefined)
    return () => {
      ignored = true
    }
  }, [workspace.project.id])

  useEffect(() => {
    if (!analysisJobId || !analysisJobState || !['queued', 'running', 'pause_requested'].includes(analysisJobState)) {
      return undefined
    }
    let stopped = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const detail = await api.getJob(analysisJobId)
        if (stopped) return
        setAnalysisJob(detail)
        if (detail.state === 'succeeded') {
          const refreshed = await api.getProjectSummary(workspace.project.id)
          if (!stopped) onWorkspaceChanged(refreshed)
          return
        }
        if (detail.state === 'failed' || detail.state === 'interrupted') {
          setError(detail.error_message ?? '拆书任务中断，可从失败块继续。')
          return
        }
        if (detail.state === 'cancelled') return
        timer = window.setTimeout(poll, 700)
      } catch (caught) {
        if (!stopped) {
          setError(caught instanceof Error ? caught.message : '读取拆书任务进度失败')
        }
      }
    }
    void poll()
    return () => {
      stopped = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [analysisJobId, analysisJobState, onWorkspaceChanged, workspace.project.id])

  const selection = useMemo(() => {
    const segmentIds: string[] = []
    const sourceLabels = new Map<string, string>()
    let workCount = 0
    let characterCount = 0
    for (const work of workspace.reference_works) {
      let workSelected = false
      for (const segment of work.segments) {
        sourceLabels.set(segment.id, `${work.title} · 区段 ${segment.ordinal}`)
        if (!selectedSegments.has(segment.id)) continue
        segmentIds.push(segment.id)
        characterCount += segment.character_count
        workSelected = true
      }
      if (workSelected) workCount += 1
    }
    return { segmentIds, sourceLabels, workCount, characterCount }
  }, [selectedSegments, workspace.reference_works])
  const analysisReady = selection.workCount >= 2
    && selection.segmentIds.length <= 12
    && selection.characterCount <= 2_000_000

  function chooseFile(nextFile: File | undefined) {
    setError(null)
    setFilePreview(null)
    setConfirmedUncertainEncoding(false)
    if (!nextFile) {
      setFile(null)
      return
    }
    const extension = nextFile.name.toLowerCase().split('.').pop()
    if (!extension || !['txt', 'md', 'markdown', 'pdf'].includes(extension)) {
      setFile(null)
      setError('当前支持 TXT、Markdown 与文本型 PDF。')
      return
    }
    if (nextFile.size > MAX_FILE_BYTES) {
      setFile(null)
      setError('单个参考文件不能超过 20 MB。')
      return
    }
    setFile(nextFile)
    setTitle(nextFile.name.replace(/\.(?:txt|md|markdown|pdf)$/i, ''))
  }

  async function previewFile() {
    if (!file) return
    setIsPreviewing(true)
    setError(null)
    try {
      setFilePreview(await api.previewReferenceFile(file))
    } catch (caught) {
      setFilePreview(null)
      setError(caught instanceof Error ? caught.message : '参考文件预览失败')
    } finally {
      setIsPreviewing(false)
    }
  }

  async function importWork() {
    if (!file || !title.trim()) return
    setIsImporting(true)
    setError(null)
    try {
      if (!filePreview) throw new Error('请先完成编码检测并查看预览')
      const imported = await api.importReferenceFile(file, {
        title: title.trim(),
        rights_basis: rightsBasis,
        segment_target_characters: segmentCharacters,
        expected_source_sha256: filePreview.source_sha256,
        confirm_preview: true,
        confirm_uncertain_encoding: confirmedUncertainEncoding,
        project_id: workspace.project.id,
      })
      onWorkspaceChanged({
        ...workspace,
        reference_works: [...workspace.reference_works, imported],
      })
      setFile(null)
      setFilePreview(null)
      setConfirmedUncertainEncoding(false)
      setTitle('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '参考作品导入失败')
    } finally {
      setIsImporting(false)
    }
  }

  function toggleSegment(segmentId: string) {
    setSelectedSegments((current) => {
      const next = new Set(current)
      if (next.has(segmentId)) next.delete(segmentId)
      else next.add(segmentId)
      return next
    })
  }

  async function synthesizePatterns() {
    if (!analysisReady || !confirmedExternalProcessing) return
    setError(null)
    try {
      const job = await api.startReferenceAnalysisJob(workspace.project.id, {
        selected_segment_ids: selection.segmentIds,
        author_focus: authorFocus.trim(),
        confirm_external_processing: true,
      })
      setAnalysisJob(job)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '多书结构萃取失败')
    }
  }

  async function cancelAnalysis() {
    if (!analysisJob || !isAnalyzing) return
    try {
      setAnalysisJob(await api.cancelJob(analysisJob.id))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '取消拆书任务失败')
    }
  }

  async function retryAnalysis() {
    if (!analysisJob || !['failed', 'interrupted', 'cancelled'].includes(analysisJob.state)) return
    setError(null)
    try {
      setAnalysisJob(await api.retryJob(analysisJob.id))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '重试拆书任务失败')
    }
  }

  return (
    <section className="reference-lab" aria-labelledby="reference-lab-title">
      <header className="reference-lab-heading">
        <div>
          <p>拆书实验室 · 本地隔离</p>
          <h2 id="reference-lab-title">把长篇拆成可组合的结构区段</h2>
        </div>
        <span>{workspace.reference_works.length} 本 · {workspace.reference_works.reduce((sum, work) => sum + work.segments.length, 0)} 段</span>
      </header>

      <div className="reference-import-grid">
        <label className="reference-file-field">
          选择参考小说文件
          <input
            type="file"
            aria-label="选择参考小说文件"
            accept=".txt,.md,.markdown,.pdf,text/plain,text/markdown,application/pdf"
            onChange={(event) => chooseFile(event.target.files?.[0])}
          />
          <span>{file ? file.name : 'TXT / Markdown / PDF · 最大 25 MB'}</span>
        </label>
        <label>
          作品名
          <input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} />
        </label>
        <label>
          作品权利基础
          <select value={rightsBasis} onChange={(event) => setRightsBasis(event.target.value as ReferenceRightsBasis)}>
            {Object.entries(rightsLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label>
          每个分析区段
          <select value={segmentCharacters} onChange={(event) => setSegmentCharacters(Number(event.target.value))}>
            <option value={250_000}>25 万字</option>
            <option value={500_000}>50 万字（推荐）</option>
            <option value={1_000_000}>100 万字</option>
          </select>
        </label>
      </div>
      {file && !filePreview ? (
        <button
          className="reference-import-action"
          type="button"
          onClick={() => { void previewFile() }}
          disabled={isPreviewing}
        >
          {isPreviewing ? '正在安全解析…' : '检测编码并查看预览'}
        </button>
      ) : null}
      {filePreview ? (
        <section className="reference-file-preview" aria-label="参考文件预览">
          <header>
            <strong>{filePreview.source_format.toUpperCase()} · {filePreview.source_encoding}</strong>
            <span>置信度 {Math.round(filePreview.encoding_confidence * 100)}%</span>
            {filePreview.page_count > 0 ? <span>{filePreview.page_count} 页</span> : null}
          </header>
          <pre>{filePreview.preview}</pre>
          <small>内容指纹 {filePreview.content_sha256.slice(0, 12)} · {filePreview.total_characters.toLocaleString('zh-CN')} 字</small>
          {filePreview.import_state === 'needs_review' ? (
            <label className="reference-processing-consent">
              <input
                type="checkbox"
                checked={confirmedUncertainEncoding}
                onChange={(event) => setConfirmedUncertainEncoding(event.target.checked)}
              />
              预览文字与原文件一致，确认按当前编码导入
            </label>
          ) : null}
        </section>
      ) : null}
      <button
        className="reference-import-action"
        type="button"
        onClick={() => { void importWork() }}
        disabled={
          !file
          || !filePreview
          || !title.trim()
          || isImporting
          || (filePreview.import_state === 'needs_review' && !confirmedUncertainEncoding)
        }
      >
        {isImporting ? '正在本地切段…' : `导入并按 ${formatWan(segmentCharacters)}字切段`}
      </button>
      <p className="reference-boundary-note">
        原文默认只保存在本地隔离库；只有勾选发送确认并点击萃取后，选中区段才会分块发送给当前 AI。正文 AI 始终不能读取参考原文。
      </p>
      {error ? <p className="agent-error" role="alert">{error}</p> : null}

      <div className="reference-shelf" aria-label="参考作品区段">
        {workspace.reference_works.length > 0 ? workspace.reference_works.map((work) => (
          <article className="reference-folio" key={work.id}>
            <header>
              <div>
                <small>{work.source_format.toUpperCase()} · {rightsLabels[work.rights_basis]}</small>
                <strong>{work.title}</strong>
              </div>
              <span>{formatWan(work.total_characters)}字</span>
            </header>
            <div className="segment-ruler" aria-hidden="true">
              {work.segments.map((segment) => <i key={segment.id} data-selected={selectedSegments.has(segment.id)} />)}
            </div>
            <div className="reference-segments">
              {work.segments.map((segment) => (
                <label key={segment.id} data-selected={selectedSegments.has(segment.id)}>
                  <input
                    type="checkbox"
                    checked={selectedSegments.has(segment.id)}
                    onChange={() => toggleSegment(segment.id)}
                    aria-label={`选择${work.title}第 ${segment.ordinal} 段`}
                  />
                  <span>区段 {String(segment.ordinal).padStart(2, '0')}</span>
                  <strong>{(segment.start_char + 1).toLocaleString('zh-CN')}–{segment.end_char.toLocaleString('zh-CN')} 字</strong>
                  <small>
                    {segment.chapter_start
                      ? `${segment.chapter_start}${segment.chapter_end && segment.chapter_end !== segment.chapter_start ? ` → ${segment.chapter_end}` : ''}`
                      : '未识别章节标题，按字符边界切分'}
                  </small>
                </label>
              ))}
            </div>
          </article>
        )) : (
          <p className="reference-empty">导入第一本作品后，这里会像书脊一样排列它的 50 万字区段。</p>
        )}
      </div>

      <footer className="reference-selection" data-ready={analysisReady}>
        <strong>
          {selectedSegments.size === 0
            ? '尚未选择分析区段'
            : selection.workCount >= 2
              ? `已跨 ${selection.workCount} 本书选择 ${selectedSegments.size} 个区段`
              : `已从 1 本书选择 ${selectedSegments.size} 个区段，还需选择另一本`}
        </strong>
        <span>
          {selection.characterCount > 2_000_000
            ? '单次最多处理 200 万字，请减少区段'
            : selection.segmentIds.length > 12
              ? '单次最多选择 12 个区段'
              : analysisReady ? '已具备多书萃取条件' : '至少选择两本不同作品'}
        </span>
      </footer>

      <section className="reference-analysis-controls" aria-label="六维结构萃取">
        <label>
          多书分析重点
          <textarea
            value={authorFocus}
            onChange={(event) => setAuthorFocus(event.target.value)}
            maxLength={1000}
            rows={2}
            placeholder="例如：重点比较资源增长与阶段结局"
          />
        </label>
        <label className="reference-processing-consent">
          <input
            type="checkbox"
            checked={confirmedExternalProcessing}
            onChange={(event) => setConfirmedExternalProcessing(event.target.checked)}
          />
          <span>允许把选中区段分块发送给当前 AI</span>
        </label>
        <p>将发送 {selection.characterCount.toLocaleString('zh-CN')} 字；每次约 5 万字分块处理，再用结构化结果跨书合成。</p>
        <button
          type="button"
          onClick={synthesizePatterns}
          disabled={!analysisReady || !confirmedExternalProcessing || isAnalyzing}
        >
          {isAnalyzing ? '正在分块萃取…' : 'AI 萃取六维结构'}
        </button>
        {analysisJob ? (
          <div className="reference-job-status" role="status" aria-live="polite">
            <div>
              <strong>{analysisJob.current_step || '拆书任务已进入本地队列'}</strong>
              <span>
                {analysisJob.progress_current} / {analysisJob.progress_total} 块 ·
                已完成 {analysisJob.completed_calls} 次模型调用
              </span>
            </div>
            <progress
              aria-label="拆书任务进度"
              value={analysisJob.progress_current}
              max={Math.max(analysisJob.progress_total, 1)}
            />
            {isAnalyzing ? (
              <button type="button" onClick={cancelAnalysis}>停止后续调用</button>
            ) : ['failed', 'interrupted', 'cancelled'].includes(analysisJob.state) ? (
              <button type="button" onClick={retryAnalysis}>从失败块继续</button>
            ) : null}
          </div>
        ) : null}
      </section>

      {workspace.reference_pattern_cards.length > 0 ? (
        <section className="reference-pattern-archive" aria-labelledby="reference-pattern-archive-title">
          <header>
            <div>
              <small>持久化档案 · 刷新后保留</small>
              <h3 id="reference-pattern-archive-title">六维结构模式卡</h3>
            </div>
            <span>{workspace.reference_pattern_cards.length} 张候选</span>
          </header>
          <div className="reference-pattern-list">
            {workspace.reference_pattern_cards.map((card) => (
              <ReferencePatternCardPanel
                key={card.id}
                card={card}
                workspace={workspace}
                sourceLabels={selection.sourceLabels}
                onWorkspaceChanged={onWorkspaceChanged}
              />
            ))}
          </div>
        </section>
      ) : null}
    </section>
  )
}

interface ReferencePatternCardPanelProps {
  card: ReferencePatternCard
  workspace: WorkspaceSummary
  sourceLabels: Map<string, string>
  onWorkspaceChanged: (workspace: Workspace | WorkspaceSummary) => void
}

function ReferencePatternCardPanel({
  card,
  workspace,
  sourceLabels,
  onWorkspaceChanged,
}: ReferencePatternCardPanelProps) {
  const [selectedDimensions, setSelectedDimensions] = useState<Set<ReferencePatternDimension>>(
    () => new Set(dimensionLabels.map(([key]) => key)),
  )
  const [applicationNote, setApplicationNote] = useState('')
  const [confirmedOriginalAdaptation, setConfirmedOriginalAdaptation] = useState(false)
  const [isApplying, setIsApplying] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)
  const [lifecycleTarget, setLifecycleTarget] = useState<ReferenceApplicationLifecycleState | null>(null)
  const [lifecycleMessage, setLifecycleMessage] = useState<string | null>(null)
  const [lifecycleError, setLifecycleError] = useState<string | null>(null)
  const existingApplication = workspace.reference_pattern_applications.find(
    (application) => application.pattern_card_id === card.id,
  )

  function toggleDimension(dimension: ReferencePatternDimension) {
    setSelectedDimensions((current) => {
      const next = new Set(current)
      if (next.has(dimension)) next.delete(dimension)
      else next.add(dimension)
      return next
    })
  }

  async function applyToProject() {
    if (selectedDimensions.size === 0 || !confirmedOriginalAdaptation || existingApplication) return
    setIsApplying(true)
    setApplyError(null)
    try {
      const application = await api.applyReferencePattern(workspace.project.id, card.id, {
        selected_dimensions: dimensionLabels
          .map(([key]) => key)
          .filter((dimension) => selectedDimensions.has(dimension)),
        application_note: applicationNote.trim(),
        confirm_original_adaptation: true,
      })
      onWorkspaceChanged({
        ...workspace,
        reference_pattern_applications: [
          ...workspace.reference_pattern_applications,
          application,
        ],
      })
    } catch (caught) {
      setApplyError(caught instanceof Error ? caught.message : '模式卡应用失败')
    } finally {
      setIsApplying(false)
    }
  }

  async function updateLifecycle(nextState: ReferenceApplicationLifecycleState) {
    if (!existingApplication || lifecycleTarget) return
    const previousState = existingApplication.lifecycle_state
    setLifecycleTarget(nextState)
    setLifecycleMessage(null)
    setLifecycleError(null)
    try {
      const updated = await api.updateReferenceApplicationLifecycle(
        workspace.project.id,
        existingApplication.id,
        {
          lifecycle_state: nextState,
          expected_lifecycle_revision: existingApplication.lifecycle_revision,
        },
      )
      onWorkspaceChanged(replaceApplication(workspace, updated))
      setLifecycleMessage(
        nextState === 'active'
          ? '已启用给 AI，后续章纲与正文会使用这份蓝图。'
          : nextState === 'archived'
            ? '已归档，蓝图、报告和来源仍会保留。'
            : previousState === 'archived'
              ? '已恢复为草稿，暂不会传给 AI。'
              : '已暂停使用，这份蓝图不再进入 AI 上下文或原创性门禁。',
      )
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        try {
          onWorkspaceChanged(await api.getProjectSummary(workspace.project.id))
          setLifecycleError(`${caught.message}，已刷新最新状态。`)
        } catch {
          setLifecycleError(`${caught.message}；最新状态读取失败，请重新打开拆书库。`)
        }
      } else {
        setLifecycleError(caught instanceof Error ? caught.message : '参考蓝图状态更新失败')
      }
    } finally {
      setLifecycleTarget(null)
    }
  }

  const lifecycleDescription = existingApplication
    ? existingApplication.lifecycle_state === 'active'
      ? existingApplication.originality_status === 'passed'
        ? '正在用于章纲与正文 AI；暂停或归档不会删除蓝图和检查报告。'
        : '仍参与原创性门禁，可能阻断 AI 写作；可先暂停使用，再继续调整。'
      : existingApplication.lifecycle_state === 'draft'
        ? existingApplication.originality_status === 'passed'
          ? '已暂停，不进入 AI 上下文或门禁；原创性检查已通过，可随时启用。'
          : '已暂停，不进入 AI 上下文或门禁；通过原创性检查后才能启用。'
        : '仅保留历史蓝图、报告和来源，不进入 AI 上下文或原创性门禁。'
    : null

  return (
    <article className="reference-proposal">
      <header>
        <div>
          <small>{card.provider} · {card.model}</small>
          <h4>{card.author_focus || '均衡比较六个结构维度'}</h4>
        </div>
        <span>{new Date(card.created_at).toLocaleDateString('zh-CN')}</span>
      </header>
      <div className="reference-dimensions">
        {dimensionLabels.map(([key, label]) => {
          const dimension = card[key]
          return (
            <article key={key}>
              <small>{label}</small>
              <strong>{dimension.summary}</strong>
              <p><b>可迁移：</b>{dimension.transferable_logic}</p>
              <p><b>风险：</b>{dimension.adaptation_risk}</p>
              <div>
                {dimension.source_segment_ids.map((sourceId) => (
                  <span key={sourceId}>{sourceLabels.get(sourceId) ?? '历史来源区段'}</span>
                ))}
              </div>
            </article>
          )
        })}
      </div>
      <dl className="reference-synthesis-notes">
        <div><dt>共同规律</dt><dd>{card.shared_patterns.join('；')}</dd></div>
        <div><dt>关键差异</dt><dd>{card.differences.join('；')}</dd></div>
        <div><dt>人物关系重组</dt><dd>{card.relationship_recomposition}</dd></div>
        <div><dt>原创性风险</dt><dd>{card.originality_risks.join('；') || '未返回额外风险'}</dd></div>
      </dl>

      <section className="reference-application" aria-label="应用结构到当前作品">
        <div className="reference-application-heading">
          <div><small>目标作品</small><strong>《{workspace.project.title}》</strong></div>
          {existingApplication ? (
            <span data-state={existingApplication.lifecycle_state}>
              {lifecycleLabels[existingApplication.lifecycle_state]}
            </span>
          ) : <span>待作者选择</span>}
        </div>
        {existingApplication ? (
          <>
            <div className="reference-lifecycle-controls">
              <p>{lifecycleDescription}</p>
              <div role="group" aria-label="参考蓝图使用状态">
                {existingApplication.lifecycle_state === 'active' ? (
                  <button
                    type="button"
                    onClick={() => updateLifecycle('draft')}
                    disabled={lifecycleTarget !== null}
                  >
                    {lifecycleTarget === 'draft' ? '正在暂停…' : '暂停用于 AI'}
                  </button>
                ) : existingApplication.lifecycle_state === 'draft' ? (
                  <button
                    type="button"
                    onClick={() => updateLifecycle('active')}
                    disabled={existingApplication.originality_status !== 'passed' || lifecycleTarget !== null}
                  >
                    {lifecycleTarget === 'active' ? '正在启用…' : '启用给 AI'}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => updateLifecycle('draft')}
                    disabled={lifecycleTarget !== null}
                  >
                    {lifecycleTarget === 'draft' ? '正在恢复…' : '恢复为草稿'}
                  </button>
                )}
                {existingApplication.lifecycle_state !== 'archived' ? (
                  <button
                    type="button"
                    onClick={() => updateLifecycle('archived')}
                    disabled={lifecycleTarget !== null}
                  >
                    {lifecycleTarget === 'archived' ? '正在归档…' : '归档'}
                  </button>
                ) : null}
              </div>
            </div>
            {lifecycleMessage ? <p className="reference-lifecycle-message" role="status" aria-live="polite">{lifecycleMessage}</p> : null}
            {lifecycleError ? <p className="agent-error" role="alert">{lifecycleError}</p> : null}
            <ReferenceBlueprintEditor
              key={`${existingApplication.id}:${existingApplication.revision}:${existingApplication.latest_report_id ?? ''}`}
              application={existingApplication}
              workspace={workspace}
              sourceLabels={sourceLabels}
              onWorkspaceChanged={onWorkspaceChanged}
            />
          </>
        ) : (
          <>
            <fieldset>
              <legend>选择要带入当前作品的维度</legend>
              {dimensionLabels.map(([key, label]) => (
                <label key={key} data-selected={selectedDimensions.has(key)}>
                  <input
                    type="checkbox"
                    aria-label={`应用维度：${label}`}
                    checked={selectedDimensions.has(key)}
                    onChange={() => toggleDimension(key)}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </fieldset>
            <label className="reference-application-note">
              用于当前作品的改编备注
              <textarea
                value={applicationNote}
                onChange={(event) => setApplicationNote(event.target.value)}
                maxLength={1000}
                rows={3}
                placeholder="例如：时代换成 1998 年南平，资源线改为本地制造业，人物关系全部重组"
              />
            </label>
            <label className="reference-originality-confirm">
              <input
                type="checkbox"
                aria-label="确认原创改编边界"
                checked={confirmedOriginalAdaptation}
                onChange={(event) => setConfirmedOriginalAdaptation(event.target.checked)}
              />
              <span>我会重写人物、地点、专名、产业细节和具体场景，不把模式卡当作仿写底稿。</span>
            </label>
            <button
              type="button"
              onClick={applyToProject}
              disabled={selectedDimensions.size === 0 || !confirmedOriginalAdaptation || isApplying}
            >
              {isApplying ? '正在建立应用蓝图…' : `应用到《${workspace.project.title}》`}
            </button>
          </>
        )}
        {applyError ? <p className="agent-error" role="alert">{applyError}</p> : null}
      </section>
    </article>
  )
}

interface ReferenceBlueprintEditorProps {
  application: ReferencePatternApplication
  workspace: WorkspaceSummary
  sourceLabels: Map<string, string>
  onWorkspaceChanged: (workspace: Workspace | WorkspaceSummary) => void
}

const modeLabels = {
  preserve: '保留功能',
  adjust: '调整表达',
  reconstruct: '重构',
} as const

const riskLabels = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
} as const

const sceneSignalLabels: Record<SceneOriginalityCheck['findings'][number]['signal'], string> = {
  semantic_scene: '场景功能',
  ordered_sequence: '场景顺序',
  causal_graph: '因果链',
  character_function_graph: '人物功能关系',
  multi_source_convergence: '多书汇聚',
}

const entityKindLabels: Record<BlueprintEntityKind, string> = {
  character: '人物',
  location: '地点',
  organization: '组织',
  proper_noun: '专名',
}

function parseNamedEntities(value: string): BlueprintDimensionState['named_entities'] {
  const kindByLabel = Object.fromEntries(
    Object.entries(entityKindLabels).map(([kind, label]) => [label, kind]),
  ) as Record<string, BlueprintEntityKind>
  return value.split('\n').map((line) => line.trim()).filter(Boolean).slice(0, 20).map((line) => {
    const [first, second = '', ...parts] = line.split('｜').map((item) => item.trim())
    const kind = kindByLabel[first] ?? (
      first in entityKindLabels ? first as BlueprintEntityKind : 'proper_noun'
    )
    return kind === 'proper_noun' && !kindByLabel[first] && !(first in entityKindLabels)
      ? { kind, name: first, function: [second, ...parts].filter(Boolean).join('｜') }
      : { kind, name: second, function: parts.join('｜') }
  }).filter((item) => item.name)
}

function copyBlueprint(blueprint: ReferenceBlueprintState): ReferenceBlueprintState {
  return JSON.parse(JSON.stringify(blueprint)) as ReferenceBlueprintState
}

function replaceApplication(
  workspace: WorkspaceSummary,
  application: ReferencePatternApplication,
): WorkspaceSummary {
  return {
    ...workspace,
    reference_pattern_applications: workspace.reference_pattern_applications.map((item) => (
      item.id === application.id ? application : item
    )),
  }
}

function ReferenceBlueprintEditor({
  application,
  workspace,
  sourceLabels,
  onWorkspaceChanged,
}: ReferenceBlueprintEditorProps) {
  const [draft, setDraft] = useState<ReferenceBlueprintState | null>(() => (
    application.blueprint ? copyBlueprint(application.blueprint) : null
  ))
  const [changedDimensions, setChangedDimensions] = useState<Set<ReferencePatternDimension>>(
    () => new Set(),
  )
  const [relationshipChanged, setRelationshipChanged] = useState(false)
  const [report, setReport] = useState<OriginalityReport | null>(null)
  const [sceneReport, setSceneReport] = useState<SceneOriginalityCheck | null>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [isLoadingReport, setIsLoadingReport] = useState(false)
  const [editorError, setEditorError] = useState<string | null>(null)

  function updateDimension(
    dimension: ReferencePatternDimension,
    update: (current: BlueprintDimensionState) => BlueprintDimensionState,
  ) {
    setDraft((current) => {
      if (!current?.dimensions[dimension]) return current
      return {
        ...current,
        dimensions: {
          ...current.dimensions,
          [dimension]: update(current.dimensions[dimension]),
        },
      }
    })
    setChangedDimensions((current) => new Set(current).add(dimension))
  }

  function updateRelationship(
    update: (current: BlueprintRelationshipState) => BlueprintRelationshipState,
  ) {
    setDraft((current) => current ? {
      ...current,
      relationship: update(current.relationship),
    } : current)
    setRelationshipChanged(true)
  }

  async function saveBlueprint() {
    if (!draft || (!changedDimensions.size && !relationshipChanged)) return
    setIsSaving(true)
    setEditorError(null)
    try {
      const updated = await api.updateReferenceBlueprint(
        workspace.project.id,
        application.id,
        {
          blueprint: draft,
          changed_dimensions: [...changedDimensions],
          relationship_changed: relationshipChanged,
          expected_revision: application.revision,
        },
      )
      onWorkspaceChanged(replaceApplication(workspace, updated))
    } catch (caught) {
      setEditorError(caught instanceof Error ? caught.message : '蓝图保存失败')
    } finally {
      setIsSaving(false)
    }
  }

  async function openReport() {
    if (!application.latest_report_id) return
    setIsLoadingReport(true)
    setEditorError(null)
    try {
      setReport(await api.getOriginalityReport(application.latest_report_id))
    } catch (caught) {
      setEditorError(caught instanceof Error ? caught.message : '原创性报告加载失败')
    } finally {
      setIsLoadingReport(false)
    }
  }

  async function acknowledgeReport() {
    setIsSaving(true)
    setEditorError(null)
    try {
      const updated = await api.acknowledgeOriginalityReport(
        workspace.project.id,
        application.id,
        { expected_revision: application.revision },
      )
      onWorkspaceChanged(replaceApplication(workspace, updated))
      if (application.latest_report_id) {
        setReport(await api.getOriginalityReport(application.latest_report_id))
      }
    } catch (caught) {
      setEditorError(caught instanceof Error ? caught.message : '风险确认失败')
    } finally {
      setIsSaving(false)
    }
  }

  async function openSceneReport() {
    setIsLoadingReport(true)
    setEditorError(null)
    try {
      const latest = await api.getOrRunSceneOriginalityCheck(
        workspace.project.id,
        application.id,
      )
      setSceneReport(await api.getSceneOriginalityCheck(latest.id))
    } catch (caught) {
      setEditorError(caught instanceof Error ? caught.message : '场景情节图报告加载失败')
    } finally {
      setIsLoadingReport(false)
    }
  }

  async function acknowledgeSceneReport() {
    setIsSaving(true)
    setEditorError(null)
    try {
      const updated = await api.acknowledgeSceneOriginalityCheck(
        workspace.project.id,
        application.id,
        { expected_revision: application.revision },
      )
      onWorkspaceChanged(replaceApplication(workspace, updated))
      if (sceneReport) {
        setSceneReport(await api.getSceneOriginalityCheck(sceneReport.id))
      }
    } catch (caught) {
      setEditorError(caught instanceof Error ? caught.message : '场景风险确认失败')
    } finally {
      setIsSaving(false)
    }
  }

  if (!draft) {
    return <p>这是旧版蓝图，已暂停传给 AI；请重新应用或恢复后完成原创性检查。</p>
  }

  const risk = application.risk_level
  return (
    <div className="reference-blueprint-editor">
      <div className="originality-gate-summary" data-risk={risk ?? 'unchecked'}>
        <div>
          <small>原创性门禁 · {application.threshold_version ?? '待检查'}</small>
          <strong>{risk ? riskLabels[risk] : '待检查'}</strong>
          <span>
            {application.originality_status === 'passed'
              ? '已通过，章纲与正文 AI 可使用这份蓝图。'
              : application.originality_status === 'review_required'
                ? '需查看完整报告并显式确认，当前不传给 AI。'
                : '当前不传给章纲或正文 AI，请先重构标记项。'}
          </span>
        </div>
        <div className="originality-gate-actions">
          <button type="button" onClick={openReport} disabled={!application.latest_report_id || isLoadingReport}>
            {isLoadingReport ? '加载报告…' : '查看文本与结构报告'}
          </button>
          <button type="button" onClick={openSceneReport} disabled={isLoadingReport}>
            查看场景情节图报告
          </button>
        </div>
      </div>

      {report ? (
        <section className="originality-report" aria-label="原创性报告" data-risk={report.risk_level}>
          <header>
            <div><small>风险分</small><strong>{report.score}/100</strong></div>
            <div><small>检查范围</small><strong>{report.checked_dimensions.length} 个维度</strong></div>
            <div><small>规则版本</small><strong>{report.threshold_version}</strong></div>
          </header>
          {report.evidence.length ? (
            <ul>
              {report.evidence.map((evidence) => (
                <li key={evidence.evidence_sha256}>
                  <strong>+{evidence.score} · {evidence.summary}</strong>
                  <span>
                    {evidence.dimension
                      ? dimensionLabels.find(([key]) => key === evidence.dimension)?.[1]
                      : '组合检查'}
                    {evidence.source_segment_id
                      ? ` · ${sourceLabels.get(evidence.source_segment_id) ?? '来源区段'}`
                      : ''}
                  </span>
                </li>
              ))}
            </ul>
          ) : <p>没有检出需提示的结构组合或文本重合。</p>}
          <p className="originality-legal-notice">{report.legal_notice}</p>
          {application.originality_status === 'review_required' && report.risk_level === 'medium' ? (
            <button type="button" onClick={acknowledgeReport} disabled={isSaving}>
              我已查看报告，确认继续使用这份蓝图
            </button>
          ) : null}
          {application.originality_status === 'blocked' ? (
            <p className="originality-blocked-note">高风险不能手动跳过；请根据证据重构下方维度后重新检查。</p>
          ) : null}
        </section>
      ) : null}

      {sceneReport ? (
        <section className="originality-report scene-originality-report" aria-label="场景情节图报告" data-risk={sceneReport.risk_level}>
          <header>
            <div><small>场景风险分</small><strong>{sceneReport.score}/100</strong></div>
            <div><small>参考范围</small><strong>{sceneReport.source_work_count} 本书</strong></div>
            <div><small>场景节点</small><strong>{sceneReport.candidate_graph.nodes.length} 个</strong></div>
          </header>
          {sceneReport.candidate_graph.nodes.length ? (
            <ol className="scene-plot-strip" aria-label="候选场景顺序">
              {sceneReport.candidate_graph.nodes.map((node, index) => (
                <li key={node.id}>
                  <small>场景 {index + 1}</small>
                  <strong>{node.label}</strong>
                  {node.semantic_terms.length ? <span>{node.semantic_terms.join(' · ')}</span> : null}
                </li>
              ))}
            </ol>
          ) : <p>当前蓝图没有可比较的明确场景节拍。</p>}
          {sceneReport.findings.length ? (
            <ul>
              {sceneReport.findings.map((finding) => (
                <li key={finding.evidence_sha256}>
                  <strong>{sceneSignalLabels[finding.signal]} · {finding.score}/100</strong>
                  <span>{finding.summary}</span>
                </li>
              ))}
            </ul>
          ) : <p>未检出需提示的场景语义、顺序或因果图相似信号。</p>}
          <p className="originality-legal-notice">{sceneReport.legal_notice}</p>
          {application.originality_status === 'review_required' && sceneReport.risk_level === 'medium' ? (
            <button type="button" onClick={acknowledgeSceneReport} disabled={isSaving}>
              我已查看情节图，确认继续使用这份蓝图
            </button>
          ) : null}
          {sceneReport.risk_level === 'high' ? (
            <p className="originality-blocked-note">高风险不能确认跳过；请改变场景顺序、关键决策或后果链后重新检查。</p>
          ) : null}
        </section>
      ) : null}

      <div className="blueprint-dimension-list">
        {application.selected_dimensions.map((dimension) => {
          const state = draft.dimensions[dimension]
          if (!state) return null
          const label = dimensionLabels.find(([key]) => key === dimension)?.[1] ?? dimension
          return (
            <section className="blueprint-dimension" key={dimension} data-changed={changedDimensions.has(dimension)}>
              <header>
                <div><small>{label}</small><strong>v{state.version}</strong></div>
                <label>
                  <input
                    type="checkbox"
                    checked={state.locked}
                    onChange={(event) => updateDimension(dimension, (current) => ({
                      ...current,
                      locked: event.target.checked,
                    }))}
                  />
                  锁定这一版
                </label>
              </header>
              <label>处理方式
                <select
                  aria-label={`${label}处理方式`}
                  value={state.mode}
                  disabled={state.locked}
                  onChange={(event) => updateDimension(dimension, (current) => ({
                    ...current,
                    mode: event.target.value as BlueprintDimensionState['mode'],
                  }))}
                >
                  {Object.entries(modeLabels).map(([value, modeLabel]) => (
                    <option key={value} value={value}>{modeLabel}</option>
                  ))}
                </select>
              </label>
              <label>来源结构（只读）
                <textarea value={`${state.source.summary}\n${state.source.transferable_logic}`} rows={3} readOnly />
              </label>
              <label>作者改编意图
                <textarea
                  value={state.author_edits}
                  rows={3}
                  maxLength={1200}
                  disabled={state.locked}
                  onChange={(event) => updateDimension(dimension, (current) => ({
                    ...current,
                    author_edits: event.target.value,
                  }))}
                />
              </label>
              <label>候选蓝图摘要
                <textarea
                  aria-label={`${label}候选蓝图摘要`}
                  value={state.generated_variant.summary}
                  rows={3}
                  maxLength={1200}
                  disabled={state.locked}
                  onChange={(event) => updateDimension(dimension, (current) => ({
                    ...current,
                    generated_variant: {
                      ...current.generated_variant,
                      summary: event.target.value,
                    },
                  }))}
                />
              </label>
              <label>可迁移逻辑
                <textarea
                  value={state.generated_variant.transferable_logic}
                  rows={3}
                  maxLength={1200}
                  disabled={state.locked}
                  onChange={(event) => updateDimension(dimension, (current) => ({
                    ...current,
                    generated_variant: {
                      ...current.generated_variant,
                      transferable_logic: event.target.value,
                    },
                  }))}
                />
              </label>
              <label>来源实体（每行：人物/地点/组织/专名｜名称｜功能）
                <textarea
                  value={state.named_entities.map((item) => (
                    `${entityKindLabels[item.kind]}｜${item.name}｜${item.function}`
                  )).join('\n')}
                  rows={2}
                  disabled={state.locked}
                  onChange={(event) => updateDimension(dimension, (current) => ({
                    ...current,
                    named_entities: parseNamedEntities(event.target.value),
                  }))}
                />
              </label>
              {dimension === 'key_scene_sequence' ? (
                <label>新作关键场景节拍（每行一个）
                  <textarea
                    value={state.key_beats.join('\n')}
                    rows={4}
                    disabled={state.locked}
                    onChange={(event) => updateDimension(dimension, (current) => ({
                      ...current,
                      key_beats: event.target.value.split('\n').map((line) => line.trim()).filter(Boolean).slice(0, 20),
                    }))}
                  />
                </label>
              ) : null}
            </section>
          )
        })}
      </div>

      <section className="blueprint-relationship" data-changed={relationshipChanged}>
        <header><div><small>人物关系重组</small><strong>v{draft.relationship.version}</strong></div>
          <label><input
            type="checkbox"
            checked={draft.relationship.locked}
            onChange={(event) => updateRelationship((current) => ({ ...current, locked: event.target.checked }))}
          />锁定这一版</label>
        </header>
        <label>来源关系（只读）<textarea value={draft.relationship.source} rows={2} readOnly /></label>
        <label>人物重组意图<textarea
          value={draft.relationship.author_edits}
          rows={3}
          disabled={draft.relationship.locked}
          onChange={(event) => updateRelationship((current) => ({ ...current, author_edits: event.target.value }))}
        /></label>
        <label>新作人物关系<textarea
          aria-label="新作人物关系"
          value={draft.relationship.generated_variant}
          rows={3}
          disabled={draft.relationship.locked}
          onChange={(event) => updateRelationship((current) => ({ ...current, generated_variant: event.target.value }))}
        /></label>
        <label>关系结构（每行：角色A｜关系｜角色B｜说明）<textarea
          value={draft.relationship.relationships.map((item) => (
            `${item.left_role}｜${item.relation}｜${item.right_role}｜${item.notes}`
          )).join('\n')}
          rows={4}
          disabled={draft.relationship.locked}
          onChange={(event) => updateRelationship((current) => ({
            ...current,
            relationships: event.target.value.split('\n').map((line) => line.trim()).filter(Boolean).slice(0, 20).flatMap((line) => {
              const [left_role, relation, right_role, ...notes] = line.split('｜').map((item) => item.trim())
              return left_role && relation && right_role
                ? [{ left_role, relation, right_role, notes: notes.join('｜') }]
                : []
            }),
          }))}
        /></label>
      </section>

      <button
        type="button"
        className="save-blueprint"
        onClick={saveBlueprint}
        disabled={isSaving || (!changedDimensions.size && !relationshipChanged)}
      >
        {isSaving ? '正在重新检查…' : `保存并重检 ${changedDimensions.size + (relationshipChanged ? 1 : 0)} 项`}
      </button>
      <p className="originality-legal-notice">原创性风险提示用于创作风控，不是法律结论。</p>
      {editorError ? <p className="agent-error" role="alert">{editorError}</p> : null}
    </div>
  )
}
