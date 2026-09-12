import type {
  FutureKnowledge,
  KnowledgeConfidence,
  KnowledgeReviewAction,
  Workspace,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { useState } from 'react'

import { api } from '../api'
import { isRebirthGenre } from '../genre'

interface FutureKnowledgePanelProps {
  workspace: WorkspaceSummary
  onWorkspaceChanged: (workspace: Workspace | WorkspaceSummary) => void
}

const confidenceLabels: Record<KnowledgeConfidence, string> = {
  certain: '确定记忆',
  likely: '大概率',
  uncertain: '模糊记忆',
}

const statusLabels = {
  valid: '当前有效',
  candidate_invalid: '分歧后待复核',
  invalid: '已确认失效',
} as const

export function FutureKnowledgePanel({
  workspace,
  onWorkspaceChanged,
}: FutureKnowledgePanelProps) {
  const [futureYear, setFutureYear] = useState(String(workspace.project.rebirth_year + 5))
  const [content, setContent] = useState('')
  const [sourceNote, setSourceNote] = useState('')
  const [confidence, setConfidence] = useState<KnowledgeConfidence>('likely')
  const [isAdding, setIsAdding] = useState(false)
  const [processingId, setProcessingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const rebirthStory = isRebirthGenre(workspace.project.genre)
  const knowledgeLabel = rebirthStory ? '未来知识' : '先验 / 预言知识'
  const reviewCount = workspace.future_knowledge.filter((item) => item.status === 'candidate_invalid').length

  function replaceKnowledge(updated: FutureKnowledge) {
    onWorkspaceChanged({
      ...workspace,
      future_knowledge: workspace.future_knowledge.map((item) => (
        item.id === updated.id ? updated : item
      )),
    })
  }

  async function addKnowledge() {
    const year = Number(futureYear)
    if (!Number.isInteger(year) || !content.trim()) return
    setIsAdding(true)
    setError(null)
    try {
      const created = await api.createFutureKnowledge(workspace.project.id, {
        future_year: year,
        content,
        source_note: sourceNote,
        confidence,
      })
      onWorkspaceChanged({
        ...workspace,
        future_knowledge: [...workspace.future_knowledge, created],
      })
      setContent('')
      setSourceNote('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '未来知识添加失败')
    } finally {
      setIsAdding(false)
    }
  }

  async function reviewKnowledge(item: FutureKnowledge, action: KnowledgeReviewAction) {
    setProcessingId(item.id)
    setError(null)
    try {
      replaceKnowledge(await api.reviewFutureKnowledge(item.id, action, item.revision))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '未来知识复核失败')
    } finally {
      setProcessingId(null)
    }
  }

  return (
    <section className="future-knowledge-card" aria-labelledby="future-knowledge-title">
      <div className="pulse-heading">
        <h3 id="future-knowledge-title">{knowledgeLabel}账本</h3>
        <span>{reviewCount > 0 ? `${reviewCount} 条待复核` : `${workspace.future_knowledge.length} 条记录`}</span>
      </div>
      <p className="knowledge-intro">
        {rebirthStory
          ? '小说时间线发生分歧时，只把相关年份之后的记忆标为待复核，不会自动删除。'
          : '记录角色明确掌握的预言、推演或先验信息；世界线变化后只标记待复核，不会自动当成事实。'}
      </p>
      {workspace.future_knowledge.length > 0 ? (
        <ol className="knowledge-list">
          {workspace.future_knowledge.map((item) => (
            <li key={item.id} data-status={item.status}>
              <div className="knowledge-meta">
                <time>{item.future_year}</time>
                <span>{confidenceLabels[item.confidence]}</span>
                <strong>{statusLabels[item.status]}</strong>
              </div>
              <p>{item.content}</p>
              {item.source_note ? <small>记忆来源：{item.source_note}</small> : null}
              {item.status === 'candidate_invalid' ? (
                <div className="knowledge-review-actions">
                  <button
                    type="button"
                    onClick={() => reviewKnowledge(item, 'keep_valid')}
                    disabled={processingId === item.id}
                  >仍然有效</button>
                  <button
                    type="button"
                    onClick={() => reviewKnowledge(item, 'confirm_invalid')}
                    disabled={processingId === item.id}
                  >确认失效</button>
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      ) : <p className="knowledge-empty">{rebirthStory ? '先记录一条主角确信自己知道的未来事件。' : '先记录一条角色明确知道的预言、推演或先验信息。'}</p>}
      <details className="knowledge-add">
        <summary>记录{knowledgeLabel}</summary>
        <div className="knowledge-form-row">
          <label>
            发生年份
            <input
              aria-label={`${knowledgeLabel}年份`}
              type="number"
              min={workspace.project.rebirth_year}
              max={2100}
              value={futureYear}
              onChange={(event) => setFutureYear(event.target.value)}
            />
          </label>
          <label>
            置信度
            <select
              aria-label="未来知识置信度"
              value={confidence}
              onChange={(event) => setConfidence(event.target.value as KnowledgeConfidence)}
            >
              <option value="certain">确定记忆</option>
              <option value="likely">大概率</option>
              <option value="uncertain">模糊记忆</option>
            </select>
          </label>
        </div>
        <label>
          记忆内容
          <textarea
            aria-label={`${knowledgeLabel}内容`}
            maxLength={500}
            rows={2}
            value={content}
            onChange={(event) => setContent(event.target.value)}
            placeholder={rebirthStory ? '例如：2003 年建阳会开出第一家大型连锁超市' : '例如：赤月升起后的第三天，北境结界会出现裂隙'}
          />
        </label>
        <label>
          来源说明
          <input
            aria-label={`${knowledgeLabel}来源`}
            maxLength={500}
            value={sourceNote}
            onChange={(event) => setSourceNote(event.target.value)}
            placeholder={rebirthStory ? '上一世亲历、新闻记忆或他人告知' : '预言文本、占星推演、导师告知或角色亲历'}
          />
        </label>
        <button
          type="button"
          onClick={addKnowledge}
          disabled={isAdding || !content.trim() || !Number.isInteger(Number(futureYear))}
        >{isAdding ? '正在记录…' : `写入${knowledgeLabel}账本`}</button>
      </details>
      {error ? <p className="knowledge-error" role="alert">{error}</p> : null}
    </section>
  )
}
