import type {
  Chapter,
  FactKind,
  TimelineEvent,
  Workspace,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { useMemo, useState } from 'react'

import { api } from '../api'
import { isRebirthGenre } from '../genre'

interface FactTimelinePanelProps {
  workspace: WorkspaceSummary
  chapter: Chapter
  onWorkspaceChanged: (workspace: Workspace | WorkspaceSummary) => void
}

const factKindLabels: Record<FactKind, string> = {
  state_change: '正式变化',
  open_thread: '待解伏笔',
}

const changeSetStateLabels = {
  candidate: '等待作者确认',
  applied: '已回灌',
  rejected: '已跳过',
} as const

function TimelineTrack({ title, events, emptyText }: {
  title: string
  events: TimelineEvent[]
  emptyText: string
}) {
  return (
    <div className="timeline-track">
      <div className="timeline-track-title">
        <strong>{title}</strong>
        <span>{events.length}</span>
      </div>
      {events.length > 0 ? (
        <ol>
          {events.map((event) => (
            <li key={event.id}>
              <time>{event.event_year}</time>
              <div>
                <strong>{event.title}</strong>
                {event.summary ? <p>{event.summary}</p> : null}
              </div>
            </li>
          ))}
        </ol>
      ) : <p className="timeline-empty">{emptyText}</p>}
    </div>
  )
}

export function FactTimelinePanel({
  workspace,
  chapter,
  onWorkspaceChanged,
}: FactTimelinePanelProps) {
  const [eventYear, setEventYear] = useState(String(workspace.project.rebirth_year))
  const [eventTitle, setEventTitle] = useState('')
  const [eventSummary, setEventSummary] = useState('')
  const [isAddingEvent, setIsAddingEvent] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const rebirthStory = isRebirthGenre(workspace.project.genre)
  const originalEvents = workspace.timeline_events.filter((event) => event.layer === 'original')
  const novelEvents = workspace.timeline_events.filter((event) => event.layer === 'novel')
  const changeSet = useMemo(() => {
    const current = workspace.fact_change_sets.filter((item) => (
      item.chapter_id === chapter.id && item.chapter_revision === chapter.revision
    ))
    return current.at(-1) ?? null
  }, [chapter.id, chapter.revision, workspace.fact_change_sets])
  const chapterFacts = workspace.story_facts.filter((fact) => fact.source_chapter_id === chapter.id)

  async function addOriginalEvent() {
    const year = Number(eventYear)
    if (!Number.isInteger(year) || !eventTitle.trim()) return
    setIsAddingEvent(true)
    setError(null)
    try {
      const created = await api.createOriginalTimelineEvent(workspace.project.id, {
        event_year: year,
        title: eventTitle,
        summary: eventSummary,
      })
      onWorkspaceChanged({
        ...workspace,
        timeline_events: [...workspace.timeline_events, created],
      })
      setEventTitle('')
      setEventSummary('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : `${rebirthStory ? '原始时间线' : '世界底稿'}事件添加失败`)
    } finally {
      setIsAddingEvent(false)
    }
  }

  return (
    <>
      {changeSet ? (
        <section className="fact-review-card" aria-labelledby="legacy-fact-review-title">
          <div className="pulse-heading">
            <h3 id="legacy-fact-review-title">旧版事实回流记录</h3>
            <span>{changeSetStateLabels[changeSet.state]}</span>
          </div>
          <p className="fact-review-intro">旧版候选仅供追溯；新的定稿事实请在上方“定稿回流审签”中处理。</p>
          <div className="fact-candidate-list" aria-label="旧版事实候选">
            {changeSet.changes.map((change) => (
              <div key={change.id} className="legacy-fact-candidate">
                <small>{factKindLabels[change.kind]}</small>
                <strong>{change.content}</strong>
              </div>
            ))}
          </div>
          <p className="fact-review-result">
            {changeSet.state === 'applied'
              ? `旧版记录中有 ${chapterFacts.length} 条事实已生效。`
              : changeSet.state === 'rejected'
                ? '这批旧版候选已跳过。'
                : '这批旧版候选尚未处理，当前版本保持只读。'}
          </p>
        </section>
      ) : null}

      <section className="dual-timeline-card" aria-labelledby="dual-timeline-title">
        <div className="pulse-heading">
          <h3 id="dual-timeline-title">双时间线</h3>
          <span>{rebirthStory ? '现实底稿 / 小说改写' : '世界底稿 / 小说演变'}</span>
        </div>
        <div className="timeline-rails">
          <TimelineTrack title={rebirthStory ? '原始' : '世界原设'} events={originalEvents} emptyText={rebirthStory ? '录入现实或历史锚点。' : '录入世界历史、规则或纪年锚点。'} />
          <TimelineTrack title="小说" events={novelEvents} emptyText="确认事实后自动落轨。" />
        </div>
        <details className="timeline-add">
          <summary>添加{rebirthStory ? '原始时间线' : '世界底稿'}事件</summary>
          <label>
            年份
            <input
              aria-label={`${rebirthStory ? '原始' : '世界底稿'}事件年份`}
              type="number"
              min={-3000}
              max={2100}
              value={eventYear}
              onChange={(event) => setEventYear(event.target.value)}
            />
          </label>
          <label>
            事件
            <input
              aria-label={`${rebirthStory ? '原始' : '世界底稿'}事件标题`}
              maxLength={120}
              value={eventTitle}
              onChange={(event) => setEventTitle(event.target.value)}
              placeholder={rebirthStory ? '例如：南平铝厂推进改制' : '例如：赤月纪元首次结界崩塌'}
            />
          </label>
          <label>
            资料摘要
            <textarea
              aria-label={`${rebirthStory ? '原始' : '世界底稿'}事件摘要`}
              maxLength={1000}
              rows={2}
              value={eventSummary}
              onChange={(event) => setEventSummary(event.target.value)}
              placeholder={rebirthStory ? '记录可核验的现实背景' : '记录已确认的世界历史或规则背景'}
            />
          </label>
          <button
            type="button"
            onClick={addOriginalEvent}
            disabled={isAddingEvent || !eventTitle.trim() || !Number.isInteger(Number(eventYear))}
          >{isAddingEvent ? '正在添加…' : `写入${rebirthStory ? '原始时间线' : '世界底稿'}`}</button>
        </details>
        {error ? <p className="timeline-error" role="alert">{error}</p> : null}
      </section>
    </>
  )
}
