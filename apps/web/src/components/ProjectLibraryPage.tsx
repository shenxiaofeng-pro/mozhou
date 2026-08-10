import type { Project, RecoveryPointSummary, Workspace } from '@mozhou/contracts'
import { type ChangeEvent, useState } from 'react'

import { api } from '../api'
import { BetaEvaluationDialog } from './BetaEvaluationDialog'
import { ManuscriptImportDialog } from './ManuscriptImportDialog'
import { NarrativeSandboxDialog } from './NarrativeSandboxDialog'
import { SystemDiagnosticsDialog } from './SystemDiagnosticsDialog'

interface ProjectLibraryPageProps {
  projects: Project[]
  openingProjectId: string | null
  error: string | null
  onOpen: (projectId: string) => void
  onCreate: () => void
  onOpenGlobalLibrary: () => void
  onProjectAdded: (workspace: Workspace) => void
  initialNotice?: string | null
}

const maxArchiveBytes = 256 * 1024 * 1024
const unsafeFilenameCharacters = '\\/:*?"<>|'

function safeArchiveFilename(title: string) {
  return Array.from(title, (character) =>
    character.charCodeAt(0) < 32 || unsafeFilenameCharacters.includes(character) ? '_' : character,
  ).join('')
}

const updatedAtFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
})

const genreLabels = {
  historical_rebirth: '历史重生',
  urban_rebirth: '都市重生',
} as const

export function ProjectLibraryPage({
  projects,
  openingProjectId,
  error,
  onOpen,
  onCreate,
  onOpenGlobalLibrary,
  onProjectAdded,
  initialNotice = null,
}: ProjectLibraryPageProps) {
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [operationError, setOperationError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(initialNotice)
  const [openRecoveryProjectId, setOpenRecoveryProjectId] = useState<string | null>(null)
  const [recoveryPoints, setRecoveryPoints] = useState<RecoveryPointSummary[]>([])
  const [recoveryLabel, setRecoveryLabel] = useState('')
  const [isManuscriptImportOpen, setIsManuscriptImportOpen] = useState(false)
  const [isDiagnosticsOpen, setIsDiagnosticsOpen] = useState(false)
  const [betaProject, setBetaProject] = useState<Project | null>(null)
  const [sandboxProject, setSandboxProject] = useState<Project | null>(null)

  const reportError = (failure: unknown, fallback: string) => {
    setOperationError(failure instanceof Error ? failure.message : fallback)
    setNotice(null)
  }

  const exportProject = async (project: Project, includeReferenceAssets = false) => {
    const action = `${includeReferenceAssets ? 'export-assets' : 'export'}:${project.id}`
    setBusyAction(action)
    setOperationError(null)
    setNotice(null)
    try {
      const archive = await api.exportProject(project.id, includeReferenceAssets)
      const blob = new Blob([JSON.stringify(archive, null, 2)], { type: 'application/json;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      const assetSuffix = includeReferenceAssets ? '-含资料原文' : ''
      anchor.download = `${safeArchiveFilename(project.title)}${assetSuffix}.mozhou.json`
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
      setNotice(
        includeReferenceAssets
          ? `《${project.title}》完整归档已导出，包含关联资料原文。`
          : `《${project.title}》归档已导出。`,
      )
      void api.recordBetaEvent(project.id, 'project_export').catch(() => undefined)
    } catch (failure) {
      reportError(failure, '归档导出失败')
    } finally {
      setBusyAction(null)
    }
  }

  const importArchive = async (event: ChangeEvent<HTMLInputElement>) => {
    const input = event.currentTarget
    const file = input.files?.[0]
    if (!file) return
    if (file.size > maxArchiveBytes) {
      setOperationError('项目归档不能超过 256 MiB')
      setNotice(null)
      input.value = ''
      return
    }
    setBusyAction('import')
    setOperationError(null)
    setNotice(null)
    try {
      const restored = await api.importProjectArchive(await file.text())
      onProjectAdded(restored)
      setNotice(`《${restored.project.title}》已恢复为新副本。`)
    } catch (failure) {
      reportError(failure, '项目归档导入失败')
    } finally {
      input.value = ''
      setBusyAction(null)
    }
  }

  const exportManuscript = async (project: Project) => {
    const action = `export-manuscript:${project.id}`
    setBusyAction(action)
    setOperationError(null)
    setNotice(null)
    try {
      const exported = await api.exportManuscript(project.id)
      const blob = new Blob([exported.content], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = exported.filename
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
      setNotice(`《${project.title}》正文已按 UTF-8 Markdown 导出。`)
      void api.recordBetaEvent(project.id, 'manuscript_export').catch(() => undefined)
    } catch (failure) {
      reportError(failure, '正文导出失败')
    } finally {
      setBusyAction(null)
    }
  }

  const toggleRecoveryPoints = async (project: Project) => {
    if (openRecoveryProjectId === project.id) {
      setOpenRecoveryProjectId(null)
      return
    }
    const action = `list:${project.id}`
    setOpenRecoveryProjectId(project.id)
    setRecoveryPoints([])
    setRecoveryLabel('')
    setBusyAction(action)
    setOperationError(null)
    try {
      setRecoveryPoints(await api.listRecoveryPoints(project.id))
    } catch (failure) {
      reportError(failure, '恢复点读取失败')
    } finally {
      setBusyAction(null)
    }
  }

  const createRecoveryPoint = async (project: Project) => {
    const label = recoveryLabel.trim()
    if (!label) return
    const action = `create-point:${project.id}`
    setBusyAction(action)
    setOperationError(null)
    setNotice(null)
    try {
      const created = await api.createRecoveryPoint(project.id, { label })
      setRecoveryPoints((current) => [created, ...current])
      setRecoveryLabel('')
      setNotice(`已为《${project.title}》创建恢复点。`)
    } catch (failure) {
      reportError(failure, '恢复点创建失败')
    } finally {
      setBusyAction(null)
    }
  }

  const restoreRecoveryPoint = async (point: RecoveryPointSummary) => {
    const action = `restore:${point.id}`
    setBusyAction(action)
    setOperationError(null)
    setNotice(null)
    try {
      const restored = await api.restoreRecoveryPoint(point.id)
      onProjectAdded(restored)
      setNotice(`《${restored.project.title}》已恢复为新副本。`)
      void api.recordBetaEvent(point.project_id, 'recovery_restore').catch(() => undefined)
    } catch (failure) {
      reportError(failure, '从恢复点创建副本失败')
    } finally {
      setBusyAction(null)
    }
  }

  return (
    <main className="project-library-page">
      <header className="project-library-header">
        <div className="project-library-brand">
          <span aria-hidden="true">墨</span>
          <div><strong>墨舟</strong><small>本地长篇创作工作台</small></div>
        </div>
        <div className="project-library-system-status">
          <p><i aria-hidden="true" />作品保存在这台设备上</p>
          <button type="button" onClick={() => setIsDiagnosticsOpen(true)}>系统诊断</button>
        </div>
      </header>

      <section className="project-library-hero" aria-labelledby="project-library-title">
        <div>
          <p>MANUSCRIPT DOCK / 作品书架</p>
          <h1 id="project-library-title">你的作品，都在这里</h1>
          <span>继续上次停下的章节，或者钉住一个新的重生时刻。</span>
        </div>
        <div className="project-library-hero-actions">
          <button type="button" onClick={onCreate}>新建一部作品</button>
          <button type="button" onClick={() => setIsManuscriptImportOpen(true)}>导入已有稿件</button>
          <button type="button" onClick={onOpenGlobalLibrary}>打开全局资料码头</button>
          <label className={busyAction === 'import' ? 'is-disabled' : undefined}>
            <input
              type="file"
              accept="application/json,.json,.mozhou.json"
              aria-label="导入墨舟项目归档"
              disabled={busyAction !== null}
              onChange={(event) => { void importArchive(event) }}
            />
            {busyAction === 'import' ? '正在校验归档…' : '导入作品副本'}
          </label>
        </div>
      </section>

      {error || operationError ? (
        <p className="project-library-error" role="alert">{operationError ?? error}</p>
      ) : null}
      {notice ? <p className="project-library-notice" role="status">{notice}</p> : null}

      <section className="project-shelf" aria-label="已有作品">
        {projects.map((project, index) => (
          <article className="project-volume" key={project.id}>
            <span className="project-volume-index" aria-hidden="true">
              {String(index + 1).padStart(2, '0')}
            </span>
            <div className="project-volume-copy">
              <p>{genreLabels[project.genre]} · {project.rebirth_year} · {project.rebirth_location}</p>
              <h2>{project.title}</h2>
              <dl>
                <div><dt>章节目标</dt><dd>{project.chapter_target_words.toLocaleString('zh-CN')} 字</dd></div>
                <div><dt>安全存稿</dt><dd>{project.safety_buffer_chapters} 章</dd></div>
                <div>
                  <dt>最近整理</dt>
                  <dd><time dateTime={project.updated_at}>{updatedAtFormatter.format(new Date(project.updated_at))}</time></dd>
                </div>
              </dl>
            </div>
            <div className="project-volume-actions">
              <button
                type="button"
                aria-label={`导出《${project.title}》Markdown 正文`}
                disabled={busyAction !== null}
                onClick={() => { void exportManuscript(project) }}
              >
                {busyAction === `export-manuscript:${project.id}` ? '正在排版…' : '导出正文'}
              </button>
              <button
                type="button"
                aria-label={`打开《${project.title}》`}
                disabled={openingProjectId !== null || busyAction !== null}
                onClick={() => onOpen(project.id)}
              >
                {openingProjectId === project.id ? '正在展开…' : '继续创作'}
              </button>
              <button
                type="button"
                aria-label={`导出《${project.title}》归档`}
                disabled={busyAction !== null}
                onClick={() => { void exportProject(project) }}
              >
                {busyAction === `export:${project.id}` ? '正在装订…' : '导出归档'}
              </button>
              <button
                type="button"
                aria-label={`导出《${project.title}》含资料原文的完整归档`}
                disabled={busyAction !== null}
                onClick={() => { void exportProject(project, true) }}
              >
                {busyAction === `export-assets:${project.id}` ? '正在收拢资料…' : '含资料归档'}
              </button>
              <button
                type="button"
                aria-expanded={openRecoveryProjectId === project.id}
                aria-label={`管理《${project.title}》恢复点`}
                disabled={busyAction !== null}
                onClick={() => { void toggleRecoveryPoints(project) }}
              >
                恢复点
              </button>
              <button
                type="button"
                aria-label={`查看《${project.title}》封测报告`}
                disabled={busyAction !== null}
                onClick={() => setBetaProject(project)}
              >
                封测报告
              </button>
              <button
                type="button"
                aria-label={`打开《${project.title}》剧情沙盘`}
                disabled={busyAction !== null}
                onClick={() => setSandboxProject(project)}
              >
                剧情沙盘
              </button>
            </div>
            {openRecoveryProjectId === project.id ? (
              <section className="project-recovery-drawer" aria-label={`《${project.title}》恢复点`}>
                <header>
                  <div>
                    <p>RECOVERY SEALS / 恢复封签</p>
                    <h3>改写之前，先留一份完整底稿</h3>
                  </div>
                  <span>恢复只会创建副本，不覆盖当前作品</span>
                </header>
                <div className="project-recovery-create">
                  <label>
                    <span>恢复点备注</span>
                    <input
                      aria-label={`《${project.title}》恢复点备注`}
                      maxLength={80}
                      value={recoveryLabel}
                      placeholder="例如：第二卷大改前"
                      onChange={(event) => setRecoveryLabel(event.target.value)}
                    />
                  </label>
                  <button
                    type="button"
                    disabled={!recoveryLabel.trim() || busyAction !== null}
                    onClick={() => { void createRecoveryPoint(project) }}
                  >
                    {busyAction === `create-point:${project.id}` ? '正在封存…' : '创建恢复点'}
                  </button>
                </div>
                {busyAction === `list:${project.id}` ? (
                  <p className="project-recovery-empty">正在读取恢复点…</p>
                ) : recoveryPoints.length === 0 ? (
                  <p className="project-recovery-empty">还没有恢复点。重大改写前，可以先封存一次。</p>
                ) : (
                  <ul className="project-recovery-list">
                    {recoveryPoints.map((point) => (
                      <li key={point.id}>
                        <div>
                          <strong>{point.label}</strong>
                          <span>
                            {updatedAtFormatter.format(new Date(point.created_at))}
                            {' · '}{Math.max(1, Math.round(point.compressed_bytes / 1024)).toLocaleString('zh-CN')} KiB
                          </span>
                        </div>
                        <button
                          type="button"
                          aria-label={`从“${point.label}”恢复为副本`}
                          disabled={busyAction !== null}
                          onClick={() => { void restoreRecoveryPoint(point) }}
                        >
                          {busyAction === `restore:${point.id}` ? '正在恢复…' : '恢复为副本'}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            ) : null}
          </article>
        ))}
      </section>
      {isManuscriptImportOpen ? (
        <ManuscriptImportDialog
          onClose={() => setIsManuscriptImportOpen(false)}
          onImported={(workspace) => {
            onProjectAdded(workspace)
            setNotice(`《${workspace.project.title}》已从稿件创建。`)
          }}
        />
      ) : null}
      {isDiagnosticsOpen ? (
        <SystemDiagnosticsDialog onClose={() => setIsDiagnosticsOpen(false)} />
      ) : null}
      {betaProject ? (
        <BetaEvaluationDialog project={betaProject} onClose={() => setBetaProject(null)} />
      ) : null}
      {sandboxProject ? (
        <NarrativeSandboxDialog project={sandboxProject} onClose={() => setSandboxProject(null)} />
      ) : null}
    </main>
  )
}
