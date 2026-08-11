import type { BetaTemplate, CreateProjectInput, Genre, Workspace } from '@mozhou/contracts'
import { useEffect, useState, type ChangeEvent, type FormEvent } from 'react'

import { api } from '../api'
import { genreDefaults, genreOptions, getStoryAnchorLabels } from '../genre'
import { ManuscriptImportDialog } from './ManuscriptImportDialog'

interface CreateProjectFormProps {
  onCreated: (workspace: Workspace) => void
  onImported?: (workspace: Workspace) => void
  onCancel?: () => void
}

const maxArchiveBytes = 256 * 1024 * 1024

export function CreateProjectForm({ onCreated, onImported, onCancel }: CreateProjectFormProps) {
  const [genre, setGenre] = useState<Genre>('urban_rebirth')
  const [title, setTitle] = useState('')
  const [rebirthYear, setRebirthYear] = useState(1998)
  const [rebirthLocation, setRebirthLocation] = useState('福建南平')
  const [templates, setTemplates] = useState<BetaTemplate[]>([])
  const [selectedTemplate, setSelectedTemplate] = useState<BetaTemplate | null>(null)
  const [isCreating, setIsCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isImporting, setIsImporting] = useState(false)
  const [isManuscriptImportOpen, setIsManuscriptImportOpen] = useState(false)
  const anchorLabels = getStoryAnchorLabels(genre)

  useEffect(() => {
    let active = true
    api.listBetaTemplates()
      .then((result) => {
        if (active) setTemplates(result)
      })
      .catch(() => undefined)
    return () => {
      active = false
    }
  }, [])

  const applyTemplate = (template: BetaTemplate) => {
    setGenre(template.genre)
    setTitle(template.suggested_title)
    setRebirthYear(template.rebirth_year)
    setRebirthLocation(template.rebirth_location)
    setSelectedTemplate(template)
  }

  const selectGenre = (nextGenre: Genre) => {
    const defaults = genreDefaults[nextGenre]
    setGenre(nextGenre)
    setRebirthYear(defaults.storyYear)
    setRebirthLocation(defaults.storyLocation)
    setSelectedTemplate(null)
  }

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
          从故事引爆点到下一章悬念，墨舟会保存故事状态，也把最终决定留给作者。
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
          <h2>先钉住故事的起点</h2>
        </header>

        {templates.length > 0 ? (
          <section className="project-beta-templates" aria-labelledby="project-beta-templates-title">
            <div>
              <p>封测起航模板</p>
              <h3 id="project-beta-templates-title">先带入一个可验证的十章目标</h3>
            </div>
            <div className="project-beta-template-grid">
              {templates.map((template) => (
                <button
                  type="button"
                  key={template.id}
                  data-selected={selectedTemplate?.id === template.id}
                  onClick={() => applyTemplate(template)}
                >
                  <strong>{template.label}</strong>
                  <span>{template.rebirth_year} · {template.rebirth_location}</span>
                </button>
              ))}
            </div>
            {selectedTemplate ? (
              <aside>
                <strong>十章验证目标</strong>
                <p>{selectedTemplate.first_ten_chapter_goal}</p>
                <span>{selectedTemplate.reality_anchor}</span>
              </aside>
            ) : null}
          </section>
        ) : null}

        <label>
          作品名
          <input
            name="title"
            maxLength={120}
            required
            placeholder={genreDefaults[genre].titlePlaceholder}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>

        <fieldset>
          <legend>作品题材</legend>
          <div className="genre-grid">
            {genreOptions.map(({ value, label }) => (
              <label className="genre-option" key={value} data-selected={genre === value}>
                <input
                  type="radio"
                  name="genre"
                  value={value}
                  checked={genre === value}
                  onChange={() => selectGenre(value)}
                />
                <span>{label}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="form-row">
          <label>
            {anchorLabels.year}
            <input
              name="rebirthYear"
              type="number"
              min="-3000"
              max="2030"
              value={rebirthYear}
              required
              onChange={(event) => setRebirthYear(Number(event.target.value))}
            />
          </label>
          <label>
            {anchorLabels.location}
            <input
              name="rebirthLocation"
              maxLength={100}
              value={rebirthLocation}
              required
              onChange={(event) => setRebirthLocation(event.target.value)}
            />
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
            <button className="project-form-manuscript-import" type="button" disabled={isImporting || isCreating} onClick={() => setIsManuscriptImportOpen(true)}>已有 TXT / Markdown / DOCX / EPUB 稿件？识别卷章后接续</button>
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
