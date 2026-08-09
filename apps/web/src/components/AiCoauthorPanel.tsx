import type {
  AiChapterBriefProposal,
  AiStatus,
  Chapter,
  GenerationRun,
  Job,
} from '@mozhou/contracts'
import type { MouseEvent } from 'react'
import { useEffect, useRef, useState } from 'react'

import { api } from '../api'
import { ModelSettingsPanel } from './ModelSettingsPanel'

interface AiCoauthorPanelProps {
  chapter: Chapter
  canUseAi: boolean
  canGenerateDraft: boolean
  onAdoptProposal: (proposal: AiChapterBriefProposal) => void
  onDraftGenerated: (run: GenerationRun) => void
}

export function AiCoauthorPanel({
  chapter,
  canUseAi,
  canGenerateDraft,
  onAdoptProposal,
  onDraftGenerated,
}: AiCoauthorPanelProps) {
  const [status, setStatus] = useState<AiStatus | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [authorIntent, setAuthorIntent] = useState('')
  const [proposal, setProposal] = useState<AiChapterBriefProposal | null>(null)
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
    if (!status?.configured || activity || !canUseAi) return
    setActivity('brief')
    setError(null)
    try {
      setActiveJob(await api.startAiChapterBriefJob(chapter.id, {
        expected_revision: chapter.revision,
        author_intent: authorIntent,
      }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'AI 章纲生成失败')
      setActivity(null)
    }
  }

  async function generateDraft() {
    if (!status?.configured || activity || !canGenerateDraft) return
    setActivity('draft')
    setError(null)
    try {
      setActiveJob(await api.startAiChapterDraftJob(chapter.id, {
        expected_revision: chapter.revision,
        author_intent: authorIntent,
      }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'AI 正文生成失败')
      setActivity(null)
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
          <p>AI 共创</p>
          <h3 id="ai-coauthor-title">说一句想法，让 AI 完成章纲和初稿</h3>
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

      {!configured ? (
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
              onChange={(event) => setAuthorIntent(event.target.value)}
              maxLength={1000}
              rows={3}
              placeholder="可以留空，让总导演根据上一章悬念、人物状态和开放伏笔自行设计。"
            />
          </label>
          <div>
            <button type="button" onClick={generateBrief} disabled={activity !== null || !canUseAi}>
              {activity === 'brief' ? '正在设计章纲…' : 'AI 设计本章'}
            </button>
            <button
              type="button"
              className="ai-draft-action"
              onClick={generateDraft}
              disabled={activity !== null || !canGenerateDraft}
            >
              {activity === 'draft' ? '正在写完整章节…' : 'AI 写完整章节'}
            </button>
          </div>
          <p className="ai-privacy-note">
            点击生成会把本章章纲、近期正文、正式事实及已确认资料发送给当前模型端点；未确认资料和 API Key 不会进入提示词。
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

      {proposal ? (
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
