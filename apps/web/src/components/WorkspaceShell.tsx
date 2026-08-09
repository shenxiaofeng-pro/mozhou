import type {
  Chapter,
  ChapterStatus,
  ChapterSummary,
  Workspace,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { useDeferredValue, useEffect, useRef, useState } from 'react'

import { api } from '../api'
import { useChapterAutosave, type SaveStatus } from '../hooks/useChapterAutosave'
import { DirectorPanel } from './DirectorPanel'

interface WorkspaceShellProps {
  workspace: WorkspaceSummary
  initialChapter: Chapter
  onChapterChanged: (chapter: Chapter) => void
  onWorkspaceChanged: (workspace: Workspace | WorkspaceSummary) => void
  onOpenReferenceLibrary: () => void
  onOpenTaskCenter: () => void
  onClose: () => void
}

interface ActiveChapterWorkspaceProps extends WorkspaceShellProps {
  chapter: Chapter
  futureChapters: ChapterSummary[]
  isCreatingChapter: boolean
  createChapterError: string | null
  chapterLoadError: string | null
  onSelectChapter: (chapterId: string) => Promise<void>
  onCreateChapter: () => void
}

const saveLabels: Record<SaveStatus, string> = {
  saved: '已保存',
  dirty: '等待保存',
  saving: '正在保存',
  error: '保存受阻',
}

const chapterStatusLabels: Record<ChapterStatus, string> = {
  planned: '待写',
  drafted: '草稿',
  reviewing: '审校中',
  approved: '已定稿',
}

const genreLabels = {
  historical_rebirth: '历史重生',
  urban_rebirth: '都市重生',
} as const

const CHAPTER_PREFIX = /^第(?:一|\d+)章\s*/

export function WorkspaceShell({
  workspace,
  initialChapter,
  onChapterChanged,
  onWorkspaceChanged,
  onOpenReferenceLibrary,
  onOpenTaskCenter,
  onClose,
}: WorkspaceShellProps) {
  const [activeChapter, setActiveChapter] = useState(initialChapter)
  const [isCreatingChapter, setIsCreatingChapter] = useState(false)
  const [createChapterError, setCreateChapterError] = useState<string | null>(null)
  const [chapterLoadError, setChapterLoadError] = useState<string | null>(null)
  const activeChapterSummary = workspace.chapters.find((item) => item.id === activeChapter.id)
  const futureChapters = workspace.chapters
    .filter((item) => item.chapter_number > activeChapter.chapter_number)
    .slice(0, 3)

  useEffect(() => {
    if (!activeChapterSummary || activeChapterSummary.revision <= activeChapter.revision) return
    let active = true
    api.getChapter(activeChapter.id).then((updated) => {
      if (active) setActiveChapter(updated)
    }).catch((caught: unknown) => {
      if (active) {
        setChapterLoadError(caught instanceof Error ? caught.message : '章节更新同步失败')
      }
    })
    return () => {
      active = false
    }
  }, [activeChapter.id, activeChapter.revision, activeChapterSummary])

  async function selectChapter(chapterId: string) {
    if (chapterId === activeChapter.id) return
    setChapterLoadError(null)
    try {
      setActiveChapter(await api.getChapter(chapterId))
    } catch (caught) {
      setChapterLoadError(caught instanceof Error ? caught.message : '章节正文读取失败')
    }
  }

  function handleChapterChanged(chapter: Chapter) {
    if (chapter.id === activeChapter.id) setActiveChapter(chapter)
    onChapterChanged(chapter)
  }

  async function createNextChapter() {
    setIsCreatingChapter(true)
    setCreateChapterError(null)
    try {
      const lastChapterNumber = Math.max(...workspace.chapters.map((item) => item.chapter_number))
      onChapterChanged(await api.createChapter(workspace.project.id, {
        expected_last_chapter_number: lastChapterNumber,
      }))
    } catch (caught) {
      setCreateChapterError(caught instanceof Error ? caught.message : '无法添加下一章')
    } finally {
      setIsCreatingChapter(false)
    }
  }

  return (
    <ActiveChapterWorkspace
      key={activeChapter.id}
      workspace={workspace}
      initialChapter={initialChapter}
      chapter={activeChapter}
      futureChapters={futureChapters}
      isCreatingChapter={isCreatingChapter}
      createChapterError={createChapterError}
      chapterLoadError={chapterLoadError}
      onChapterChanged={handleChapterChanged}
      onWorkspaceChanged={onWorkspaceChanged}
      onOpenReferenceLibrary={onOpenReferenceLibrary}
      onOpenTaskCenter={onOpenTaskCenter}
      onSelectChapter={selectChapter}
      onCreateChapter={createNextChapter}
      onClose={onClose}
    />
  )
}

function ActiveChapterWorkspace({
  workspace,
  chapter,
  futureChapters,
  isCreatingChapter,
  createChapterError,
  chapterLoadError,
  onChapterChanged,
  onWorkspaceChanged,
  onOpenReferenceLibrary,
  onOpenTaskCenter,
  onSelectChapter,
  onCreateChapter,
  onClose,
}: ActiveChapterWorkspaceProps) {
  const { draft, saveStatus, saveError, setDraft, flushNow, retry, adoptServerVersion } = useChapterAutosave(
    chapter,
    onChapterChanged,
  )
  const [isNavigating, setIsNavigating] = useState(false)
  const [isDirectorOpen, setIsDirectorOpen] = useState(false)
  const directorTriggerRef = useRef<HTMLButtonElement>(null)
  const directorCloseRef = useRef<HTMLButtonElement>(null)
  const deferredDraft = useDeferredValue(draft)
  const wordCount = deferredDraft.replace(/\s/g, '').length
  const progress = Math.min(100, Math.round((wordCount / workspace.project.chapter_target_words) * 100))
  const isApproved = chapter.status === 'approved'

  useEffect(() => {
    if (saveStatus === 'saved') return
    function warnBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault()
      event.returnValue = true
    }
    window.addEventListener('beforeunload', warnBeforeUnload)
    return () => window.removeEventListener('beforeunload', warnBeforeUnload)
  }, [saveStatus])

  useEffect(() => {
    if (!isDirectorOpen) return
    directorCloseRef.current?.focus()

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key !== 'Escape') return
      setIsDirectorOpen(false)
      directorTriggerRef.current?.focus()
    }

    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [isDirectorOpen])

  function closeDirector() {
    setIsDirectorOpen(false)
    directorTriggerRef.current?.focus()
  }

  async function navigateAfterSave(action: () => void | Promise<void>) {
    if (isNavigating) return
    setIsNavigating(true)
    try {
      const saved = await flushNow()
      if (saved) await action()
    } finally {
      setIsNavigating(false)
    }
  }

  function handleChapterUpdated(updated: Chapter) {
    adoptServerVersion(updated)
    onChapterChanged(updated)
  }

  return (
    <main className="workspace-shell">
      <header className="workspace-header">
        <div className="compact-brand">
          <span aria-hidden="true">墨</span>
          <strong>墨舟</strong>
        </div>
        <div className="project-heading">
          <p>{genreLabels[workspace.project.genre]} · {workspace.project.rebirth_year}</p>
          <h1>{workspace.project.title}</h1>
        </div>
        <div className="header-metrics" aria-label="连载状态">
          <span><small>本章</small>{wordCount.toLocaleString()} / {workspace.project.chapter_target_words.toLocaleString()}</span>
          <span><small>当前状态</small>{chapterStatusLabels[chapter.status]}</span>
          <button
            className="library-action task-action"
            type="button"
            aria-label="打开任务中心"
            disabled={isNavigating}
            onClick={() => { void navigateAfterSave(onOpenTaskCenter) }}
          >任务中心</button>
          <button
            className="library-action"
            type="button"
            aria-label="打开拆书库"
            disabled={isNavigating}
            onClick={() => { void navigateAfterSave(onOpenReferenceLibrary) }}
          >
            {isNavigating ? '正在保存…' : '打开拆书库'}
          </button>
          <button
            className="quiet-action"
            type="button"
            disabled={isNavigating}
            onClick={() => { void navigateAfterSave(onClose) }}
          >退出作品</button>
        </div>
      </header>

      <aside className="story-tree" aria-label="作品目录">
        <section className="project-card">
          <p className="section-kicker">重生锚点</p>
          <strong>{workspace.project.rebirth_year} · {workspace.project.rebirth_location}</strong>
          <span>
            {workspace.timeline_events.filter((event) => event.layer === 'original').length > 0
              ? `已有 ${workspace.timeline_events.filter((event) => event.layer === 'original').length} 条原始事件`
              : '原始时间线尚未建立'}
          </span>
        </section>
        <nav aria-label="章节目录">
          <div className="tree-section-title">
            <span>第一卷</span>
            <button type="button" aria-label="添加下一章" onClick={onCreateChapter} disabled={isCreatingChapter}>＋</button>
          </div>
          {workspace.chapters.map((item) => (
            <button
              className="chapter-item"
              data-active={item.id === chapter.id}
              type="button"
              key={item.id}
              aria-label={`打开第 ${item.chapter_number} 章：${item.title}`}
              disabled={isNavigating}
              onClick={() => { void navigateAfterSave(() => onSelectChapter(item.id)) }}
            >
              <span>{String(item.chapter_number).padStart(2, '0')}</span>
              <strong>{item.title.replace(CHAPTER_PREFIX, '')}</strong>
              <small>{chapterStatusLabels[item.status]}</small>
            </button>
          ))}
        </nav>
        <section className="rolling-plan" aria-labelledby="rolling-plan-title">
          <div>
            <span id="rolling-plan-title">未来三章</span>
            <strong>{futureChapters.length} / 3</strong>
          </div>
          {futureChapters.length > 0 ? (
            <ol>
              {futureChapters.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    disabled={isNavigating}
                    onClick={() => { void navigateAfterSave(() => onSelectChapter(item.id)) }}
                  >
                    <span>第 {item.chapter_number} 章</span>
                    <strong>{item.state_change || '等待设置状态变化'}</strong>
                  </button>
                </li>
              ))}
            </ol>
          ) : <p>先为当前章节补一条后续路线。</p>}
          <button type="button" className="rolling-add" onClick={onCreateChapter} disabled={isCreatingChapter}>
            {isCreatingChapter ? '正在添加…' : futureChapters.length >= 3 ? '继续添加远期章' : '添加下一章'}
          </button>
          {createChapterError ? <p className="tree-error" role="alert">{createChapterError}</p> : null}
        </section>
      </aside>

      <section className="editor-panel" aria-labelledby="chapter-title">
        <header className="editor-heading">
          <div>
            <p>第一卷 · 第 {chapter.chapter_number} 章</p>
            <h2 id="chapter-title">{chapter.title}</h2>
          </div>
          <span className="save-state" data-status={saveStatus} role="status">
            <i aria-hidden="true" />{isApproved ? '定稿锁定' : saveLabels[saveStatus]}
          </span>
        </header>
        <textarea
          className="manuscript"
          aria-label="章节正文"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          readOnly={isApproved}
          spellCheck
          placeholder="从人物此刻最想得到、也最怕失去的东西写起……"
        />
        <footer className="editor-footer">
          <div className="writing-progress" aria-label={`本章完成 ${progress}%`}>
            <span style={{ width: `${progress}%` }} />
          </div>
          <p>{wordCount.toLocaleString()} 字 · 目标完成 {progress}%</p>
          {saveError ? (
            <p className="save-error" role="alert">
              {saveError} <button type="button" onClick={retry}>重试</button>
            </p>
          ) : null}
          {chapterLoadError ? <p className="save-error" role="alert">{chapterLoadError}</p> : null}
        </footer>
      </section>

      <button
        ref={directorTriggerRef}
        className="director-drawer-trigger"
        type="button"
        aria-label="打开 AI 导演"
        aria-controls="ai-director-surface"
        aria-expanded={isDirectorOpen}
        onClick={() => setIsDirectorOpen(true)}
      >
        <span aria-hidden="true">AI</span>
        <strong aria-hidden="true">导演</strong>
      </button>
      <button
        className="director-drawer-backdrop"
        type="button"
        tabIndex={-1}
        aria-label="关闭 AI 导演背景"
        data-open={isDirectorOpen}
        onClick={closeDirector}
      />
      <section
        id="ai-director-surface"
        className="director-surface"
        role="region"
        aria-label="AI 导演"
        data-open={isDirectorOpen}
      >
        <div className="director-drawer-bar">
          <div>
            <span>AI 共创</span>
            <strong>本章导演</strong>
          </div>
          <button
            ref={directorCloseRef}
            type="button"
            aria-label="关闭 AI 导演"
            onClick={closeDirector}
          >×</button>
        </div>
        <DirectorPanel
          key={`${chapter.id}:${chapter.title}:${chapter.reader_promise ?? ''}:${chapter.opening_hook ?? ''}:${chapter.state_change ?? ''}:${chapter.emotional_payoff ?? ''}:${chapter.ending_cliffhanger ?? ''}`}
          project={workspace.project}
          workspace={workspace}
          chapter={chapter}
          wordCount={wordCount}
          canUpdateChapter={saveStatus === 'saved'}
          onChapterUpdated={handleChapterUpdated}
          onWorkspaceChanged={onWorkspaceChanged}
        />
      </section>
    </main>
  )
}
