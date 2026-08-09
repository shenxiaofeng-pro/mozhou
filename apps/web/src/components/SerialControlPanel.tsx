import type { ChapterStatus, WorkspaceSummary } from '@mozhou/contracts'

interface SerialControlPanelProps {
  workspace: WorkspaceSummary
}

const statusLabels: Record<ChapterStatus, string> = {
  planned: '待写',
  drafted: '草稿',
  reviewing: '审校中',
  approved: '已定稿',
}

export function SerialControlPanel({ workspace }: SerialControlPanelProps) {
  const card = workspace.resume_card
  if (!card) return null
  const issues = workspace.continuity_issues

  return (
    <section className="serial-control-card" aria-labelledby="serial-control-title">
      <div className="pulse-heading">
        <h3 id="serial-control-title">断更恢复与连续性</h3>
        <span>{card.warning_count > 0 ? `${card.warning_count} 项需注意` : '可继续写'}</span>
      </div>
      <div className="resume-marker">
        <span>上次停在 · 第 {card.chapter_number} 章 · {statusLabels[card.chapter_status]}</span>
        <strong>{card.chapter_title}</strong>
        <p>{card.last_progress}</p>
      </div>
      <div className="resume-entry">
        <small>重新进入</small>
        <p>{card.next_entry}</p>
      </div>
      <div className="resume-counts" aria-label="待处理事项">
        <span><strong>{card.open_threads.length}</strong> 条开放伏笔</span>
        <span><strong>{card.active_entities.length}</strong> 项人物资源</span>
        <span><strong>{card.pending_reviews}</strong> 项待确认</span>
      </div>

      {card.open_threads.length > 0 || card.active_entities.length > 0 ? (
        <details className="resume-evidence">
          <summary>查看复更依据</summary>
          {card.open_threads.map((item) => (
            <article key={`thread-${item.label}`}>
              <span>伏笔 · {item.source}</span>
              <strong>{item.label}</strong>
              <p>{item.detail}</p>
            </article>
          ))}
          {card.active_entities.map((item) => (
            <article key={`entity-${item.label}`}>
              <span>{item.source}</span>
              <strong>{item.label}</strong>
              <p>{item.detail}</p>
            </article>
          ))}
        </details>
      ) : null}

      <details className="continuity-diagnosis" open={issues.some((issue) => issue.severity === 'warning')}>
        <summary>连续性检查 · {issues.length} 项</summary>
        {issues.length > 0 ? (
          <ul>
            {issues.map((issue) => (
              <li key={issue.id} data-severity={issue.severity}>
                <span>{issue.severity === 'warning' ? '需处理' : '建议'}</span>
                <strong>{issue.title}</strong>
                <p>{issue.detail}</p>
                {issue.source_labels.length > 0 ? <small>依据：{issue.source_labels.join(' · ')}</small> : null}
              </li>
            ))}
          </ul>
        ) : <p className="continuity-clear">当前没有确定性连续性问题。</p>}
      </details>
    </section>
  )
}
