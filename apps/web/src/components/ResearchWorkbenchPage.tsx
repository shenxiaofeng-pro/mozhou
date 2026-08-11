import type { Project, ResearchFinding, ResearchInput, ResearchPreview, ResearchSession, ResearchWorkspace, SourceDocument } from '@mozhou/contracts'
import { useEffect, useMemo, useState } from 'react'

import { api } from '../api'
import { isRebirthGenre } from '../genre'

interface Props { project: Project; onBack: () => void; onSourceCardsChanged: () => void }

const categories = {
  historical_event: '历史事件', local_system: '地方制度 / 地理', industry_rule: '行业规则',
  price_technology: '价格 / 技术条件', controversy: '争议点',
} as const

export function ResearchWorkbenchPage({ project, onBack, onSourceCardsChanged }: Props) {
  const rebirthStory = isRebirthGenre(project.genre)
  const [documents, setDocuments] = useState<SourceDocument[]>([])
  const [sessions, setSessions] = useState<ResearchSession[]>([])
  const [active, setActive] = useState<ResearchWorkspace | null>(null)
  const [preview, setPreview] = useState<ResearchPreview | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState<ResearchInput>({
    title: '新资料研究', question: '', era_start: project.rebirth_year, era_end: project.rebirth_year,
    region: project.rebirth_location, material_type: rebirthStory ? '地方志 / 行业资料' : '世界设定 / 神话资料', mode: 'local',
    source_document_ids: [], pasted_text: '', pasted_label: '临时粘贴资料',
  })
  const selectedChars = useMemo(() => documents.filter((item) => form.source_document_ids.includes(item.id)).reduce((sum, item) => sum + item.total_characters, 0) + form.pasted_text.length, [documents, form.pasted_text, form.source_document_ids])

  useEffect(() => {
    void Promise.all([api.listSourceDocuments(), api.listResearchSessions(project.id)])
      .then(([nextDocuments, nextSessions]) => { setDocuments(nextDocuments); setSessions(nextSessions) })
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : '无法读取研究台'))
  }, [project.id])

  useEffect(() => {
    if (!active?.session.job_id || !['queued', 'running'].includes(active.session.state)) return
    const timer = window.setInterval(() => {
      void api.getJob(active.session.job_id!).then(async (job) => {
        if (job.state === 'succeeded') {
          const workspace = await api.getResearchSession(active.session.id)
          setActive(workspace); setSessions(await api.listResearchSessions(project.id))
        } else if (['failed', 'cancelled', 'interrupted'].includes(job.state)) {
          setError(job.error_message ?? '研究任务未完成，可在任务中心重试')
        }
      }).catch(() => undefined)
    }, 800)
    return () => window.clearInterval(timer)
  }, [active?.session.id, active?.session.job_id, active?.session.state, project.id])

  function toggleDocument(id: string) {
    setPreview(null); setConfirmed(false)
    setForm((current) => ({ ...current, source_document_ids: current.source_document_ids.includes(id) ? current.source_document_ids.filter((item) => item !== id) : [...current.source_document_ids, id] }))
  }

  async function inspect() {
    setBusy(true); setError(null); setConfirmed(false)
    try { setPreview(await api.previewResearch(project.id, form)) }
    catch (caught) { setError(caught instanceof Error ? caught.message : '无法预览研究范围') }
    finally { setBusy(false) }
  }

  async function submit() {
    if (!preview) return
    setBusy(true); setError(null)
    try {
      const result = await api.submitResearch(project.id, { ...form, expected_source_set_sha256: preview.source_set_sha256, confirm_external_processing: form.mode === 'local' || confirmed, ...(preview.estimated_cost_microusd === null ? {} : { max_estimated_cost_microusd: preview.estimated_cost_microusd }) })
      setActive({ session: result.session, sources: preview.sources, findings: [] })
      setSessions((current) => [result.session, ...current.filter((item) => item.id !== result.session.id)])
    } catch (caught) { setError(caught instanceof Error ? caught.message : '研究任务提交失败') }
    finally { setBusy(false) }
  }

  async function openSession(session: ResearchSession) {
    setBusy(true); setError(null)
    try { setActive(await api.getResearchSession(session.id)) }
    catch (caught) { setError(caught instanceof Error ? caught.message : '研究会话读取失败') }
    finally { setBusy(false) }
  }

  async function review(finding: ResearchFinding, action: 'approve' | 'reject') {
    setBusy(true); setError(null)
    try {
      const updated = await api.reviewResearchFinding(finding.id, action, finding.revision)
      setActive((current) => current ? { ...current, findings: current.findings.map((item) => item.id === updated.id ? updated : item) } : current)
      if (action === 'approve') onSourceCardsChanged()
    } catch (caught) { setError(caught instanceof Error ? caught.message : '候选审核失败') }
    finally { setBusy(false) }
  }

  return <main className="research-page">
    <header className="research-bar"><div><small>RESEARCH AGENT</small><h1>资料研究台</h1><p>《{project.title}》 · 只有逐条批准的证据卡才进入 AI 上下文</p></div><button type="button" onClick={onBack}>返回写作</button></header>
    <div className="research-layout">
      <aside className="research-history"><h2>研究档案</h2>{sessions.length ? sessions.map((session) => <button type="button" key={session.id} data-active={active?.session.id === session.id} onClick={() => { void openSession(session) }}><strong>{session.title}</strong><span>{session.state} · {session.finding_count} 条</span></button>) : <p>尚无研究任务</p>}</aside>
      <section className="research-stage">
        <div className="research-form"><header><small>新研究</small><h2>先冻结来源，再提取结论</h2></header>
          <div className="research-fields">
            <label>任务名<input value={form.title} onChange={(event) => { setPreview(null); setForm({ ...form, title: event.target.value }) }} /></label>
            <label>研究问题<input value={form.question} placeholder={rebirthStory ? '例：1992年南平纸厂的价格和进货规则？' : '例：云泽灵脉枯竭会怎样改变宗门资源与修炼代价？'} onChange={(event) => { setPreview(null); setForm({ ...form, question: event.target.value }) }} /></label>
            <label>地区<input value={form.region} onChange={(event) => { setPreview(null); setForm({ ...form, region: event.target.value }) }} /></label>
            <label>资料类型<input value={form.material_type} onChange={(event) => { setPreview(null); setForm({ ...form, material_type: event.target.value }) }} /></label>
            <label>起始年<input type="number" value={form.era_start} onChange={(event) => { setPreview(null); setForm({ ...form, era_start: Number(event.target.value) }) }} /></label>
            <label>结束年<input type="number" value={form.era_end} onChange={(event) => { setPreview(null); setForm({ ...form, era_end: Number(event.target.value) }) }} /></label>
            <label>提取模式<select value={form.mode} onChange={(event) => { setPreview(null); setForm({ ...form, mode: event.target.value as ResearchInput['mode'] }) }}><option value="local">本地证据规则（零费用）</option><option value="ai">AI 深度归纳</option></select></label>
          </div>
          <fieldset className="research-source-picker"><legend>{rebirthStory ? '全局现实资料' : '全局参考资料'}</legend>{documents.map((document) => <label key={document.id}><input type="checkbox" checked={form.source_document_ids.includes(document.id)} onChange={() => toggleDocument(document.id)} /><span><strong>{document.title}</strong><small>{document.source_format.toUpperCase()} · {document.total_characters.toLocaleString()} 字</small></span></label>)}</fieldset>
          <label className="research-paste">或粘贴本地资料（最多 20 万字）<textarea maxLength={200000} value={form.pasted_text} onChange={(event) => { setPreview(null); setForm({ ...form, pasted_text: event.target.value }) }} /></label>
          <p>已选 {selectedChars.toLocaleString()} 字符。资料中的命令会被当作不可信文本，无法回链原文的 AI 结论会被丢弃。</p>
          {!preview ? <button type="button" className="research-primary" disabled={busy || !form.question.trim() || selectedChars === 0} onClick={() => { void inspect() }}>预览范围与费用</button> : <div className="research-preview"><strong>{preview.content_scope}</strong><span>指纹 {preview.source_set_sha256.slice(0, 12)} · {preview.profile_name}</span>{form.mode === 'ai' ? <label><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />确认向当前模型线路发送上述原文，预估上限 {preview.estimated_cost_microusd === null ? '未知' : `US$ ${(preview.estimated_cost_microusd / 1_000_000).toFixed(4)}`}</label> : null}<button type="button" className="research-primary" disabled={busy || (form.mode === 'ai' && !confirmed)} onClick={() => { void submit() }}>创建可恢复研究任务</button></div>}
        </div>
        {error ? <p className="agent-error" role="alert">{error}</p> : null}
        {active ? <section className="research-results"><header><div><small>{active.session.mode.toUpperCase()} · {active.session.state}</small><h2>{active.session.title}</h2></div><p>{active.findings.length} 条可回链候选 · 已丢弃 {active.session.invalid_ai_findings} 条无效 AI 引用</p></header><div className="research-cards">{active.findings.map((finding) => <article key={finding.id} data-state={finding.state}><header><span>{categories[finding.category]}</span><small>{finding.origin === 'ai' ? 'AI 归纳' : '本地提取'} · {finding.confidence}</small></header><h3>{finding.title}</h3><p>{finding.summary}</p><blockquote>{finding.evidence_excerpt}</blockquote><footer><span>{finding.source_label} · 字符 {finding.start_char}–{finding.end_char}{finding.page_number_start ? ` · 第 ${finding.page_number_start}${finding.page_number_end !== finding.page_number_start ? `–${finding.page_number_end}` : ''} 页` : ''} · {finding.evidence_sha256.slice(0, 10)}</span>{finding.conflict_count > 1 ? <em>同组 {finding.conflict_count} 种说法，未自动裁决</em> : null}{finding.state === 'candidate' ? <div><button disabled={busy} type="button" onClick={() => { void review(finding, 'reject') }}>排除</button><button disabled={busy} type="button" onClick={() => { void review(finding, 'approve') }}>批准进入现实资料卡</button></div> : <strong>{finding.state === 'approved' ? '已批准入库' : '已排除'}</strong>}</footer></article>)}</div></section> : null}
      </section>
    </div>
  </main>
}
