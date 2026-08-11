import type {
  Genre,
  ManuscriptImportPreview,
  ManuscriptImportVolume,
  Workspace,
} from '@mozhou/contracts'
import { useRef, useState } from 'react'

import { api } from '../api'
import { genreDefaults, genreOptions, getStoryAnchorLabels } from '../genre'

interface ManuscriptImportDialogProps {
  onClose: () => void
  onImported: (workspace: Workspace) => void
}

const maxManuscriptBytes = 20 * 1024 * 1024

export function ManuscriptImportDialog({ onClose, onImported }: ManuscriptImportDialogProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ManuscriptImportPreview | null>(null)
  const [title, setTitle] = useState('')
  const [genre, setGenre] = useState<Genre>('historical_rebirth')
  const [rebirthYear, setRebirthYear] = useState(genreDefaults.historical_rebirth.storyYear)
  const [rebirthLocation, setRebirthLocation] = useState(genreDefaults.historical_rebirth.storyLocation)
  const [chapterTargetWords, setChapterTargetWords] = useState(3000)
  const [safetyBufferChapters, setSafetyBufferChapters] = useState(5)
  const [preambleAction, setPreambleAction] = useState<'prepend' | 'omit'>('prepend')
  const [warningsConfirmed, setWarningsConfirmed] = useState(false)
  const [isBusy, setIsBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const anchorLabels = getStoryAnchorLabels(genre)

  function selectGenre(nextGenre: Genre) {
    const defaults = genreDefaults[nextGenre]
    setGenre(nextGenre)
    setRebirthYear(defaults.storyYear)
    setRebirthLocation(defaults.storyLocation)
  }

  function selectFile(next: File | undefined) {
    setError(null)
    setPreview(null)
    setWarningsConfirmed(false)
    if (!next) {
      setFile(null)
      return
    }
    if (!/\.(?:txt|md|markdown|docx|epub)$/i.test(next.name)) {
      setFile(null)
      setError('请选择 TXT、Markdown、DOCX 或 EPUB 稿件')
      return
    }
    if (next.size > maxManuscriptBytes) {
      setFile(null)
      setError('单个稿件不能超过 20 MiB')
      return
    }
    setFile(next)
  }

  async function inspect() {
    if (!file) return
    setIsBusy(true)
    setError(null)
    try {
      const next = await api.previewManuscript(file)
      setPreview(next)
      setTitle(next.inferred_project_title)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '稿件识别失败')
    } finally {
      setIsBusy(false)
    }
  }

  function updateVolume(volumeIndex: number, transform: (volume: ManuscriptImportVolume) => ManuscriptImportVolume) {
    setPreview((current) => current ? {
      ...current,
      volumes: current.volumes.map((volume, index) => index === volumeIndex ? transform(volume) : volume),
    } : current)
  }

  async function confirmImport() {
    if (!preview) return
    setIsBusy(true)
    setError(null)
    try {
      const workspace = await api.confirmManuscriptImport({
        title: title.trim(),
        genre,
        rebirth_year: rebirthYear,
        rebirth_location: rebirthLocation.trim(),
        chapter_target_words: chapterTargetWords,
        safety_buffer_chapters: safetyBufferChapters,
        source_filename: preview.source_filename,
        source_sha256: preview.source_sha256,
        source_encoding: preview.source_encoding,
        warnings: preview.warnings,
        volumes: preview.volumes,
        unrecognized_text: preview.unrecognized_text,
        unrecognized_action: preview.unrecognized_text
          ? (preambleAction === 'prepend' ? 'prepend_first_chapter' : 'omit')
          : null,
        confirm_warnings: warningsConfirmed,
      })
      onImported(workspace)
      onClose()
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '稿件导入失败')
    } finally {
      setIsBusy(false)
    }
  }

  const chapterCount = preview?.volumes.reduce((sum, volume) => sum + volume.chapters.length, 0) ?? 0
  const hasWarnings = Boolean(preview?.warnings.length)
  const canImport = Boolean(
    preview
    && title.trim()
    && rebirthLocation.trim()
    && preview.volumes.length
    && chapterCount
    && (!hasWarnings || warningsConfirmed),
  )

  return (
    <div className="manuscript-import-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !isBusy) onClose()
    }}>
      <section className="manuscript-import-dialog" role="dialog" aria-modal="true" aria-labelledby="manuscript-import-title">
        <header>
          <div>
            <p>MANUSCRIPT INTAKE / 旧稿接续</p>
            <h2 id="manuscript-import-title">先识别，再决定如何入库</h2>
            <span>预览和校正不会写入作品；点击确认后才创建新项目。</span>
          </div>
          <button type="button" aria-label="关闭稿件导入" disabled={isBusy} onClick={onClose}>×</button>
        </header>

        <div className="manuscript-import-file">
          <input
            ref={fileInputRef}
            type="file"
            accept=".txt,.md,.markdown,.docx,.epub,text/plain,text/markdown,application/epub+zip,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            aria-label="选择 TXT、Markdown、DOCX 或 EPUB 稿件"
            disabled={isBusy}
            onChange={(event) => selectFile(event.target.files?.[0])}
          />
          <button type="button" disabled={!file || isBusy} onClick={() => { void inspect() }}>
            {isBusy && !preview ? '正在识别…' : '识别卷章结构'}
          </button>
          <small>{file ? `${file.name} · ${Math.max(1, Math.round(file.size / 1024)).toLocaleString('zh-CN')} KiB` : '支持 UTF-8、UTF-8 BOM、GB18030，最大 20 MiB'}</small>
        </div>

        {error ? <p className="manuscript-import-error" role="alert">{error}</p> : null}

        {preview ? (
          <div className="manuscript-import-preview">
            <section className="manuscript-import-settings" aria-label="作品信息">
              <label><span>书名</span><input value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} /></label>
              <label><span>类型</span><select value={genre} onChange={(event) => selectGenre(event.target.value as Genre)}>{genreOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
              <label><span>{anchorLabels.year}</span><input type="number" min="-3000" max="2030" value={rebirthYear} onChange={(event) => setRebirthYear(Number(event.target.value))} /></label>
              <label><span>{anchorLabels.location}</span><input value={rebirthLocation} maxLength={100} onChange={(event) => setRebirthLocation(event.target.value)} /></label>
              <label><span>单章目标</span><input type="number" min="500" max="20000" step="100" value={chapterTargetWords} onChange={(event) => setChapterTargetWords(Number(event.target.value))} /></label>
              <label><span>安全存稿</span><input type="number" min="0" max="100" value={safetyBufferChapters} onChange={(event) => setSafetyBufferChapters(Number(event.target.value))} /></label>
            </section>

            <section className="manuscript-import-summary" aria-label="识别摘要">
              <strong>{preview.volumes.length} 卷 · {chapterCount} 章 · {preview.total_characters.toLocaleString('zh-CN')} 字符</strong>
              <span>{preview.source_encoding} · 编码置信度 {Math.round(preview.encoding_confidence * 100)}%</span>
            </section>

            {preview.unrecognized_text ? (
              <fieldset className="manuscript-import-preamble">
                <legend>章前散落文字</legend>
                <p>{preview.unrecognized_text.slice(0, 180)}{preview.unrecognized_text.length > 180 ? '…' : ''}</p>
                <label><input type="radio" checked={preambleAction === 'prepend'} onChange={() => setPreambleAction('prepend')} />并入第一章</label>
                <label><input type="radio" checked={preambleAction === 'omit'} onChange={() => setPreambleAction('omit')} />本次不导入</label>
              </fieldset>
            ) : null}

            <ol className="manuscript-import-tree" aria-label="可校正卷章目录">
              {preview.volumes.map((volume, volumeIndex) => (
                <li key={volume.client_id}>
                  <label>
                    <span>第 {volumeIndex + 1} 卷</span>
                    <input aria-label={`第 ${volumeIndex + 1} 卷标题`} value={volume.title} maxLength={120} onChange={(event) => updateVolume(volumeIndex, (current) => ({ ...current, title: event.target.value }))} />
                  </label>
                  <ol>
                    {volume.chapters.map((chapter, chapterIndex) => (
                      <li key={chapter.client_id}>
                        <label>
                          <span>{String(chapterIndex + 1).padStart(2, '0')}</span>
                          <input aria-label={`第 ${volumeIndex + 1} 卷第 ${chapterIndex + 1} 章标题`} value={chapter.title} maxLength={120} onChange={(event) => updateVolume(volumeIndex, (current) => ({
                            ...current,
                            chapters: current.chapters.map((item, index) => index === chapterIndex ? { ...item, title: event.target.value } : item),
                          }))} />
                          <small>{chapter.content.length.toLocaleString('zh-CN')} 字符 · 置信度 {Math.round(chapter.heading_confidence * 100)}%</small>
                        </label>
                      </li>
                    ))}
                  </ol>
                </li>
              ))}
            </ol>

            {hasWarnings ? (
              <section className="manuscript-import-warnings" aria-label="导入提醒">
                <strong>请确认 {preview.warnings.length} 项识别提醒</strong>
                <ul>{preview.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
                <label><input type="checkbox" checked={warningsConfirmed} onChange={(event) => setWarningsConfirmed(event.target.checked)} />我已检查目录与正文预览</label>
              </section>
            ) : null}
          </div>
        ) : null}

        <footer>
          <button type="button" disabled={isBusy} onClick={onClose}>取消</button>
          <button type="button" disabled={!canImport || isBusy} onClick={() => { void confirmImport() }}>{isBusy && preview ? '正在创建作品…' : '确认并创建作品'}</button>
        </footer>
      </section>
    </div>
  )
}
