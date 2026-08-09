import type {
  AiChapterBriefProposal,
  AiStatus,
  Chapter,
  GenerationRun,
} from '@mozhou/contracts'
import { useEffect, useState } from 'react'

import { api } from '../api'

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
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('gpt-5.6')
  const [authorIntent, setAuthorIntent] = useState('')
  const [proposal, setProposal] = useState<AiChapterBriefProposal | null>(null)
  const [activity, setActivity] = useState<'configuring' | 'brief' | 'draft' | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    api.getAiStatus()
      .then((result) => {
        if (active) {
          setStatus(result)
          if (result.model) setModel(result.model)
        }
      })
      .catch((caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught.message : '无法读取 AI 状态')
      })
    return () => {
      active = false
    }
  }, [])

  async function configureAi() {
    if (!apiKey.trim() || activity) return
    setActivity('configuring')
    setError(null)
    try {
      setStatus(await api.configureAi({ api_key: apiKey, model }))
      setApiKey('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'AI 配置失败')
    } finally {
      setActivity(null)
    }
  }

  async function generateBrief() {
    if (!status?.configured || activity || !canUseAi) return
    setActivity('brief')
    setError(null)
    try {
      setProposal(await api.proposeAiChapterBrief(chapter.id, {
        expected_revision: chapter.revision,
        author_intent: authorIntent,
      }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'AI 章纲生成失败')
    } finally {
      setActivity(null)
    }
  }

  async function generateDraft() {
    if (!status?.configured || activity || !canGenerateDraft) return
    setActivity('draft')
    setError(null)
    try {
      onDraftGenerated(await api.generateAiDraft(chapter.id, {
        expected_revision: chapter.revision,
        author_intent: authorIntent,
      }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'AI 正文生成失败')
    } finally {
      setActivity(null)
    }
  }

  function adoptProposal() {
    if (!proposal) return
    onAdoptProposal(proposal)
    setProposal(null)
  }

  const configured = status?.configured === true

  return (
    <section className="ai-coauthor" aria-labelledby="ai-coauthor-title">
      <header>
        <div>
          <p>AI 共创</p>
          <h3 id="ai-coauthor-title">说一句想法，让 AI 完成章纲和初稿</h3>
        </div>
        <span data-ready={configured}>
          {status === null ? '读取中' : configured ? `${status.provider} · ${status.model}` : '未配置'}
        </span>
      </header>

      {!configured ? (
        <div className="ai-setup">
          <p>API Key 只保存在本地服务内存，重启后清除，不写入作品或浏览器存储。</p>
          <label>
            OpenAI API Key
            <input
              type="password"
              aria-label="OpenAI API Key"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              autoComplete="off"
              spellCheck={false}
              placeholder="sk-…"
            />
          </label>
          <label>
            模型
            <input
              aria-label="AI 模型"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              maxLength={100}
              spellCheck={false}
            />
          </label>
          <button type="button" onClick={configureAi} disabled={activity !== null || apiKey.trim().length < 20}>
            {activity === 'configuring' ? '正在配置…' : '启用 AI 共创'}
          </button>
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
            点击生成会把本章章纲、近期正文、正式事实及已确认资料发送给 OpenAI；未确认资料和 API Key 不会进入提示词。
          </p>
          {!canGenerateDraft ? <p>先采用并保存完整章纲，即可让 AI 写整章。</p> : null}
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
    </section>
  )
}
