import type {
  ContextDirective,
  ContextDirectiveAction,
  ContextItem,
  ContextPacket,
  ContextTier,
} from '@mozhou/contracts'

interface ContextPacketPanelProps {
  packet: ContextPacket
  directives: ContextDirective[]
  busy: boolean
  onSetDirective: (item: ContextItem, action: ContextDirectiveAction) => void
  onClearDirective: (item: ContextItem) => void
}

const tierLabels: Record<ContextTier, string> = {
  hard_constraint: '硬约束',
  canon: '正式事实',
  current_state: '人物与伏笔',
  recent_chapter: '近期章节',
  distant_chapter: '远期摘要',
  timeline: '双时间线',
  reality_source: '现实资料',
  blueprint: '批准蓝图',
}

function sourceLabel(item: ContextItem): string {
  const source = item.source_refs[0]
  if (!source) return '本地编译规则'
  const range = source.character_start !== null && source.character_end !== null
    ? ` · 字符 ${source.character_start.toLocaleString('zh-CN')}–${source.character_end.toLocaleString('zh-CN')}`
    : ''
  return `${source.label}${range}`
}

function contentExcerpt(content: string): string {
  if (content.length <= 180) return content
  return `${content.slice(0, 180)}…`
}

export function ContextPacketPanel({
  packet,
  directives,
  busy,
  onSetDirective,
  onClearDirective,
}: ContextPacketPanelProps) {
  const included = packet.items.filter((item) => item.included)
  const excluded = packet.items.filter((item) => !item.included)
  const usagePercent = Math.min(100, Math.round(packet.used_tokens / packet.token_budget * 100))

  function directiveFor(item: ContextItem): ContextDirective | undefined {
    const source = item.source_refs[0]
    if (!source) return undefined
    return directives.find((directive) => (
      directive.source_kind === source.kind && directive.source_id === source.source_id
    ))
  }

  function renderItem(item: ContextItem) {
    const directive = directiveFor(item)
    const effectiveDirective = directive?.action ?? item.directive
    const canDirect = (
      item.source_refs.length > 0
      && (
        effectiveDirective != null
        || (
          !item.required
          && (
            item.included
            || item.exclusion_reason?.includes('预算') === true
          )
        )
      )
    )
    return (
      <li key={item.id} className="context-packet-item" data-included={item.included}>
        <div className="context-packet-item-head">
          <div>
            <span>{tierLabels[item.tier]}</span>
            <strong>{item.label}</strong>
          </div>
          <small>{item.token_estimate.toLocaleString('zh-CN')} Token</small>
        </div>
        <p>{contentExcerpt(item.content)}</p>
        <dl>
          <div><dt>{item.included ? '入选原因' : '未选原因'}</dt><dd>{item.included ? item.selection_reason : item.exclusion_reason}</dd></div>
          <div><dt>来源</dt><dd>{sourceLabel(item)}</dd></div>
        </dl>
        {item.conflict_notes.map((note) => <p className="context-conflict-note" key={note}>{note}</p>)}
        <div className="context-item-actions">
          {item.required ? <span>硬约束 · 不可静默移除</span> : null}
          {canDirect && effectiveDirective == null ? (
            <>
              <button type="button" disabled={busy} onClick={() => onSetDirective(item, 'pin')}>本章固定</button>
              <button type="button" disabled={busy} onClick={() => onSetDirective(item, 'exclude')}>本章排除</button>
            </>
          ) : null}
          {canDirect && effectiveDirective != null ? (
            <button type="button" disabled={busy} onClick={() => onClearDirective(item)}>
              取消{effectiveDirective === 'pin' ? '固定' : '排除'}
            </button>
          ) : null}
        </div>
      </li>
    )
  }

  return (
    <section className="context-packet-panel" aria-labelledby="context-packet-title">
      <header>
        <div>
          <small>CONTEXT PACKET · {packet.compiler_version}</small>
          <h5 id="context-packet-title">本次模型真正会读到什么</h5>
        </div>
        <span>{packet.packet_sha256.slice(0, 8)}</span>
      </header>
      <div className="context-budget-meter">
        <div>
          <strong>{packet.used_tokens.toLocaleString('zh-CN')}</strong>
          <span>/ {packet.token_budget.toLocaleString('zh-CN')} Token</span>
        </div>
        <div className="context-budget-track" aria-label={`上下文预算使用 ${usagePercent}%`}>
          <i style={{ width: `${usagePercent}%` }} />
        </div>
        <p>{included.length} 项入选 · {excluded.length} 项未选 · 快照 {packet.id.slice(0, 8)}</p>
      </div>
      {packet.overflow_tokens > 0 ? (
        <p className="context-overflow" role="alert">
          硬约束超出预算 {packet.overflow_tokens.toLocaleString('zh-CN')} Token；系统已完整保留并明确标记，没有静默丢弃。
        </p>
      ) : null}
      {packet.conflict_notes.length > 0 ? (
        <ul className="context-conflict-list">
          {packet.conflict_notes.map((note) => <li key={note}>{note}</li>)}
        </ul>
      ) : null}
      <details open>
        <summary>已入选 · {included.length}</summary>
        <ul className="context-packet-items">{included.map(renderItem)}</ul>
      </details>
      <details>
        <summary>未入选与原因 · {excluded.length}</summary>
        <ul className="context-packet-items">{excluded.map(renderItem)}</ul>
      </details>
    </section>
  )
}
