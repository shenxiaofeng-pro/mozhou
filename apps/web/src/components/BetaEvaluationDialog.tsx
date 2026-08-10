import type {
  BetaEvaluationReport,
  BetaFeedbackCategory,
  BetaFeedbackContext,
  Project,
} from '@mozhou/contracts'
import { useEffect, useState, type FormEvent } from 'react'

import { api } from '../api'

interface BetaEvaluationDialogProps {
  project: Project
  onClose: () => void
}

const categoryLabels: Record<BetaFeedbackCategory, string> = {
  workflow: '创作流程',
  ai_quality: 'AI 成稿质量',
  reliability: '可靠性与恢复',
  originality: '原创性保护',
  usability: '使用体验',
}

const contextLabels: Record<BetaFeedbackContext, string> = {
  writing: '正文写作',
  director: '整书总导演',
  review: '审校与改稿',
  reference: '拆书与资料',
  recovery: '保存与恢复',
  release: '安装与发布',
}

function formatRate(value: number | null) {
  return value === null ? '尚无数据' : `${Math.round(value * 100)}%`
}

function formatCost(microusd: number) {
  return `$${(microusd / 1_000_000).toFixed(3)}`
}

export function BetaEvaluationDialog({ project, onClose }: BetaEvaluationDialogProps) {
  const [report, setReport] = useState<BetaEvaluationReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const loadReport = async () => {
    try {
      const nextReport = await api.getBetaReport(project.id)
      setReport(nextReport)
      setError(null)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '无法生成封测报告')
    }
  }

  useEffect(() => {
    let active = true
    api.getBetaReport(project.id)
      .then((nextReport) => {
        if (active) setReport(nextReport)
      })
      .catch((failure: unknown) => {
        if (active) setError(failure instanceof Error ? failure.message : '无法生成封测报告')
      })
    return () => {
      active = false
    }
  }, [project.id])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  const submitFeedback = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    setIsSubmitting(true)
    setError(null)
    try {
      await api.createBetaFeedback(project.id, {
        category: String(data.get('category')) as BetaFeedbackCategory,
        context: String(data.get('context')) as BetaFeedbackContext,
        rating: Number(data.get('rating')),
        note: String(data.get('note') ?? ''),
      })
      form.reset()
      await loadReport()
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '反馈保存失败')
    } finally {
      setIsSubmitting(false)
    }
  }

  const exportReport = () => {
    if (!report) return
    const blob = new Blob([JSON.stringify(report, null, 2)], {
      type: 'application/json;charset=utf-8',
    })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `墨舟封测报告-${project.id.slice(0, 8)}.json`
    document.body.append(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
    void api.recordBetaEvent(project.id, 'report_export').catch(() => undefined)
  }

  return (
    <div className="beta-dialog-backdrop" role="presentation">
      <section
        className="beta-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="beta-dialog-title"
      >
        <header>
          <div>
            <p>CLOSED BETA / 封测航海日志</p>
            <h2 id="beta-dialog-title">《{project.title}》十章闭环</h2>
          </div>
          <button type="button" aria-label="关闭封测报告" onClick={onClose}>×</button>
        </header>

        {error ? <p className="beta-dialog-error" role="alert">{error}</p> : null}
        {!report ? (
          <p className="beta-dialog-loading" role="status">正在汇总本机流程证据…</p>
        ) : (
          <div className="beta-dialog-content">
            <section className="beta-milestones" aria-labelledby="beta-milestone-title">
              <div>
                <p>10 TASKS / 不收集正文</p>
                <h3 id="beta-milestone-title">创作闭环检查</h3>
              </div>
              <ol>
                {report.milestones.map((milestone) => (
                  <li key={milestone.key} data-completed={milestone.completed}>
                    <span aria-hidden="true">{milestone.completed ? '✓' : '○'}</span>
                    <div><strong>{milestone.label}</strong><small>证据 {milestone.evidence_count}</small></div>
                  </li>
                ))}
              </ol>
            </section>

            <section className="beta-metrics" aria-labelledby="beta-metrics-title">
              <div>
                <p>LOCAL METRICS / 本地度量</p>
                <h3 id="beta-metrics-title">AI 是否真正减轻写作</h3>
              </div>
              <dl>
                <div><dt>已写章节</dt><dd>{report.metrics.written_chapter_count}</dd></div>
                <div><dt>定稿章节</dt><dd>{report.metrics.approved_chapter_count}</dd></div>
                <div><dt>候选采用率</dt><dd>{formatRate(report.metrics.ai_adoption_rate)}</dd></div>
                <div><dt>人工修改比例</dt><dd>{formatRate(report.metrics.mean_manual_modification_ratio)}</dd></div>
                <div><dt>审校接受率</dt><dd>{formatRate(report.metrics.review_acceptance_rate)}</dd></div>
                <div><dt>失败恢复率</dt><dd>{formatRate(report.metrics.retry_recovery_rate)}</dd></div>
                <div><dt>模型成本估算</dt><dd>{formatCost(report.metrics.estimated_cost_microusd)}</dd></div>
                <div><dt>开放严重问题</dt><dd>{report.metrics.open_critical_findings}</dd></div>
              </dl>
            </section>

            <form className="beta-feedback-form" onSubmit={(event) => { void submitFeedback(event) }}>
              <div>
                <p>AUTHOR SIGNAL / 作者反馈</p>
                <h3>记录一个真实摩擦点</h3>
              </div>
              <div className="beta-feedback-fields">
                <label>评价维度
                  <select name="category" defaultValue="usability">
                    {Object.entries(categoryLabels).map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                </label>
                <label>发生环节
                  <select name="context" defaultValue="writing">
                    {Object.entries(contextLabels).map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                </label>
                <label>评分
                  <select name="rating" defaultValue="4">
                    {[1, 2, 3, 4, 5].map((rating) => (
                      <option key={rating} value={rating}>{rating} / 5</option>
                    ))}
                  </select>
                </label>
              </div>
              <label>具体反馈（可选）
                <textarea name="note" maxLength={2000} placeholder="发生了什么？你期望怎样更顺？" />
              </label>
              <button type="submit" disabled={isSubmitting}>
                {isSubmitting ? '正在记入本机…' : '保存反馈'}
              </button>
            </form>

            <aside className="beta-privacy-note">
              <strong>报告默认留在本机</strong>
              <p>{report.privacy_notice} 导出后是否交给测试组织者，由作者自行决定。</p>
              <span>已记录反馈 {report.feedback.length} 条</span>
            </aside>
          </div>
        )}

        <footer>
          <button type="button" onClick={onClose}>返回书架</button>
          <button type="button" disabled={!report} onClick={exportReport}>导出脱敏封测报告</button>
        </footer>
      </section>
    </div>
  )
}
