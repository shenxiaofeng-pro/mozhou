import type {
  AiChapterBriefProposal,
  Chapter,
  ChapterStatus,
  GenerationRun,
  Project,
  Workspace,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { useCallback, useState } from 'react'

import { ApiError, api } from '../api'
import { getStoryAnchorLabels } from '../genre'
import { AiCoauthorPanel } from './AiCoauthorPanel'
import { BookDirectorPanel } from './BookDirectorPanel'
import { FactTimelinePanel } from './FactTimelinePanel'
import { FutureKnowledgePanel } from './FutureKnowledgePanel'
import { RhythmWindowPanel } from './RhythmWindowPanel'
import { ReviewWorkbench } from './ReviewWorkbench'
import { SerialControlPanel } from './SerialControlPanel'
import { StoryLedgerPanel } from './StoryLedgerPanel'
import { SourceLibraryPanel } from './SourceLibraryPanel'

interface DirectorPanelProps {
  project: Project
  workspace: WorkspaceSummary
  chapter: Chapter
  wordCount: number
  canUpdateChapter: boolean
  onChapterUpdated: (chapter: Chapter) => void
  onWorkspaceChanged: (workspace: Workspace | WorkspaceSummary) => void
  onOpenChapterProduction?: () => void
}

type BriefField = 'title' | 'reader_promise' | 'opening_hook' | 'state_change' | 'emotional_payoff' | 'ending_cliffhanger'

const statusLabels: Record<ChapterStatus, string> = {
  planned: '待写',
  drafted: '草稿',
  reviewing: '审校中',
  approved: '已定稿',
}

const primaryTransitions: Record<ChapterStatus, { target: ChapterStatus, label: string }> = {
  planned: { target: 'drafted', label: '标记为草稿' },
  drafted: { target: 'reviewing', label: '提交审校' },
  reviewing: { target: 'approved', label: '批准定稿' },
  approved: { target: 'drafted', label: '重新打开修改' },
}

export function DirectorPanel({
  project,
  workspace,
  chapter,
  wordCount,
  canUpdateChapter,
  onChapterUpdated,
  onWorkspaceChanged,
  onOpenChapterProduction,
}: DirectorPanelProps) {
  const [brief, setBrief] = useState(() => ({
    title: chapter.title,
    reader_promise: chapter.reader_promise ?? '',
    opening_hook: chapter.opening_hook ?? '',
    state_change: chapter.state_change ?? '',
    emotional_payoff: chapter.emotional_payoff ?? '',
    ending_cliffhanger: chapter.ending_cliffhanger ?? '',
  }))
  const [contextReady, setContextReady] = useState(false)
  const [run, setRun] = useState<GenerationRun | null>(null)
  const [staleRunId, setStaleRunId] = useState<string | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const [isSavingBrief, setIsSavingBrief] = useState(false)
  const [isTransitioning, setIsTransitioning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const anchorLabels = getStoryAnchorLabels(project.genre)
  const briefComplete = brief.opening_hook.trim().length > 0
    && brief.state_change.trim().length > 0
    && brief.ending_cliffhanger.trim().length > 0
  const savedBriefComplete = Boolean(
    chapter.opening_hook.trim()
    && chapter.state_change.trim()
    && chapter.ending_cliffhanger.trim(),
  )
  const briefDirty = brief.title !== chapter.title
    || brief.reader_promise !== (chapter.reader_promise ?? '')
    || brief.opening_hook !== (chapter.opening_hook ?? '')
    || brief.state_change !== (chapter.state_change ?? '')
    || brief.emotional_payoff !== (chapter.emotional_payoff ?? '')
    || brief.ending_cliffhanger !== (chapter.ending_cliffhanger ?? '')
  const isApproved = chapter.status === 'approved'
  const canGenerate = chapter.status === 'planned' || chapter.status === 'drafted'
  const candidateIsStale = Boolean(
    run
    && run.state !== 'applied'
    && (
      staleRunId === run.id
      || run.expected_chapter_revision !== chapter.revision
      || isApproved
    ),
  )
  const primaryTransition = primaryTransitions[chapter.status]
  const transitionNeedsPlan = primaryTransition.target === 'reviewing' || primaryTransition.target === 'approved'
  const transitionDisabled = !canUpdateChapter
    || isTransitioning
    || (primaryTransition.target !== 'drafted' && wordCount === 0)
    || (chapter.status === 'planned' && wordCount === 0)
    || (transitionNeedsPlan && !savedBriefComplete)

  function updateBrief(field: BriefField, value: string) {
    setBrief((current) => ({ ...current, [field]: value }))
    setContextReady(false)
    setRun(null)
    setStaleRunId(null)
  }

  async function saveBrief() {
    if (!canUpdateChapter || !briefDirty || isApproved) return
    setIsSavingBrief(true)
    setError(null)
    try {
      const updated = await api.updateChapterBrief(chapter.id, {
        ...brief,
        expected_revision: chapter.revision,
      })
      onChapterUpdated(updated)
      setContextReady(false)
      setRun(null)
      setStaleRunId(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '章纲保存失败')
    } finally {
      setIsSavingBrief(false)
    }
  }

  async function transitionChapter(targetStatus: ChapterStatus) {
    setIsTransitioning(true)
    setError(null)
    try {
      onChapterUpdated(await api.transitionChapter(chapter.id, {
        target_status: targetStatus,
        expected_revision: chapter.revision,
      }))
      setContextReady(false)
      setRun(null)
      setStaleRunId(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '章节状态更新失败')
    } finally {
      setIsTransitioning(false)
    }
  }

  async function generateCandidate() {
    setIsRunning(true)
    setError(null)
    try {
      const nextRun = await api.startGeneration(chapter.id, chapter.revision)
      setRun(nextRun)
      setStaleRunId(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '假模型运行失败')
    } finally {
      setIsRunning(false)
    }
  }

  async function applyCandidate() {
    if (!run || candidateIsStale) return
    setIsRunning(true)
    setError(null)
    try {
      onChapterUpdated(await api.applyGeneration(run.id, chapter.revision))
      setRun((current) => current ? { ...current, state: 'applied' } : current)
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        setStaleRunId(run.id)
        setError(null)
      } else {
        setError(caught instanceof Error ? caught.message : '候选稿采用失败')
      }
    } finally {
      setIsRunning(false)
    }
  }

  function adoptAiProposal(proposal: AiChapterBriefProposal) {
    setBrief({
      title: proposal.title,
      reader_promise: proposal.reader_promise,
      opening_hook: proposal.opening_hook,
      state_change: proposal.state_change,
      emotional_payoff: proposal.emotional_payoff,
      ending_cliffhanger: proposal.ending_cliffhanger,
    })
    setContextReady(false)
    setRun(null)
    setStaleRunId(null)
  }

  const showDraftCandidate = useCallback((nextRun: GenerationRun) => {
    setRun(nextRun)
    setStaleRunId(null)
    setError(null)
  }, [])

  function closeCandidate() {
    setRun(null)
    setStaleRunId(null)
    setError(null)
  }

  return (
    <aside className="agent-panel" aria-label="AI 工作台">
      <header>
        <p className="section-kicker">本章导演台</p>
        <h2>先确定这一章改变什么</h2>
      </header>
      {onOpenChapterProduction ? (
        <section className="chapter-production-compatibility" aria-labelledby="chapter-production-compatibility-title">
          <p className="section-kicker">UNIFIED CHAPTER FLOW</p>
          <h3 id="chapter-production-compatibility-title">单章 AI 入口已合并</h3>
          <p>原“AI 共创”、“一键单章链”和“示范候选稿”已并入同一个工作台，统一使用费用确认、候选隔离和版本门禁。</p>
          <button type="button" onClick={onOpenChapterProduction}>前往单章生产工作台</button>
        </section>
      ) : null}
      <BookDirectorPanel
        project={project}
        workspace={workspace}
        chapter={chapter}
        canUseChapter={canGenerate && canUpdateChapter}
        onWorkspaceChanged={onWorkspaceChanged}
        onAdoptBrief={adoptAiProposal}
        onDraftGenerated={showDraftCandidate}
        onOpenChapterProduction={onOpenChapterProduction}
      />
      <ReviewWorkbench
        key={`${chapter.id}:${chapter.revision}`}
        chapter={chapter}
        canReview={canUpdateChapter && wordCount > 0}
        onChapterUpdated={onChapterUpdated}
      />
      <AiCoauthorPanel
        chapter={chapter}
        canUseAi={canGenerate && canUpdateChapter}
        canGenerateDraft={canGenerate && canUpdateChapter && savedBriefComplete && !briefDirty}
        onAdoptProposal={adoptAiProposal}
        onDraftGenerated={showDraftCandidate}
        onOpenChapterProduction={onOpenChapterProduction}
      />
      {!onOpenChapterProduction ? <section className="chapter-brief">
        <div className="brief-fields">
          <label>
            章节标题
            <input
              value={brief.title}
              onChange={(event) => updateBrief('title', event.target.value)}
              maxLength={120}
              readOnly={isApproved}
            />
          </label>
          <label>
            读者承诺
            <textarea
              value={brief.reader_promise}
              onChange={(event) => updateBrief('reader_promise', event.target.value)}
              maxLength={300}
              rows={2}
              readOnly={isApproved}
              placeholder="这一章承诺让读者得到什么？"
            />
          </label>
          <label>
            开篇钩子
            <textarea
              value={brief.opening_hook}
              onChange={(event) => updateBrief('opening_hook', event.target.value)}
              maxLength={300}
              rows={2}
              readOnly={isApproved}
              placeholder="读者为什么必须继续看？"
            />
          </label>
          <label>
            状态变化
            <textarea
              value={brief.state_change}
              onChange={(event) => updateBrief('state_change', event.target.value)}
              maxLength={300}
              rows={2}
              readOnly={isApproved}
              placeholder="人物、资源或关系发生什么变化？"
            />
          </label>
          <label>
            情绪回报
            <textarea
              value={brief.emotional_payoff}
              onChange={(event) => updateBrief('emotional_payoff', event.target.value)}
              maxLength={300}
              rows={2}
              readOnly={isApproved}
              placeholder="本章兑现爽感、情感或信息差了吗？"
            />
          </label>
          <label>
            章尾悬念
            <textarea
              value={brief.ending_cliffhanger}
              onChange={(event) => updateBrief('ending_cliffhanger', event.target.value)}
              maxLength={300}
              rows={2}
              readOnly={isApproved}
              placeholder="最后一屏留下什么未决问题？"
            />
          </label>
        </div>
        <button
          type="button"
          className="brief-save-action"
          onClick={saveBrief}
          disabled={!briefDirty || !canUpdateChapter || isSavingBrief || isApproved}
        >
          {isSavingBrief ? '正在保存章纲…' : briefDirty ? '保存章纲' : '章纲已保存'}
        </button>
        {!canUpdateChapter ? <p className="brief-hint">正文保存完成后才能更新章纲。</p> : null}
        {isApproved ? <p className="brief-hint">定稿章节已锁定，重新打开后才能修改。</p> : null}
        <button
          type="button"
          className="secondary-action"
          onClick={() => setContextReady(true)}
          disabled={contextReady || briefDirty || !briefComplete || !canGenerate}
        >
          {contextReady
            ? '上下文已准备'
            : !canGenerate
              ? '当前状态不允许生成'
              : briefComplete && !briefDirty
                ? '准备章节上下文'
                : '先完成并保存章纲'}
        </button>
      </section> : null}

      {contextReady && !onOpenChapterProduction ? (
        <section className="context-preview" aria-labelledby="context-title">
          <div className="pulse-heading">
            <h3 id="context-title">本次使用的上下文</h3>
            <span>本地预览</span>
          </div>
          <ul>
            <li><span>{anchorLabels.anchor}</span><strong>{project.rebirth_year} · {project.rebirth_location}</strong></li>
            <li><span>当前正文</span><strong>{wordCount} 字 · revision {chapter.revision}</strong></li>
            <li><span>章节目标</span><strong>{chapter.state_change || '尚未设置'}</strong></li>
            <li><span>运行模型</span><strong>内置假模型 · ¥0</strong></li>
          </ul>
          <button className="generate-action" type="button" onClick={generateCandidate} disabled={isRunning || !canGenerate}>
            {isRunning && !run ? '正在生成检查点…' : '生成示范候选稿'}
          </button>
        </section>
      ) : null}

      {run?.candidate_content && !onOpenChapterProduction ? (
        <section className="candidate-card" aria-labelledby="candidate-title">
          <div className="pulse-heading">
            <h3 id="candidate-title">候选正文</h3>
            <span>{run.state === 'applied' ? '已采用' : candidateIsStale ? '旧版本' : `${run.provider} · ${run.model}`}</span>
          </div>
          <p>{run.candidate_content}</p>
          {candidateIsStale ? (
            <div id="candidate-stale-explanation" className="agent-error" role="alert">
              <strong>候选基于旧版本</strong>
              <p>生成后正文已被修改或定稿，这份候选不能再覆盖当前稿件。</p>
              <div className="state-actions">
                <button type="button" onClick={generateCandidate} disabled={isRunning || !canGenerate}>
                  {isRunning ? '正在重新生成…' : '基于当前正文重新生成'}
                </button>
                <button type="button" onClick={closeCandidate} disabled={isRunning}>关闭此候选</button>
              </div>
            </div>
          ) : null}
          <button
            className="primary-action"
            type="button"
            onClick={applyCandidate}
            disabled={isRunning || run.state === 'applied' || candidateIsStale}
            aria-describedby={candidateIsStale ? 'candidate-stale-explanation' : undefined}
          >
            {run.state === 'applied' ? '已写入草稿' : '采用并写入编辑器'}
          </button>
        </section>
      ) : null}

      {error ? <p className="agent-error" role="alert">{error}</p> : null}

      <section className="chapter-state-card" aria-labelledby="chapter-state-title">
        <div className="pulse-heading">
          <h3 id="chapter-state-title">章节状态</h3>
          <span>{statusLabels[chapter.status]}</span>
        </div>
        <p>
          {chapter.status === 'planned' ? '正文保存后可进入草稿。' : null}
          {chapter.status === 'drafted' ? '章纲完整后可提交审校。' : null}
          {chapter.status === 'reviewing' ? '确认本章可发布后批准定稿。' : null}
          {chapter.status === 'approved' ? '定稿正文和章纲已锁定。' : null}
        </p>
        <div className="state-actions">
          {chapter.status === 'reviewing' ? (
            <button
              type="button"
              onClick={() => transitionChapter('drafted')}
              disabled={!canUpdateChapter || isTransitioning}
            >
              退回修改
            </button>
          ) : null}
          <button
            type="button"
            className="state-primary"
            onClick={() => transitionChapter(primaryTransition.target)}
            disabled={transitionDisabled}
          >
            {isTransitioning ? '正在更新…' : primaryTransition.label}
          </button>
        </div>
      </section>

      <RhythmWindowPanel chapters={workspace.chapters} activeChapterId={chapter.id} />

      <SerialControlPanel workspace={workspace} />

      <StoryLedgerPanel
        workspace={workspace}
        chapter={chapter}
        onWorkspaceChanged={onWorkspaceChanged}
      />


      <FactTimelinePanel
        workspace={workspace}
        chapter={chapter}
        onWorkspaceChanged={onWorkspaceChanged}
      />

      <FutureKnowledgePanel
        workspace={workspace}
        onWorkspaceChanged={onWorkspaceChanged}
      />

      <SourceLibraryPanel
        workspace={workspace}
        onWorkspaceChanged={onWorkspaceChanged}
      />

      <section className="pulse-card" aria-labelledby="pulse-title">
        <div className="pulse-heading">
          <h3 id="pulse-title">章节脉搏</h3>
          <span>{briefComplete && !briefDirty ? '已规划' : '未规划'}</span>
        </div>
        <div className="pulse-line" aria-hidden="true">
          <i data-kind="hook" /><i data-kind="build" /><i data-kind="payoff" /><i data-kind="cliff" />
        </div>
        <div className="pulse-labels" aria-hidden="true">
          <span>钩子</span><span>推进</span><span>兑现</span><span>悬念</span>
        </div>
      </section>
      <section className="context-note">
        <strong>所有 AI 结果都先作为候选</strong>
        <p>真实模型与离线示范共用同一道 revision 门禁，只有点击“采用”后才会写入正文。</p>
      </section>
    </aside>
  )
}
