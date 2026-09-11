import type {
  CraftPatternAsset,
  CraftPatternAssetSummary,
  CraftPatternAssetType,
  CraftPatternLifecycleState,
  Project,
  ReferenceFilePreview,
  ReferenceRightsBasis,
  ReferenceWork,
  SourceConfidence,
  SourceDocument,
  SourceKind,
} from '@mozhou/contracts'
import { useEffect, useMemo, useRef, useState } from 'react'

import { ApiError, api } from '../api'
import { CraftPatternAssetCard } from './CraftPatternAssetCard'
import { craftAssetTypeLabels } from './craftPatternLabels'

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

const CRAFT_PAGE_SIZE = 50

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
  const [craftAssets, setCraftAssets] = useState<CraftPatternAssetSummary[] | null>(null)
  const [craftAssetTotal, setCraftAssetTotal] = useState(0)
  const [craftAssetOffset, setCraftAssetOffset] = useState(0)
  const [craftAssetType, setCraftAssetType] = useState<CraftPatternAssetType | ''>('')
  const [craftAssetDetails, setCraftAssetDetails] = useState<Record<string, CraftPatternAsset>>({})
  const [lineagePreviewId, setLineagePreviewId] = useState<string | null>(null)
  const [craftDetailLoadingId, setCraftDetailLoadingId] = useState<string | null>(null)
  const [craftBusyId, setCraftBusyId] = useState<string | null>(null)
  const [craftError, setCraftError] = useState<string | null>(null)
  const [craftNotice, setCraftNotice] = useState<string | null>(null)
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

  useEffect(() => {
    let ignore = false
    void api.listGlobalReferenceCraftAssets({
      for_project_id: targetProjectId || undefined,
      asset_type: craftAssetType || undefined,
      limit: CRAFT_PAGE_SIZE,
      offset: craftAssetOffset,
    }).then((page) => {
      if (ignore) return
      setCraftAssets(page.items)
      setCraftAssetTotal(page.total)
      setCraftAssetDetails({})
    }).catch((caught: unknown) => {
      if (ignore) return
      setCraftAssets([])
      setCraftError(caught instanceof Error ? caught.message : '无法读取全局写作模式素材')
    })
    return () => { ignore = true }
  }, [craftAssetOffset, craftAssetType, targetProjectId])

  function changeTargetProject(projectId: string) {
    setCraftAssets(null)
    setCraftError(null)
    setCraftNotice(null)
    setCraftAssetOffset(0)
    setTargetProjectId(projectId)
  }

  function changeCraftAssetType(assetType: CraftPatternAssetType | '') {
    setCraftAssets(null)
    setCraftError(null)
    setCraftNotice(null)
    setCraftAssetOffset(0)
    setCraftAssetType(assetType)
  }

  function changeCraftPage(offset: number) {
    setCraftAssets(null)
    setCraftError(null)
    setCraftAssetOffset(Math.max(0, offset))
  }

  async function refreshCraftAssets() {
    const page = await api.listGlobalReferenceCraftAssets({
      for_project_id: targetProjectId || undefined,
      asset_type: craftAssetType || undefined,
      limit: CRAFT_PAGE_SIZE,
      offset: craftAssetOffset,
    })
    setCraftAssets(page.items)
    setCraftAssetTotal(page.total)
    setCraftAssetDetails({})
  }

  async function loadCraftAssetDetail(assetId: string) {
    if (craftAssetDetails[assetId] || craftDetailLoadingId === assetId) return
    setCraftDetailLoadingId(assetId)
    setCraftError(null)
    try {
      const detail = await api.getReferenceCraftAsset(assetId)
      setCraftAssetDetails((current) => ({ ...current, [assetId]: detail }))
    } catch (caught) {
      setCraftError(caught instanceof Error ? caught.message : '无法读取写作模式的来源证据')
    } finally {
      setCraftDetailLoadingId(null)
    }
  }

  async function openCraftSourceAsset(assetId: string) {
    setCraftDetailLoadingId(assetId)
    setCraftError(null)
    try {
      const detail = craftAssetDetails[assetId] ?? await api.getReferenceCraftAsset(assetId)
      setCraftAssetDetails((current) => ({ ...current, [assetId]: detail }))
      if (craftAssets?.some((asset) => asset.id === assetId)) {
        setLineagePreviewId(null)
        window.requestAnimationFrame(() => {
          document.getElementById(`craft-asset-${assetId}`)?.scrollIntoView?.({ block: 'center' })
        })
      } else {
        setLineagePreviewId(assetId)
      }
    } catch (caught) {
      setCraftError(caught instanceof Error ? caught.message : '无法读取来源素材')
    } finally {
      setCraftDetailLoadingId(null)
    }
  }

  async function installCraftAsset(asset: CraftPatternAssetSummary) {
    if (!targetProjectId || craftBusyId) return
    setCraftBusyId(asset.id)
    setCraftError(null)
    setCraftNotice(null)
    try {
      const installed = await api.reuseReferenceCraftAsset(targetProjectId, asset.id)
      setCraftAssetDetails((current) => ({ ...current, [installed.id]: installed }))
      onProjectAssetsChanged(targetProjectId)
      setCraftNotice(`《${asset.title}》已装入目标作品，可在拆书库中选择它参与后续融合。`)
      await refreshCraftAssets()
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        try {
          await refreshCraftAssets()
          setCraftError(`${caught.message}，已载入最新素材状态。`)
        } catch {
          setCraftError(`${caught.message}；最新状态读取失败，请稍后重试。`)
        }
      } else {
        setCraftError(caught instanceof Error ? caught.message : '无法装入写作模式素材')
      }
    } finally {
      setCraftBusyId(null)
    }
  }

  async function updateCraftLifecycle(
    asset: CraftPatternAssetSummary,
    state: CraftPatternLifecycleState,
  ) {
    if (!targetProjectId || asset.lifecycle_revision === null || craftBusyId) return
    setCraftBusyId(asset.id)
    setCraftError(null)
    setCraftNotice(null)
    try {
      const updated = await api.updateCraftPatternLifecycle(targetProjectId, asset.id, {
        state,
        expected_lifecycle_revision: asset.lifecycle_revision,
      })
      setCraftAssets((current) => current?.map((item) => item.id === updated.id ? updated : item) ?? [])
      setCraftAssetDetails((current) => ({ ...current, [updated.id]: updated }))
      onProjectAssetsChanged(targetProjectId)
      setCraftNotice(state === 'active'
        ? `《${asset.title}》已恢复，可在拆书库中加入融合。`
        : `《${asset.title}》已归档；内容版本和来源证据仍保留。`)
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        try {
          await refreshCraftAssets()
          setCraftError(`${caught.message}，已载入最新素材状态。`)
        } catch {
          setCraftError(`${caught.message}；最新状态读取失败，请稍后重试。`)
        }
      } else {
        setCraftError(caught instanceof Error ? caught.message : '无法更新写作模式素材状态')
      }
    } finally {
      setCraftBusyId(null)
    }
  }

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
    if (!extension || !['txt', 'md', 'markdown', 'pdf', 'docx', 'epub'].includes(extension)) {
      setFile(null)
      setError('请选择 TXT、Markdown、文本型 PDF、DOCX 或 EPUB。')
      return
    }
    if (nextFile.size > 25 * 1024 * 1024) {
      setFile(null)
      setError('单个资料文件不能超过 25 MB。')
      return
    }
    setFile(nextFile)
    setTitle(nextFile.name.replace(/\.(?:txt|md|markdown|pdf|docx|epub)$/i, ''))
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
    const retainedAssets = impact.retained_craft_asset_count === undefined
      ? '旧版服务未返回保留数量；已有抽象模式、证据哈希和旧应用蓝图不会随原文删除。'
      : `${impact.retained_craft_asset_count} 张抽象模式素材及其证据哈希会保留；旧应用蓝图也会保留。`
    const affectedJobs = impact.affected_craft_job_count === undefined
      ? '运行中拆解任务的影响数量未知，请先在任务中心确认。'
      : impact.affected_craft_job_count > 0
        ? `${impact.affected_craft_job_count} 个运行中拆解任务会停止或失效。`
        : '没有运行中的拆解任务会受影响。'
    if (!window.confirm(`永久清理《${work.title}》？\n原文、区段与 ${impact.cache_entries} 项缓存会删除。\n${retainedAssets}\n${affectedJobs}\n受影响作品：${projectNames}`)) return
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

  const lineagePreview = lineagePreviewId ? craftAssetDetails[lineagePreviewId] ?? null : null
  const craftAssetTitles = Object.fromEntries([
    ...(craftAssets ?? []).map((asset) => [asset.id, asset.title] as const),
    ...Object.values(craftAssetDetails).map((asset) => [asset.id, asset.title] as const),
  ])

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
            <input ref={fileInputRef} type="file" aria-label="全局资料文件" accept=".txt,.md,.markdown,.pdf,.docx,.epub" onChange={(event) => chooseFile(event.target.files?.[0])} />
            <span>{file?.name ?? 'TXT / Markdown / PDF / DOCX / EPUB · 最大 25 MB'}</span>
          </label>
          <label>资料标题<input value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} /></label>
          {assetKind === 'reference' ? (
            <label>权利基础<select value={rightsBasis} onChange={(event) => setRightsBasis(event.target.value as ReferenceRightsBasis)}>{Object.entries(rightsLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
          ) : (
            <>
              <label>应用到<select value={targetProjectId} onChange={(event) => changeTargetProject(event.target.value)}>{projects.map((project) => <option value={project.id} key={project.id}>{project.title}</option>)}</select></label>
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

      <section className="global-pattern-vault" aria-labelledby="global-pattern-vault-title">
        <header>
          <div>
            <small>CRAFT PATTERN VAULT · 只列摘要</small>
            <h2 id="global-pattern-vault-title">可跨作品装入的写作模式素材</h2>
            <p>这里保存的是不可变的阶段卡、单书演变与融合素材。展开时才读取技法与抽象证据，不读取参考原文。</p>
          </div>
          <span>{craftAssetTotal} 个内容版本</span>
        </header>
        <div className="global-pattern-toolbar">
          <label>
            装入目标作品
            <select
              value={targetProjectId}
              onChange={(event) => changeTargetProject(event.target.value)}
            >
              <option value="">选择作品</option>
              {projects.map((project) => <option value={project.id} key={project.id}>{project.title}</option>)}
            </select>
          </label>
          <label>
            素材类型
            <select
              value={craftAssetType}
              onChange={(event) => changeCraftAssetType(event.target.value as CraftPatternAssetType | '')}
            >
              <option value="">全部类型</option>
              {Object.entries(craftAssetTypeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <p>装入后，请回到目标作品的拆书库选择阶段卡或单书演变卡，发起多书融合。</p>
        </div>
        {craftError ? <p className="agent-error" role="alert">{craftError}</p> : null}
        {craftNotice ? <p className="global-library-notice" role="status">{craftNotice}</p> : null}
        {lineagePreview ? (
          <aside className="global-pattern-lineage-preview" aria-label="来源素材预览">
            <header>
              <div><small>来源路径</small><h3>上一层素材</h3></div>
              <button type="button" onClick={() => setLineagePreviewId(null)}>关闭预览</button>
            </header>
            <CraftPatternAssetCard
              asset={lineagePreview}
              detail={lineagePreview}
              detailLoading={false}
              detailError={null}
              selectedForFusion={false}
              lifecycleBusy={false}
              onRequestDetail={() => undefined}
              onToggleFusion={() => undefined}
              onLifecycleChange={() => undefined}
              onOpenSourceAsset={(assetId) => { void openCraftSourceAsset(assetId) }}
              sourceAssetTitles={craftAssetTitles}
              showFusionSelection={false}
              showLifecycleAction={false}
            />
          </aside>
        ) : null}
        {craftAssets === null ? <p className="global-pattern-empty" role="status">正在读取全局写作模式素材…</p> : null}
        {craftAssets?.length === 0 ? <p className="global-pattern-empty">还没有匹配的写作模式素材。先在任一作品的拆书库完成一次拆解。</p> : null}
        {craftAssets && craftAssets.length > 0 ? (
          <div className="global-pattern-list">
            {craftAssets.map((asset) => (
              <CraftPatternAssetCard
                key={asset.id}
                asset={asset}
                detail={craftAssetDetails[asset.id] ?? null}
                detailLoading={craftDetailLoadingId === asset.id}
                detailError={null}
                selectedForFusion={false}
                lifecycleBusy={craftBusyId === asset.id}
                onRequestDetail={() => { void loadCraftAssetDetail(asset.id) }}
                onToggleFusion={() => undefined}
                onLifecycleChange={(state) => { void updateCraftLifecycle(asset, state) }}
                onOpenSourceAsset={(assetId) => { void openCraftSourceAsset(assetId) }}
                sourceAssetTitles={craftAssetTitles}
                showFusionSelection={false}
                showLifecycleAction={asset.lifecycle_state !== null}
                installAction={asset.lifecycle_state === null ? {
                  label: targetProjectId
                    ? `装入《${projectById.get(targetProjectId)?.title ?? '目标作品'}》`
                    : '先选择目标作品',
                  busyLabel: '正在装入…',
                  busy: craftBusyId === asset.id,
                  disabled: !targetProjectId || isBusy,
                  onClick: () => { void installCraftAsset(asset) },
                } : undefined}
              />
            ))}
          </div>
        ) : null}
        {craftAssetTotal > CRAFT_PAGE_SIZE ? (
          <nav className="global-pattern-pages" aria-label="写作模式素材分页">
            <button
              type="button"
              disabled={craftAssetOffset === 0}
              onClick={() => changeCraftPage(craftAssetOffset - CRAFT_PAGE_SIZE)}
            >上一页</button>
            <span>第 {Math.floor(craftAssetOffset / CRAFT_PAGE_SIZE) + 1} 页</span>
            <button
              type="button"
              disabled={craftAssetOffset + CRAFT_PAGE_SIZE >= craftAssetTotal}
              onClick={() => changeCraftPage(craftAssetOffset + CRAFT_PAGE_SIZE)}
            >下一页</button>
          </nav>
        ) : null}
      </section>

      <section className="global-harbor-grid">
        <div className="global-asset-column">
          <header><small>REFERENCE BERTHS</small><h2>参考作品泊位</h2></header>
          <label className="global-target-project">当前装船目标<select value={targetProjectId} onChange={(event) => changeTargetProject(event.target.value)}><option value="">选择作品</option>{projects.map((project) => <option value={project.id} key={project.id}>{project.title}</option>)}</select></label>
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
