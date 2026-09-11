import type {
  CraftPatternAsset,
  CraftPatternAssetSummary,
  CraftPatternLifecycleState,
  CraftPatternPreflight,
  Job,
  ReferenceWork,
  Workspace,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { useEffect, useMemo, useState } from 'react'

import { ApiError, api } from '../api'
import { CraftPatternAssetCard } from './CraftPatternAssetCard'

interface CraftPatternWorkbenchProps {
  workspace: WorkspaceSummary
  onWorkspaceChanged: (workspace: Workspace | WorkspaceSummary) => void
  onOpenTaskCenter?: () => void
}

type CraftOperation = 'analysis' | 'fusion'

const runningStates = new Set(['queued', 'running', 'pause_requested'])
const retryableStates = new Set(['failed', 'interrupted', 'cancelled'])
const v2Workflows = new Set(['craft_pattern_analysis_v2', 'craft_pattern_fusion_v2'])

function formatWan(value: number): string {
  if (value >= 10_000) return `${(value / 10_000).toLocaleString('zh-CN', { maximumFractionDigits: 1 })} 万`
  return value.toLocaleString('zh-CN')
}

function formatCost(value: number | null): string {
  return value === null ? '费用未知' : `$${(value / 1_000_000).toFixed(4)}`
}

function mergeAssets(
  current: CraftPatternAssetSummary[],
  incoming: CraftPatternAssetSummary[],
): CraftPatternAssetSummary[] {
  const byId = new Map(current.map((asset) => [asset.id, asset]))
  for (const asset of incoming) byId.set(asset.id, asset)
  return [...byId.values()].sort((left, right) => right.created_at.localeCompare(left.created_at))
}

function jobIsCraftPattern(job: Job): boolean {
  return v2Workflows.has(job.workflow)
}

function selectedSegmentSummary(works: ReferenceWork[], selectedIds: Set<string>) {
  const segmentIds: string[] = []
  const workIds = new Set<string>()
  let characterCount = 0
  for (const work of works) {
    for (const segment of work.segments) {
      if (!selectedIds.has(segment.id)) continue
      segmentIds.push(segment.id)
      workIds.add(work.id)
      characterCount += segment.character_count
    }
  }
  return { segmentIds, workIds, characterCount }
}

export function CraftPatternWorkbench({
  workspace,
  onWorkspaceChanged,
  onOpenTaskCenter,
}: CraftPatternWorkbenchProps) {
  const [assets, setAssets] = useState<CraftPatternAssetSummary[] | null>(null)
  const [assetDetails, setAssetDetails] = useState<Record<string, CraftPatternAsset>>({})
  const [detailLoadingId, setDetailLoadingId] = useState<string | null>(null)
  const [detailErrors, setDetailErrors] = useState<Record<string, string>>({})
  const [selectedSegments, setSelectedSegments] = useState<Set<string>>(() => new Set())
  const [selectedAssetVersionIds, setSelectedAssetVersionIds] = useState<Set<string>>(() => new Set())
  const [authorFocus, setAuthorFocus] = useState('')
  const [preflight, setPreflight] = useState<CraftPatternPreflight | null>(null)
  const [confirmedSubmission, setConfirmedSubmission] = useState(false)
  const [confirmedUnknownCost, setConfirmedUnknownCost] = useState(false)
  const [budgetUsd, setBudgetUsd] = useState('')
  const [activeJob, setActiveJob] = useState<Job | null>(null)
  const [busy, setBusy] = useState<CraftOperation | 'lifecycle' | null>(null)
  const [lifecycleBusyId, setLifecycleBusyId] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const projectId = workspace.project.id
  const activeJobId = activeJob?.id
  const activeJobState = activeJob?.state

  useEffect(() => {
    let active = true
    const restore = async () => {
      const [assetsResult, jobsResult] = await Promise.allSettled([
        api.listReferenceCraftAssets(projectId),
        api.listJobs(projectId),
      ])
      if (!active) return
      if (assetsResult.status === 'fulfilled') {
        setAssets(assetsResult.value)
      } else {
        setAssets([])
        setError(assetsResult.reason instanceof Error ? assetsResult.reason.message : '无法读取写作模式素材')
      }
      if (jobsResult.status !== 'fulfilled') return
      const latest = jobsResult.value.find(jobIsCraftPattern)
      if (!latest) return
      if (latest.state === 'succeeded') {
        try {
          const produced = await api.listJobReferenceCraftAssets(latest.id)
          if (!active) return
          setAssets((current) => mergeAssets(current ?? [], produced))
          setAssetDetails((current) => ({
            ...current,
            ...Object.fromEntries(produced.map((asset) => [asset.id, asset])),
          }))
        } catch {
          // The persisted project asset list remains authoritative when job artifacts are unavailable.
        }
      } else if (latest.state !== 'cancelled') {
        setActiveJob(latest)
      }
    }
    void restore()
    return () => {
      active = false
    }
  }, [projectId])

  useEffect(() => {
    if (!activeJobId || !activeJobState || !runningStates.has(activeJobState)) return undefined
    let stopped = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const job = await api.getJob(activeJobId)
        if (stopped) return
        if (job.state === 'succeeded') {
          const produced = await api.listJobReferenceCraftAssets(job.id)
          if (stopped) return
          setAssets((current) => mergeAssets(current ?? [], produced))
          setAssetDetails((current) => ({
            ...current,
            ...Object.fromEntries(produced.map((asset) => [asset.id, asset])),
          }))
          setSelectedSegments(new Set())
          setSelectedAssetVersionIds(new Set())
          setActiveJob(null)
          setConfirmedSubmission(false)
          setConfirmedUnknownCost(false)
          setBudgetUsd('')
          setNotice(`已生成 ${produced.length} 张可追溯模式素材。`)
          return
        }
        setActiveJob(job)
        if (retryableStates.has(job.state)) {
          setError(job.error_message ?? '拆书任务已中断，可从已完成的缓存继续。')
          return
        }
        timer = window.setTimeout(poll, 700)
      } catch (caught) {
        if (!stopped) setError(caught instanceof Error ? caught.message : '无法读取拆书进度')
      }
    }
    void poll()
    return () => {
      stopped = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [activeJobId, activeJobState])

  const analysisSelection = useMemo(
    () => selectedSegmentSummary(workspace.reference_works, selectedSegments),
    [selectedSegments, workspace.reference_works],
  )
  const activeAssets = assets ?? []
  const selectedFusionAssets = activeAssets.filter((asset) => selectedAssetVersionIds.has(asset.id))
  const fusionWorkCount = new Set(selectedFusionAssets.flatMap((asset) => asset.source_work_ids)).size
  const stageAssets = activeAssets.filter((asset) => asset.asset_type === 'stage')
  const bookAssets = activeAssets.filter((asset) => asset.asset_type === 'book_evolution')
  const fusionAssets = activeAssets.filter((asset) => asset.asset_type === 'fusion_material')
  const assetTitles = Object.fromEntries(activeAssets.map((asset) => [asset.id, asset.title]))
  const jobRunning = activeJob !== null && runningStates.has(activeJob.state)
  const hasExternalCalls = (preflight?.uncached_calls ?? 0) > 0
  const estimatedCost = preflight?.estimated_cost_microusd ?? null
  const hasUnknownCost = hasExternalCalls && estimatedCost === null
  const budgetMicrousd = budgetUsd.trim() === '' ? null : Math.round(Number(budgetUsd) * 1_000_000)
  const budgetIsValid = estimatedCost === null
    || (budgetMicrousd !== null
      && Number.isFinite(budgetMicrousd)
      && budgetMicrousd >= estimatedCost)
  const submissionReady = preflight !== null
    && confirmedSubmission
    && (!hasUnknownCost || confirmedUnknownCost)
    && (!hasExternalCalls || hasUnknownCost || budgetIsValid)

  function invalidatePreflight() {
    setPreflight(null)
    setConfirmedSubmission(false)
    setConfirmedUnknownCost(false)
    setBudgetUsd('')
  }

  function toggleSegment(workId: string, segmentId: string) {
    invalidatePreflight()
    setSelectedSegments((current) => {
      const currentSummary = selectedSegmentSummary(workspace.reference_works, current)
      const next = currentSummary.workIds.size > 0 && !currentSummary.workIds.has(workId)
        ? new Set<string>()
        : new Set(current)
      if (next.has(segmentId)) next.delete(segmentId)
      else next.add(segmentId)
      return next
    })
  }

  function selectWholeWork(work: ReferenceWork) {
    invalidatePreflight()
    const allSelected = work.segments.length > 0 && work.segments.every((segment) => selectedSegments.has(segment.id))
    setSelectedSegments(allSelected ? new Set() : new Set(work.segments.map((segment) => segment.id)))
  }

  function toggleFusionAsset(asset: CraftPatternAssetSummary) {
    if (asset.lifecycle_state !== 'active' || asset.asset_type === 'fusion_material') return
    invalidatePreflight()
    setSelectedAssetVersionIds((current) => {
      const next = new Set(current)
      if (next.has(asset.id)) next.delete(asset.id)
      else next.add(asset.id)
      return next
    })
  }

  async function loadAssetDetail(assetId: string) {
    if (assetDetails[assetId] || detailLoadingId === assetId) return
    setDetailLoadingId(assetId)
    setDetailErrors((current) => ({ ...current, [assetId]: '' }))
    try {
      const detail = await api.getReferenceCraftAsset(assetId, projectId)
      setAssetDetails((current) => ({ ...current, [assetId]: detail }))
    } catch (caught) {
      setDetailErrors((current) => ({
        ...current,
        [assetId]: caught instanceof Error ? caught.message : '无法读取这张卡的来源证据',
      }))
    } finally {
      setDetailLoadingId(null)
    }
  }

  async function openSourceAsset(assetId: string) {
    await loadAssetDetail(assetId)
    window.requestAnimationFrame(() => {
      document.getElementById(`craft-asset-${assetId}`)?.scrollIntoView?.({ block: 'center' })
    })
  }

  async function refreshAfterConflict(message: string) {
    const [latestAssets, latestWorkspace] = await Promise.all([
      api.listReferenceCraftAssets(projectId),
      api.getProjectSummary(projectId),
    ])
    setAssets(latestAssets)
    setAssetDetails({})
    setSelectedAssetVersionIds(new Set())
    invalidatePreflight()
    onWorkspaceChanged(latestWorkspace)
    setError(`${message}，已载入最新素材状态。`)
  }

  async function updateLifecycle(asset: CraftPatternAssetSummary, state: CraftPatternLifecycleState) {
    if (asset.lifecycle_revision === null || lifecycleBusyId) return
    setBusy('lifecycle')
    setLifecycleBusyId(asset.id)
    setError(null)
    setNotice(null)
    try {
      const updated = await api.updateCraftPatternLifecycle(projectId, asset.id, {
        state,
        expected_lifecycle_revision: asset.lifecycle_revision,
      })
      setAssets((current) => mergeAssets(current ?? [], [updated]))
      setAssetDetails((current) => ({ ...current, [updated.id]: updated }))
      if (state === 'archived') {
        setSelectedAssetVersionIds((current) => {
          const next = new Set(current)
          next.delete(asset.id)
          return next
        })
        invalidatePreflight()
      }
      setNotice(state === 'active' ? '素材已恢复，可再次加入融合。' : '素材已归档，内容和来源证据仍保留。')
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        try {
          await refreshAfterConflict(caught.message)
        } catch {
          setError(`${caught.message}；最新状态读取失败，请重新打开拆书库。`)
        }
      } else {
        setError(caught instanceof Error ? caught.message : '写作模式素材状态更新失败')
      }
    } finally {
      setBusy(null)
      setLifecycleBusyId(null)
    }
  }

  async function requestPreflight(operation: CraftOperation) {
    setError(null)
    setNotice(null)
    if (operation === 'analysis' && analysisSelection.segmentIds.length === 0) {
      setError('请先选择一本书中的至少一个阶段。')
      return
    }
    if (operation === 'fusion' && fusionWorkCount < 2) {
      setError('多书融合需要至少两本不同来源作品的阶段卡或单书演变卡。')
      return
    }
    setBusy(operation)
    invalidatePreflight()
    try {
      const result = operation === 'analysis'
        ? await api.previewCraftPatternAnalysis(projectId, {
          selected_segment_ids: analysisSelection.segmentIds,
          author_focus: authorFocus.trim(),
        })
        : await api.previewCraftPatternFusion(projectId, {
          selected_asset_version_ids: selectedFusionAssets.map((asset) => asset.id),
          author_focus: authorFocus.trim(),
        })
      setPreflight(result)
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        try {
          await refreshAfterConflict(caught.message)
        } catch {
          setError(`${caught.message}；无法刷新预检依据，请重新打开拆书库。`)
        }
      } else {
        setError(caught instanceof Error ? caught.message : '无法生成调用预检')
      }
    } finally {
      setBusy(null)
    }
  }

  async function startJob() {
    if (!preflight || !submissionReady) return
    setBusy(preflight.operation)
    setError(null)
    setNotice(null)
    try {
      const sharedConfirmation = {
        expected_preflight_sha256: preflight.preflight_sha256,
        confirm_external_processing: hasExternalCalls && confirmedSubmission,
        confirm_unknown_cost: hasUnknownCost && confirmedUnknownCost,
        max_estimated_cost_microusd: hasExternalCalls && !hasUnknownCost ? budgetMicrousd : null,
      }
      const job = preflight.operation === 'analysis'
        ? await api.startCraftPatternAnalysisJob(projectId, {
          selected_segment_ids: preflight.selected_segments.map((segment) => segment.segment_id),
          author_focus: authorFocus.trim(),
          ...sharedConfirmation,
        })
        : await api.startCraftPatternFusionJob(projectId, {
          selected_asset_version_ids: preflight.selected_assets.map((asset) => asset.asset_version_id),
          author_focus: authorFocus.trim(),
          ...sharedConfirmation,
        })
      setActiveJob(job)
      setPreflight(null)
      setConfirmedSubmission(false)
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        try {
          await refreshAfterConflict(caught.message)
        } catch {
          setError(`${caught.message}；无法刷新预检依据，请重新打开拆书库。`)
        }
      } else {
        setError(caught instanceof Error ? caught.message : '无法启动拆书任务')
      }
    } finally {
      setBusy(null)
    }
  }

  async function cancelJob() {
    if (!activeJob || !jobRunning) return
    try {
      setActiveJob(await api.cancelJob(activeJob.id))
      setNotice('已停止后续调用；已完成的缓存和素材会保留。')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '无法停止拆书任务')
    }
  }

  async function retryJob() {
    if (!activeJob || !retryableStates.has(activeJob.state)) return
    setError(null)
    try {
      setActiveJob(await api.retryJob(activeJob.id))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '无法从已完成结果继续')
    }
  }

  function renderAssetGroup(
    id: string,
    eyebrow: string,
    title: string,
    description: string,
    groupAssets: CraftPatternAssetSummary[],
  ) {
    return (
      <section className="craft-asset-group" id={id} aria-labelledby={`${id}-title`}>
        <header>
          <div><small>{eyebrow}</small><h3 id={`${id}-title`}>{title}</h3></div>
          <span>{groupAssets.length} 张</span>
        </header>
        <p>{description}</p>
        {groupAssets.length > 0 ? (
          <div className="craft-asset-list">
            {groupAssets.map((asset) => (
              <CraftPatternAssetCard
                key={asset.id}
                asset={asset}
                detail={assetDetails[asset.id] ?? null}
                detailLoading={detailLoadingId === asset.id}
                detailError={detailErrors[asset.id] || null}
                selectedForFusion={selectedAssetVersionIds.has(asset.id)}
                lifecycleBusy={lifecycleBusyId === asset.id}
                onRequestDetail={() => { void loadAssetDetail(asset.id) }}
                onToggleFusion={() => toggleFusionAsset(asset)}
                onLifecycleChange={(state) => { void updateLifecycle(asset, state) }}
                onOpenSourceAsset={(assetId) => { void openSourceAsset(assetId) }}
                sourceAssetTitles={assetTitles}
              />
            ))}
          </div>
        ) : (
          <p className="craft-asset-empty">
            {assets === null ? '正在读取素材…' : '这一层还没有素材。从来源作品选阶段并完成预检后，AI 候选会保存到这里。'}
          </p>
        )}
      </section>
    )
  }

  return (
    <section className="craft-pattern-workbench" aria-labelledby="craft-pattern-title">
      <header className="craft-pattern-heading">
        <div>
          <p>CRAFT PATTERN V2 · 参考原文隔离</p>
          <h2 id="craft-pattern-title">从一本书的阶段变化，提炼可审查的写作模式</h2>
        </div>
        <span>只产出配方素材，不直接写入作品</span>
      </header>

      <nav className="craft-asset-route" aria-label="长篇拆解资产路径">
        <a href="#craft-source-works"><b>01</b><span>来源作品</span><small>选一本或其中阶段</small></a>
        <a href="#craft-stage-assets"><b>02</b><span>阶段卡</span><small>约 50 万字一张</small></a>
        <a href="#craft-book-assets"><b>03</b><span>单书演变</span><small>看钩子与兑现如何变化</small></a>
        <a href="#craft-fusion-assets"><b>04</b><span>多书融合</span><small>只使用已保存素材</small></a>
      </nav>

      <div className="craft-pattern-layout">
        <section className="craft-source-works" id="craft-source-works" aria-labelledby="craft-source-title">
          <header>
            <div><small>01 / 原文只在拆解任务中使用</small><h3 id="craft-source-title">选一本书的阶段</h3></div>
            <span>{analysisSelection.segmentIds.length} 段 · {formatWan(analysisSelection.characterCount)} 字</span>
          </header>
          <p>可只拆一个约 50 万字阶段，也可选整本。切换到另一本书时，上一本的勾选会自动清空。</p>
          {workspace.reference_works.length > 0 ? (
            <div className="craft-source-list">
              {workspace.reference_works.map((work) => {
                const selectedCount = work.segments.filter((segment) => selectedSegments.has(segment.id)).length
                return (
                  <article key={work.id} data-selected={selectedCount > 0}>
                    <header>
                      <div>
                        <small>{work.source_format.toUpperCase()} · {formatWan(work.total_characters)} 字</small>
                        <strong>{work.title}</strong>
                      </div>
                      <button type="button" onClick={() => selectWholeWork(work)} disabled={work.segments.length === 0}>
                        {selectedCount === work.segments.length && selectedCount > 0 ? '清空这本' : '选择整本'}
                      </button>
                    </header>
                    <div className="craft-stage-picker">
                      {work.segments.map((segment) => (
                        <label key={segment.id} data-selected={selectedSegments.has(segment.id)}>
                          <input
                            type="checkbox"
                            checked={selectedSegments.has(segment.id)}
                            onChange={() => toggleSegment(work.id, segment.id)}
                            aria-label={`选择${work.title}第 ${segment.ordinal} 阶段`}
                          />
                          <b>{String(segment.ordinal).padStart(2, '0')}</b>
                          <span>
                            <strong>{formatWan(segment.character_count)} 字</strong>
                            <small>{segment.chapter_start ?? '未识别章节起点'}{segment.chapter_end && segment.chapter_end !== segment.chapter_start ? ` → ${segment.chapter_end}` : ''}</small>
                          </span>
                        </label>
                      ))}
                    </div>
                  </article>
                )
              })}
            </div>
          ) : <p className="craft-asset-empty">先在上方导入一本拥有合法使用权的参考作品。</p>}
        </section>

        <aside className="craft-run-desk" aria-labelledby="craft-run-title">
          <header><small>CALL PREFLIGHT</small><h3 id="craft-run-title">调用前先算清范围和费用</h3></header>
          <label>
            这次想重点研究什么？
            <textarea
              value={authorFocus}
              rows={3}
              maxLength={1000}
              placeholder="例如：比较章末钩子如何在中期转向情绪兑现"
              onChange={(event) => {
                setAuthorFocus(event.target.value)
                invalidatePreflight()
              }}
            />
          </label>
          <div className="craft-operation-choices">
            <section>
              <span>拆一本书</span>
              <p>{analysisSelection.segmentIds.length > 0 ? `已选 ${analysisSelection.segmentIds.length} 个阶段` : '先在来源作品中勾选阶段'}</p>
              <button type="button" disabled={busy !== null || jobRunning} onClick={() => { void requestPreflight('analysis') }}>
                {busy === 'analysis' ? '正在预检…' : '预检“拆一本书”'}
              </button>
            </section>
            <section>
              <span>融合多本</span>
              <p>{selectedFusionAssets.length > 0 ? `已选 ${selectedFusionAssets.length} 张持久素材` : '从阶段卡或单书演变卡勾选'}</p>
              <button type="button" disabled={busy !== null || jobRunning} onClick={() => { void requestPreflight('fusion') }}>
                {busy === 'fusion' ? '正在预检…' : '预检“融合多本”'}
              </button>
            </section>
          </div>

          {error ? <p className="agent-error" role="alert">{error}</p> : null}
          {notice ? <p className="craft-run-notice" role="status" aria-live="polite">{notice}</p> : null}

          {preflight ? (
            <section className="craft-preflight" aria-label="拆书调用预检">
              <header>
                <div><small>{preflight.operation === 'analysis' ? '拆书分析' : '多书融合'}</small><strong>预计 {preflight.planned_calls} 次处理</strong></div>
                <span>{formatCost(preflight.estimated_cost_microusd)}</span>
              </header>
              <p className="craft-preflight-selection">
                <b>本次依据</b>
                {preflight.operation === 'analysis'
                  ? `${preflight.selected_works.map((work) => `《${work.title}》`).join('、')} · ${preflight.selected_segments.length} 个阶段`
                  : `${preflight.selected_assets.map((asset) => `《${asset.title}》v${asset.version}`).join('、')} · ${preflight.selected_works.length} 本来源作品`}
              </p>
              <dl className="craft-call-ledger">
                <div><dt>选中字符</dt><dd>{formatWan(preflight.selected_character_count)}</dd></div>
                <div><dt>原文分块分析</dt><dd>{preflight.map_calls}</dd></div>
                <div><dt>阶段卡</dt><dd>{preflight.stage_calls}</dd></div>
                <div><dt>单书演变</dt><dd>{preflight.book_calls}</dd></div>
                <div><dt>多书融合</dt><dd>{preflight.fusion_calls}</dd></div>
                <div><dt>缓存命中</dt><dd>{preflight.cache_hit_calls}</dd></div>
                <div><dt>预计计费调用</dt><dd>{preflight.uncached_calls}</dd></div>
                <div><dt>输入 / 输出 token</dt><dd>{preflight.estimated_input_tokens.toLocaleString('zh-CN')} / {preflight.estimated_output_tokens.toLocaleString('zh-CN')}</dd></div>
              </dl>
              <details className="craft-preflight-scope">
                <summary>查看模型、数据范围与预检指纹</summary>
                <dl>
                  <div><dt>模型线路</dt><dd>{preflight.profile_name ?? '当前默认线路'} · {preflight.provider} / {preflight.model}</dd></div>
                  <div><dt>数据类型</dt><dd>{preflight.data_types.join('、')}</dd></div>
                  <div><dt>外发范围</dt><dd>{preflight.content_scope}</dd></div>
                  <div><dt>预检指纹</dt><dd>{preflight.preflight_sha256}</dd></div>
                  <div><dt>规则版本</dt><dd>{preflight.prompt_version}</dd></div>
                </dl>
              </details>
              {hasExternalCalls && !hasUnknownCost ? (
                <label className="craft-budget-field">
                  允许启动的预估费用上限（美元）
                  <input
                    type="number"
                    inputMode="decimal"
                    min="0"
                    step="0.0001"
                    value={budgetUsd}
                    onChange={(event) => setBudgetUsd(event.target.value)}
                    aria-describedby="craft-budget-help"
                  />
                  <small id="craft-budget-help">填入不低于 {formatCost(preflight.estimated_cost_microusd)} 的数值才会启动；这里只校验本次预估，实际费用按模型服务商用量结算，可能有偏差。</small>
                </label>
              ) : null}
              <label className="craft-submit-confirm">
                <input
                  type="checkbox"
                  checked={confirmedSubmission}
                  onChange={(event) => setConfirmedSubmission(event.target.checked)}
                />
                <span>{hasExternalCalls
                  ? `确认按上述范围发送给 ${preflight.model}；只保存抽象结论和短证据摘要。`
                  : '本次全部复用本地缓存，确认按这份预检生成素材。'}</span>
              </label>
              {hasUnknownCost ? (
                <label className="craft-submit-confirm" data-warning="true">
                  <input
                    type="checkbox"
                    checked={confirmedUnknownCost}
                    onChange={(event) => setConfirmedUnknownCost(event.target.checked)}
                  />
                  <span>当前模型未配置价格，我理解费用未知，仍要继续。</span>
                </label>
              ) : null}
              {!budgetIsValid && budgetUsd.trim() !== '' ? <p className="craft-budget-error">费用上限低于预计值，任务不会启动。</p> : null}
              <button type="button" disabled={!submissionReady || busy !== null} onClick={() => { void startJob() }}>
                {busy ? '正在提交…' : preflight.operation === 'analysis' ? '确认预检并开始拆书' : '确认预检并融合多本'}
              </button>
            </section>
          ) : null}

          {activeJob ? (
            <section className="craft-job-status" role="status" aria-live="polite">
              <header><strong>{activeJob.current_step || '拆书任务已进入队列'}</strong><span>{activeJob.progress_current} / {activeJob.progress_total}</span></header>
              <progress value={activeJob.progress_current} max={Math.max(1, activeJob.progress_total)} aria-label="拆书任务进度" />
              <p>已完成 {activeJob.completed_calls} 次调用；中断后会复用已付费结果。</p>
              <div>
                {jobRunning ? <button type="button" onClick={() => { void cancelJob() }}>停止后续调用</button> : null}
                {retryableStates.has(activeJob.state) ? <button type="button" onClick={() => { void retryJob() }}>从缓存继续</button> : null}
                {onOpenTaskCenter ? <button type="button" onClick={onOpenTaskCenter}>打开任务中心</button> : null}
              </div>
            </section>
          ) : null}
        </aside>

        <section className="craft-asset-catalog" aria-label="写作模式素材库">
          <header>
            <div><small>02–04 / 可追溯的抽象素材</small><h3>从阶段到跨书的演变路径</h3></div>
            <span>{activeAssets.length} 个不可变内容版本</span>
          </header>
          <p>展开卡片才读取技法与证据。只有“可复用”的阶段卡和单书演变卡能加入新的多书融合。</p>
          {renderAssetGroup('craft-stage-assets', '02 / STAGE', '约 50 万字阶段卡', '看每个长篇阶段的钩子、兑现、情绪、场景和表达规律。', stageAssets)}
          {renderAssetGroup('craft-book-assets', '03 / EVOLUTION', '单书演变卡', '按阶段顺序展示一本书的长期承诺怎样加码和兑现。', bookAssets)}
          {renderAssetGroup('craft-fusion-assets', '04 / FUSION', '多书融合素材', '仅融合已持久化的抽象模式，不会再读取任何参考原文。', fusionAssets)}
        </section>
      </div>
    </section>
  )
}
