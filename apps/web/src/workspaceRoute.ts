import type { AuthorWorkflowStage } from '@mozhou/contracts'

export type WorkspaceView =
  | 'topic-decision'
  | 'writing'
  | 'reference-library'
  | 'writing-patterns'
  | 'research'
  | 'comic-drama'

export interface WorkspaceRoute {
  projectId: string | null
  view: WorkspaceView | null
  stage: AuthorWorkflowStage | null
  chapterId: string | null
}

const WORKSPACE_VIEWS = new Set<WorkspaceView>([
  'topic-decision',
  'writing',
  'reference-library',
  'writing-patterns',
  'research',
  'comic-drama',
])

const AUTHOR_STAGES = new Set<AuthorWorkflowStage>([
  'topic',
  'book',
  'plan',
  'candidate',
  'review',
  'feedback',
  'complete',
])

export function readWorkspaceRoute(location: Pick<Location, 'href'> = window.location): WorkspaceRoute {
  const anchor = document.createElement('a')
  anchor.href = location.href
  const params = new URLSearchParams(anchor.search)
  const view = params.get('view')
  const stage = params.get('stage')
  return {
    projectId: cleanParam(params.get('project')),
    view: view && WORKSPACE_VIEWS.has(view as WorkspaceView) ? view as WorkspaceView : null,
    stage: stage && AUTHOR_STAGES.has(stage as AuthorWorkflowStage) ? stage as AuthorWorkflowStage : null,
    chapterId: cleanParam(params.get('chapter')),
  }
}

export function writeWorkspaceRoute(
  route: WorkspaceRoute,
  mode: 'push' | 'replace' = 'push',
): void {
  const params = new URLSearchParams(window.location.search)
  setParam(params, 'project', route.projectId)
  setParam(params, 'view', route.view)
  setParam(params, 'stage', route.stage)
  setParam(params, 'chapter', route.chapterId)
  const search = params.toString()
  const url = `${window.location.pathname}${search ? `?${search}` : ''}${window.location.hash}`
  const state = { mozhouWorkspaceRoute: true }
  if (mode === 'replace') window.history.replaceState(state, '', url)
  else window.history.pushState(state, '', url)
}

export function clearWorkspaceRoute(mode: 'push' | 'replace' = 'push'): void {
  writeWorkspaceRoute({ projectId: null, view: null, stage: null, chapterId: null }, mode)
}

function cleanParam(value: string | null): string | null {
  const cleaned = value?.trim() ?? ''
  return cleaned.length > 0 ? cleaned : null
}

function setParam(params: URLSearchParams, key: string, value: string | null): void {
  if (value) params.set(key, value)
  else params.delete(key)
}
