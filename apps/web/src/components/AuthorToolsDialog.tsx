import type { AuthorIdea, Chapter, ChapterAnnotation, Project, StoryGraphEdge, StoryGraphNode, StoryGraphs, WritingCalendar } from '@mozhou/contracts'
import { useEffect, useMemo, useState } from 'react'

import { api } from '../api'

type Tab = 'calendar' | 'annotations' | 'ideas' | 'graphs'
interface Props { project: Project; chapter: Chapter; initialTab: Tab; selection: { start: number; end: number } | null; onClose: () => void }

export function AuthorToolsDialog({ project, chapter, initialTab, selection, onClose }: Props) {
  const [tab, setTab] = useState<Tab>(initialTab)
  const [calendar, setCalendar] = useState<WritingCalendar | null>(null)
  const [annotations, setAnnotations] = useState<ChapterAnnotation[]>([])
  const [ideas, setIdeas] = useState<AuthorIdea[]>([])
  const [graphs, setGraphs] = useState<StoryGraphs | null>(null)
  const [ideaTitle, setIdeaTitle] = useState('')
  const [ideaContent, setIdeaContent] = useState('')
  const [ideaTags, setIdeaTags] = useState('')
  const [comment, setComment] = useState('')
  const [relationSource, setRelationSource] = useState('')
  const [relationTarget, setRelationTarget] = useState('')
  const [relationType, setRelationType] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const request = tab === 'calendar' ? api.getWritingCalendar(project.id).then(setCalendar)
      : tab === 'annotations' ? api.listChapterAnnotations(chapter.id).then(setAnnotations)
      : tab === 'ideas' ? api.listAuthorIdeas(project.id).then(setIdeas)
      : api.getStoryGraphs(project.id).then(setGraphs)
    void request.catch((caught: unknown) => setError(caught instanceof Error ? caught.message : '作者工具读取失败'))
  }, [chapter.id, project.id, tab])

  async function addAnnotation() {
    if (!selection || selection.end <= selection.start || !comment.trim()) return
    setBusy(true); setError(null)
    try {
      const created = await api.createChapterAnnotation(chapter.id, { comment: comment.trim(), start_char: selection.start, end_char: selection.end, expected_chapter_revision: chapter.revision })
      setAnnotations((current) => [...current, created]); setComment('')
    } catch (caught) { setError(caught instanceof Error ? caught.message : '批注创建失败') }
    finally { setBusy(false) }
  }

  async function resolveAnnotation(annotation: ChapterAnnotation) {
    setBusy(true)
    try { const updated = await api.resolveChapterAnnotation(annotation.id, annotation.revision); setAnnotations((current) => current.map((item) => item.id === updated.id ? updated : item)) }
    catch (caught) { setError(caught instanceof Error ? caught.message : '批注更新失败') }
    finally { setBusy(false) }
  }

  async function addIdea() {
    if (!ideaTitle.trim() || !ideaContent.trim()) return
    setBusy(true); setError(null)
    try {
      const created = await api.createAuthorIdea({ project_id: project.id, title: ideaTitle.trim(), content: ideaContent.trim(), tags: ideaTags.split(/[,，]/).map((item) => item.trim()).filter(Boolean) })
      setIdeas((current) => [created, ...current]); setIdeaTitle(''); setIdeaContent(''); setIdeaTags('')
    } catch (caught) { setError(caught instanceof Error ? caught.message : '灵感保存失败') }
    finally { setBusy(false) }
  }

  async function prepareIdea(idea: AuthorIdea, target: NonNullable<AuthorIdea['target_kind']>) {
    setBusy(true)
    try { const updated = await api.prepareAuthorIdea(idea.id, target, idea.revision); setIdeas((current) => current.map((item) => item.id === updated.id ? updated : item)) }
    catch (caught) { setError(caught instanceof Error ? caught.message : '灵感候选转换失败') }
    finally { setBusy(false) }
  }

  async function addRelationship() {
    if (!relationSource || !relationTarget || !relationType.trim() || relationSource === relationTarget) return
    setBusy(true); setError(null)
    try {
      await api.createStoryRelationship(project.id, { source_entity_id: relationSource, target_entity_id: relationTarget, relation_type: relationType.trim(), summary: '', source_chapter_id: chapter.id })
      setGraphs(await api.getStoryGraphs(project.id)); setRelationType('')
    } catch (caught) { setError(caught instanceof Error ? caught.message : '人物关系保存失败') }
    finally { setBusy(false) }
  }

  return <div className="author-tools-backdrop" role="presentation"><section className="author-tools-dialog" role="dialog" aria-modal="true" aria-label="作者效率工具">
    <header><div><small>AUTHOR DESK</small><h2>作者工具台</h2></div><button type="button" onClick={onClose}>关闭</button></header>
    <nav aria-label="作者工具分类">{([['calendar', '码字日历'], ['annotations', '章节批注'], ['ideas', '灵感箱'], ['graphs', '关系 / 伏笔图谱']] as const).map(([value, label]) => <button type="button" key={value} data-active={tab === value} onClick={() => { setError(null); setTab(value) }}>{label}</button>)}</nav>
    {error ? <p className="agent-error" role="alert">{error}</p> : null}
    <div className="author-tools-content">
      {tab === 'calendar' && calendar ? <CalendarView calendar={calendar} /> : null}
      {tab === 'annotations' ? <section className="annotation-tools"><header><div><h3>{chapter.title}</h3><p>批注锁定当前 revision 和原文选区；改稿后无法唯一定位会标记待定位。</p></div></header>{selection && selection.end > selection.start ? <div className="annotation-compose"><blockquote>{chapter.content.slice(selection.start, selection.end)}</blockquote><input value={comment} placeholder="这段需要处理什么？" onChange={(event) => setComment(event.target.value)} /><button type="button" disabled={busy || !comment.trim()} onClick={() => { void addAnnotation() }}>添加批注</button></div> : <p>请先在正文编辑器选中文字，再点击“批注选中文字”。</p>}<div className="annotation-list">{annotations.map((annotation) => <article key={annotation.id} data-status={annotation.status}><blockquote>{annotation.selected_text}</blockquote><p>{annotation.comment}</p><footer><span>{annotation.status === 'stale' ? '待定位' : annotation.status === 'resolved' ? '已解决' : `字符 ${annotation.start_char}–${annotation.end_char}`}</span>{annotation.status === 'open' ? <button disabled={busy} type="button" onClick={() => { void resolveAnnotation(annotation) }}>标记已解决</button> : null}</footer></article>)}</div></section> : null}
      {tab === 'ideas' ? <section className="idea-box"><div className="idea-compose"><input value={ideaTitle} placeholder="一句话标题" onChange={(event) => setIdeaTitle(event.target.value)} autoFocus /><textarea value={ideaContent} placeholder="人物、桥段、资料线索……" onChange={(event) => setIdeaContent(event.target.value)} /><input value={ideaTags} placeholder="标签，用逗号分隔" onChange={(event) => setIdeaTags(event.target.value)} /><button type="button" disabled={busy || !ideaTitle.trim() || !ideaContent.trim()} onClick={() => { void addIdea() }}>收进灵感箱</button></div><p className="isolation-note">“准备为候选”只标记用途，不会直接改章纲、资料卡或人物账本。</p><div className="idea-list">{ideas.map((idea) => <article key={idea.id} data-status={idea.status}><header><h3>{idea.title}</h3><span>{idea.status}</span></header><p>{idea.content}</p><small>{idea.tags.join(' · ') || '无标签'}</small>{idea.status === 'inbox' ? <footer><button disabled={busy} type="button" onClick={() => { void prepareIdea(idea, 'chapter_brief') }}>准备为章纲候选</button><button disabled={busy} type="button" onClick={() => { void prepareIdea(idea, 'source_card') }}>准备为资料候选</button><button disabled={busy} type="button" onClick={() => { void prepareIdea(idea, 'character') }}>准备为人物候选</button></footer> : <strong>已准备：{idea.target_kind}</strong>}</article>)}</div></section> : null}
      {tab === 'graphs' && graphs ? <section className="story-graphs"><h3>正式人物关系</h3><div className="relationship-compose"><select aria-label="关系起点" value={relationSource} onChange={(event) => setRelationSource(event.target.value)}><option value="">选择人物</option>{graphs.relationship_nodes.filter((node) => node.kind === 'character').map((node) => <option key={node.id} value={node.id}>{node.label}</option>)}</select><input value={relationType} placeholder="例：师徒、竞争对手" onChange={(event) => setRelationType(event.target.value)} /><select aria-label="关系终点" value={relationTarget} onChange={(event) => setRelationTarget(event.target.value)}><option value="">选择人物</option>{graphs.relationship_nodes.filter((node) => node.kind === 'character').map((node) => <option key={node.id} value={node.id}>{node.label}</option>)}</select><button type="button" disabled={busy || !relationSource || !relationTarget || relationSource === relationTarget || !relationType.trim()} onClick={() => { void addRelationship() }}>记入正式关系</button></div><GraphView nodes={graphs.relationship_nodes} edges={graphs.relationship_edges} /><GraphList nodes={graphs.relationship_nodes} edges={graphs.relationship_edges} /><h3>伏笔埋设与回收</h3><GraphView nodes={graphs.thread_nodes} edges={graphs.thread_edges} /><GraphList nodes={graphs.thread_nodes} edges={graphs.thread_edges} /></section> : null}
    </div>
  </section></div>
}

function CalendarView({ calendar }: { calendar: WritingCalendar }) {
  const weeks = Array.from({ length: Math.ceil(calendar.days.length / 7) }, (_, index) => calendar.days.slice(index * 7, index * 7 + 7))
  const today = calendar.days.at(-1)
  const goalDays = calendar.days.filter((day) => day.met_goal).length
  const activeDays = calendar.days.filter((day) => day.net_characters !== 0).length
  const formatCharacters = (value: number) => `${value > 0 ? '+' : ''}${value.toLocaleString('zh-CN')}`
  const formatDate = (date: string) => {
    const [, month, day] = date.split('-')
    return `${Number(month)}月${Number(day)}日`
  }
  const weekday = (date: string) => ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][new Date(`${date}T00:00:00Z`).getUTCDay()]
  const range = calendar.days.length ? `${formatDate(calendar.days[0].date)}—${formatDate(calendar.days.at(-1)!.date)}` : '尚无记录'
  const todayMessage = !today || today.net_characters === 0 ? '今天还没有落笔，先写下第一段。'
    : today.net_characters < 0 ? `今天以删改为主，正文净变化 ${formatCharacters(today.net_characters)} 字。`
    : `今天已完成 ${formatCharacters(today.net_characters)} 字，${today.met_goal ? '目标达成。' : '继续保持手感。'}`

  return <section className="writing-calendar">
    <header className="calendar-hero">
      <div className="calendar-heading">
        <small>WRITING RHYTHM · {range}</small>
        <h3>六周码字轨迹</h3>
        <p>{todayMessage}</p>
      </div>
      <div className="calendar-today" data-state={today?.met_goal ? 'met' : today && today.net_characters < 0 ? 'negative' : 'open'}>
        <span>今日净增</span>
        <strong>{today ? formatCharacters(today.net_characters) : '—'}<small>字</small></strong>
        <small>{today?.met_goal ? `已完成 ${Math.round(today.net_characters / Math.max(1, today.target_characters) * 100)}% 日目标` : `日目标 ${today?.target_characters.toLocaleString('zh-CN') ?? '—'} 字`}</small>
      </div>
    </header>

    <dl className="calendar-metrics">
      <div><dt>六周净增</dt><dd>{calendar.total_net_characters.toLocaleString('zh-CN')}<small>字</small></dd></div>
      <div><dt>连续写作</dt><dd>{calendar.streak_days}<small>天</small></dd></div>
      <div><dt>达标天数</dt><dd>{goalDays}<small>天</small></dd></div>
      <div><dt>有记录</dt><dd>{activeDays}<small>天</small></dd></div>
    </dl>

    <div className="calendar-board">
      <header className="calendar-board-head">
        <div><strong>每日手稿</strong><small>{calendar.timezone}</small></div>
        <div className="calendar-legend" aria-label="状态图例"><span data-tone="met">达标</span><span data-tone="writing">写作中</span><span data-tone="negative">净删改</span></div>
      </header>
      <div className="calendar-grid" role="list" aria-label="过去六周码字记录">
        {weeks.map((week, weekIndex) => <div className="calendar-week-row" key={week[0]?.date ?? weekIndex} aria-label={`第 ${weekIndex + 1} 周`}>
          <div className="calendar-week-label" aria-hidden="true"><strong>W{String(weekIndex + 1).padStart(2, '0')}</strong><small>{week.length ? `${week[0].date.slice(5).replace('-', '.')}—${week.at(-1)!.date.slice(5).replace('-', '.')}` : ''}</small></div>
          {week.map((day, dayIndex) => {
            const progress = Math.min(100, Math.max(0, day.net_characters) / Math.max(1, day.target_characters) * 100)
            const isToday = weekIndex === weeks.length - 1 && dayIndex === week.length - 1
            const status = day.met_goal ? '已达标' : day.net_characters < 0 ? '净删改' : day.net_characters > 0 ? '写作中' : '未开始'
            return <article className="calendar-day" key={day.date} role="listitem" aria-label={`${formatDate(day.date)} ${status}，净增 ${day.net_characters} 字，目标 ${day.target_characters} 字`} data-met={day.met_goal} data-negative={day.net_characters < 0} data-today={isToday}>
              <header><time dateTime={day.date}>{formatDate(day.date)}</time><span>{weekday(day.date)}</span></header>
              <strong>{day.net_characters === 0 ? '—' : formatCharacters(day.net_characters)}</strong>
              <small>{status}</small>
              <div className="calendar-day-track" aria-hidden="true"><span style={{ width: `${progress}%` }} /></div>
            </article>
          })}
        </div>)}
      </div>
    </div>
  </section>
}

function GraphView({ nodes, edges }: { nodes: StoryGraphNode[]; edges: StoryGraphEdge[] }) {
  const positioned = useMemo(() => nodes.map((node, index) => ({ ...node, x: 200 + 155 * Math.cos(index * 2 * Math.PI / Math.max(1, nodes.length)), y: 150 + 105 * Math.sin(index * 2 * Math.PI / Math.max(1, nodes.length)) })), [nodes])
  const byId = new Map(positioned.map((node) => [node.id, node]))
  if (!nodes.length) return <p>暂无正式账本节点。图谱不读取 AI 候选或沙盘假设。</p>
  return <svg className="author-graph" viewBox="0 0 400 300" role="img" aria-label="故事关系图"><g>{edges.map((edge) => { const source = byId.get(edge.source); const target = byId.get(edge.target); return source && target ? <g key={edge.id}><line x1={source.x} y1={source.y} x2={target.x} y2={target.y} /><text x={(source.x + target.x) / 2} y={(source.y + target.y) / 2}>{edge.label}</text></g> : null })}</g>{positioned.map((node) => <g key={node.id} transform={`translate(${node.x} ${node.y})`}><circle r="30" /><text textAnchor="middle" y="4">{node.label.slice(0, 7)}</text></g>)}</svg>
}

function GraphList({ nodes, edges }: { nodes: StoryGraphNode[]; edges: StoryGraphEdge[] }) {
  const names = new Map(nodes.map((node) => [node.id, node.label]))
  return <ul className="graph-list">{edges.map((edge) => <li key={edge.id}><strong>{names.get(edge.source) ?? '未知'}</strong><span>{edge.label} · {edge.status}</span><strong>{names.get(edge.target) ?? '未知'}</strong></li>)}</ul>
}
