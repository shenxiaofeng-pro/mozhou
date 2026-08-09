import type {
  Chapter,
  StoryEntity,
  StoryEntityFields,
  StoryEntityKind,
  StoryThread,
  StoryThreadStatus,
  Workspace,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { useState } from 'react'

import { api } from '../api'

interface StoryLedgerPanelProps {
  workspace: WorkspaceSummary
  chapter: Chapter
  onWorkspaceChanged: (workspace: Workspace | WorkspaceSummary) => void
}

const entityKindLabels = {
  character: '人物',
  resource: '资源',
} as const

const threadStatusLabels = {
  open: '待回收',
  resolved: '已回收',
  abandoned: '已放弃',
} as const

function StoryEntityRow({ entity, onSaved }: {
  entity: StoryEntity
  onSaved: (entity: StoryEntity) => void
}) {
  const [fields, setFields] = useState<StoryEntityFields>(() => ({
    name: entity.name,
    role: entity.role,
    goal: entity.goal,
    current_state: entity.current_state,
    relationship_notes: entity.relationship_notes,
  }))
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function updateField(field: keyof StoryEntityFields, value: string) {
    setFields((current) => ({ ...current, [field]: value }))
  }

  async function save() {
    if (!fields.name.trim()) return
    setIsSaving(true)
    setError(null)
    try {
      onSaved(await api.updateStoryEntity(entity.id, {
        ...fields,
        expected_revision: entity.revision,
      }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '账本更新失败')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <details className="entity-record">
      <summary>
        <span>{entityKindLabels[entity.kind]}</span>
        <strong>{entity.name}</strong>
        <small>{entity.current_state || '等待记录当前状态'}</small>
      </summary>
      <label>
        名称
        <input value={fields.name} maxLength={120} onChange={(event) => updateField('name', event.target.value)} />
      </label>
      <label>
        {entity.kind === 'character' ? '角色定位' : '资源类型'}
        <input value={fields.role} maxLength={300} onChange={(event) => updateField('role', event.target.value)} />
      </label>
      <label>
        {entity.kind === 'character' ? '核心欲望' : '用途与价值'}
        <textarea value={fields.goal} maxLength={500} rows={2} onChange={(event) => updateField('goal', event.target.value)} />
      </label>
      <label>
        {entity.kind === 'character' ? '当前状态' : '当前归属与数量'}
        <textarea value={fields.current_state} maxLength={1000} rows={2} onChange={(event) => updateField('current_state', event.target.value)} />
      </label>
      <label>
        关系与关联备注
        <textarea value={fields.relationship_notes} maxLength={1000} rows={2} onChange={(event) => updateField('relationship_notes', event.target.value)} />
      </label>
      <button type="button" onClick={save} disabled={isSaving || !fields.name.trim()}>
        {isSaving ? '正在更新…' : '更新账本'}
      </button>
      {error ? <p className="ledger-error" role="alert">{error}</p> : null}
    </details>
  )
}

function ThreadActions({ thread, chapter, onTransition }: {
  thread: StoryThread
  chapter: Chapter
  onTransition: (thread: StoryThread, target: StoryThreadStatus, resolvedChapterId?: string) => void
}) {
  if (thread.status !== 'open') {
    return <button type="button" onClick={() => onTransition(thread, 'open')}>重新打开</button>
  }
  return (
    <>
      <button type="button" onClick={() => onTransition(thread, 'abandoned')}>放弃线索</button>
      <button type="button" onClick={() => onTransition(thread, 'resolved', chapter.id)}>在本章回收</button>
    </>
  )
}

export function StoryLedgerPanel({
  workspace,
  chapter,
  onWorkspaceChanged,
}: StoryLedgerPanelProps) {
  const [entityKind, setEntityKind] = useState<StoryEntityKind>('character')
  const [entityFields, setEntityFields] = useState<StoryEntityFields>({
    name: '',
    role: '',
    goal: '',
    current_state: '',
    relationship_notes: '',
  })
  const [threadTitle, setThreadTitle] = useState('')
  const [threadSummary, setThreadSummary] = useState('')
  const [isCreatingEntity, setIsCreatingEntity] = useState(false)
  const [isCreatingThread, setIsCreatingThread] = useState(false)
  const [processingThreadId, setProcessingThreadId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const openThreadCount = workspace.story_threads.filter((thread) => thread.status === 'open').length

  function updateEntityField(field: keyof StoryEntityFields, value: string) {
    setEntityFields((current) => ({ ...current, [field]: value }))
  }

  function replaceEntity(updated: StoryEntity) {
    onWorkspaceChanged({
      ...workspace,
      story_entities: workspace.story_entities.map((entity) => entity.id === updated.id ? updated : entity),
    })
  }

  async function createEntity() {
    if (!entityFields.name.trim()) return
    setIsCreatingEntity(true)
    setError(null)
    try {
      const created = await api.createStoryEntity(workspace.project.id, {
        kind: entityKind,
        ...entityFields,
      })
      onWorkspaceChanged({
        ...workspace,
        story_entities: [...workspace.story_entities, created],
      })
      setEntityFields({ name: '', role: '', goal: '', current_state: '', relationship_notes: '' })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '人物或资源创建失败')
    } finally {
      setIsCreatingEntity(false)
    }
  }

  async function createThread() {
    if (!threadTitle.trim()) return
    setIsCreatingThread(true)
    setError(null)
    try {
      const created = await api.createStoryThread(workspace.project.id, {
        title: threadTitle,
        summary: threadSummary,
        planted_chapter_number: chapter.chapter_number,
      })
      onWorkspaceChanged({
        ...workspace,
        story_threads: [...workspace.story_threads, created],
      })
      setThreadTitle('')
      setThreadSummary('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '伏笔创建失败')
    } finally {
      setIsCreatingThread(false)
    }
  }

  async function transitionThread(
    thread: StoryThread,
    target: StoryThreadStatus,
    resolvedChapterId?: string,
  ) {
    setProcessingThreadId(thread.id)
    setError(null)
    try {
      const updated = await api.transitionStoryThread(thread.id, {
        target_status: target,
        resolved_chapter_id: resolvedChapterId,
        expected_revision: thread.revision,
      })
      onWorkspaceChanged({
        ...workspace,
        story_threads: workspace.story_threads.map((item) => item.id === updated.id ? updated : item),
      })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '伏笔状态更新失败')
    } finally {
      setProcessingThreadId(null)
    }
  }

  return (
    <section className="story-ledger-card" aria-labelledby="story-ledger-title">
      <div className="pulse-heading">
        <h3 id="story-ledger-title">人物·资源·伏笔</h3>
        <span>{workspace.story_entities.length} 项 · {openThreadCount} 条未收</span>
      </div>

      <details className="ledger-drawer">
        <summary>人物与资源账本</summary>
        <div className="entity-records">
          {workspace.story_entities.map((entity) => (
            <StoryEntityRow
              key={`${entity.id}:${entity.revision}`}
              entity={entity}
              onSaved={replaceEntity}
            />
          ))}
          {workspace.story_entities.length === 0 ? <p>先记录主角或本卷最关键的资源。</p> : null}
        </div>
        <div className="ledger-create-form">
          <div className="ledger-kind-switch" aria-label="账本类型">
            <button type="button" data-active={entityKind === 'character'} onClick={() => setEntityKind('character')}>人物</button>
            <button type="button" data-active={entityKind === 'resource'} onClick={() => setEntityKind('resource')}>资源</button>
          </div>
          <label>
            名称
            <input aria-label="人物或资源名称" value={entityFields.name} maxLength={120} onChange={(event) => updateEntityField('name', event.target.value)} />
          </label>
          <label>
            {entityKind === 'character' ? '角色定位' : '资源类型'}
            <input aria-label="人物或资源定位" value={entityFields.role} maxLength={300} onChange={(event) => updateEntityField('role', event.target.value)} />
          </label>
          <label>
            {entityKind === 'character' ? '核心欲望' : '用途与价值'}
            <textarea aria-label="人物欲望或资源用途" value={entityFields.goal} maxLength={500} rows={2} onChange={(event) => updateEntityField('goal', event.target.value)} />
          </label>
          <label>
            当前状态
            <textarea aria-label="人物或资源当前状态" value={entityFields.current_state} maxLength={1000} rows={2} onChange={(event) => updateEntityField('current_state', event.target.value)} />
          </label>
          <label>
            关系与关联
            <textarea aria-label="人物或资源关系备注" value={entityFields.relationship_notes} maxLength={1000} rows={2} onChange={(event) => updateEntityField('relationship_notes', event.target.value)} />
          </label>
          <button type="button" onClick={createEntity} disabled={isCreatingEntity || !entityFields.name.trim()}>
            {isCreatingEntity ? '正在写入…' : `添加${entityKindLabels[entityKind]}`}
          </button>
        </div>
      </details>

      <details className="ledger-drawer" open={openThreadCount > 0}>
        <summary>伏笔账本</summary>
        <ol className="thread-records">
          {workspace.story_threads.map((thread) => (
            <li key={thread.id} data-status={thread.status}>
              <div><strong>{thread.title}</strong><span>{threadStatusLabels[thread.status]}</span></div>
              {thread.summary ? <p>{thread.summary}</p> : null}
              <small>{thread.planted_chapter_number ? `第 ${thread.planted_chapter_number} 章埋设` : '手动线索'}</small>
              <div className="thread-actions">
                <ThreadActions thread={thread} chapter={chapter} onTransition={transitionThread} />
              </div>
              {processingThreadId === thread.id ? <em>正在更新…</em> : null}
            </li>
          ))}
        </ol>
        <div className="ledger-create-form">
          <label>
            新伏笔
            <input aria-label="新伏笔标题" value={threadTitle} maxLength={300} onChange={(event) => setThreadTitle(event.target.value)} />
          </label>
          <label>
            计划与备注
            <textarea aria-label="新伏笔备注" value={threadSummary} maxLength={1000} rows={2} onChange={(event) => setThreadSummary(event.target.value)} />
          </label>
          <button type="button" onClick={createThread} disabled={isCreatingThread || !threadTitle.trim()}>
            {isCreatingThread ? '正在写入…' : '在本章埋设伏笔'}
          </button>
        </div>
      </details>
      {error ? <p className="ledger-error" role="alert">{error}</p> : null}
    </section>
  )
}
