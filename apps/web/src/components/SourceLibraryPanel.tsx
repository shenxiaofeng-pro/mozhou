import type {
  SourceCard,
  SourceConfidence,
  SourceKind,
  Workspace,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { useState } from 'react'

import { api } from '../api'

interface SourceLibraryPanelProps {
  workspace: WorkspaceSummary
  onWorkspaceChanged: (workspace: Workspace | WorkspaceSummary) => void
}

const sourceKindLabels = {
  historical_record: '史料',
  news: '新闻',
  industry: '行业资料',
  personal_note: '个人笔记',
} as const

const confidenceLabels = {
  high: '高可信',
  medium: '待交叉核对',
  low: '仅作线索',
} as const

export function SourceLibraryPanel({ workspace, onWorkspaceChanged }: SourceLibraryPanelProps) {
  const [sourceKind, setSourceKind] = useState<SourceKind>('personal_note')
  const [title, setTitle] = useState('')
  const [sourceReference, setSourceReference] = useState('')
  const [yearStart, setYearStart] = useState(String(workspace.project.rebirth_year))
  const [yearEnd, setYearEnd] = useState(String(workspace.project.rebirth_year))
  const [confidence, setConfidence] = useState<SourceConfidence>('medium')
  const [excerpt, setExcerpt] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const [processingId, setProcessingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const confirmedCount = workspace.source_cards.filter((card) => card.confirmed).length

  function replaceCard(updated: SourceCard) {
    onWorkspaceChanged({
      ...workspace,
      source_cards: workspace.source_cards.map((card) => card.id === updated.id ? updated : card),
    })
  }

  async function createCard() {
    const start = Number(yearStart)
    const end = Number(yearEnd)
    if (!title.trim() || !sourceReference.trim() || !Number.isInteger(start) || !Number.isInteger(end)) return
    setIsCreating(true)
    setError(null)
    try {
      const created = await api.createSourceCard(workspace.project.id, {
        source_kind: sourceKind,
        title,
        source_reference: sourceReference,
        applicable_year_start: start,
        applicable_year_end: end,
        confidence,
        excerpt,
      })
      onWorkspaceChanged({
        ...workspace,
        source_cards: [...workspace.source_cards, created],
      })
      setTitle('')
      setSourceReference('')
      setExcerpt('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '资料卡创建失败')
    } finally {
      setIsCreating(false)
    }
  }

  async function toggleConfirmation(card: SourceCard) {
    setProcessingId(card.id)
    setError(null)
    try {
      replaceCard(await api.setSourceCardConfirmation(card.id, !card.confirmed, card.revision))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '资料卡确认状态更新失败')
    } finally {
      setProcessingId(null)
    }
  }

  return (
    <section className="source-library-card" aria-labelledby="source-library-title">
      <div className="pulse-heading">
        <h3 id="source-library-title">现实资料卡</h3>
        <span>{confirmedCount} / {workspace.source_cards.length} 已确认</span>
      </div>
      <p className="source-library-intro">先保存来源和适用年代，再由作者确认能否作为现实锚点。</p>
      <div className="source-card-list">
        {workspace.source_cards.map((card) => (
          <article key={card.id} data-confirmed={card.confirmed}>
            <header>
              <span>{sourceKindLabels[card.source_kind]}</span>
              <strong>{card.title}</strong>
              <small>{card.confirmed ? '已确认' : '待确认'}</small>
            </header>
            <p>{card.excerpt || '尚未记录摘要。'}</p>
            <dl>
              <div><dt>年代</dt><dd>{card.applicable_year_start}–{card.applicable_year_end}</dd></div>
              <div><dt>可信度</dt><dd>{confidenceLabels[card.confidence]}</dd></div>
              <div><dt>来源</dt><dd>{card.source_reference}</dd></div>
            </dl>
            <button
              type="button"
              onClick={() => toggleConfirmation(card)}
              disabled={processingId === card.id}
            >
              {processingId === card.id ? '正在更新…' : card.confirmed ? '撤回确认' : '确认为现实锚点'}
            </button>
          </article>
        ))}
      </div>
      <details className="source-card-create">
        <summary>新建资料卡</summary>
        <div className="source-form-row">
          <label>
            资料类型
            <select aria-label="资料类型" value={sourceKind} onChange={(event) => setSourceKind(event.target.value as SourceKind)}>
              <option value="historical_record">史料</option>
              <option value="news">新闻</option>
              <option value="industry">行业资料</option>
              <option value="personal_note">个人笔记</option>
            </select>
          </label>
          <label>
            可信度
            <select aria-label="资料可信度" value={confidence} onChange={(event) => setConfidence(event.target.value as SourceConfidence)}>
              <option value="high">高可信</option>
              <option value="medium">待交叉核对</option>
              <option value="low">仅作线索</option>
            </select>
          </label>
        </div>
        <label>
          标题
          <input aria-label="资料卡标题" value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} />
        </label>
        <label>
          来源
          <input aria-label="资料卡来源" value={sourceReference} maxLength={1000} onChange={(event) => setSourceReference(event.target.value)} placeholder="文件名、书目、网址或采访记录" />
        </label>
        <div className="source-form-row">
          <label>
            适用起年
            <input aria-label="资料适用起年" type="number" min={-3000} max={2100} value={yearStart} onChange={(event) => setYearStart(event.target.value)} />
          </label>
          <label>
            适用止年
            <input aria-label="资料适用止年" type="number" min={-3000} max={2100} value={yearEnd} onChange={(event) => setYearEnd(event.target.value)} />
          </label>
        </div>
        <label>
          摘要
          <textarea aria-label="资料卡摘要" value={excerpt} maxLength={4000} rows={3} onChange={(event) => setExcerpt(event.target.value)} />
        </label>
        <button
          type="button"
          onClick={createCard}
          disabled={isCreating || !title.trim() || !sourceReference.trim()}
        >{isCreating ? '正在保存…' : '保存为待确认资料卡'}</button>
      </details>
      {error ? <p className="source-card-error" role="alert">{error}</p> : null}
    </section>
  )
}
