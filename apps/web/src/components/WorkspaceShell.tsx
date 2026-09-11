import type {
  Chapter,
  ChapterStatus,
  ChapterSummary,
  Workspace,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { useDeferredValue, useEffect, useRef, useState } from 'react'

import { api } from '../api'
import { genreLabels, getStoryAnchorLabels, isRebirthGenre } from '../genre'
import { useChapterAutosave, type SaveStatus } from '../hooks/useChapterAutosave'
import { AuthorToolsDialog } from './AuthorToolsDialog'
import { DirectorPanel } from './DirectorPanel'
import { ManuscriptDirectoryDialog } from './ManuscriptDirectoryDialog'
import { SerialWorkspaceDialog } from './SerialWorkspaceDialog'

interface WorkspaceShellProps {
  workspace: WorkspaceSummary
  initialChapter: Chapter
  onChapterChanged: (chapter: Chapter) => void
  onWorkspaceChanged: (workspace: Workspace | WorkspaceSummary) => void
  onOpenReferenceLibrary: () => void
  onOpenTopicDecision?: () => void
  onOpenResearch?: () => void
  onOpenComicDrama?: () => void
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

const CHAPTER_PREFIX = /^第[零〇一二三四五六七八九十百千万两\d]+章\s*/

export function WorkspaceShell({
  workspace,
  initialChapter,
  onChapterChanged,
  onWorkspaceChanged,
  onOpenReferenceLibrary,
  onOpenTopicDecision = () => undefined,
  onOpenResearch = () => undefined,
  onOpenComicDrama = () => undefined,
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
      onOpenTopicDecision={onOpenTopicDecision}
      onOpenResearch={onOpenResearch}
      onOpenComicDrama={onOpenComicDrama}
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
  onOpenTopicDecision = () => undefined,
  onOpenResearch = () => undefined,
  onOpenComicDrama = () => undefined,
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
  const [isDirectoryOpen, setIsDirectoryOpen] = useState(false)
  const [serialDialogMode, setSerialDialogMode] = useState<'dashboard' | 'search' | null>(null)
  const [isFocusMode, setIsFocusMode] = useState(false)
  const [authorTools, setAuthorTools] = useState<{ tab: 'calendar' | 'annotations' | 'ideas' | 'graphs'; selection: { start: number; end: number } | null } | null>(null)
  const manuscriptRef = useRef<HTMLTextAreaElement>(null)
  const directorTriggerRef = useRef<HTMLButtonElement>(null)
  const directorCloseRef = useRef<HTMLButtonElement>(null)
  const authorToolsTriggerRef = useRef<HTMLButtonElement>(null)
  const deferredDraft = useDeferredValue(draft)
  const wordCount = deferredDraft.replace(/\s/g, '').length
  const progress = Math.min(100, Math.round((wordCount / workspace.project.chapter_target_words) * 100))
  const anchorLabels = getStoryAnchorLabels(workspace.project.genre)
  const rebirthStory = isRebirthGenre(workspace.project.genre)
  const isApproved = chapter.status === 'approved'
  const treeVolumes = (workspace.manuscript_volumes?.length ?? 0) > 0
    ? workspace.manuscript_volumes!.map((volume) => ({
      id: volume.id,
      title: volume.title,
      volumeNumber: volume.volume_number,
      stable: true,
    }))
    : Array.from(new Set(workspace.chapters.map((item) => item.volume_number))).map((volumeNumber) => ({
      id: `legacy-volume-${volumeNumber}`,
      title: `第 ${volumeNumber} 卷`,
      volumeNumber,
      stable: false,
    }))

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

  async function navigateAfterSave(action: () => void | Promise<void>): Promise<boolean> {
    if (isNavigating) return false
    setIsNavigating(true)
    try {
      const saved = await flushNow()
      if (!saved) return false
      await action()
      return true
    } finally {
      setIsNavigating(false)
    }
  }

  async function commitDirectory(action: () => Promise<WorkspaceSummary>) {
    const completed = await navigateAfterSave(async () => {
      onWorkspaceChanged(await action())
    })
    if (!completed) throw new Error('正文尚未保存，目录操作未执行')
  }

  async function openSerialChapter(chapterId: string) {
    const completed = await navigateAfterSave(() => onSelectChapter(chapterId))
    if (!completed) throw new Error('正文尚未保存，未切换章节')
  }

  useEffect(() => {
    function handleWorkspaceShortcut(event: KeyboardEvent) {
      const command = event.metaKey || event.ctrlKey
      if (command && event.key.toLowerCase() === 's') {
        event.preventDefault()
        void flushNow()
        return
      }
      if (command && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        void flushNow().then((saved) => {
          if (saved) setSerialDialogMode('search')
        })
        return
      }
      if (command && event.shiftKey && event.key.toLowerCase() === 'f') {
        event.preventDefault()
        setIsFocusMode((current) => !current)
        return
      }
      if (command && event.shiftKey && event.key.toLowerCase() === 'i') {
        event.preventDefault()
        void navigateAfterSave(() => setAuthorTools({ tab: 'ideas', selection: null }))
        return
      }
      if (!event.altKey || !['ArrowUp', 'ArrowDown'].includes(event.key)) return
      if (isDirectorOpen || isDirectoryOpen || serialDialogMode) return
      const index = workspace.chapters.findIndex((item) => item.id === chapter.id)
      const nextIndex = index + (event.key === 'ArrowUp' ? -1 : 1)
      const next = workspace.chapters[nextIndex]
      if (!next) return
      event.preventDefault()
      void navigateAfterSave(() => onSelectChapter(next.id))
    }
    window.addEventListener('keydown', handleWorkspaceShortcut)
    return () => window.removeEventListener('keydown', handleWorkspaceShortcut)
  })

  function handleChapterUpdated(updated: Chapter) {
    adoptServerVersion(updated)
    onChapterChanged(updated)
  }

  function closeAuthorTools() {
    setAuthorTools(null)
    authorToolsTriggerRef.current?.focus()
  }

  return (
    <main className="workspace-shell" data-focus-mode={isFocusMode}>
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
            className="library-action serial-action"
            type="button"
            aria-label="打开连载工作台"
            disabled={isNavigating}
            onClick={() => { void navigateAfterSave(() => setSerialDialogMode('dashboard')) }}
          >连载台</button>
          <button ref={authorToolsTriggerRef} className="library-action" type="button" aria-label="打开作者工具台" disabled={isNavigating} onClick={() => { void navigateAfterSave(() => setAuthorTools({ tab: 'calendar', selection: null })) }}>作者工具</button>
          <button
            className="library-action"
            type="button"
            aria-label="打开资料研究台"
            disabled={isNavigating}
            onClick={() => { void navigateAfterSave(onOpenResearch) }}
          >资料研究</button>
          <button
            className="library-action task-action"
            type="button"
            aria-label="打开任务中心"
            disabled={isNavigating}
            onClick={() => { void navigateAfterSave(onOpenTaskCenter) }}
          >任务中心</button>
          <button
            className="library-action comic-action"
            type="button"
            aria-label="打开 AI 漫剧改编"
            disabled={isNavigating}
            onClick={() => { void navigateAfterSave(onOpenComicDrama) }}
          >AI 漫剧</button>
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
          <p className="section-kicker">{anchorLabels.anchor}</p>
          <strong>{workspace.project.rebirth_year} · {workspace.project.rebirth_location}</strong>
          <span>
            {workspace.timeline_events.filter((event) => event.layer === 'original').length > 0
              ? `已有 ${workspace.timeline_events.filter((event) => event.layer === 'original').length} 条${rebirthStory ? '原始' : '世界底稿'}事件`
              : `${rebirthStory ? '原始时间线' : '世界底稿'}尚未建立`}
          </span>
          {workspace.topic_decision ? (
            <button
              className="topic-decision-entry"
              type="button"
              disabled={isNavigating}
              onClick={() => { void navigateAfterSave(onOpenTopicDecision) }}
            >
              <strong>{workspace.topic_decision.status === 'confirmed' ? '查看选题单' : '补充并确认选题'}</strong>
              <small>{workspace.topic_decision.status === 'pending_reconfirmation' ? '内容已改，等待复核' : '不会打断当前正文'}</small>
            </button>
          ) : null}
        </section>
        <nav aria-label="章节目录">
          <div className="tree-section-title">
            <span>作品目录</span>
            <div>
              <button type="button" aria-label="管理卷章场景" disabled={isNavigating} onClick={() => { void navigateAfterSave(() => setIsDirectoryOpen(true)) }}>管理</button>
              <button type="button" aria-label="添加下一章" onClick={onCreateChapter} disabled={isCreatingChapter}>＋</button>
            </div>
          </div>
          {treeVolumes.map((volume) => (
            <section className="story-tree-volume" key={volume.id} aria-label={volume.title}>
              <h3>{volume.title}</h3>
              {workspace.chapters.filter((item) => volume.stable
                ? item.volume_id === volume.id
                : item.volume_number === volume.volumeNumber).map((item) => (
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
            </section>
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
            <p>{(workspace.manuscript_volumes ?? []).find((volume) => volume.id === chapter.volume_id)?.title ?? `第 ${chapter.volume_number} 卷`} · 第 {chapter.chapter_number} 章</p>
            <h2 id="chapter-title">{chapter.title}</h2>
          </div>
          <span className="save-state" data-status={saveStatus} role="status">
            <i aria-hidden="true" />{isApproved ? '定稿锁定' : saveLabels[saveStatus]}
          </span>
        </header>
        <textarea
          ref={manuscriptRef}
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
          <button type="button" disabled={isNavigating || isApproved} onClick={() => {
            const target = manuscriptRef.current
            const selection = target && target.selectionEnd > target.selectionStart ? { start: target.selectionStart, end: target.selectionEnd } : null
            void navigateAfterSave(() => setAuthorTools({ tab: 'annotations', selection }))
          }}>批注选中文字</button>
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
      {isDirectoryOpen ? (
        <ManuscriptDirectoryDialog
          workspace={workspace}
          activeChapterId={chapter.id}
          onClose={() => setIsDirectoryOpen(false)}
          onCommit={commitDirectory}
        />
      ) : null}
      {serialDialogMode ? (
        <SerialWorkspaceDialog
          projectId={workspace.project.id}
          initialMode={serialDialogMode}
          onClose={() => setSerialDialogMode(null)}
          onOpenChapter={openSerialChapter}
        />
      ) : null}
      {authorTools ? <AuthorToolsDialog project={workspace.project} chapter={chapter} initialTab={authorTools.tab} selection={authorTools.selection} onClose={closeAuthorTools} onAdjustGoal={() => { setAuthorTools(null); setSerialDialogMode('dashboard') }} /> : null}
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
