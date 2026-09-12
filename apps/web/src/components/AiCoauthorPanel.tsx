import type {
  AiChapterBriefProposal,
  AiOutboundPreview,
  AiStatus,
  Chapter,
  ContextDirective,
  ContextDirectiveAction,
  ContextItem,
  GenerationRun,
  Job,
} from '@mozhou/contracts'
import { creativeContextCanSubmit } from '@mozhou/contracts'
import type { MouseEvent } from 'react'
import { useEffect, useRef, useState } from 'react'

import { aiCredentialStore, api } from '../api'
import { ContextPacketPanel } from './ContextPacketPanel'
import { ModelSettingsPanel } from './ModelSettingsPanel'

interface AiCoauthorPanelProps {
  chapter: Chapter
  canUseAi: boolean
  canGenerateDraft: boolean
  onAdoptProposal: (proposal: AiChapterBriefProposal) => void
  onDraftGenerated: (run: GenerationRun) => void
  onOpenChapterProduction?: () => void
}

export function AiCoauthorPanel({
  chapter,
  canUseAi,
  canGenerateDraft,
  onAdoptProposal,
  onDraftGenerated,
  onOpenChapterProduction,
}: AiCoauthorPanelProps) {
  const [status, setStatus] = useState<AiStatus | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [authorIntent, setAuthorIntent] = useState('')
  const [proposal, setProposal] = useState<AiChapterBriefProposal | null>(null)
  const [outboundPreview, setOutboundPreview] = useState<AiOutboundPreview | null>(null)
  const [contextDirectives, setContextDirectives] = useState<ContextDirective[]>([])
  const [contextTokenBudget, setContextTokenBudget] = useState(24_000)
  const [contextUpdating, setContextUpdating] = useState(false)
  const [previewing, setPreviewing] = useState<'brief' | 'draft' | null>(null)
  const [activity, setActivity] = useState<'brief' | 'draft' | null>(null)
  const [activeJob, setActiveJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const settingsTrigger = useRef<HTMLButtonElement | null>(null)
  const activeJobId = activeJob?.id
  const activeJobState = activeJob?.state

  useEffect(() => {
    let active = true
    api.getAiStatus()
      .then((result) => {
        if (active) {
          setStatus(result)
        }
      })
      .catch((caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught.message : '无法读取 AI 状态')
      })
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (!activeJobId || !activeJobState) return undefined
    let stopped = false
    let timer: number | undefined
    const finish = async (job: Job) => {
      if (job.kind === 'chapter_brief') {
        const result = await api.getAiChapterBriefJobResult(job.id)
        if (stopped) return
        setProposal(result)
      } else if (job.kind === 'chapter_draft') {
        const result = await api.getAiChapterDraftJobResult(job.id)
        if (stopped) return
        onDraftGenerated(result)
      }
      if (!stopped) {
        setActiveJob(null)
        setActivity(null)
      }
    }
    const poll = async () => {
      try {
        const job = await api.getJob(activeJobId)
        if (stopped || !job) return
        setActiveJob(job)
        if (job.state === 'succeeded') {
          await finish(job)
          return
        }
        if (job.state === 'failed' || job.state === 'interrupted' || job.state === 'cancelled') {
          setActivity(null)
          setError(job.error_message ?? 'AI 任务已中断，可从现有任务继续。')
          return
        }
        timer = window.setTimeout(poll, 700)
      } catch (caught) {
        if (!stopped) {
          setActivity(null)
          setError(caught instanceof Error ? caught.message : '读取 AI 任务进度失败')
        }
      }
    }
    void poll()
    return () => {
      stopped = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [activeJobId, activeJobState, onDraftGenerated])

  async function generateBrief() {
    if (!status?.configured || activity || previewing || !canUseAi) return
    setPreviewing('brief')
    setError(null)
    try {
      const preview = await api.previewAiChapterBrief(chapter.id, {
        expected_revision: chapter.revision,
        author_intent: authorIntent,
        context_token_budget: contextTokenBudget,
      })
      setOutboundPreview(preview)
      setContextDirectives(await api.listContextDirectives(chapter.id))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '无法预览本次外发内容')
    } finally {
      setPreviewing(null)
    }
  }

  async function generateDraft() {
    if (!status?.configured || activity || previewing || !canGenerateDraft) return
    setPreviewing('draft')
    setError(null)
    try {
      const preview = await api.previewAiChapterDraft(chapter.id, {
        expected_revision: chapter.revision,
        author_intent: authorIntent,
        context_token_budget: contextTokenBudget,
      })
      setOutboundPreview(preview)
      setContextDirectives(await api.listContextDirectives(chapter.id))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '无法预览本次外发内容')
    } finally {
      setPreviewing(null)
    }
  }

  async function confirmOutbound() {
    if (!outboundPreview || activity || !creativeContextCanSubmit(outboundPreview.context_packet)) return
    const kind = outboundPreview.task_type === 'chapter_brief' ? 'brief' : 'draft'
    setActivity(kind)
    setError(null)
    try {
      if (outboundPreview.profile_id && outboundPreview.profile_id !== status?.profile_id) {
        await aiCredentialStore.activateSaved(outboundPreview.profile_id)
        setStatus(await api.getAiStatus())
      }
      const input = {
        expected_revision: chapter.revision,
        author_intent: authorIntent,
        context_packet_id: outboundPreview.context_packet.id,
        context_token_budget: outboundPreview.context_packet.token_budget,
      }
      const job = kind === 'brief'
        ? await api.startAiChapterBriefJob(chapter.id, input)
        : await api.startAiChapterDraftJob(chapter.id, input)
      setActiveJob(job)
      setOutboundPreview(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'AI 任务启动失败')
      setActivity(null)
    }
  }

  async function refreshContextPreview(taskType: 'chapter_brief' | 'chapter_draft') {
    const input = {
      expected_revision: chapter.revision,
      author_intent: authorIntent,
      context_token_budget: contextTokenBudget,
    }
    const preview = taskType === 'chapter_brief'
      ? await api.previewAiChapterBrief(chapter.id, input)
      : await api.previewAiChapterDraft(chapter.id, input)
    setOutboundPreview(preview)
    setContextDirectives(await api.listContextDirectives(chapter.id))
  }

  async function setContextDirective(item: ContextItem, action: ContextDirectiveAction) {
    if (!outboundPreview || contextUpdating) return
    const source = item.source_refs[0]
    if (!source) return
    const existing = contextDirectives.find((directive) => (
      directive.source_kind === source.kind && directive.source_id === source.source_id
    ))
    setContextUpdating(true)
    setError(null)
    try {
      await api.setContextDirective(chapter.id, {
        source_kind: source.kind,
        source_id: source.source_id,
        action,
        expected_revision: existing?.revision ?? null,
      })
      await refreshContextPreview(
        outboundPreview.task_type === 'chapter_draft' ? 'chapter_draft' : 'chapter_brief',
      )
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '上下文选择更新失败')
    } finally {
      setContextUpdating(false)
    }
  }

  async function clearContextDirective(item: ContextItem) {
    if (!outboundPreview || contextUpdating) return
    const source = item.source_refs[0]
    if (!source) return
    const existing = contextDirectives.find((directive) => (
      directive.source_kind === source.kind && directive.source_id === source.source_id
    ))
    if (!existing) return
    setContextUpdating(true)
    setError(null)
    try {
      await api.deleteContextDirective(existing.id, existing.revision)
      await refreshContextPreview(
        outboundPreview.task_type === 'chapter_draft' ? 'chapter_draft' : 'chapter_brief',
      )
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '上下文选择更新失败')
    } finally {
      setContextUpdating(false)
    }
  }

  async function cancelActiveJob() {
    if (!activeJob || !['queued', 'running', 'pause_requested'].includes(activeJob.state)) return
    try {
      setActiveJob(await api.cancelJob(activeJob.id))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '取消 AI 任务失败')
    }
  }

  async function retryActiveJob() {
    if (!activeJob || !['failed', 'interrupted', 'cancelled'].includes(activeJob.state)) return
    setError(null)
    setActivity(activeJob.kind === 'chapter_brief' ? 'brief' : 'draft')
    try {
      setActiveJob(await api.retryJob(activeJob.id))
    } catch (caught) {
      setActivity(null)
      setError(caught instanceof Error ? caught.message : '重试 AI 任务失败')
    }
  }

  function adoptProposal() {
    if (!proposal) return
    onAdoptProposal(proposal)
    setProposal(null)
  }

  function openModelSettings(event: MouseEvent<HTMLButtonElement>) {
    settingsTrigger.current = event.currentTarget
    setSettingsOpen(true)
  }

  function closeModelSettings() {
    setSettingsOpen(false)
    window.setTimeout(() => settingsTrigger.current?.focus(), 0)
  }

  const configured = status?.configured === true

  return (
    <section className="ai-coauthor" aria-labelledby="ai-coauthor-title">
      <header>
        <div>
          <p>{onOpenChapterProduction ? '模型线路' : 'AI 共创'}</p>
          <h3 id="ai-coauthor-title">{onOpenChapterProduction ? '管理本章使用的 AI 线路' : '说一句想法，让 AI 完成章纲和初稿'}</h3>
        </div>
        <div className="ai-route-status">
          <span data-ready={configured}>
            {status === null
              ? '读取中'
              : configured
                ? `${status.profile_name ?? status.provider} · ${status.model}`
                : '未配置'}
          </span>
          <button type="button" onClick={openModelSettings}>模型设置</button>
        </div>
      </header>

      {onOpenChapterProduction ? (
        <div className="ai-setup chapter-production-route-note">
          <p>章纲设计和完整正文已迁移到单章生产工作台；这里只保留模型线路管理，不再产生另一份正文候选。</p>
          <button type="button" onClick={onOpenChapterProduction}>前往单章生产工作台</button>
          {!configured ? <button type="button" onClick={openModelSettings}>打开模型线路台</button> : null}
        </div>
      ) : !configured ? (
        <div className="ai-setup">
          <p>先建立一条模型线路。桌面版会把 API Key 放进 macOS 系统凭据库，作品数据库和导出包都不保存密钥。</p>
          <button type="button" onClick={openModelSettings}>打开模型线路台</button>
        </div>
      ) : (
        <div className="ai-command-deck">
          <label>
            这一章你想看到什么？
            <textarea
              aria-label="本章创作意图"
              value={authorIntent}
              onChange={(event) => {
                setAuthorIntent(event.target.value)
                setOutboundPreview(null)
              }}
              maxLength={1000}
              rows={3}
              placeholder="可以留空，让总导演根据上一章悬念、人物状态和开放伏笔自行设计。"
            />
          </label>
          <label className="context-budget-control">
            本次上下文预算
            <select
              aria-label="本次上下文预算"
              value={contextTokenBudget}
              onChange={(event) => {
                setContextTokenBudget(Number(event.target.value))
                setOutboundPreview(null)
              }}
            >
              <option value={8000}>8,000 Token · 精简</option>
              <option value={16000}>16,000 Token · 标准</option>
              <option value={24000}>24,000 Token · 长篇推荐</option>
              <option value={48000}>48,000 Token · 大上下文</option>
            </select>
          </label>
          <div>
            <button type="button" onClick={generateBrief} disabled={activity !== null || previewing !== null || !canUseAi}>
              {previewing === 'brief' ? '正在核算外发内容…' : activity === 'brief' ? '正在设计章纲…' : 'AI 设计本章'}
            </button>
            <button
              type="button"
              className="ai-draft-action"
              onClick={generateDraft}
              disabled={activity !== null || previewing !== null || !canGenerateDraft}
            >
              {previewing === 'draft' ? '正在核算外发内容…' : activity === 'draft' ? '正在写完整章节…' : 'AI 写完整章节'}
            </button>
          </div>
          <p className="ai-privacy-note">
            点击生成后先展示外发清单、目标线路与费用估算；只有再次确认才会调用模型。未确认资料和 API Key 不会进入提示词。
          </p>
          {!canGenerateDraft ? <p>先采用并保存完整章纲，即可让 AI 写整章。</p> : null}
          {activeJob ? (
            <div className="ai-job-progress" role="status" aria-live="polite">
              <div>
                <strong>{activeJob.current_step || '任务已进入本地队列'}</strong>
                <span>{activeJob.progress_current} / {activeJob.progress_total}</span>
              </div>
              <progress
                aria-label="AI 章节任务进度"
                value={activeJob.progress_current}
                max={Math.max(activeJob.progress_total, 1)}
              />
              {['queued', 'running', 'pause_requested'].includes(activeJob.state) ? (
                <button type="button" onClick={cancelActiveJob}>停止任务</button>
              ) : (
                <button type="button" onClick={retryActiveJob}>从任务断点继续</button>
              )}
            </div>
          ) : null}
        </div>
      )}

      {outboundPreview && !onOpenChapterProduction ? (
        <article className="ai-outbound-preview" aria-labelledby="ai-outbound-preview-title">
          <header>
            <div><small>OUTBOUND CHECK</small><h4 id="ai-outbound-preview-title">发送前确认</h4></div>
            <strong>{outboundPreview.profile_name} · {outboundPreview.model}</strong>
          </header>
          <p>{outboundPreview.content_scope}</p>
          <ul aria-label="本次外发数据类型">
            {outboundPreview.data_types.map((item) => <li key={item}>{item}</li>)}
          </ul>
          <dl>
            <div><dt>上下文字符</dt><dd>{outboundPreview.character_count.toLocaleString('zh-CN')}</dd></div>
            <div><dt>预计输入</dt><dd>{outboundPreview.estimated_input_tokens.toLocaleString('zh-CN')} Token</dd></div>
            <div><dt>预计输出</dt><dd>{outboundPreview.estimated_output_tokens.toLocaleString('zh-CN')} Token</dd></div>
            <div><dt>预计费用</dt><dd>{outboundPreview.estimated_cost_microusd === null ? '线路未填写价格' : `约 $${(outboundPreview.estimated_cost_microusd / 1_000_000).toFixed(4)}`}</dd></div>
          </dl>
          <ContextPacketPanel
            packet={outboundPreview.context_packet}
            directives={contextDirectives}
            busy={contextUpdating || activity !== null}
            onSetDirective={(item, action) => { void setContextDirective(item, action) }}
            onClearDirective={(item) => { void clearContextDirective(item) }}
          />
          <footer>
            <button type="button" onClick={() => setOutboundPreview(null)}>返回修改</button>
            <button
              type="button"
              onClick={() => { void confirmOutbound() }}
              disabled={activity !== null || !creativeContextCanSubmit(outboundPreview.context_packet)}
            >
              {activity ? '正在启动…' : '确认外发并开始'}
            </button>
          </footer>
        </article>
      ) : null}

      {proposal && !onOpenChapterProduction ? (
        <article className="ai-proposal">
          <div><span>候选章纲</span><strong>{proposal.title}</strong></div>
          <dl>
            <div><dt>承诺</dt><dd>{proposal.reader_promise}</dd></div>
            <div><dt>变化</dt><dd>{proposal.state_change}</dd></div>
            <div><dt>回报</dt><dd>{proposal.emotional_payoff}</dd></div>
            <div><dt>悬念</dt><dd>{proposal.ending_cliffhanger}</dd></div>
          </dl>
          <p>{proposal.why_this_works}</p>
          {proposal.risk_notes.length > 0 ? (
            <ul>{proposal.risk_notes.map((note) => <li key={note}>{note}</li>)}</ul>
          ) : null}
          <button type="button" onClick={adoptProposal}>采用到章纲，继续确认</button>
        </article>
      ) : null}
      {error ? <p className="ai-coauthor-error" role="alert">{error}</p> : null}
      <ModelSettingsPanel
        open={settingsOpen}
        status={status}
        onClose={closeModelSettings}
        onStatusChanged={(nextStatus) => {
          setStatus(nextStatus)
          setError(null)
        }}
      />
    </section>
  )
}
