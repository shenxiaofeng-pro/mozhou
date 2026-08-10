import type { SerialDashboard, WorkspaceSearchResult } from '@mozhou/contracts'
import { useEffect, useRef, useState } from 'react'

import { api } from '../api'

interface SerialWorkspaceDialogProps {
  projectId: string
  initialMode: 'dashboard' | 'search'
  onClose: () => void
  onOpenChapter: (chapterId: string) => Promise<void>
}

const searchKindLabels: Record<WorkspaceSearchResult['kind'], string> = {
  project: '作品',
  chapter: '章节',
  character: '人物',
  resource: '资源',
  thread: '伏笔',
}

export function SerialWorkspaceDialog({
  projectId,
  initialMode,
  onClose,
  onOpenChapter,
}: SerialWorkspaceDialogProps) {
  const searchRef = useRef<HTMLInputElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const [mode, setMode] = useState(initialMode)
  const [dashboard, setDashboard] = useState<SerialDashboard | null>(null)
  const [target, setTarget] = useState(0)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<WorkspaceSearchResult[]>([])
  const [isBusy, setIsBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    api.getSerialDashboard(projectId).then((next) => {
      if (!active) return
      setDashboard(next)
      setTarget(next.goal.target_characters)
    }).catch((failure: unknown) => {
      if (active) setError(failure instanceof Error ? failure.message : '连载看板读取失败')
    }).finally(() => {
      if (active) setIsBusy(false)
    })
    return () => { active = false }
  }, [projectId])

  useEffect(() => {
    if (mode === 'search') searchRef.current?.focus()
    else closeRef.current?.focus()
  }, [mode])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  async function saveGoal() {
    if (!dashboard) return
    setIsBusy(true)
    setError(null)
    try {
      const next = await api.setSerialDailyGoal(
        projectId,
        dashboard.goal.goal_date,
        target,
        dashboard.goal.revision,
      )
      setDashboard(next)
      setTarget(next.goal.target_characters)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '日更目标保存失败')
    } finally {
      setIsBusy(false)
    }
  }

  async function search() {
    if (!query.trim()) {
      setResults([])
      return
    }
    setIsBusy(true)
    setError(null)
    try {
      setResults(await api.searchWorkspace(projectId, query.trim()))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '搜索失败')
    } finally {
      setIsBusy(false)
    }
  }

  const progress = dashboard && dashboard.goal.target_characters > 0
    ? Math.min(100, Math.round(dashboard.goal.actual_characters / dashboard.goal.target_characters * 100))
    : 0

  return (
    <div className="serial-dialog-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !isBusy) onClose()
    }}>
      <section className="serial-dialog" role="dialog" aria-modal="true" aria-labelledby="serial-dialog-title">
        <header>
          <div><p>SERIAL DESK / 连载驾驶舱</p><h2 id="serial-dialog-title">今天写多少，下一章到哪里</h2></div>
          <button ref={closeRef} type="button" aria-label="关闭连载工作台" onClick={onClose}>×</button>
        </header>
        <nav aria-label="连载工作台页面">
          <button type="button" aria-current={mode === 'dashboard' ? 'page' : undefined} onClick={() => setMode('dashboard')}>日更看板</button>
          <button type="button" aria-current={mode === 'search' ? 'page' : undefined} onClick={() => setMode('search')}>全局搜索 <kbd>⌘K</kbd></button>
        </nav>
        {error ? <p className="serial-dialog-error" role="alert">{error}</p> : null}
        {mode === 'dashboard' ? (
          <div className="serial-dashboard">
            {dashboard ? (
              <>
                <section className="serial-today">
                  <div><span>{dashboard.goal.goal_date}</span><strong>{dashboard.goal.actual_characters.toLocaleString('zh-CN')} / {dashboard.goal.target_characters.toLocaleString('zh-CN')}</strong><small>今日新增字符</small></div>
                  <div className="serial-progress" aria-label={`今日日更完成 ${progress}%`}><span style={{ width: `${progress}%` }} /></div>
                  <label><span>今日目标</span><input type="number" min="0" max="100000" step="100" value={target} onChange={(event) => setTarget(Number(event.target.value))} /></label>
                  <button type="button" disabled={isBusy || target === dashboard.goal.target_characters} onClick={() => { void saveGoal() }}>保存目标</button>
                </section>
                <dl className="serial-metrics">
                  <div><dt>全书正文</dt><dd>{dashboard.total_characters.toLocaleString('zh-CN')}</dd><small>{dashboard.chapter_count} 章</small></div>
                  <div><dt>存稿</dt><dd>{dashboard.stockpile_chapters}</dd><small>有正文的章节</small></div>
                  <div><dt>待审校</dt><dd>{dashboard.pending_review_chapters}</dd><small>草稿状态</small></div>
                  <div><dt>审校中</dt><dd>{dashboard.reviewing_chapters}</dd><small>等待定稿</small></div>
                  <div><dt>已定稿</dt><dd>{dashboard.approved_chapters}</dd><small>锁定正文</small></div>
                  <div><dt>可发布</dt><dd>{dashboard.ready_to_publish_chapters}</dd><small>已通过批准门</small></div>
                </dl>
              </>
            ) : <p role="status">正在汇总连载状态…</p>}
          </div>
        ) : (
          <div className="workspace-search">
            <form role="search" onSubmit={(event) => { event.preventDefault(); void search() }}>
              <label htmlFor="workspace-search-input">搜索章节正文、人物、资源与伏笔</label>
              <div><input ref={searchRef} id="workspace-search-input" value={query} maxLength={100} placeholder="例如：竹海订单" onChange={(event) => setQuery(event.target.value)} /><button type="submit" disabled={!query.trim() || isBusy}>{isBusy ? '搜索中…' : '搜索'}</button></div>
            </form>
            {results.length ? <ul aria-label="搜索结果">{results.map((result) => (
              <li key={`${result.kind}:${result.id}`}>
                <span>{searchKindLabels[result.kind]}</span><strong>{result.title}</strong><p>{result.snippet}</p>
                {result.chapter_id ? <button type="button" onClick={() => { void onOpenChapter(result.chapter_id!).then(onClose) }}>打开章节</button> : null}
              </li>
            ))}</ul> : query && !isBusy ? <p>没有匹配结果。</p> : <p>结果片段最多 160 字，不会一次载入整本正文。</p>}
          </div>
        )}
      </section>
    </div>
  )
}
