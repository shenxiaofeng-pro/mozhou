import type { Chapter, Project, Workspace } from '@mozhou/contracts'
import { useCallback, useEffect, useState } from 'react'

import { api } from './api'
import { CreateProjectForm } from './components/CreateProjectForm'
import { ProjectLibraryPage } from './components/ProjectLibraryPage'
import { ReferenceLibraryPage } from './components/ReferenceLibraryPage'
import { WorkspaceShell } from './components/WorkspaceShell'
import { clearActiveProjectId, loadActiveProjectId, saveActiveProjectId } from './storage'

export function App() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [projects, setProjects] = useState<Project[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [openingProjectId, setOpeningProjectId] = useState<string | null>(null)
  const [isCreatingProject, setIsCreatingProject] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [libraryNotice, setLibraryNotice] = useState<string | null>(null)
  const [activeView, setActiveView] = useState<'writing' | 'reference-library'>('writing')

  useEffect(() => {
    const projectId = loadActiveProjectId()
    let active = true

    const projectsRequest = api.listProjects()
    const workspaceRequest = projectId ? api.getProject(projectId) : Promise.resolve(null)

    Promise.allSettled([projectsRequest, workspaceRequest]).then(([projectResult, workspaceResult]) => {
      if (!active) return
      if (projectResult.status === 'fulfilled') {
        setProjects(projectResult.value)
      } else {
        setLoadError(projectResult.reason instanceof Error ? projectResult.reason.message : '无法读取作品书架')
      }
      if (workspaceResult.status === 'fulfilled') {
        setWorkspace(workspaceResult.value)
      } else {
        clearActiveProjectId()
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
    setWorkspace(created)
    setLoadError(null)
    setLibraryNotice(null)
    setIsCreatingProject(false)
    setActiveView('writing')
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
      const loaded = await api.getProject(projectId)
      saveActiveProjectId(projectId)
      setWorkspace(loaded)
      setLibraryNotice(null)
      setProjects((current) => [
        loaded.project,
        ...current.filter((project) => project.id !== projectId),
      ])
      setActiveView('writing')
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : '无法打开作品')
    } finally {
      setOpeningProjectId(null)
    }
  }, [])

  const handleChapterChanged = useCallback((saved: Chapter) => {
    setWorkspace((current) => current ? {
      ...current,
      project: { ...current.project, updated_at: saved.updated_at },
      chapters: current.chapters.some((chapter) => chapter.id === saved.id)
        ? current.chapters.map((chapter) => chapter.id === saved.id ? saved : chapter)
        : [...current.chapters, saved].sort((left, right) => left.chapter_number - right.chapter_number),
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
    setIsCreatingProject(false)
    setActiveView('writing')
  }, [])

  const handleWorkspaceChanged = useCallback((updated: Workspace) => {
    setWorkspace(updated)
  }, [])

  if (isLoading) {
    return (
      <main className="loading-shell" aria-live="polite">
        <div className="brand-mark" aria-hidden="true">墨</div>
        <p>正在展开上次的稿纸…</p>
      </main>
    )
  }

  if (!workspace) {
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

  if (activeView === 'reference-library') {
    return (
      <ReferenceLibraryPage
        workspace={workspace}
        onWorkspaceChanged={handleWorkspaceChanged}
        onBack={() => setActiveView('writing')}
      />
    )
  }

  return (
    <WorkspaceShell
      workspace={workspace}
      onChapterChanged={handleChapterChanged}
      onWorkspaceChanged={handleWorkspaceChanged}
      onOpenReferenceLibrary={() => setActiveView('reference-library')}
      onClose={handleClose}
    />
  )
}
