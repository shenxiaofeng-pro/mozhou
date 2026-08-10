import type {
  ChapterSummary,
  DirectoryDeleteImpact,
  DirectoryNodeKind,
  ManuscriptScene,
  ManuscriptVolume,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { useEffect, useRef, useState } from 'react'

import { api } from '../api'

interface ManuscriptDirectoryDialogProps {
  workspace: WorkspaceSummary
  activeChapterId: string
  onClose: () => void
  onCommit: (action: () => Promise<WorkspaceSummary>) => Promise<void>
}

interface EditableNodeProps {
  kind: DirectoryNodeKind
  node: ManuscriptVolume | ChapterSummary | ManuscriptScene
  onRename: (title: string, summary?: string) => Promise<void>
}

function EditableNode({ kind, node, onRename }: EditableNodeProps) {
  const [title, setTitle] = useState(node.title)
  const [summary, setSummary] = useState(kind === 'scene' ? (node as ManuscriptScene).summary : '')
  const changed = title.trim() !== node.title
    || (kind === 'scene' && summary.trim() !== (node as ManuscriptScene).summary)
  return (
    <div className="directory-node-editor">
      <input aria-label={`${node.title}标题`} value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} />
      {kind === 'scene' ? <input aria-label={`${node.title}摘要`} value={summary} maxLength={2000} placeholder="场景目标或转折" onChange={(event) => setSummary(event.target.value)} /> : null}
      <button type="button" disabled={!changed || !title.trim()} onClick={() => { void onRename(title.trim(), summary.trim()) }}>保存名称</button>
    </div>
  )
}

export function ManuscriptDirectoryDialog({
  workspace,
  activeChapterId,
  onClose,
  onCommit,
}: ManuscriptDirectoryDialogProps) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const [isBusy, setIsBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [newKind, setNewKind] = useState<DirectoryNodeKind | null>(null)
  const [newParentId, setNewParentId] = useState<string | null>(null)
  const [newTitle, setNewTitle] = useState('')
  const [deleteImpact, setDeleteImpact] = useState<DirectoryDeleteImpact | null>(null)

  useEffect(() => {
    closeRef.current?.focus()
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !isBusy) onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [isBusy, onClose])

  async function run(action: () => Promise<WorkspaceSummary>, success: string) {
    setIsBusy(true)
    setError(null)
    setNotice(null)
    try {
      await onCommit(action)
      setNotice(success)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '目录操作失败')
    } finally {
      setIsBusy(false)
    }
  }

  function beginCreate(kind: DirectoryNodeKind, parentId: string | null = null) {
    setNewKind(kind)
    setNewParentId(parentId)
    setNewTitle(kind === 'volume' ? '新卷' : kind === 'chapter' ? '新章节' : '新场景')
  }

  async function createNode() {
    if (!newKind || !newTitle.trim()) return
    const kind = newKind
    await run(
      () => api.createDirectoryNode(workspace.project.id, {
        kind,
        title: newTitle.trim(),
        parent_id: newParentId,
      }),
      '目录节点已创建，可继续调整顺序。',
    )
    setNewKind(null)
    setNewParentId(null)
    setNewTitle('')
  }

  async function inspectDelete(kind: DirectoryNodeKind, nodeId: string) {
    setIsBusy(true)
    setError(null)
    try {
      setDeleteImpact(await api.getDirectoryDeleteImpact(kind, nodeId))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '无法读取删除影响')
    } finally {
      setIsBusy(false)
    }
  }

  function move(
    kind: DirectoryNodeKind,
    node: ManuscriptVolume | ChapterSummary | ManuscriptScene,
    parentId: string | null,
    siblings: Array<ManuscriptVolume | ChapterSummary | ManuscriptScene>,
    direction: -1 | 1,
  ) {
    const index = siblings.findIndex((item) => item.id === node.id)
    if (index < 0 || index + direction < 0 || index + direction >= siblings.length) return
    const beforeId = direction < 0 ? siblings[index - 1].id : siblings[index + 2]?.id ?? null
    void run(
      () => api.moveDirectoryNode(kind, node.id, {
        parent_id: parentId,
        before_id: beforeId,
        expected_revision: node.revision,
      }),
      '目录顺序已更新。',
    )
  }

  const volumes = workspace.manuscript_volumes ?? []
  const scenes = workspace.manuscript_scenes ?? []
  const referenceTotal = deleteImpact
    ? Object.values(deleteImpact.references).reduce((sum, count) => sum + count, 0)
    : 0

  return (
    <div className="directory-dialog-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !isBusy) onClose()
    }}>
      <section className="directory-dialog" role="dialog" aria-modal="true" aria-labelledby="directory-dialog-title">
        <header>
          <div><p>STORY TREE / 稳定目录</p><h2 id="directory-dialog-title">管理卷、章与场景</h2><span>移动不会改变节点标识；删除先展示影响，并可撤销最近一步。</span></div>
          <button ref={closeRef} type="button" aria-label="关闭目录管理" disabled={isBusy} onClick={onClose}>×</button>
        </header>
        <div className="directory-toolbar">
          <button type="button" disabled={isBusy} onClick={() => beginCreate('volume')}>＋ 新建卷</button>
          <button type="button" disabled={isBusy} onClick={() => { void run(() => api.undoDirectoryEvent(workspace.project.id), '最近一次目录操作已撤销。') }}>撤销上一步</button>
          {notice ? <span role="status">{notice}</span> : null}
        </div>
        {error ? <p className="directory-error" role="alert">{error}</p> : null}
        <div className="directory-tree-manager">
          {volumes.map((volume, volumeIndex) => {
            const chapters = workspace.chapters.filter((chapter) => chapter.volume_id === volume.id)
            return (
              <section className="directory-volume" key={volume.id}>
                <header>
                  <strong>卷 {volumeIndex + 1}</strong>
                  <EditableNode key={`${volume.id}:${volume.revision}`} kind="volume" node={volume} onRename={(title) => run(
                    () => api.renameDirectoryNode('volume', volume.id, { title, expected_revision: volume.revision }),
                    '卷名已更新。',
                  )} />
                  <div>
                    <button type="button" aria-label={`${volume.title}上移`} disabled={volumeIndex === 0 || isBusy} onClick={() => move('volume', volume, null, volumes, -1)}>↑</button>
                    <button type="button" aria-label={`${volume.title}下移`} disabled={volumeIndex === volumes.length - 1 || isBusy} onClick={() => move('volume', volume, null, volumes, 1)}>↓</button>
                    <button type="button" disabled={isBusy} onClick={() => beginCreate('chapter', volume.id)}>＋章</button>
                    <button type="button" disabled={isBusy} onClick={() => { void inspectDelete('volume', volume.id) }}>删除</button>
                  </div>
                </header>
                <ol>
                  {chapters.map((chapter, chapterIndex) => {
                    const chapterScenes = scenes.filter((scene) => scene.chapter_id === chapter.id)
                    return (
                      <li key={chapter.id}>
                        <div className="directory-chapter-row">
                          <span>{String(chapter.chapter_number).padStart(2, '0')}</span>
                          <EditableNode key={`${chapter.id}:${chapter.revision}`} kind="chapter" node={chapter} onRename={(title) => run(
                            () => api.renameDirectoryNode('chapter', chapter.id, { title, expected_revision: chapter.revision }),
                            '章名已更新。',
                          )} />
                          <select aria-label={`移动${chapter.title}到卷`} value={volume.id} disabled={isBusy} onChange={(event) => { void run(
                            () => api.moveDirectoryNode('chapter', chapter.id, {
                              parent_id: event.target.value,
                              before_id: null,
                              expected_revision: chapter.revision,
                            }),
                            '章节已移入目标卷。',
                          ) }}>
                            {volumes.map((target) => <option value={target.id} key={target.id}>{target.title}</option>)}
                          </select>
                          <div>
                            <button type="button" aria-label={`${chapter.title}上移`} disabled={chapterIndex === 0 || isBusy} onClick={() => move('chapter', chapter, volume.id, chapters, -1)}>↑</button>
                            <button type="button" aria-label={`${chapter.title}下移`} disabled={chapterIndex === chapters.length - 1 || isBusy} onClick={() => move('chapter', chapter, volume.id, chapters, 1)}>↓</button>
                            <button type="button" disabled={isBusy} onClick={() => beginCreate('scene', chapter.id)}>＋场景</button>
                            <button type="button" disabled={isBusy || chapter.id === activeChapterId} title={chapter.id === activeChapterId ? '请先切换到其他章节' : undefined} onClick={() => { void inspectDelete('chapter', chapter.id) }}>删除</button>
                          </div>
                        </div>
                        {chapterScenes.length ? <ol className="directory-scenes">
                          {chapterScenes.map((scene, sceneIndex) => (
                            <li key={scene.id}>
                              <span>场景 {sceneIndex + 1}</span>
                              <EditableNode key={`${scene.id}:${scene.revision}`} kind="scene" node={scene} onRename={(title, summary) => run(
                                () => api.renameDirectoryNode('scene', scene.id, { title, summary, expected_revision: scene.revision }),
                                '场景已更新。',
                              )} />
                              <div>
                                <button type="button" aria-label={`${scene.title}上移`} disabled={sceneIndex === 0 || isBusy} onClick={() => move('scene', scene, chapter.id, chapterScenes, -1)}>↑</button>
                                <button type="button" aria-label={`${scene.title}下移`} disabled={sceneIndex === chapterScenes.length - 1 || isBusy} onClick={() => move('scene', scene, chapter.id, chapterScenes, 1)}>↓</button>
                                <button type="button" disabled={isBusy} onClick={() => { void inspectDelete('scene', scene.id) }}>删除</button>
                              </div>
                            </li>
                          ))}
                        </ol> : null}
                      </li>
                    )
                  })}
                </ol>
              </section>
            )
          })}
        </div>
        {newKind ? (
          <form className="directory-create-bar" onSubmit={(event) => { event.preventDefault(); void createNode() }}>
            <label><span>新{newKind === 'volume' ? '卷' : newKind === 'chapter' ? '章节' : '场景'}名称</span><input autoFocus value={newTitle} maxLength={120} onChange={(event) => setNewTitle(event.target.value)} /></label>
            <button type="submit" disabled={!newTitle.trim() || isBusy}>创建</button>
            <button type="button" disabled={isBusy} onClick={() => setNewKind(null)}>取消</button>
          </form>
        ) : null}
        {deleteImpact ? (
          <section className="directory-delete-impact" role="alertdialog" aria-labelledby="directory-delete-title">
            <h3 id="directory-delete-title">确认删除“{deleteImpact.title}”</h3>
            <p>{deleteImpact.descendant_chapters} 章、{deleteImpact.descendant_scenes} 个场景会从目录隐藏；{referenceTotal} 条关联记录保留，可通过撤销恢复。</p>
            {Object.keys(deleteImpact.references).length ? <ul>{Object.entries(deleteImpact.references).map(([label, count]) => <li key={label}>{label}：{count}</li>)}</ul> : null}
            {deleteImpact.reason ? <p>{deleteImpact.reason}</p> : null}
            <button type="button" disabled={!deleteImpact.can_delete || isBusy} onClick={() => {
              const node = deleteImpact.node_kind === 'volume'
                ? volumes.find((item) => item.id === deleteImpact.node_id)
                : deleteImpact.node_kind === 'chapter'
                  ? workspace.chapters.find((item) => item.id === deleteImpact.node_id)
                  : scenes.find((item) => item.id === deleteImpact.node_id)
              if (!node) return
              void run(
                () => api.deleteDirectoryNode(deleteImpact.node_kind, deleteImpact.node_id, {
                  expected_revision: node.revision,
                  confirm_impact: true,
                }),
                '目录节点已删除，可用“撤销上一步”恢复。',
              ).then(() => setDeleteImpact(null))
            }}>确认删除</button>
            <button type="button" disabled={isBusy} onClick={() => setDeleteImpact(null)}>保留</button>
          </section>
        ) : null}
        <footer><button type="button" disabled={isBusy} onClick={onClose}>完成</button></footer>
      </section>
    </div>
  )
}
