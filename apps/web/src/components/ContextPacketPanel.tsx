import type {
  ContextDirective,
  ContextDirectiveAction,
  ContextItem,
  ContextPacket,
  ContextTier,
} from '@mozhou/contracts'

import { CreativeContextPreflight } from './CreativeContextPreflight'

interface ContextPacketPanelProps {
  packet: ContextPacket
  directives?: ContextDirective[]
  busy?: boolean
  onSetDirective?: (item: ContextItem, action: ContextDirectiveAction) => void
  onClearDirective?: (item: ContextItem) => void
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

function isProtectedPatternItem(item: ContextItem): boolean {
  const itemKind = String(item.kind).toLowerCase()
  return itemKind.includes('writing_pattern')
    || itemKind.includes('craft_pattern')
    || item.source_refs.some((source) => {
      const kind = source.kind.toLowerCase()
      return kind.includes('reference') || kind.includes('craft_pattern') || kind.includes('writing_pattern')
    })
}

function contentExcerpt(content: string): string {
  if (content.length <= 180) return content
  return `${content.slice(0, 180)}…`
}

export function ContextPacketPanel({
  packet,
  directives = [],
  busy = false,
  onSetDirective,
  onClearDirective,
}: ContextPacketPanelProps) {
  const included = packet.items.filter((item) => item.included)
  const excluded = packet.items.filter((item) => !item.included)
  const containsProtectedPattern = packet.items.some(isProtectedPatternItem)

  function directiveFor(item: ContextItem): ContextDirective | undefined {
    const source = item.source_refs[0]
    if (!source) return undefined
    return directives.find((directive) => (
      directive.source_kind === source.kind && directive.source_id === source.source_id
    ))
  }

  function renderItem(item: ContextItem) {
    const protectedPattern = isProtectedPatternItem(item)
    const directive = directiveFor(item)
    const effectiveDirective = directive?.action ?? item.directive
    const canDirect = (
      Boolean(onSetDirective && onClearDirective)
      && !protectedPattern
      && item.source_refs.length > 0
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
            <strong>{protectedPattern ? '写作模式规则' : item.label}</strong>
          </div>
          <small>{item.token_estimate.toLocaleString('zh-CN')} Token</small>
        </div>
        <p>{protectedPattern
          ? '已编译为抽象创作规则；这里不会显示参考作品原文、书名或证据句。'
          : contentExcerpt(item.content)}</p>
        <dl>
          <div><dt>{item.included ? '入选原因' : '未选原因'}</dt><dd>{protectedPattern ? '已启用写作模式的安全规则' : item.included ? item.selection_reason : item.exclusion_reason}</dd></div>
          <div><dt>来源</dt><dd>{protectedPattern ? '已确认的抽象模式快照' : sourceLabel(item)}</dd></div>
        </dl>
        {protectedPattern ? null : item.conflict_notes.map((note) => <p className="context-conflict-note" key={note}>{note}</p>)}
        <div className="context-item-actions">
          {item.required ? <span>硬约束 · 不可静默移除</span> : null}
          {canDirect && effectiveDirective == null ? (
            <>
              <button type="button" disabled={busy} onClick={() => onSetDirective?.(item, 'pin')}>本章固定</button>
              <button type="button" disabled={busy} onClick={() => onSetDirective?.(item, 'exclude')}>本章排除</button>
            </>
          ) : null}
          {canDirect && effectiveDirective != null ? (
            <button type="button" disabled={busy} onClick={() => onClearDirective?.(item)}>
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
      </header>
      <CreativeContextPreflight packet={packet} />
      {packet.overflow_tokens > 0 ? (
        <p className="context-overflow" role="alert">
          硬约束超出预算 {packet.overflow_tokens.toLocaleString('zh-CN')} Token；系统已完整保留并明确标记，没有静默丢弃。
        </p>
      ) : null}
      {packet.conflict_notes.length > 0 ? (
        containsProtectedPattern ? (
          <p className="context-conflict-list">已检测到 {packet.conflict_notes.length} 条模式约束冲突；仅向模型提供抽象后的安全决策。</p>
        ) : (
          <ul className="context-conflict-list">
            {packet.conflict_notes.map((note) => <li key={note}>{note}</li>)}
          </ul>
        )
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
