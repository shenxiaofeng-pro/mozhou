import { useEffect, useRef } from 'react'

interface AuthorUtilityDrawerProps {
  onClose: () => void
  onOpenSerial: () => void
  onOpenAuthorTools: () => void
  onOpenWritingPatterns: () => void
  onOpenResearch: () => void
  onOpenTasks: () => void
  onOpenComicDrama: () => void
  onOpenReferences: () => void
}

const FOCUSABLE = [
  'button:not([disabled])',
  '[href]',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

export function AuthorUtilityDrawer({
  onClose,
  onOpenSerial,
  onOpenAuthorTools,
  onOpenWritingPatterns,
  onOpenResearch,
  onOpenTasks,
  onOpenComicDrama,
  onOpenReferences,
}: AuthorUtilityDrawerProps) {
  const dialogRef = useRef<HTMLElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    closeRef.current?.focus()

    function handleKeydown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab' || !dialogRef.current) return
      const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)]
      const first = focusable[0]
      const last = focusable.at(-1)
      if (!first || !last) return
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    window.addEventListener('keydown', handleKeydown)
    return () => window.removeEventListener('keydown', handleKeydown)
  }, [onClose])

  const entries = [
    { eyebrow: 'SERIAL', title: '连载台', detail: '日更、存稿和章节搜索', action: onOpenSerial, label: '打开连载工作台' },
    { eyebrow: 'AUTHOR', title: '作者工具', detail: '日历、批注、灵感与图谱', action: onOpenAuthorTools, label: '打开作者工具台' },
    { eyebrow: 'CRAFT', title: '写作配方', detail: '管理抽象写法与参考模式', action: onOpenWritingPatterns, label: '打开写作配方' },
    { eyebrow: 'SOURCE', title: '资料研究', detail: '整理带来源的现实资料卡', action: onOpenResearch, label: '打开资料研究台' },
    { eyebrow: 'JOBS', title: '任务中心', detail: '查看长任务、重试与断点', action: onOpenTasks, label: '打开任务中心' },
    { eyebrow: 'COMIC', title: 'AI 漫剧', detail: '按剧情段改编分集剧本', action: onOpenComicDrama, label: '打开 AI 漫剧改编' },
    { eyebrow: 'LIBRARY', title: '拆书库', detail: '导入作品并萃取抽象结构', action: onOpenReferences, label: '打开拆书库' },
  ]

  return (
    <div
      className="author-utility-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section
        ref={dialogRef}
        className="author-utility-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="author-utility-title"
      >
        <header>
          <div>
            <p>SUPPORT DESK</p>
            <h2 id="author-utility-title">辅助工具</h2>
            <span>这些工具不会改变本章的唯一下一步。</span>
          </div>
          <button ref={closeRef} type="button" aria-label="关闭辅助工具" onClick={onClose}>×</button>
        </header>
        <nav aria-label="辅助创作工具">
          {entries.map((entry) => (
            <button key={entry.eyebrow} type="button" aria-label={entry.label} onClick={entry.action}>
              <span>{entry.eyebrow}</span>
              <strong>{entry.title}</strong>
              <small>{entry.detail}</small>
            </button>
          ))}
        </nav>
      </section>
    </div>
  )
}
