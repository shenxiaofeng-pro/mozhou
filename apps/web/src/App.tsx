import type {
  AuthorWorkflowStage,
  Chapter,
  ChapterSummary,
  Project,
  Workspace,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'

import { api } from './api'
import { CreateProjectForm } from './components/CreateProjectForm'
import { ProjectLibraryPage } from './components/ProjectLibraryPage'
import { WorkspaceShell } from './components/WorkspaceShell'
import { clearActiveProjectId, loadActiveProjectId, saveActiveProjectId } from './storage'
import {
  clearWorkspaceRoute,
  readWorkspaceRoute,
  type WorkspaceRoute,
  type WorkspaceView,
  writeWorkspaceRoute,
} from './workspaceRoute'

interface LoadedProject {
  workspace: WorkspaceSummary
  initialChapter: Chapter
}

const TopicDecisionWorkbench = lazy(async () => {
  const module = await import('./components/TopicDecisionWorkbench')
  return { default: module.TopicDecisionWorkbench }
})

const WritingPatternRecipePage = lazy(async () => {
  const module = await import('./components/WritingPatternRecipePage')
  return { default: module.WritingPatternRecipePage }
})

const ReferenceLibraryPage = lazy(async () => {
  const module = await import('./components/ReferenceLibraryPage')
  return { default: module.ReferenceLibraryPage }
})

const GlobalReferenceLibraryPage = lazy(async () => {
  const module = await import('./components/GlobalReferenceLibraryPage')
  return { default: module.GlobalReferenceLibraryPage }
})

const ResearchWorkbenchPage = lazy(async () => {
  const module = await import('./components/ResearchWorkbenchPage')
  return { default: module.ResearchWorkbenchPage }
})

const ComicDramaWorkbenchPage = lazy(async () => {
  const module = await import('./components/ComicDramaWorkbenchPage')
  return { default: module.ComicDramaWorkbenchPage }
})

const TaskCenter = lazy(async () => {
  const module = await import('./components/TaskCenter')
  return { default: module.TaskCenter }
})

function startingView(workspace: WorkspaceSummary): WorkspaceView {
  if (workspace.author_next_action?.target_view) return workspace.author_next_action.target_view
  return workspace.next_action === 'confirm_topic' || workspace.next_action === 'review_topic_changes'
    ? 'topic-decision'
    : 'writing'
}

function startingStage(workspace: WorkspaceSummary): AuthorWorkflowStage {
  return workspace.author_next_action?.target_stage
    ?? (startingView(workspace) === 'topic-decision' ? 'topic' : 'plan')
}

function suggestedChapterId(workspace: WorkspaceSummary): string | null {
  return workspace.author_next_action?.chapter_id
    ?? workspace.resume_card?.chapter_id
    ?? workspace.chapters[0]?.id
    ?? null
}

function authorActionKey(workspace: WorkspaceSummary): string | null {
  const action = workspace.author_next_action
  return action
    ? [action.kind, action.target_view, action.target_stage, action.chapter_id ?? ''].join(':')
    : null
}

function summarizeChapter({ content, ...chapter }: Chapter): ChapterSummary {
  return {
    ...chapter,
    has_content: content.trim().length > 0,
    content_characters: content.length,
  }
}

function summarizeWorkspace(workspace: Workspace): WorkspaceSummary {
  return {
    ...workspace,
    chapters: workspace.chapters.map(summarizeChapter),
  }
}

function isFullWorkspace(workspace: Workspace | WorkspaceSummary): workspace is Workspace {
  return workspace.chapters.some((chapter) => 'content' in chapter)
}

function WorkspacePageFallback({ label }: { label: string }) {
  return <main className="loading-shell" aria-live="polite"><p>{label}</p></main>
}

async function loadProjectForWriting(projectId: string, preferredChapterId: string | null = null): Promise<LoadedProject> {
  const workspace = await api.getProjectSummary(projectId)
  const chapterId = preferredChapterId ?? suggestedChapterId(workspace)
  const initialChapterSummary = workspace.chapters.find((chapter) => chapter.id === chapterId)
    ?? workspace.chapters[0]
  if (!initialChapterSummary) throw new Error('作品中没有可打开的章节')
  return {
    workspace,
    initialChapter: await api.getChapter(initialChapterSummary.id),
  }
}

export function App() {
  const [initialRoute] = useState(readWorkspaceRoute)
  const [workspace, setWorkspace] = useState<WorkspaceSummary | null>(null)
  const [initialChapter, setInitialChapter] = useState<Chapter | null>(null)
  const [projects, setProjects] = useState<Project[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [openingProjectId, setOpeningProjectId] = useState<string | null>(null)
  const [isCreatingProject, setIsCreatingProject] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [libraryNotice, setLibraryNotice] = useState<string | null>(null)
  const [activeView, setActiveView] = useState<WorkspaceView>(initialRoute.view ?? 'writing')
  const [activeStage, setActiveStage] = useState<AuthorWorkflowStage>(initialRoute.stage ?? 'plan')
  const [routeChapterId, setRouteChapterId] = useState<string | null>(initialRoute.chapterId)
  const [isTaskCenterOpen, setIsTaskCenterOpen] = useState(false)
  const [chapterProductionRequest, setChapterProductionRequest] = useState<{
    chapterId: string | null
    requestId: number
  } | null>(null)
  const [isGlobalLibraryOpen, setIsGlobalLibraryOpen] = useState(false)
  const lastSuggestedActionRef = useRef<string | null | undefined>(undefined)
  const navigationGuardRef = useRef<(() => Promise<boolean>) | null>(null)
  const workspaceRef = useRef<WorkspaceSummary | null>(workspace)
  const workspaceRouteRef = useRef<WorkspaceRoute>({
    projectId: null,
    view: null,
    stage: null,
    chapterId: null,
  })

  const handleNavigationGuardChanged = useCallback((guard: (() => Promise<boolean>) | null) => {
    navigationGuardRef.current = guard
  }, [])

  useEffect(() => {
    workspaceRef.current = workspace
    workspaceRouteRef.current = workspace
      ? { projectId: workspace.project.id, view: activeView, stage: activeStage, chapterId: routeChapterId }
      : { projectId: null, view: null, stage: null, chapterId: null }
  }, [activeStage, activeView, routeChapterId, workspace])

  useEffect(() => {
    const requestedRoute = initialRoute
    const projectId = requestedRoute.projectId ?? loadActiveProjectId()
    let active = true

    const projectsRequest = api.listProjects()
    const workspaceRequest = projectId
      ? loadProjectForWriting(
        projectId,
        requestedRoute.projectId === projectId ? requestedRoute.chapterId : null,
      )
      : Promise.resolve(null)

    Promise.allSettled([projectsRequest, workspaceRequest]).then(([projectResult, workspaceResult]) => {
      if (!active) return
      if (projectResult.status === 'fulfilled') {
        setProjects(projectResult.value)
      } else {
        setLoadError(projectResult.reason instanceof Error ? projectResult.reason.message : '无法读取作品书架')
      }
      if (workspaceResult.status === 'fulfilled') {
        const loaded = workspaceResult.value
        setWorkspace(loaded?.workspace ?? null)
        setInitialChapter(loaded?.initialChapter ?? null)
        if (loaded) {
          const hasExplicitRoute = requestedRoute.projectId === loaded.workspace.project.id
          const view = hasExplicitRoute && requestedRoute.view
            ? requestedRoute.view
            : startingView(loaded.workspace)
          const stage = hasExplicitRoute && requestedRoute.stage
            ? requestedRoute.stage
            : startingStage(loaded.workspace)
          const chapterId = loaded.initialChapter.id
          setActiveView(view)
          setActiveStage(stage)
          setRouteChapterId(chapterId)
          lastSuggestedActionRef.current = authorActionKey(loaded.workspace)
          writeWorkspaceRoute({
            projectId: loaded.workspace.project.id,
            view,
            stage,
            chapterId,
          }, 'replace')
        }
      } else {
        clearActiveProjectId()
        setInitialChapter(null)
        clearWorkspaceRoute('replace')
        setLoadError(workspaceResult.reason instanceof Error ? workspaceResult.reason.message : '无法打开上次作品')
      }
      setIsLoading(false)
    })
    return () => {
      active = false
    }
  }, [initialRoute])

  const navigateWorkspace = useCallback((
    view: WorkspaceView,
    options: {
      stage?: AuthorWorkflowStage
      chapterId?: string | null
      mode?: 'push' | 'replace'
    } = {},
  ) => {
    const stage = options.stage ?? activeStage
    const chapterId = options.chapterId === undefined ? routeChapterId : options.chapterId
    setActiveView(view)
    setActiveStage(stage)
    setRouteChapterId(chapterId)
    writeWorkspaceRoute({
      projectId: workspace?.project.id ?? null,
      view,
      stage,
      chapterId,
    }, options.mode ?? 'push')
  }, [activeStage, routeChapterId, workspace?.project.id])

  const restoreRequestedChapterRoute = useCallback((previousChapterId: string) => {
    const currentWorkspace = workspaceRef.current
    if (!currentWorkspace) return
    const currentRoute = readWorkspaceRoute()
    const restoredRoute: WorkspaceRoute = {
      projectId: currentWorkspace.project.id,
      view: currentRoute.view ?? 'writing',
      stage: currentRoute.stage ?? 'plan',
      chapterId: previousChapterId,
    }
    workspaceRouteRef.current = restoredRoute
    setRouteChapterId(previousChapterId)
    writeWorkspaceRoute(restoredRoute, 'replace')
  }, [])

  useEffect(() => {
    let requestVersion = 0

    async function restoreFromHistory() {
      const version = ++requestVersion
      const route = readWorkspaceRoute()
      const previousRoute = workspaceRouteRef.current
      const guard = navigationGuardRef.current
      let canLeave = true
      if (guard) {
        try {
          canLeave = await guard()
        } catch {
          canLeave = false
        }
      }
      if (version !== requestVersion) return
      if (!canLeave) {
        writeWorkspaceRoute(previousRoute, 'replace')
        return
      }

      setIsGlobalLibraryOpen(false)
      setIsTaskCenterOpen(false)
      if (!route.projectId) {
        clearActiveProjectId()
        setWorkspace(null)
        setInitialChapter(null)
        setRouteChapterId(null)
        setActiveView('writing')
        setActiveStage('plan')
        return
      }

      const currentWorkspace = workspaceRef.current
      if (route.projectId === currentWorkspace?.project.id) {
        setActiveView(route.view ?? startingView(currentWorkspace))
        setActiveStage(route.stage ?? startingStage(currentWorkspace))
        setRouteChapterId(route.chapterId ?? suggestedChapterId(currentWorkspace))
        return
      }

      try {
        const loaded = await loadProjectForWriting(route.projectId, route.chapterId)
        if (version !== requestVersion) return
        saveActiveProjectId(route.projectId)
        setWorkspace(loaded.workspace)
        setInitialChapter(loaded.initialChapter)
        setActiveView(route.view ?? startingView(loaded.workspace))
        setActiveStage(route.stage ?? startingStage(loaded.workspace))
        setRouteChapterId(loaded.initialChapter.id)
        setLoadError(null)
        lastSuggestedActionRef.current = authorActionKey(loaded.workspace)
      } catch (error) {
        if (version !== requestVersion) return
        writeWorkspaceRoute(previousRoute, 'replace')
        setLoadError(error instanceof Error ? error.message : '无法恢复链接中的作品')
      }
    }

    window.addEventListener('popstate', restoreFromHistory)
    return () => {
      requestVersion += 1
      window.removeEventListener('popstate', restoreFromHistory)
    }
  }, [])

  const followAuthorRecommendation = useCallback((nextWorkspace: WorkspaceSummary) => {
    const action = nextWorkspace.author_next_action
    const key = authorActionKey(nextWorkspace)
    if (lastSuggestedActionRef.current === key) return
    lastSuggestedActionRef.current = key
    if (!action) return

    const chapterId = action.chapter_id ?? routeChapterId ?? suggestedChapterId(nextWorkspace)
    setActiveView(action.target_view)
    setActiveStage(action.target_stage)
    setRouteChapterId(chapterId)
    writeWorkspaceRoute({
      projectId: nextWorkspace.project.id,
      view: action.target_view,
      stage: action.target_stage,
      chapterId,
    }, 'replace')
  }, [routeChapterId])

  const handleCreated = useCallback((created: Workspace) => {
    const summary = summarizeWorkspace(created)
    const view = startingView(summary)
    const stage = startingStage(summary)
    const chapterId = suggestedChapterId(summary)
    saveActiveProjectId(created.project.id)
    setProjects((current) => [
      created.project,
      ...current.filter((project) => project.id !== created.project.id),
    ])
    setWorkspace(summary)
    setInitialChapter(created.chapters.find((chapter) => chapter.id === chapterId) ?? created.chapters[0] ?? null)
    setLoadError(null)
    setLibraryNotice(null)
    setIsCreatingProject(false)
    setActiveView(view)
    setActiveStage(stage)
    setRouteChapterId(chapterId)
    lastSuggestedActionRef.current = authorActionKey(summary)
    writeWorkspaceRoute({ projectId: created.project.id, view, stage, chapterId })
    setIsTaskCenterOpen(false)
    setChapterProductionRequest(null)
  }, [])

  const handleProjectAdded = useCallback((added: Workspace) => {
    setProjects((current) => [
      added.project,
      ...current.filter((project) => project.id !== added.project.id),
    ])
    setLibraryNotice(`《${added.project.title}》已恢复为新副本。`)
  }, [])

  const handleOpenProject = useCallback(async (projectId: string) => {
    setOpeningProjectId(projectId)
    setLoadError(null)
    try {
      const loaded = await loadProjectForWriting(projectId)
      saveActiveProjectId(projectId)
      setWorkspace(loaded.workspace)
      setInitialChapter(loaded.initialChapter)
      setLibraryNotice(null)
      setProjects((current) => [
        loaded.workspace.project,
        ...current.filter((project) => project.id !== projectId),
      ])
      const view = startingView(loaded.workspace)
      const stage = startingStage(loaded.workspace)
      const chapterId = loaded.initialChapter.id
      setActiveView(view)
      setActiveStage(stage)
      setRouteChapterId(chapterId)
      lastSuggestedActionRef.current = authorActionKey(loaded.workspace)
      writeWorkspaceRoute({ projectId, view, stage, chapterId })
      setIsTaskCenterOpen(false)
      setChapterProductionRequest(null)
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : '无法打开作品')
    } finally {
      setOpeningProjectId(null)
    }
  }, [])

  const handleChapterChanged = useCallback((saved: Chapter) => {
    const summary = summarizeChapter(saved)
    const previous = workspace?.chapters.find((chapter) => chapter.id === saved.id)
    const shouldRefreshAuthorRoute = previous !== undefined && (
      previous.status !== summary.status
      || previous.has_content !== summary.has_content
    )
    setInitialChapter((current) => current?.id === saved.id ? saved : current)
    setWorkspace((current) => current ? {
      ...current,
      project: { ...current.project, updated_at: saved.updated_at },
      chapters: current.chapters.some((chapter) => chapter.id === saved.id)
        ? current.chapters.map((chapter) => chapter.id === saved.id ? summary : chapter)
        : [...current.chapters, summary].sort((left, right) => left.chapter_number - right.chapter_number),
    } : current)
    setProjects((current) => {
      const project = current.find((item) => item.id === saved.project_id)
      return project
        ? [{ ...project, updated_at: saved.updated_at }, ...current.filter((item) => item.id !== saved.project_id)]
        : current
    })
    if (shouldRefreshAuthorRoute) {
      void api.getProjectSummary(saved.project_id).then((refreshed) => {
        setWorkspace(refreshed)
        followAuthorRecommendation(refreshed)
      }).catch(() => undefined)
    }
  }, [followAuthorRecommendation, workspace?.chapters])

  const handleClose = useCallback(() => {
    clearActiveProjectId()
    setWorkspace(null)
    setInitialChapter(null)
    setIsCreatingProject(false)
    setActiveView('writing')
    setActiveStage('plan')
    setRouteChapterId(null)
    clearWorkspaceRoute()
    lastSuggestedActionRef.current = undefined
    setIsTaskCenterOpen(false)
    setChapterProductionRequest(null)
  }, [])

  const handleWorkspaceChanged = useCallback((updated: Workspace | WorkspaceSummary) => {
    if (!isFullWorkspace(updated)) {
      setWorkspace(updated)
      followAuthorRecommendation(updated)
      return
    }

    const summary = summarizeWorkspace(updated)
    setWorkspace(summary)
    followAuthorRecommendation(summary)
    setInitialChapter((current) => (
      current
        ? updated.chapters.find((chapter) => chapter.id === current.id) ?? current
        : updated.chapters[0] ?? null
    ))
  }, [followAuthorRecommendation])

  const refreshAuthorRoute = useCallback(async () => {
    const projectId = workspaceRef.current?.project.id
    if (!projectId) throw new Error('当前作品已关闭，无法刷新下一步。')
    const refreshed = await api.getProjectSummary(projectId)
    setWorkspace(refreshed)
    followAuthorRecommendation(refreshed)
  }, [followAuthorRecommendation])

  const handleProjectAssetsChanged = useCallback((projectId: string) => {
    void api.listProjects().then(setProjects).catch(() => undefined)
    if (workspace?.project.id === projectId) {
      void api.getProjectSummary(projectId).then((refreshed) => {
        setWorkspace(refreshed)
        followAuthorRecommendation(refreshed)
      }).catch(() => undefined)
    }
  }, [followAuthorRecommendation, workspace?.project.id])

  if (isLoading) {
    return (
      <main className="loading-shell" aria-live="polite">
        <div className="brand-mark" aria-hidden="true">墨</div>
        <p>正在展开上次的稿纸…</p>
      </main>
    )
  }

  if (isGlobalLibraryOpen) {
    return (
      <Suspense fallback={<WorkspacePageFallback label="正在展开全局拆书库…" />}>
        <GlobalReferenceLibraryPage
          projects={projects}
          activeProjectId={workspace?.project.id}
          onBack={() => setIsGlobalLibraryOpen(false)}
          onProjectAssetsChanged={handleProjectAssetsChanged}
        />
      </Suspense>
    )
  }

  if (!workspace || !initialChapter) {
    if (projects.length > 0 && !isCreatingProject) {
      return (
        <ProjectLibraryPage
          projects={projects}
          openingProjectId={openingProjectId}
          error={loadError}
          onOpen={(projectId) => { void handleOpenProject(projectId) }}
          onCreate={() => setIsCreatingProject(true)}
          onOpenGlobalLibrary={() => setIsGlobalLibraryOpen(true)}
          onProjectAdded={handleProjectAdded}
          initialNotice={libraryNotice}
        />
      )
    }
    return (
      <>
        {loadError ? <p className="load-notice" role="status">{loadError}，可以新建作品继续。</p> : null}
        <CreateProjectForm
          onCreated={handleCreated}
          onImported={handleProjectAdded}
          onCancel={projects.length > 0 ? () => setIsCreatingProject(false) : undefined}
        />
      </>
    )
  }

  const activePage = activeView === 'topic-decision'
    ? (
      <Suspense fallback={<main className="loading-shell" aria-live="polite"><p>正在展开选题单…</p></main>}>
        <TopicDecisionWorkbench
          workspace={workspace}
          onWorkspaceChanged={handleWorkspaceChanged}
          onContinue={() => navigateWorkspace('writing', { stage: 'book' })}
          onClose={handleClose}
          onOpenTaskCenter={() => setIsTaskCenterOpen(true)}
        />
      </Suspense>
    ) : activeView === 'writing-patterns'
    ? (
      <Suspense fallback={<main className="loading-shell" aria-live="polite"><p>正在展开写作配方…</p></main>}>
        <WritingPatternRecipePage
          workspace={workspace}
          onBack={() => navigateWorkspace('writing')}
          onOpenTopicDecision={() => navigateWorkspace('topic-decision', { stage: 'topic' })}
          onWorkspaceChanged={handleWorkspaceChanged}
        />
      </Suspense>
    ) : activeView === 'reference-library'
    ? (
      <Suspense fallback={<WorkspacePageFallback label="正在展开拆书库…" />}>
        <ReferenceLibraryPage
          workspace={workspace}
          onWorkspaceChanged={handleWorkspaceChanged}
          onBack={() => navigateWorkspace('writing')}
          onOpenTaskCenter={() => setIsTaskCenterOpen(true)}
          onOpenGlobalLibrary={() => setIsGlobalLibraryOpen(true)}
        />
      </Suspense>
    ) : activeView === 'research' ? (
      <Suspense fallback={<WorkspacePageFallback label="正在展开资料研究台…" />}>
        <ResearchWorkbenchPage
          project={workspace.project}
          onBack={() => navigateWorkspace('writing')}
          onSourceCardsChanged={() => handleProjectAssetsChanged(workspace.project.id)}
        />
      </Suspense>
    ) : activeView === 'comic-drama' ? (
      <Suspense fallback={<WorkspacePageFallback label="正在展开 AI 漫剧工作台…" />}>
        <ComicDramaWorkbenchPage
          project={workspace.project}
          chapters={workspace.chapters}
          onBack={() => navigateWorkspace('writing')}
          onOpenTaskCenter={() => setIsTaskCenterOpen(true)}
        />
      </Suspense>
    ) : (
      <WorkspaceShell
        key={`workspace:${workspace.project.id}`}
        workspace={workspace}
        initialChapter={initialChapter}
        activeStage={activeStage}
        requestedChapterId={routeChapterId}
        onChapterChanged={handleChapterChanged}
        onWorkspaceChanged={handleWorkspaceChanged}
        onRefreshAuthorRoute={refreshAuthorRoute}
        onNavigationGuardChanged={handleNavigationGuardChanged}
        onStageChanged={(stage) => navigateWorkspace('writing', { stage })}
        onActiveChapterChanged={(chapterId) => navigateWorkspace('writing', { chapterId })}
        onRequestedChapterLoadFailed={restoreRequestedChapterRoute}
        onOpenTopicDecision={() => navigateWorkspace('topic-decision', { stage: 'topic' })}
        onOpenWritingPatterns={() => navigateWorkspace('writing-patterns')}
        onOpenReferenceLibrary={() => navigateWorkspace('reference-library')}
        onOpenResearch={() => navigateWorkspace('research')}
        onOpenComicDrama={() => navigateWorkspace('comic-drama')}
        onOpenTaskCenter={() => setIsTaskCenterOpen(true)}
        chapterProductionRequest={chapterProductionRequest}
        onChapterProductionRequestHandled={() => setChapterProductionRequest(null)}
        onClose={handleClose}
      />
    )

  return (
    <>
      {activePage}
      {isTaskCenterOpen ? (
        <Suspense fallback={<WorkspacePageFallback label="正在打开任务中心…" />}>
          <TaskCenter
            key={workspace.project.id}
            projectId={workspace.project.id}
            chapters={workspace.chapters}
            open
            onClose={() => setIsTaskCenterOpen(false)}
            onChapterChanged={handleChapterChanged}
            onWorkspaceChanged={handleWorkspaceChanged}
            onOpenReferenceLibrary={() => navigateWorkspace('reference-library')}
            onOpenWritingPatterns={() => navigateWorkspace('writing-patterns')}
            onOpenChapterProduction={(chapterId) => {
              navigateWorkspace('writing', { stage: 'candidate', chapterId })
              setChapterProductionRequest({ chapterId, requestId: Date.now() })
            }}
          />
        </Suspense>
      ) : null}
    </>
  )
}
