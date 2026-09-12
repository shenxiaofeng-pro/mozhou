import type {
  AuthorWorkflowStage,
  Chapter,
  ChapterStatus,
  ChapterSummary,
  Workspace,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { lazy, Suspense, useCallback, useDeferredValue, useEffect, useRef, useState } from 'react'

import { api } from '../api'
import { presentAuthorAction, type AuthorActionOperation } from '../authorWorkflow'
import { genreLabels, getStoryAnchorLabels, isRebirthGenre } from '../genre'
import { useChapterAutosave, type SaveStatus } from '../hooks/useChapterAutosave'
import { AuthorUtilityDrawer } from './AuthorUtilityDrawer'
import { AuthorWorkflowRail } from './AuthorWorkflowRail'
import { DirectorPanel } from './DirectorPanel'

const AuthorToolsDialog = lazy(async () => {
  const module = await import('./AuthorToolsDialog')
  return { default: module.AuthorToolsDialog }
})

const ChapterProductionDialog = lazy(async () => {
  const module = await import('./ChapterProductionDialog')
  return { default: module.ChapterProductionDialog }
})

const ManuscriptDirectoryDialog = lazy(async () => {
  const module = await import('./ManuscriptDirectoryDialog')
  return { default: module.ManuscriptDirectoryDialog }
})

const SerialWorkspaceDialog = lazy(async () => {
  const module = await import('./SerialWorkspaceDialog')
  return { default: module.SerialWorkspaceDialog }
})

interface WorkspaceShellProps {
  workspace: WorkspaceSummary
  initialChapter: Chapter
  activeStage: AuthorWorkflowStage
  requestedChapterId?: string | null
  onChapterChanged: (chapter: Chapter) => void
  onWorkspaceChanged: (workspace: Workspace | WorkspaceSummary) => void
  onRefreshAuthorRoute: () => Promise<void>
  onNavigationGuardChanged: (guard: (() => Promise<boolean>) | null) => void
  onStageChanged: (stage: AuthorWorkflowStage) => void
  onActiveChapterChanged: (chapterId: string) => void
  onRequestedChapterLoadFailed: (previousChapterId: string) => void
  onOpenReferenceLibrary: () => void
  onOpenWritingPatterns?: () => void
  onOpenTopicDecision?: () => void
  onOpenResearch?: () => void
  onOpenComicDrama?: () => void
  onOpenTaskCenter: () => void
  chapterProductionRequest?: { chapterId: string | null; requestId: number } | null
  onChapterProductionRequestHandled?: () => void
  onClose: () => void
}

interface ActiveChapterWorkspaceProps extends Omit<WorkspaceShellProps, 'onRequestedChapterLoadFailed'> {
  chapter: Chapter
  futureChapters: ChapterSummary[]
  isCreatingChapter: boolean
  nextActionRefreshRequired: boolean
  createChapterError: string | null
  chapterLoadError: string | null
  onSelectChapter: (chapterId: string) => Promise<boolean>
  onCreateChapter: () => void
  onCreateAndOpenChapter: () => void
  onRefreshNextAction: () => void
  queuedAuthorOperation: AuthorActionOperation | null
  onQueueAuthorOperation: (operation: AuthorActionOperation) => void
  onQueuedAuthorOperationHandled: () => void
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
type ProductionFocusTarget = 'outline' | 'candidate'
const DIRECTOR_FOCUSABLE = [
  'button:not([disabled])',
  '[href]',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function directorAnchorId(stage: AuthorWorkflowStage): string {
  if (stage === 'feedback') return 'director-stage-feedback'
  if (stage === 'review' || stage === 'complete') return 'director-stage-review'
  return 'director-stage-book'
}

export function WorkspaceShell({
  workspace,
  initialChapter,
  activeStage,
  requestedChapterId = null,
  onChapterChanged,
  onWorkspaceChanged,
  onRefreshAuthorRoute,
  onNavigationGuardChanged,
  onStageChanged,
  onActiveChapterChanged,
  onRequestedChapterLoadFailed,
  onOpenReferenceLibrary,
  onOpenWritingPatterns = () => undefined,
  onOpenTopicDecision = () => undefined,
  onOpenResearch = () => undefined,
  onOpenComicDrama = () => undefined,
  onOpenTaskCenter,
  chapterProductionRequest = null,
  onChapterProductionRequestHandled = () => undefined,
  onClose,
}: WorkspaceShellProps) {
  const [activeChapter, setActiveChapter] = useState(initialChapter)
  const [isCreatingChapter, setIsCreatingChapter] = useState(false)
  const [nextActionRefreshRequired, setNextActionRefreshRequired] = useState(false)
  const [createChapterError, setCreateChapterError] = useState<string | null>(null)
  const [chapterLoadError, setChapterLoadError] = useState<string | null>(null)
  const [queuedAuthorOperation, setQueuedAuthorOperation] = useState<AuthorActionOperation | null>(null)
  const creatingChapterRef = useRef(false)
  const chapterLoadRequestRef = useRef(0)
  const activeChapterSummary = workspace.chapters.find((item) => item.id === activeChapter.id)
  const futureChapters = workspace.chapters
    .filter((item) => item.chapter_number > activeChapter.chapter_number)
    .slice(0, 3)

  const selectChapter = useCallback(async (
    chapterId: string,
    updateRoute = true,
    onCurrentFailure?: () => void,
  ): Promise<boolean> => {
    const requestVersion = ++chapterLoadRequestRef.current
    if (chapterId === activeChapter.id) return true
    setChapterLoadError(null)
    try {
      const loaded = await api.getChapter(chapterId)
      if (requestVersion !== chapterLoadRequestRef.current) return false
      setActiveChapter(loaded)
      if (updateRoute) onActiveChapterChanged(chapterId)
      return true
    } catch (caught) {
      if (requestVersion !== chapterLoadRequestRef.current) return false
      setChapterLoadError(caught instanceof Error ? caught.message : '章节正文读取失败')
      onCurrentFailure?.()
      return false
    }
  }, [activeChapter.id, onActiveChapterChanged])

  useEffect(() => {
    chapterLoadRequestRef.current += 1
  }, [requestedChapterId])

  useEffect(() => {
    if (!requestedChapterId || requestedChapterId === activeChapter.id) return
    if (!workspace.chapters.some((chapter) => chapter.id === requestedChapterId)) {
      onRequestedChapterLoadFailed(activeChapter.id)
      return
    }
    const previousChapterId = activeChapter.id
    const timer = window.setTimeout(() => {
      void selectChapter(requestedChapterId, false, () => {
        onRequestedChapterLoadFailed(previousChapterId)
      })
    }, 0)
    return () => window.clearTimeout(timer)
  }, [
    activeChapter.id,
    onRequestedChapterLoadFailed,
    requestedChapterId,
    selectChapter,
    workspace.chapters,
  ])

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

  useEffect(() => {
    const chapterId = chapterProductionRequest?.chapterId
    if (!chapterId || chapterId === activeChapter.id) return
    const timer = window.setTimeout(() => {
      void selectChapter(chapterId).then((selected) => {
        if (!selected) onChapterProductionRequestHandled()
      })
    }, 0)
    return () => window.clearTimeout(timer)
  }, [activeChapter.id, chapterProductionRequest, onChapterProductionRequestHandled, selectChapter])

  function handleChapterChanged(chapter: Chapter) {
    if (chapter.id === activeChapter.id) setActiveChapter(chapter)
    onChapterChanged(chapter)
  }

  async function refreshNextAction() {
    if (creatingChapterRef.current) return
    creatingChapterRef.current = true
    setIsCreatingChapter(true)
    try {
      await onRefreshAuthorRoute()
      setNextActionRefreshRequired(false)
      setCreateChapterError(null)
    } catch (caught) {
      setNextActionRefreshRequired(true)
      setCreateChapterError(caught instanceof Error
        ? `章节已创建，但下一步同步失败：${caught.message}`
        : '章节已创建，但下一步同步失败。')
    } finally {
      creatingChapterRef.current = false
      setIsCreatingChapter(false)
    }
  }

  async function createNextChapter(openCreated: boolean) {
    if (creatingChapterRef.current || nextActionRefreshRequired) return
    creatingChapterRef.current = true
    setIsCreatingChapter(true)
    setCreateChapterError(null)
    try {
      const lastChapterNumber = Math.max(...workspace.chapters.map((item) => item.chapter_number))
      const created = await api.createChapter(workspace.project.id, {
        expected_last_chapter_number: lastChapterNumber,
      })
      onChapterChanged(created)
      if (openCreated) {
        setActiveChapter(created)
        onActiveChapterChanged(created.id)
      }
      try {
        await onRefreshAuthorRoute()
        setNextActionRefreshRequired(false)
      } catch (caught) {
        setNextActionRefreshRequired(true)
        setCreateChapterError(caught instanceof Error
          ? `章节已创建，但下一步同步失败：${caught.message}`
          : '章节已创建，但下一步同步失败。')
      }
    } catch (caught) {
      setCreateChapterError(caught instanceof Error ? caught.message : '无法添加下一章')
    } finally {
      creatingChapterRef.current = false
      setIsCreatingChapter(false)
    }
  }

  return (
    <ActiveChapterWorkspace
      key={activeChapter.id}
      workspace={workspace}
      initialChapter={initialChapter}
      activeStage={activeStage}
      requestedChapterId={requestedChapterId}
      chapter={activeChapter}
      futureChapters={futureChapters}
      isCreatingChapter={isCreatingChapter}
      nextActionRefreshRequired={nextActionRefreshRequired}
      createChapterError={createChapterError}
      chapterLoadError={chapterLoadError}
      onChapterChanged={handleChapterChanged}
      onWorkspaceChanged={onWorkspaceChanged}
      onRefreshAuthorRoute={onRefreshAuthorRoute}
      onNavigationGuardChanged={onNavigationGuardChanged}
      onStageChanged={onStageChanged}
      onActiveChapterChanged={onActiveChapterChanged}
      onOpenReferenceLibrary={onOpenReferenceLibrary}
      onOpenWritingPatterns={onOpenWritingPatterns}
      onOpenTopicDecision={onOpenTopicDecision}
      onOpenResearch={onOpenResearch}
      onOpenComicDrama={onOpenComicDrama}
      onOpenTaskCenter={onOpenTaskCenter}
      chapterProductionRequest={chapterProductionRequest}
      onChapterProductionRequestHandled={onChapterProductionRequestHandled}
      onSelectChapter={selectChapter}
      onCreateChapter={() => { void createNextChapter(false) }}
      onCreateAndOpenChapter={() => { void createNextChapter(true) }}
      onRefreshNextAction={() => { void refreshNextAction() }}
      queuedAuthorOperation={queuedAuthorOperation}
      onQueueAuthorOperation={setQueuedAuthorOperation}
      onQueuedAuthorOperationHandled={() => setQueuedAuthorOperation(null)}
      onClose={onClose}
    />
  )
}

function ActiveChapterWorkspace({
  workspace,
  chapter,
  activeStage,
  futureChapters,
  isCreatingChapter,
  nextActionRefreshRequired,
  createChapterError,
  chapterLoadError,
  onChapterChanged,
  onWorkspaceChanged,
  onNavigationGuardChanged,
  onStageChanged,
  onOpenReferenceLibrary,
  onOpenWritingPatterns = () => undefined,
  onOpenTopicDecision = () => undefined,
  onOpenResearch = () => undefined,
  onOpenComicDrama = () => undefined,
  onOpenTaskCenter,
  chapterProductionRequest = null,
  onChapterProductionRequestHandled = () => undefined,
  onSelectChapter,
  onCreateChapter,
  onCreateAndOpenChapter,
  onRefreshNextAction,
  queuedAuthorOperation,
  onQueueAuthorOperation,
  onQueuedAuthorOperationHandled,
  onClose,
}: ActiveChapterWorkspaceProps) {
  const { draft, saveStatus, saveError, setDraft, flushNow, retry, adoptServerVersion } = useChapterAutosave(
    chapter,
    onChapterChanged,
  )
  const [isNavigating, setIsNavigating] = useState(false)
  const [isDirectorOpen, setIsDirectorOpen] = useState(false)
  const [directorStageTarget, setDirectorStageTarget] = useState<AuthorWorkflowStage | null>(null)
  const [isDirectoryOpen, setIsDirectoryOpen] = useState(false)
  const [isProductionOpen, setIsProductionOpen] = useState(false)
  const [productionFocusTarget, setProductionFocusTarget] = useState<ProductionFocusTarget>('outline')
  const [isUtilityOpen, setIsUtilityOpen] = useState(false)
  const [serialDialogMode, setSerialDialogMode] = useState<'dashboard' | 'search' | null>(null)
  const [isFocusMode, setIsFocusMode] = useState(false)
  const [authorTools, setAuthorTools] = useState<{ tab: 'calendar' | 'annotations' | 'ideas' | 'graphs'; selection: { start: number; end: number } | null } | null>(null)
  const manuscriptRef = useRef<HTMLTextAreaElement>(null)
  const authorWorkflowRef = useRef<HTMLDivElement>(null)
  const productionReturnFocusRef = useRef<HTMLElement | null>(null)
  const directorTriggerRef = useRef<HTMLButtonElement>(null)
  const planReviewTriggerRef = useRef<HTMLButtonElement>(null)
  const directorReturnFocusRef = useRef<HTMLButtonElement | null>(null)
  const directorCloseRef = useRef<HTMLButtonElement>(null)
  const utilityTriggerRef = useRef<HTMLButtonElement>(null)
  const flushNowRef = useRef<() => Promise<boolean>>(() => Promise.resolve(true))
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

  flushNowRef.current = flushNow

  useEffect(() => {
    const guard = () => flushNowRef.current()
    onNavigationGuardChanged(guard)
    return () => onNavigationGuardChanged(null)
  }, [onNavigationGuardChanged])

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
    if (!directorStageTarget) directorCloseRef.current?.focus()
    let frame = 0
    let settleTimer: number | undefined
    let remainingAttempts = 20
    function focusDirectorStage() {
      if (!directorStageTarget) return
      const target = document.getElementById(directorAnchorId(directorStageTarget))
      if (target) {
        target.focus()
        if (typeof target.scrollIntoView === 'function') target.scrollIntoView({ block: 'start' })
        return
      }
      remainingAttempts -= 1
      if (remainingAttempts > 0) frame = window.requestAnimationFrame(focusDirectorStage)
    }
    frame = window.requestAnimationFrame(focusDirectorStage)
    if (directorStageTarget) {
      // Opening the drawer also makes the invoking rail inert. Chromium may
      // finish that blur after the first animation frame, so reinforce the
      // intended stage focus once the drawer transition has settled.
      settleTimer = window.setTimeout(focusDirectorStage, 250)
    }

    function handleDirectorKeyboard(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        closeDirector()
        return
      }
      if (event.key !== 'Tab') return
      const surface = document.getElementById('ai-director-surface')
      if (!surface) return
      const focusable = [...surface.querySelectorAll<HTMLElement>(DIRECTOR_FOCUSABLE)]
      const first = focusable[0]
      const last = focusable.at(-1)
      if (!first || !last) return
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    window.addEventListener('keydown', handleDirectorKeyboard)
    return () => {
      if (frame) window.cancelAnimationFrame(frame)
      if (settleTimer !== undefined) window.clearTimeout(settleTimer)
      window.removeEventListener('keydown', handleDirectorKeyboard)
    }
  }, [directorStageTarget, isDirectorOpen])

  useEffect(() => {
    if (!isDirectorOpen && !isUtilityOpen) return
    const selectors = isDirectorOpen
      ? '.workspace-header, .story-tree, .editor-panel, .author-workflow-surface, .director-drawer-trigger'
      : '.workspace-header, .story-tree, .editor-panel, .author-workflow-surface, .director-drawer-trigger, .director-surface'
    const background = [...document.querySelectorAll<HTMLElement>(selectors)]
      .map((element) => ({ element, inert: element.inert, ariaHidden: element.getAttribute('aria-hidden') }))
    for (const { element } of background) {
      element.inert = true
      element.setAttribute('aria-hidden', 'true')
    }
    return () => {
      for (const { element, inert, ariaHidden } of background) {
        element.inert = inert
        if (ariaHidden === null) element.removeAttribute('aria-hidden')
        else element.setAttribute('aria-hidden', ariaHidden)
      }
    }
  }, [isDirectorOpen, isUtilityOpen])

  useEffect(() => {
    if (!chapterProductionRequest) return
    if (chapterProductionRequest.chapterId && chapterProductionRequest.chapterId !== chapter.id) return
    const timer = window.setTimeout(() => {
      openProduction('candidate')
      onChapterProductionRequestHandled()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [chapter.id, chapterProductionRequest, onChapterProductionRequestHandled])

  function closeDirector() {
    setIsDirectorOpen(false)
    const returnTarget = directorReturnFocusRef.current ?? directorTriggerRef.current
    returnTarget?.focus()
  }

  async function navigateAfterSave(action: () => void | Promise<unknown>): Promise<boolean> {
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
    utilityTriggerRef.current?.focus()
  }

  function closeProduction() {
    setIsProductionOpen(false)
    window.requestAnimationFrame(() => {
      const returnTarget = productionReturnFocusRef.current
      if (returnTarget?.isConnected) returnTarget.focus()
      else authorWorkflowRef.current?.focus()
    })
  }

  function openProduction(target: ProductionFocusTarget) {
    const activeElement = document.activeElement
    productionReturnFocusRef.current = activeElement instanceof HTMLElement ? activeElement : null
    setIsDirectorOpen(false)
    setProductionFocusTarget(target)
    setIsProductionOpen(true)
  }

  function openDirector(stage?: AuthorWorkflowStage) {
    directorReturnFocusRef.current = document.activeElement instanceof HTMLButtonElement
      ? document.activeElement
      : directorTriggerRef.current
    setDirectorStageTarget(stage ?? null)
    setIsDirectorOpen(true)
  }

  function closeUtility() {
    setIsUtilityOpen(false)
    window.requestAnimationFrame(() => utilityTriggerRef.current?.focus())
  }

  function runAuthorOperation(operation: AuthorActionOperation) {
    if (operation === 'topic') {
      onOpenTopicDecision()
    } else if (operation === 'production') {
      const stage = workspace.author_next_action?.target_stage ?? activeStage
      openProduction(stage === 'candidate' ? 'candidate' : 'outline')
    } else if (operation === 'manuscript') {
      manuscriptRef.current?.focus()
    } else if (operation === 'create') {
      onCreateAndOpenChapter()
    } else if (operation === 'final') {
      const chapterId = workspace.author_next_action?.last_approved_chapter_id
      if (chapterId && chapterId !== chapter.id) void onSelectChapter(chapterId)
      else manuscriptRef.current?.focus()
    } else {
      openDirector(workspace.author_next_action?.target_stage ?? activeStage)
    }
  }

  async function handlePrimaryAuthorAction() {
    const action = workspace.author_next_action
    const presentation = presentAuthorAction(action)
    if (presentation.disabled) return
    await navigateAfterSave(async () => {
      if (action) onStageChanged(action.target_stage)
      const targetChapterId = action?.chapter_id
      if (targetChapterId && targetChapterId !== chapter.id) {
        const selected = await onSelectChapter(targetChapterId)
        if (selected && presentation.operation !== 'final') onQueueAuthorOperation(presentation.operation)
        return
      }
      runAuthorOperation(presentation.operation)
    })
  }

  function handleWorkflowStage(stage: AuthorWorkflowStage) {
    void navigateAfterSave(() => {
      onStageChanged(stage)
      if (stage === 'plan' || stage === 'candidate') {
        openProduction(stage === 'candidate' ? 'candidate' : 'outline')
      } else if (stage === 'book' && workspace.topic_decision?.status !== 'confirmed') {
        onOpenTopicDecision()
      } else {
        openDirector(stage)
      }
    })
  }

  useEffect(() => {
    if (!queuedAuthorOperation) return
    const timer = window.setTimeout(() => {
      if (queuedAuthorOperation === 'production') {
        const stage = workspace.author_next_action?.target_stage ?? activeStage
        openProduction(stage === 'candidate' ? 'candidate' : 'outline')
      } else if (queuedAuthorOperation === 'manuscript') {
        manuscriptRef.current?.focus()
      } else {
        setDirectorStageTarget(workspace.author_next_action?.target_stage ?? activeStage)
        setIsDirectorOpen(true)
      }
      onQueuedAuthorOperationHandled()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [activeStage, onQueuedAuthorOperationHandled, queuedAuthorOperation, workspace.author_next_action?.target_stage])

  return (
    <main className="workspace-shell" data-focus-mode={isFocusMode}>
      <a className="workspace-skip-link" href="#manuscript-editor">跳到正文</a>
      <a className="workspace-skip-link workspace-skip-ai" href="#author-workflow">跳到本章 AI</a>
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
            ref={utilityTriggerRef}
            className="library-action utility-action"
            type="button"
            aria-label="打开辅助工具"
            aria-haspopup="dialog"
            disabled={isNavigating}
            onClick={() => { void navigateAfterSave(() => setIsUtilityOpen(true)) }}
          >{isNavigating ? '正在保存…' : '辅助工具'}</button>
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
          {workspace.next_action === 'review_downstream_plans' ? (
            <button
              ref={planReviewTriggerRef}
              className="plan-rebase-entry"
              type="button"
              disabled={isNavigating}
              onClick={() => { void navigateAfterSave(() => {
                directorReturnFocusRef.current = planReviewTriggerRef.current
                setDirectorStageTarget('book')
                setIsDirectorOpen(true)
              }) }}
            >
              <strong>计划需复核 · 查看影响</strong>
              <small>选题或写作模式已更新；已定稿正文不会被改动</small>
            </button>
          ) : null}
        </section>
        <nav aria-label="章节目录">
          <div className="tree-section-title">
            <span>作品目录</span>
            <div>
              <button type="button" aria-label="管理卷章场景" disabled={isNavigating} onClick={() => { void navigateAfterSave(() => setIsDirectoryOpen(true)) }}>管理</button>
              <button
                type="button"
                aria-label={nextActionRefreshRequired ? '等待刷新下一步' : '添加下一章'}
                onClick={onCreateChapter}
                disabled={isCreatingChapter || nextActionRefreshRequired}
              >＋</button>
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
          <button type="button" className="rolling-add" onClick={onCreateChapter} disabled={isCreatingChapter || nextActionRefreshRequired}>
            {isCreatingChapter
              ? '正在添加…'
              : nextActionRefreshRequired
                ? '等待刷新下一步'
                : futureChapters.length >= 3 ? '继续添加远期章' : '添加下一章'}
          </button>
          {createChapterError && !nextActionRefreshRequired ? <p className="tree-error" role="alert">{createChapterError}</p> : null}
        </section>
      </aside>

      <section className="editor-panel" aria-labelledby="chapter-title">
        <header className="editor-heading">
          <div>
            <p>{(workspace.manuscript_volumes ?? []).find((volume) => volume.id === chapter.volume_id)?.title ?? `第 ${chapter.volume_number} 卷`} · 第 {chapter.chapter_number} 章</p>
            <h2 id="chapter-title">{chapter.title}</h2>
          </div>
          <div className="editor-heading-actions">
            <span className="save-state" data-status={saveStatus} role="status">
              <i aria-hidden="true" />{isApproved ? '定稿锁定' : saveLabels[saveStatus]}
            </span>
          </div>
        </header>
        <textarea
          id="manuscript-editor"
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

      <div id="author-workflow" ref={authorWorkflowRef} className="author-workflow-surface" tabIndex={-1}>
        <AuthorWorkflowRail
          action={workspace.author_next_action}
          activeStage={activeStage}
          busy={isNavigating || isCreatingChapter}
          nextActionRecovery={nextActionRefreshRequired ? createChapterError : null}
          onSelectStage={handleWorkflowStage}
          onPrimaryAction={() => { void handlePrimaryAuthorAction() }}
          onRefreshNextAction={onRefreshNextAction}
          onOpenLastApproved={(chapterId) => {
            void navigateAfterSave(() => onSelectChapter(chapterId))
          }}
        />
      </div>

      <button
        ref={directorTriggerRef}
        className="director-drawer-trigger"
        type="button"
        aria-label="打开 AI 导演"
        aria-controls="ai-director-surface"
        aria-expanded={isDirectorOpen}
        onClick={() => {
          directorReturnFocusRef.current = directorTriggerRef.current
          setDirectorStageTarget(null)
          setIsDirectorOpen(true)
        }}
      >
        <span aria-hidden="true">AI</span>
        <strong aria-hidden="true">导演</strong>
      </button>
      {isUtilityOpen ? (
        <AuthorUtilityDrawer
          onClose={closeUtility}
          onOpenSerial={() => { setIsUtilityOpen(false); setSerialDialogMode('dashboard') }}
          onOpenAuthorTools={() => { setIsUtilityOpen(false); setAuthorTools({ tab: 'calendar', selection: null }) }}
          onOpenWritingPatterns={() => { setIsUtilityOpen(false); onOpenWritingPatterns() }}
          onOpenResearch={() => { setIsUtilityOpen(false); onOpenResearch() }}
          onOpenTasks={() => { setIsUtilityOpen(false); onOpenTaskCenter() }}
          onOpenComicDrama={() => { setIsUtilityOpen(false); onOpenComicDrama() }}
          onOpenReferences={() => { setIsUtilityOpen(false); onOpenReferenceLibrary() }}
        />
      ) : null}
      {isDirectoryOpen ? (
        <Suspense fallback={null}>
          <ManuscriptDirectoryDialog
            workspace={workspace}
            activeChapterId={chapter.id}
            onClose={() => setIsDirectoryOpen(false)}
            onCommit={commitDirectory}
          />
        </Suspense>
      ) : null}
      {serialDialogMode ? (
        <Suspense fallback={null}>
          <SerialWorkspaceDialog
            projectId={workspace.project.id}
            initialMode={serialDialogMode}
            onClose={() => setSerialDialogMode(null)}
            onOpenChapter={openSerialChapter}
          />
        </Suspense>
      ) : null}
      {authorTools ? (
        <Suspense fallback={null}>
          <AuthorToolsDialog project={workspace.project} chapter={chapter} initialTab={authorTools.tab} selection={authorTools.selection} onClose={closeAuthorTools} onAdjustGoal={() => { setAuthorTools(null); setSerialDialogMode('dashboard') }} />
        </Suspense>
      ) : null}
      {isProductionOpen ? (
        <Suspense fallback={null}>
          <ChapterProductionDialog
            project={workspace.project}
            chapter={chapter}
            initialFocus={productionFocusTarget}
            onClose={closeProduction}
            onChapterChanged={handleChapterUpdated}
            onOpenTaskCenter={() => {
              setIsProductionOpen(false)
              onOpenTaskCenter()
            }}
          />
        </Suspense>
      ) : null}
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
        role={isDirectorOpen ? 'dialog' : 'region'}
        aria-modal={isDirectorOpen ? 'true' : undefined}
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
          onOpenChapterProduction={() => {
            closeDirector()
            void navigateAfterSave(() => openProduction('outline'))
          }}
        />
      </section>
    </main>
  )
}
