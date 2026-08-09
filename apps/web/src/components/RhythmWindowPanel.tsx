import type { ChapterSummary } from '@mozhou/contracts'

interface RhythmWindowPanelProps {
  chapters: ChapterSummary[]
  activeChapterId: string
}

const rhythmRows = [
  { key: 'reader_promise', label: '承诺' },
  { key: 'opening_hook', label: '钩子' },
  { key: 'state_change', label: '变化' },
  { key: 'emotional_payoff', label: '回报' },
  { key: 'ending_cliffhanger', label: '悬念' },
] as const

const statusLabels = {
  planned: '待写',
  drafted: '草稿',
  reviewing: '审校',
  approved: '定稿',
} as const

export function RhythmWindowPanel({ chapters, activeChapterId }: RhythmWindowPanelProps) {
  const activeIndex = Math.max(0, chapters.findIndex((chapter) => chapter.id === activeChapterId))
  const start = Math.max(0, Math.min(activeIndex - 1, chapters.length - 3))
  const windowChapters = chapters.slice(start, start + 3)
  const repeatedRows = rhythmRows.filter(({ key }) => {
    const values = windowChapters.map((chapter) => chapter[key].trim()).filter(Boolean)
    return values.length > 1 && new Set(values).size < values.length
  })

  return (
    <section className="rhythm-window-card" aria-labelledby="rhythm-window-title">
      <div className="pulse-heading">
        <h3 id="rhythm-window-title">连续三章节奏窗</h3>
        <span>{windowChapters.length} / 3 章</span>
      </div>
      <p className="rhythm-intro">横向看承诺、兑现和悬念，避免连续几章只制造问题、不提供回报。</p>
      <div className="rhythm-matrix" role="table" aria-label="连续三章节奏分布">
        <div className="rhythm-corner" role="columnheader">节拍</div>
        {windowChapters.map((chapter) => (
          <div className="rhythm-chapter-head" role="columnheader" key={chapter.id}>
            <strong>第 {chapter.chapter_number} 章</strong>
            <span>{statusLabels[chapter.status]}</span>
          </div>
        ))}
        {rhythmRows.map(({ key, label }) => (
          <div className="rhythm-row" role="row" key={key}>
            <strong role="rowheader">{label}</strong>
            {windowChapters.map((chapter) => (
              <div role="cell" key={chapter.id} data-filled={Boolean(chapter[key].trim())}>
                {chapter[key] || '未设置'}
              </div>
            ))}
          </div>
        ))}
      </div>
      {repeatedRows.length > 0 ? (
        <p className="rhythm-warning" role="status">
          {repeatedRows.map((row) => row.label).join('、')}出现完全相同的节拍，建议拉开变化。
        </p>
      ) : null}
    </section>
  )
}
