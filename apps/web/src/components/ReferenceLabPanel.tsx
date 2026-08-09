import type {
  ReferencePatternCard,
  ReferencePatternDimension,
  ReferenceRightsBasis,
  Workspace,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { useMemo, useState } from 'react'

import { api } from '../api'

interface ReferenceLabPanelProps {
  workspace: WorkspaceSummary
  onWorkspaceChanged: (workspace: Workspace | WorkspaceSummary) => void
}

const MAX_FILE_BYTES = 20 * 1024 * 1024
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

function formatWan(value: number) {
  return value % 10_000 === 0 ? `${value / 10_000} 万` : value.toLocaleString('zh-CN')
}

export function ReferenceLabPanel({ workspace, onWorkspaceChanged }: ReferenceLabPanelProps) {
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [rightsBasis, setRightsBasis] = useState<ReferenceRightsBasis>('self_owned')
  const [segmentCharacters, setSegmentCharacters] = useState(DEFAULT_SEGMENT_CHARACTERS)
  const [selectedSegments, setSelectedSegments] = useState<Set<string>>(() => new Set())
  const [isImporting, setIsImporting] = useState(false)
  const [authorFocus, setAuthorFocus] = useState('')
  const [confirmedExternalProcessing, setConfirmedExternalProcessing] = useState(false)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
    if (!nextFile) {
      setFile(null)
      return
    }
    const extension = nextFile.name.toLowerCase().split('.').pop()
    if (!extension || !['txt', 'md', 'markdown'].includes(extension)) {
      setFile(null)
      setError('当前只支持 UTF-8 TXT 或 Markdown 文件。')
      return
    }
    if (nextFile.size > MAX_FILE_BYTES) {
      setFile(null)
      setError('单个参考文件不能超过 20 MB。')
      return
    }
    setFile(nextFile)
    setTitle(nextFile.name.replace(/\.(?:txt|md|markdown)$/i, ''))
  }

  async function importWork() {
    if (!file || !title.trim()) return
    setIsImporting(true)
    setError(null)
    try {
      const content = await file.text()
      const imported = await api.importReferenceWork(workspace.project.id, {
        title: title.trim(),
        source_filename: file.name,
        rights_basis: rightsBasis,
        segment_target_characters: segmentCharacters,
        content,
      })
      onWorkspaceChanged({
        ...workspace,
        reference_works: [...workspace.reference_works, imported],
      })
      setFile(null)
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
    setIsAnalyzing(true)
    setError(null)
    try {
      const card = await api.synthesizeReferencePatterns(workspace.project.id, {
        selected_segment_ids: selection.segmentIds,
        author_focus: authorFocus.trim(),
        confirm_external_processing: true,
      })
      onWorkspaceChanged({
        ...workspace,
        reference_pattern_cards: [
          card,
          ...workspace.reference_pattern_cards.filter((item) => item.id !== card.id),
        ],
      })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '多书结构萃取失败')
    } finally {
      setIsAnalyzing(false)
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
            accept=".txt,.md,.markdown,text/plain,text/markdown"
            onChange={(event) => chooseFile(event.target.files?.[0])}
          />
          <span>{file ? file.name : 'TXT / Markdown · 最大 20 MB'}</span>
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
      <button
        className="reference-import-action"
        type="button"
        onClick={importWork}
        disabled={!file || !title.trim() || isImporting}
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
                <small>{work.source_format === 'markdown' ? 'MARKDOWN' : 'TXT'} · {rightsLabels[work.rights_basis]}</small>
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
          {existingApplication ? <span>已应用到当前作品</span> : <span>待作者选择</span>}
        </div>
        {existingApplication ? (
          <p>已带入 {existingApplication.selected_dimensions.length} 个抽象维度；后续章节 AI 可以读取这份应用蓝图。</p>
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
