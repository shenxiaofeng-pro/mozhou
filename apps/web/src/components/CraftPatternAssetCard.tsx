import type {
  CraftPatternAsset,
  CraftPatternAssetSummary,
  CraftPatternItem,
  CraftPatternLifecycleState,
} from '@mozhou/contracts'

import { craftAssetTypeLabels, craftDimensionLabels } from './craftPatternLabels'

interface CraftPatternAssetCardProps {
  asset: CraftPatternAssetSummary
  detail: CraftPatternAsset | null
  detailLoading: boolean
  detailError: string | null
  selectedForFusion: boolean
  lifecycleBusy: boolean
  onRequestDetail: () => void
  onToggleFusion: () => void
  onLifecycleChange: (state: CraftPatternLifecycleState) => void
  onOpenSourceAsset?: (assetVersionId: string) => void
  sourceAssetTitles?: Record<string, string>
  showFusionSelection?: boolean
  showLifecycleAction?: boolean
  installAction?: {
    label: string
    busyLabel?: string
    busy: boolean
    disabled: boolean
    onClick: () => void
  }
  craftItemAction?: {
    label: (item: CraftPatternItem) => string
    disabled: (item: CraftPatternItem) => boolean
    onClick: (item: CraftPatternItem) => void
  }
}

function formatConfidence(confidence: number): string {
  return `${Math.round(Math.max(0, Math.min(1, confidence)) * 100)}%`
}

function formatCoordinate(start: number, end: number): string {
  return `${(start + 1).toLocaleString('zh-CN')}–${end.toLocaleString('zh-CN')} 字`
}

export function CraftPatternAssetCard({
  asset,
  detail,
  detailLoading,
  detailError,
  selectedForFusion,
  lifecycleBusy,
  onRequestDetail,
  onToggleFusion,
  onLifecycleChange,
  onOpenSourceAsset,
  sourceAssetTitles = {},
  showFusionSelection = true,
  showLifecycleAction = true,
  installAction,
  craftItemAction,
}: CraftPatternAssetCardProps) {
  const active = asset.lifecycle_state === 'active'
  const fusionEligible = active && asset.asset_type !== 'fusion_material'
  const lifecycleLabel = asset.lifecycle_state === null ? '未装入当前作品' : active ? '可复用' : '已归档'

  return (
    <article
      className="craft-asset-card"
      id={`craft-asset-${asset.id}`}
      data-asset-type={asset.asset_type}
      data-lifecycle={asset.lifecycle_state}
    >
      <header>
        <div>
          <small>{craftAssetTypeLabels[asset.asset_type]} · 版本 {asset.version}</small>
          <h4>{asset.title}</h4>
        </div>
        <span>{lifecycleLabel}</span>
      </header>

      <p className="craft-asset-summary">{asset.summary}</p>
      <dl className="craft-asset-provenance">
        <div><dt>来源作品</dt><dd>{asset.source_work_ids.length} 本</dd></div>
        <div><dt>阶段范围</dt><dd>{asset.source_segment_ids.length || '融合资产'}</dd></div>
        <div><dt>技法结论</dt><dd>{detail ? `${detail.craft_items.length} 项` : '展开查看'}</dd></div>
        <div><dt>模型</dt><dd>{asset.model}</dd></div>
      </dl>

      <details
        className="craft-asset-detail"
        onToggle={(event) => {
          if (event.currentTarget.open && !detail && !detailLoading) onRequestDetail()
        }}
      >
        <summary>查看技法与来源证据</summary>
        {detailLoading ? <p role="status">正在读取这张卡的技法证据…</p> : null}
        {detailError ? <p className="agent-error" role="alert">{detailError}</p> : null}
        {detail ? (
          <>
            {detail.author_focus ? <p className="craft-asset-focus"><b>本次重点</b>{detail.author_focus}</p> : null}
            {detail.source_asset_version_ids.length > 0 ? (
              <nav className="craft-source-lineage" aria-label="这张卡的来源素材">
                <strong>由这些已保存素材归纳</strong>
                <div>
                  {detail.source_asset_version_ids.map((sourceAssetId) => (
                    <button
                      type="button"
                      key={sourceAssetId}
                      onClick={() => onOpenSourceAsset?.(sourceAssetId)}
                      disabled={!onOpenSourceAsset}
                    >
                      {sourceAssetTitles[sourceAssetId] ?? `查看来源素材 ${sourceAssetId.slice(0, 8)}`}
                    </button>
                  ))}
                </div>
              </nav>
            ) : null}
            <div className="craft-item-list">
              {detail.craft_items.map((item, index) => (
                <section className="craft-item" key={`${item.dimension}:${item.name}:${index}`}>
                  <header>
                    <span>{craftDimensionLabels[item.dimension]}</span>
                    <strong>{item.name}</strong>
                  </header>
                  <p>{item.observation}</p>
                  <dl>
                    <div><dt>可迁移规则</dt><dd>{item.transferable_rule}</dd></div>
                    <div><dt>改编风险</dt><dd>{item.adaptation_risk}</dd></div>
                  </dl>
                  <details className="craft-evidence-drawer">
                    <summary>查看 {item.evidence.length} 条来源证据</summary>
                    <ol>
                      {item.evidence.map((evidence) => (
                        <li key={evidence.id}>
                          <div>
                            <strong>{evidence.work_title}</strong>
                            <span>{formatConfidence(evidence.confidence)} 置信</span>
                          </div>
                          <p>{evidence.evidence_summary}</p>
                          <small>
                            {evidence.stage_label}
                            {evidence.chapter_label ? ` · ${evidence.chapter_label}` : ''}
                            {' · '}{formatCoordinate(evidence.absolute_start_char, evidence.absolute_end_char)}
                            {' · 证据指纹 '}{evidence.evidence_sha256.slice(0, 10)}
                          </small>
                        </li>
                      ))}
                    </ol>
                  </details>
                  {craftItemAction ? (
                    <button
                      className="craft-item-action"
                      type="button"
                      disabled={craftItemAction.disabled(item)}
                      onClick={() => craftItemAction.onClick(item)}
                    >{craftItemAction.label(item)}</button>
                  ) : null}
                </section>
              ))}
            </div>
            <small className="craft-content-fingerprint">内容指纹 {detail.content_sha256.slice(0, 12)} · 只供版本校验</small>
          </>
        ) : null}
      </details>

      {showFusionSelection || (showLifecycleAction && asset.lifecycle_state !== null) || installAction ? (
        <footer className="craft-asset-actions">
          {showFusionSelection ? (
            <label data-selected={selectedForFusion}>
              <input
                type="checkbox"
                checked={selectedForFusion}
                disabled={!fusionEligible || lifecycleBusy}
                onChange={onToggleFusion}
                aria-label={`选择《${asset.title}》用于多书融合`}
              />
              <span>
                {asset.asset_type === 'fusion_material'
                  ? '融合结果不再作为本轮来源'
                  : active ? '加入本次多书融合' : '恢复后才能融合'}
              </span>
            </label>
          ) : null}
          {showLifecycleAction && asset.lifecycle_state !== null ? (
            <button
              type="button"
              disabled={lifecycleBusy || asset.lifecycle_revision === null}
              onClick={() => onLifecycleChange(active ? 'archived' : 'active')}
              aria-label={`${active ? '归档' : '恢复'}素材《${asset.title}》`}
            >
              {lifecycleBusy ? '正在更新…' : active ? '归档素材' : '恢复素材'}
            </button>
          ) : null}
          {installAction ? (
            <button
              type="button"
              disabled={installAction.disabled || installAction.busy}
              onClick={installAction.onClick}
            >
              {installAction.busy ? (installAction.busyLabel ?? '正在装入…') : installAction.label}
            </button>
          ) : null}
        </footer>
      ) : null}
    </article>
  )
}
