import type { CreateProjectInput, Genre, Workspace } from '@mozhou/contracts'
import { useState, type ChangeEvent, type FormEvent } from 'react'

import { api } from '../api'
import { ManuscriptImportDialog } from './ManuscriptImportDialog'

interface CreateProjectFormProps {
  onCreated: (workspace: Workspace) => void
  onImported?: (workspace: Workspace) => void
  onCancel?: () => void
}

const maxArchiveBytes = 256 * 1024 * 1024

const genreLabels: Record<Genre, string> = {
  historical_rebirth: '历史重生',
  urban_rebirth: '都市重生',
}

export function CreateProjectForm({ onCreated, onImported, onCancel }: CreateProjectFormProps) {
  const [genre, setGenre] = useState<Genre>('urban_rebirth')
  const [isCreating, setIsCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isImporting, setIsImporting] = useState(false)
  const [isManuscriptImportOpen, setIsManuscriptImportOpen] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const input: CreateProjectInput = {
      title: String(form.get('title') ?? ''),
      genre,
      rebirth_year: Number(form.get('rebirthYear')),
      rebirth_location: String(form.get('rebirthLocation') ?? ''),
      chapter_target_words: Number(form.get('chapterTargetWords')),
      safety_buffer_chapters: Number(form.get('safetyBufferChapters')),
    }
    setIsCreating(true)
    setError(null)
    try {
      onCreated(await api.createProject(input))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '项目创建失败')
    } finally {
      setIsCreating(false)
    }
  }

  async function handleArchiveImport(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget
    const file = input.files?.[0]
    if (!file || !onImported) return
    if (file.size > maxArchiveBytes) {
      setError('项目归档不能超过 256 MiB')
      input.value = ''
      return
    }
    setIsImporting(true)
    setError(null)
    try {
      onImported(await api.importProjectArchive(await file.text()))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '项目归档导入失败')
    } finally {
      input.value = ''
      setIsImporting(false)
    }
  }

  return (
    <main className="onboarding-shell">
      <section className="onboarding-intro" aria-labelledby="welcome-title">
        <div className="brand-mark" aria-hidden="true">
          墨
        </div>
        <p className="eyebrow">本地长篇创作工作台</p>
        <h1 id="welcome-title">把一部长篇，稳稳写下去。</h1>
        <p className="welcome-copy">
          从重生分歧点到下一章悬念，墨舟会保存故事状态，也把最终决定留给作者。
        </p>
        <ol className="onboarding-promise" aria-label="创作流程">
          <li>定位故事</li>
          <li>写完本章</li>
          <li>回灌事实</li>
        </ol>
      </section>

      <form className="project-form" onSubmit={handleSubmit}>
        <header>
          <div>
            <p className="section-kicker">新建作品</p>
            {onCancel ? <button type="button" className="project-form-back" onClick={onCancel}>返回作品书架</button> : null}
          </div>
          <h2>先钉住重生的那一刻</h2>
        </header>

        <label>
          作品名
          <input name="title" maxLength={120} required placeholder="例如：回到九八年的南平" />
        </label>

        <fieldset>
          <legend>首发题材</legend>
          <div className="genre-grid">
            {(Object.keys(genreLabels) as Genre[]).map((value) => (
              <label className="genre-option" key={value} data-selected={genre === value}>
                <input
                  type="radio"
                  name="genre"
                  value={value}
                  checked={genre === value}
                  onChange={() => setGenre(value)}
                />
                <span>{genreLabels[value]}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="form-row">
          <label>
            重生年份
            <input name="rebirthYear" type="number" min="-3000" max="2030" defaultValue="1998" required />
          </label>
          <label>
            重生地点
            <input name="rebirthLocation" maxLength={100} defaultValue="福建南平" required />
          </label>
        </div>

        <div className="form-row">
          <label>
            每章目标字数
            <input name="chapterTargetWords" type="number" min="500" max="20000" defaultValue="3000" required />
          </label>
          <label>
            安全存稿章数
            <input name="safetyBufferChapters" type="number" min="0" max="100" defaultValue="3" required />
          </label>
        </div>

        {error ? <p role="alert" className="form-error">{error}</p> : null}
        <button className="primary-action" type="submit" disabled={isCreating}>
          {isCreating ? '正在铺开稿纸…' : '创建作品并进入工作台'}
        </button>
        {onImported ? (
          <>
            <button className="project-form-manuscript-import" type="button" disabled={isImporting || isCreating} onClick={() => setIsManuscriptImportOpen(true)}>已有 TXT / Markdown 稿件？识别卷章后接续</button>
            <label className="project-form-import">
              <input
                type="file"
                accept="application/json,.json,.mozhou.json"
                aria-label="从本机导入墨舟项目归档"
                disabled={isImporting || isCreating}
                onChange={(event) => { void handleArchiveImport(event) }}
              />
              {isImporting ? '正在校验并恢复…' : '已有墨舟归档？恢复为新副本'}
            </label>
          </>
        ) : null}
        <p className="privacy-note">正文与设定保存在这台设备上。当前步骤不会调用外部模型。</p>
      </form>
      {isManuscriptImportOpen && onImported ? (
        <ManuscriptImportDialog
          onClose={() => setIsManuscriptImportOpen(false)}
          onImported={onImported}
        />
      ) : null}
    </main>
  )
}
