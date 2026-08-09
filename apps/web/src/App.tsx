import type { Chapter, ChapterSummary, Project, Workspace, WorkspaceSummary } from '@mozhou/contracts'
import { useCallback, useEffect, useState } from 'react'

import { api } from './api'
import { CreateProjectForm } from './components/CreateProjectForm'
import { ProjectLibraryPage } from './components/ProjectLibraryPage'
import { ReferenceLibraryPage } from './components/ReferenceLibraryPage'
import { TaskCenter } from './components/TaskCenter'
import { WorkspaceShell } from './components/WorkspaceShell'
import { clearActiveProjectId, loadActiveProjectId, saveActiveProjectId } from './storage'

interface LoadedProject {
  workspace: WorkspaceSummary
  initialChapter: Chapter
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

async function loadProjectForWriting(projectId: string): Promise<LoadedProject> {
  const workspace = await api.getProjectSummary(projectId)
  const initialChapterSummary = workspace.chapters.find(
    (chapter) => chapter.id === workspace.resume_card?.chapter_id,
  ) ?? workspace.chapters[0]
  if (!initialChapterSummary) throw new Error('作品中没有可打开的章节')
  return {
    workspace,
    initialChapter: await api.getChapter(initialChapterSummary.id),
  }
}

export function App() {
  const [workspace, setWorkspace] = useState<WorkspaceSummary | null>(null)
  const [initialChapter, setInitialChapter] = useState<Chapter | null>(null)
  const [projects, setProjects] = useState<Project[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [openingProjectId, setOpeningProjectId] = useState<string | null>(null)
  const [isCreatingProject, setIsCreatingProject] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [libraryNotice, setLibraryNotice] = useState<string | null>(null)
  const [activeView, setActiveView] = useState<'writing' | 'reference-library'>('writing')
  const [isTaskCenterOpen, setIsTaskCenterOpen] = useState(false)

  useEffect(() => {
    const projectId = loadActiveProjectId()
    let active = true

    const projectsRequest = api.listProjects()
    const workspaceRequest = projectId ? loadProjectForWriting(projectId) : Promise.resolve(null)

    Promise.allSettled([projectsRequest, workspaceRequest]).then(([projectResult, workspaceResult]) => {
      if (!active) return
      if (projectResult.status === 'fulfilled') {
        setProjects(projectResult.value)
      } else {
        setLoadError(projectResult.reason instanceof Error ? projectResult.reason.message : '无法读取作品书架')
      }
      if (workspaceResult.status === 'fulfilled') {
        setWorkspace(workspaceResult.value?.workspace ?? null)
        setInitialChapter(workspaceResult.value?.initialChapter ?? null)
      } else {
        clearActiveProjectId()
        setInitialChapter(null)
        setLoadError(workspaceResult.reason instanceof Error ? workspaceResult.reason.message : '无法打开上次作品')
      }
      setIsLoading(false)
    })
    return () => {
      active = false
    }
  }, [])

  const handleCreated = useCallback((created: Workspace) => {
    saveActiveProjectId(created.project.id)
    setProjects((current) => [
      created.project,
      ...current.filter((project) => project.id !== created.project.id),
    ])
    setWorkspace(summarizeWorkspace(created))
    setInitialChapter(created.chapters[0] ?? null)
    setLoadError(null)
    setLibraryNotice(null)
    setIsCreatingProject(false)
    setActiveView('writing')
    setIsTaskCenterOpen(false)
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
      setActiveView('writing')
      setIsTaskCenterOpen(false)
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : '无法打开作品')
    } finally {
      setOpeningProjectId(null)
    }
  }, [])

  const handleChapterChanged = useCallback((saved: Chapter) => {
    const summary = summarizeChapter(saved)
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
  }, [])

  const handleClose = useCallback(() => {
    clearActiveProjectId()
    setWorkspace(null)
    setInitialChapter(null)
    setIsCreatingProject(false)
    setActiveView('writing')
    setIsTaskCenterOpen(false)
  }, [])

  const handleWorkspaceChanged = useCallback((updated: Workspace | WorkspaceSummary) => {
    if (!isFullWorkspace(updated)) {
      setWorkspace(updated)
      return
    }

    setWorkspace(summarizeWorkspace(updated))
    setInitialChapter((current) => (
      current
        ? updated.chapters.find((chapter) => chapter.id === current.id) ?? current
        : updated.chapters[0] ?? null
    ))
  }, [])

  if (isLoading) {
    return (
      <main className="loading-shell" aria-live="polite">
        <div className="brand-mark" aria-hidden="true">墨</div>
        <p>正在展开上次的稿纸…</p>
      </main>
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

  const activePage = activeView === 'reference-library'
    ? (
      <ReferenceLibraryPage
        workspace={workspace}
        onWorkspaceChanged={handleWorkspaceChanged}
        onBack={() => setActiveView('writing')}
        onOpenTaskCenter={() => setIsTaskCenterOpen(true)}
      />
    ) : (
      <WorkspaceShell
        workspace={workspace}
        initialChapter={initialChapter}
        onChapterChanged={handleChapterChanged}
        onWorkspaceChanged={handleWorkspaceChanged}
        onOpenReferenceLibrary={() => setActiveView('reference-library')}
        onOpenTaskCenter={() => setIsTaskCenterOpen(true)}
        onClose={handleClose}
      />
    )

  return (
    <>
      {activePage}
      <TaskCenter
        key={workspace.project.id}
        projectId={workspace.project.id}
        chapters={workspace.chapters}
        open={isTaskCenterOpen}
        onClose={() => setIsTaskCenterOpen(false)}
        onChapterChanged={handleChapterChanged}
        onWorkspaceChanged={handleWorkspaceChanged}
      />
    </>
  )
}
