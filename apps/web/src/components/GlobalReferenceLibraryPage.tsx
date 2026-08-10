import type {
  Project,
  ReferenceFilePreview,
  ReferenceRightsBasis,
  ReferenceWork,
  SourceConfidence,
  SourceDocument,
  SourceKind,
} from '@mozhou/contracts'
import { useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../api'

interface GlobalReferenceLibraryPageProps {
  projects: Project[]
  activeProjectId?: string
  onBack: () => void
  onProjectAssetsChanged: (projectId: string) => void
}

const rightsLabels: Record<ReferenceRightsBasis, string> = {
  self_owned: '作者自有',
  authorized: '已经授权',
  public_domain: '公版作品',
}

const sourceKindLabels: Record<SourceKind, string> = {
  historical_record: '历史档案',
  news: '新闻报道',
  industry: '行业资料',
  personal_note: '个人笔记',
}

export function GlobalReferenceLibraryPage({
  projects,
  activeProjectId,
  onBack,
  onProjectAssetsChanged,
}: GlobalReferenceLibraryPageProps) {
  const [works, setWorks] = useState<ReferenceWork[]>([])
  const [documents, setDocuments] = useState<SourceDocument[]>([])
  const [targetProjectId, setTargetProjectId] = useState(activeProjectId ?? projects[0]?.id ?? '')
  const [assetKind, setAssetKind] = useState<'reference' | 'reality'>('reference')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ReferenceFilePreview | null>(null)
  const [title, setTitle] = useState('')
  const [rightsBasis, setRightsBasis] = useState<ReferenceRightsBasis>('self_owned')
  const [sourceKind, setSourceKind] = useState<SourceKind>('historical_record')
  const [sourceReference, setSourceReference] = useState('作者本地资料')
  const [sourceDate, setSourceDate] = useState('')
  const [yearStart, setYearStart] = useState(
    projects.find((project) => project.id === targetProjectId)?.rebirth_year ?? 1998,
  )
  const [yearEnd, setYearEnd] = useState(yearStart)
  const [confidence, setConfidence] = useState<SourceConfidence>('medium')
  const [confirmUncertain, setConfirmUncertain] = useState(false)
  const [isBusy, setIsBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const projectById = useMemo(
    () => new Map(projects.map((project) => [project.id, project])),
    [projects],
  )

  async function refreshLibrary() {
    const [nextWorks, nextDocuments] = await Promise.all([
      api.listReferenceWorks(),
      api.listSourceDocuments(),
    ])
    setWorks(nextWorks)
    setDocuments(nextDocuments)
  }

  useEffect(() => {
    let ignore = false
    void Promise.all([api.listReferenceWorks(), api.listSourceDocuments()])
      .then(([nextWorks, nextDocuments]) => {
        if (ignore) return
        setWorks(nextWorks)
        setDocuments(nextDocuments)
      })
      .catch((caught: unknown) => {
        if (!ignore) setError(caught instanceof Error ? caught.message : '无法读取全局资料库')
      })
    return () => { ignore = true }
  }, [])

  function chooseFile(nextFile: File | undefined) {
    setError(null)
    setNotice(null)
    setPreview(null)
    setConfirmUncertain(false)
    if (!nextFile) {
      setFile(null)
      return
    }
    const extension = nextFile.name.toLowerCase().split('.').pop()
    if (!extension || !['txt', 'md', 'markdown', 'pdf'].includes(extension)) {
      setFile(null)
      setError('请选择 TXT、Markdown 或文本型 PDF。')
      return
    }
    if (nextFile.size > 25 * 1024 * 1024) {
      setFile(null)
      setError('单个资料文件不能超过 25 MB。')
      return
    }
    setFile(nextFile)
    setTitle(nextFile.name.replace(/\.(?:txt|md|markdown|pdf)$/i, ''))
  }

  async function inspectFile() {
    if (!file) return
    setIsBusy(true)
    setError(null)
    try {
      setPreview(await api.previewReferenceFile(file))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '资料解析失败')
    } finally {
      setIsBusy(false)
    }
  }

  async function importAsset() {
    if (!file || !preview || !title.trim()) return
    setIsBusy(true)
    setError(null)
    setNotice(null)
    try {
      if (assetKind === 'reference') {
        const imported = await api.importReferenceFile(file, {
          title: title.trim(),
          rights_basis: rightsBasis,
          segment_target_characters: 500_000,
          expected_source_sha256: preview.source_sha256,
          confirm_preview: true,
          confirm_uncertain_encoding: confirmUncertain,
        })
        setNotice(`《${imported.title}》已进入全局拆书库，可装入任意作品。`)
      } else {
        if (!targetProjectId) throw new Error('请先选择现实资料要应用的作品')
        await api.importRealitySourceFile(file, {
          project_id: targetProjectId,
          title: title.trim(),
          source_kind: sourceKind,
          source_reference: sourceReference.trim(),
          applicable_year_start: yearStart,
          applicable_year_end: yearEnd,
          confidence,
          source_date: sourceDate.trim() || undefined,
          expected_source_sha256: preview.source_sha256,
          confirm_preview: true,
          confirm_uncertain_encoding: confirmUncertain,
        })
        onProjectAssetsChanged(targetProjectId)
        setNotice('现实资料已入库并生成未确认资料卡；确认后才会进入 AI 上下文。')
      }
      setFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
      setPreview(null)
      setTitle('')
      await refreshLibrary()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '资料导入失败')
    } finally {
      setIsBusy(false)
    }
  }

  async function toggleProjectLink(work: ReferenceWork) {
    if (!targetProjectId) return
    setIsBusy(true)
    setError(null)
    try {
      if (work.project_ids.includes(targetProjectId)) {
        await api.unlinkReferenceWork(targetProjectId, work.id)
        setNotice(`《${work.title}》已从目标作品卸下，全局原文仍保留。`)
      } else {
        await api.linkReferenceWork(targetProjectId, work.id)
        setNotice(`《${work.title}》已装入目标作品。`)
      }
      onProjectAssetsChanged(targetProjectId)
      await refreshLibrary()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '无法更新作品关联')
    } finally {
      setIsBusy(false)
    }
  }

  async function purgeWork(work: ReferenceWork) {
    setError(null)
    const impact = await api.getReferenceWorkImpact(work.id)
    const projectNames = impact.projects.map((project) => `《${project.title}》`).join('、') || '无'
    if (!window.confirm(`永久清理《${work.title}》原文与 ${impact.cache_entries} 项缓存？\n受影响作品：${projectNames}\n已应用的抽象蓝图仍会保留。`)) return
    await api.purgeReferenceWork(work.id)
    impact.projects.forEach((project) => onProjectAssetsChanged(project.id))
    setNotice(`《${work.title}》原文、索引与派生缓存已清理。`)
    await refreshLibrary()
  }

  async function purgeDocument(document: SourceDocument) {
    if (!window.confirm(`永久清理现实资料《${document.title}》的原文？已生成的资料卡摘要仍会保留。`)) return
    const result = await api.deleteSourceDocument(document.id)
    setNotice(`现实资料原文已清理，${result.affected_cards} 张候选资料卡保留为快照。`)
    await refreshLibrary()
  }

  async function applyDocument(document: SourceDocument) {
    if (!targetProjectId) return
    setIsBusy(true)
    setError(null)
    try {
      await api.applySourceDocument(targetProjectId, document.id, {
        source_kind: sourceKind,
        title: document.title,
        source_reference: sourceReference.trim() || `全局资料库：${document.source_filename}`,
        applicable_year_start: yearStart,
        applicable_year_end: yearEnd,
        confidence,
      }, sourceDate.trim() || undefined)
      onProjectAssetsChanged(targetProjectId)
      setNotice(`《${document.title}》已为目标作品生成未确认资料卡。`)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '无法应用现实资料')
    } finally {
      setIsBusy(false)
    }
  }

  return (
    <main className="global-library-page">
      <header className="global-library-bar">
        <div><span aria-hidden="true">舟</span><p>墨舟 · 作者资产库</p></div>
        <button type="button" onClick={onBack}>返回</button>
      </header>

      <section className="global-library-hero">
        <div>
          <p>AUTHOR MATERIAL HARBOR</p>
          <h1>全局资料码头</h1>
          <span>原文只泊一次；结构规律与现实证据按需装入不同作品。</span>
        </div>
        <dl>
          <div><dt>参考作品</dt><dd>{works.length}</dd></div>
          <div><dt>现实资料</dt><dd>{documents.length}</dd></div>
          <div><dt>服务作品</dt><dd>{new Set(works.flatMap((work) => work.project_ids)).size}</dd></div>
        </dl>
      </section>

      <section className="global-intake" aria-labelledby="global-intake-title">
        <header>
          <div><small>入港检查</small><h2 id="global-intake-title">先验文件，再决定它属于哪条航道</h2></div>
          <div className="global-kind-switch" role="group" aria-label="资料类型">
            <button type="button" data-active={assetKind === 'reference'} onClick={() => setAssetKind('reference')}>参考小说</button>
            <button type="button" data-active={assetKind === 'reality'} onClick={() => setAssetKind('reality')}>现实资料</button>
          </div>
        </header>
        <div className="global-intake-grid">
          <label className="reference-file-field">
            选择文件
            <input ref={fileInputRef} type="file" aria-label="全局资料文件" accept=".txt,.md,.markdown,.pdf" onChange={(event) => chooseFile(event.target.files?.[0])} />
            <span>{file?.name ?? 'TXT / Markdown / PDF · 最大 25 MB'}</span>
          </label>
          <label>资料标题<input value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} /></label>
          {assetKind === 'reference' ? (
            <label>权利基础<select value={rightsBasis} onChange={(event) => setRightsBasis(event.target.value as ReferenceRightsBasis)}>{Object.entries(rightsLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
          ) : (
            <>
              <label>应用到<select value={targetProjectId} onChange={(event) => setTargetProjectId(event.target.value)}>{projects.map((project) => <option value={project.id} key={project.id}>{project.title}</option>)}</select></label>
              <label>资料类型<select value={sourceKind} onChange={(event) => setSourceKind(event.target.value as SourceKind)}>{Object.entries(sourceKindLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
              <label>来源说明<input value={sourceReference} maxLength={1000} onChange={(event) => setSourceReference(event.target.value)} /></label>
              <label>适用起年<input type="number" value={yearStart} onChange={(event) => setYearStart(Number(event.target.value))} /></label>
              <label>适用止年<input type="number" value={yearEnd} onChange={(event) => setYearEnd(Number(event.target.value))} /></label>
              <label>资料日期<input value={sourceDate} maxLength={40} placeholder="1998-04" onChange={(event) => setSourceDate(event.target.value)} /></label>
              <label>可信度<select value={confidence} onChange={(event) => setConfidence(event.target.value as SourceConfidence)}><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select></label>
            </>
          )}
        </div>
        {!preview ? (
          <button className="global-primary-action" type="button" disabled={!file || isBusy} onClick={() => { void inspectFile() }}>{isBusy ? '正在检查…' : '检测编码与安全内容'}</button>
        ) : (
          <div className="global-preview-passport">
            <div className="passport-spine"><span>{preview.source_format.toUpperCase()}</span><strong>{Math.round(preview.encoding_confidence * 100)}%</strong></div>
            <div><small>来源护照 · {preview.source_encoding}</small><pre>{preview.preview}</pre><p>{preview.total_characters.toLocaleString('zh-CN')} 字 · 指纹 {preview.content_sha256.slice(0, 12)}{preview.page_count ? ` · ${preview.page_count} 页` : ''}</p></div>
            {preview.import_state === 'needs_review' ? <label><input type="checkbox" checked={confirmUncertain} onChange={(event) => setConfirmUncertain(event.target.checked)} />预览与原文件一致，确认当前编码</label> : null}
            <button className="global-primary-action" type="button" disabled={isBusy || (preview.import_state === 'needs_review' && !confirmUncertain)} onClick={() => { void importAsset() }}>{assetKind === 'reference' ? '收入全局拆书库' : '入库并生成候选资料卡'}</button>
          </div>
        )}
        {error ? <p className="agent-error" role="alert">{error}</p> : null}
        {notice ? <p className="global-library-notice" role="status">{notice}</p> : null}
      </section>

      <section className="global-harbor-grid">
        <div className="global-asset-column">
          <header><small>REFERENCE BERTHS</small><h2>参考作品泊位</h2></header>
          <label className="global-target-project">当前装船目标<select value={targetProjectId} onChange={(event) => setTargetProjectId(event.target.value)}><option value="">选择作品</option>{projects.map((project) => <option value={project.id} key={project.id}>{project.title}</option>)}</select></label>
          {works.map((work) => {
            const linked = Boolean(targetProjectId && work.project_ids.includes(targetProjectId))
            return <article className="global-asset-passport" key={work.id}>
              <div className="passport-spine"><span>{work.source_format.toUpperCase()}</span><strong>{work.segments.length}</strong><small>段</small></div>
              <div className="passport-body">
                <header><div><small>{rightsLabels[work.rights_basis]} · {work.source_encoding}</small><h3>{work.title}</h3></div><span>{work.total_characters.toLocaleString('zh-CN')} 字</span></header>
                <p>内容指纹 {work.content_sha256.slice(0, 12)} · 编码置信度 {Math.round(work.encoding_confidence * 100)}%{work.source_spans.length ? ` · ${work.source_spans.length} 个页码来源` : ''}</p>
                {work.duplicate_of_id ? <p className="duplicate-candidate">内容与库内资产重复；权利声明未自动合并。</p> : null}
                <div className="passport-projects">{work.project_ids.length ? work.project_ids.map((id) => <span key={id}>{projectById.get(id)?.title ?? '已关联作品'}</span>) : <span>尚未装入作品</span>}</div>
                <footer><button type="button" disabled={!targetProjectId || isBusy} onClick={() => { void toggleProjectLink(work) }}>{linked ? '从目标作品卸下' : '装入目标作品'}</button><button className="danger-quiet" type="button" onClick={() => { void purgeWork(work).catch((caught) => setError(caught instanceof Error ? caught.message : '清理失败')) }}>查看影响并清理</button></footer>
              </div>
            </article>
          })}
          {works.length === 0 ? <p className="global-empty">还没有参考作品入港。</p> : null}
        </div>

        <aside className="global-source-column">
          <header><small>REALITY ANCHORS</small><h2>现实资料锚点</h2></header>
          {documents.map((document) => <article key={document.id}>
            <div><span>{document.source_format.toUpperCase()}</span><small>{document.source_encoding}</small></div>
            <h3>{document.title}</h3>
            <p>{document.total_characters.toLocaleString('zh-CN')} 字 · {document.source_spans.length ? `${document.source_spans.length} 个页码来源` : '字符范围来源'}</p>
            <code>{document.content_sha256.slice(0, 12)}</code>
            <button type="button" disabled={!targetProjectId || isBusy} onClick={() => { void applyDocument(document) }}>为目标作品生成候选卡</button>
            <button className="danger-quiet" type="button" onClick={() => { void purgeDocument(document).catch((caught) => setError(caught instanceof Error ? caught.message : '清理失败')) }}>清理原文</button>
          </article>)}
          {documents.length === 0 ? <p className="global-empty">现实资料入库后会在这里留下来源护照。</p> : null}
        </aside>
      </section>
    </main>
  )
}
