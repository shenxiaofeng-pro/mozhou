import type { DiagnosticSummary } from '@mozhou/contracts'
import { useEffect, useState } from 'react'

import { api } from '../api'

interface SystemDiagnosticsDialogProps {
  onClose: () => void
}

const checkLabels: Record<string, string> = {
  database_integrity: '数据库完整性',
  free_disk: '可用磁盘',
  schema_compatibility: '数据版本',
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024).toLocaleString('zh-CN')} KiB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MiB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GiB`
}

export function SystemDiagnosticsDialog({ onClose }: SystemDiagnosticsDialogProps) {
  const [summary, setSummary] = useState<DiagnosticSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isExporting, setIsExporting] = useState(false)

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  useEffect(() => {
    let active = true
    api.getDiagnostics()
      .then((result) => {
        if (active) setSummary(result)
      })
      .catch((failure: unknown) => {
        if (active) setError(failure instanceof Error ? failure.message : '无法完成系统检查')
      })
    return () => {
      active = false
    }
  }, [])

  const exportBundle = async () => {
    setIsExporting(true)
    setError(null)
    try {
      const { blob, filename } = await api.exportDiagnosticBundle()
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = filename
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '诊断包导出失败')
    } finally {
      setIsExporting(false)
    }
  }

  return (
    <div className="diagnostics-dialog-backdrop" role="presentation">
      <section
        className="diagnostics-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="diagnostics-dialog-title"
      >
        <header>
          <div>
            <p>SYSTEM HEALTH / 本机体检</p>
            <h2 id="diagnostics-dialog-title">创作数据是否安稳</h2>
          </div>
          <button type="button" aria-label="关闭系统诊断" onClick={onClose}>×</button>
        </header>

        {error ? <p className="diagnostics-error" role="alert">{error}</p> : null}
        {!summary ? (
          <p className="diagnostics-loading" role="status">正在执行只读检查…</p>
        ) : (
          <div className="diagnostics-content">
            <ul className="diagnostics-checks" aria-label="检查结果">
              {summary.checks.map((check) => (
                <li key={check.key} data-status={check.status}>
                  <span aria-hidden="true">{check.status === 'ok' ? '✓' : '!'}</span>
                  <div>
                    <strong>{checkLabels[check.key] ?? check.key}</strong>
                    <p>{check.message}</p>
                  </div>
                </li>
              ))}
            </ul>

            <dl className="diagnostics-stats">
              <div><dt>作品</dt><dd>{summary.counts.projects ?? 0}</dd></div>
              <div><dt>章节</dt><dd>{summary.counts.chapters ?? 0}</dd></div>
              <div><dt>任务</dt><dd>{summary.counts.jobs ?? 0}</dd></div>
              <div><dt>数据库</dt><dd>{formatBytes(summary.database_bytes)}</dd></div>
              <div><dt>磁盘可用</dt><dd>{formatBytes(summary.free_disk_bytes)}</dd></div>
              <div><dt>数据版本</dt><dd>v{summary.schema_version}</dd></div>
            </dl>

            <aside>
              <strong>诊断包默认不带创作内容</strong>
              <p>只含系统版本、数量统计、完整性结果和脱敏事件；不含书名、正文、资料原文、文件路径或 API Key。</p>
            </aside>
          </div>
        )}

        <footer>
          <button type="button" onClick={onClose}>返回书架</button>
          <button type="button" disabled={!summary || isExporting} onClick={() => { void exportBundle() }}>
            {isExporting ? '正在封装…' : '导出脱敏诊断包'}
          </button>
        </footer>
      </section>
    </div>
  )
}
