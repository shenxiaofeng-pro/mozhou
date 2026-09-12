import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { clearWorkspaceRoute, readWorkspaceRoute, writeWorkspaceRoute } from './workspaceRoute'

beforeEach(() => {
  window.history.replaceState({}, '', '/author')
})

afterEach(() => {
  window.history.replaceState({}, '', '/')
})

describe('workspace URL state', () => {
  it('round-trips project, writing stage and chapter', () => {
    writeWorkspaceRoute({
      projectId: 'project-1',
      view: 'writing',
      stage: 'candidate',
      chapterId: 'chapter-3',
    })

    expect(readWorkspaceRoute()).toEqual({
      projectId: 'project-1',
      view: 'writing',
      stage: 'candidate',
      chapterId: 'chapter-3',
    })
  })

  it('ignores unsupported view and stage values', () => {
    window.history.replaceState({}, '', '/?project=p1&view=admin&stage=unknown&chapter=c1')
    expect(readWorkspaceRoute()).toEqual({
      projectId: 'p1',
      view: null,
      stage: null,
      chapterId: 'c1',
    })
  })

  it('removes workspace parameters without replacing unrelated URL state', () => {
    window.history.replaceState({}, '', '/?theme=paper&project=p1&view=writing&stage=plan&chapter=c1')
    clearWorkspaceRoute()
    expect(window.location.search).toBe('?theme=paper')
  })
})
