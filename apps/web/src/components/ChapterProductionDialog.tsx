import type {
  Chapter,
  ChapterDraftCandidate,
  ChapterOutlineCandidate,
  ChapterProductionOutboundPreview,
  ChapterProductionSnapshot,
  GenerateChapterDraftInput,
  GenerateChapterOutlineInput,
  Job,
  Project,
  RegenerateChapterSelectionInput,
  ReviewChapterCandidateInput,
} from '@mozhou/contracts'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { ApiError, aiCredentialStore, api } from '../api'
import {
  ChapterProductionWorkbench,
  type AdoptChapterCandidateRequest,
  type ChapterProductionCandidate,
  type ChapterProductionOutline,
  type ChapterProductionPreflight,
  type LockChangeRequest,
  type MergeCandidatesRequest,
  type SaveCandidateRequest,
  type SelectionInstructionRequest,
  type UndoRequest,
} from './ChapterProductionWorkbench'

interface ChapterProductionDialogProps {
  project: Project
  chapter: Chapter
  initialFocus?: 'outline' | 'candidate'
  onClose: () => void
  onChapterChanged: (chapter: Chapter) => void
  onOpenTaskCenter: () => void
}

type PendingAction =
  | { kind: 'outline'; input: GenerateChapterOutlineInput }
  | { kind: 'draft'; input: GenerateChapterDraftInput }
  | { kind: 'rewrite'; candidateId: string; input: RegenerateChapterSelectionInput }
  | { kind: 'review'; candidateId: string; input: ReviewChapterCandidateInput }

interface PendingPreview {
  action: PendingAction
  preview: ChapterProductionOutboundPreview
}

const activeJobStates = new Set(['queued', 'running', 'pause_requested'])
const retryableJobStates = new Set(['failed', 'interrupted', 'cancelled'])
const productionWorkflows = new Set([
  'chapter_production_outline',
  'chapter_production_draft',
  'chapter_production_rewrite',
  'chapter_production_review',
])

const dimensionLabels = {
  continuity: '连续性',
  serial_rhythm: '连载节奏',
  character: '人物',
  realism: '现实性',
  rebirth_logic: '重生逻辑',
  style: '文风',
  format: '格式',
} as const

const outlineFieldMeta: Array<{
  key: keyof ChapterProductionOutline
  apiKey: 'reader_promise' | 'opening_hook' | 'state_change' | 'emotional_payoff' | 'ending_cliffhanger'
  label: string
}> = [
  { key: 'readerPromise', apiKey: 'reader_promise', label: '读者承诺' },
  { key: 'openingHook', apiKey: 'opening_hook', label: '开篇钩子' },
  { key: 'stateChange', apiKey: 'state_change', label: '状态变化' },
  { key: 'emotionalPayoff', apiKey: 'emotional_payoff', label: '情绪兑现' },
  { key: 'endingCliffhanger', apiKey: 'ending_cliffhanger', label: '章末悬念' },
]

function idempotencyKey(prefix: string): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return `${prefix}:${crypto.randomUUID()}`
  return `${prefix}:${Date.now()}:${Math.random().toString(16).slice(2)}`
}

async function sha256Text(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

function viewOutline(chapter: Chapter, outline: ChapterOutlineCandidate | null): ChapterProductionOutline {
  const content = outline?.current_version.content
  return {
    readerPromise: content?.reader_promise ?? chapter.reader_promise ?? '',
    openingHook: content?.opening_hook ?? chapter.opening_hook ?? '',
    stateChange: content?.state_change ?? chapter.state_change ?? '',
    emotionalPayoff: content?.emotional_payoff ?? chapter.emotional_payoff ?? '',
    endingCliffhanger: content?.ending_cliffhanger ?? chapter.ending_cliffhanger ?? '',
  }
}

function apiOutline(
  chapter: Chapter,
  current: ChapterOutlineCandidate,
  outline: ChapterProductionOutline,
) {
  return {
    ...current.current_version.content,
    title: current.current_version.content.title || chapter.title,
    reader_promise: outline.readerPromise,
    opening_hook: outline.openingHook,
    state_change: outline.stateChange,
    emotional_payoff: outline.emotionalPayoff,
    ending_cliffhanger: outline.endingCliffhanger,
  }
}

function currentOutline(snapshot: ChapterProductionSnapshot | null): ChapterOutlineCandidate | null {
  if (!snapshot) return null
  return snapshot.outlines.find(
    (outline) => outline.id === snapshot.production.current_outline_candidate_id,
  ) ?? snapshot.outlines.at(-1) ?? null
}

function viewPreflight(
  outline: ChapterProductionOutline,
  outlineCandidate: ChapterOutlineCandidate | null,
  snapshot: ChapterProductionSnapshot | null,
): ChapterProductionPreflight {
  if (!outlineCandidate) {
    return {
      state: 'ready',
      checks: outlineFieldMeta.map(({ key, label }) => ({
        id: key,
        label,
        state: outline[key].trim() ? 'passed' : 'warning',
        detail: outline[key].trim() ? '已有作者输入，AI 会把它纳入章纲候选。' : '可由 AI 先提出章纲候选。',
      })),
      blockingReasons: [],
    }
  }

  const content = outlineCandidate.current_version.content
  const latest = snapshot?.preflight_checks.find((check) => (
    check.outline_candidate_id === outlineCandidate.id
    && check.outline_revision === outlineCandidate.current_version.revision
    && check.outline_content_sha256 === outlineCandidate.current_version.content_sha256
  ))
  const missing = outlineFieldMeta
    .filter(({ apiKey }) => !content[apiKey].trim())
    .map(({ label }) => label)
  return {
    state: missing.length > 0 ? 'blocked' : 'ready',
    checks: outlineFieldMeta.map(({ key, apiKey, label }) => {
      const passed = Boolean(content[apiKey].trim())
      return {
        id: key,
        label,
        state: passed ? 'passed' : 'blocked',
        detail: passed
          ? latest?.passed ? '已通过当前章纲版本的写前检查。' : '生成前会再由本地服务校验。'
          : `请先补全${label}，正文模型不会被调用。`,
      }
    }),
    blockingReasons: missing.map((label) => `请先补全${label}`),
  }
}

function viewCandidates(snapshot: ChapterProductionSnapshot | null): ChapterProductionCandidate[] {
  if (!snapshot) return []
  return snapshot.candidates.map((candidate) => {
    const review = snapshot.reviews.find((item) => (
      item.candidate_id === candidate.id
      && item.candidate_version_id === candidate.current_version.id
      && item.candidate_revision === candidate.current_version.revision
      && item.candidate_content_sha256 === candidate.current_version.content_sha256
    ))
    return {
      id: candidate.id,
      label: candidate.label,
      revision: candidate.current_version.revision,
      versionId: candidate.current_version.id,
      contentSha256: candidate.current_version.content_sha256,
      basedOnChapterRevision: snapshot.production.base_chapter_revision,
      text: candidate.current_version.content,
      state: candidate.state === 'available' ? 'candidate' : candidate.state,
      reviewItems: review?.findings.map((finding) => ({
        dimension: dimensionLabels[finding.dimension],
        state: finding.severity === 'critical' ? 'blocked' : finding.severity === 'warning' ? 'warning' : 'passed',
        summary: finding.suggestion ? `${finding.summary} ${finding.suggestion}` : finding.summary,
      })) ?? [],
      lockedRanges: candidate.locks.map((lock) => ({
        id: lock.id,
        start: lock.start_char,
        end: lock.end_char,
      })),
    }
  })
}

function candidateEdit(before: string, after: string): { start: number; end: number; replacement: string } | null {
  if (before === after) return null
  let start = 0
  while (start < before.length && start < after.length && before[start] === after[start]) start += 1
  let beforeEnd = before.length
  let afterEnd = after.length
  while (beforeEnd > start && afterEnd > start && before[beforeEnd - 1] === after[afterEnd - 1]) {
    beforeEnd -= 1
    afterEnd -= 1
  }
  return { start, end: beforeEnd, replacement: after.slice(start, afterEnd) }
}

function productionError(caught: unknown): string {
  if (!(caught instanceof ApiError)) {
    return caught instanceof Error ? caught.message : '单章生产操作失败。'
  }
  const labels: Record<string, string> = {
    chapter_changed: '正式正文已变更；候选编辑已保留，请刷新后重新检查。',
    production_chapter_changed: '本轮生产基于旧正文，不能写入当前版本。',
    candidate_changed: '候选已在其他位置更新，当前编辑已保留，请刷新对照。',
    outline_changed: '章纲候选已更新，请刷新后继续。',
    preflight_not_passed: '写前检查未通过，正文模型没有被调用。',
    external_processing_not_confirmed: '请先确认把预览中的内容发送给当前模型线路。',
    unknown_cost_not_confirmed: '当前线路费用未知，需要作者额外确认。',
    estimated_cost_exceeds_limit: '最新估算超过你已确认的费用上限，请重新预览。',
    creative_context_changed: '创作上下文已变化，请重新预览外发内容。',
    writing_pattern_profile_required: '缺少已启用的写作模式，请先完成写作配方。',
    writing_pattern_profile_stale: '写作配方已更新，请重新检查本章上下文。',
    writing_pattern_profile_over_limit: '当前写作配方过长，请精简后再生成。',
    required_context_over_budget: '必需的创作上下文超出预算，请提高上下文预算。',
  }
  return caught.code ? labels[caught.code] ?? caught.message : caught.message
}

async function withProductionError<T>(action: () => Promise<T>): Promise<T> {
  try {
    return await action()
  } catch (caught) {
    throw new Error(productionError(caught), { cause: caught })
  }
}

export function ChapterProductionDialog({
  project,
  chapter,
  initialFocus,
  onClose,
  onChapterChanged,
  onOpenTaskCenter,
}: ChapterProductionDialogProps) {
  const [snapshot, setSnapshot] = useState<ChapterProductionSnapshot | null>(null)
  const [outlineDraft, setOutlineDraft] = useState<ChapterProductionOutline>(() => viewOutline(chapter, null))
  const [authorIntent, setAuthorIntent] = useState('')
  const [tokenBudget, setTokenBudget] = useState(24_000)
  const [pending, setPending] = useState<PendingPreview | null>(null)
  const [unknownCostConfirmed, setUnknownCostConfirmed] = useState(false)
  const [activeJob, setActiveJob] = useState<Job | null>(null)
  const [loading, setLoading] = useState(true)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [recoveryText, setRecoveryText] = useState<string | null>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const backdropRef = useRef<HTMLDivElement>(null)
  const dialogRef = useRef<HTMLElement>(null)
  const previewTitleRef = useRef<HTMLHeadingElement>(null)
  const decisionKeys = useRef(new Map<string, string>())

  const productionId = snapshot?.production.id ?? null
  const outlineCandidate = useMemo(() => currentOutline(snapshot), [snapshot])
  const candidates = useMemo(() => viewCandidates(snapshot), [snapshot])
  const preflight = useMemo(
    () => viewPreflight(outlineDraft, outlineCandidate, snapshot),
    [outlineCandidate, outlineDraft, snapshot],
  )
  const hasConflict = Boolean(
    snapshot
    && !['adopted', 'rejected'].includes(snapshot.production.state)
    && snapshot.production.base_chapter_revision !== chapter.revision,
  )

  const refreshSnapshot = useCallback(async (id: string) => {
    const next = await api.getChapterProduction(id)
    setSnapshot(next)
    const nextOutline = currentOutline(next)
    if (nextOutline) setOutlineDraft(viewOutline(chapter, nextOutline))
    return next
  }, [chapter])

  useEffect(() => {
    let stopped = false
    async function load() {
      setLoading(true)
      setError(null)
      const digestPromise = sha256Text(chapter.content)
      const jobsPromise = api.listJobs(project.id)
      const productionPromise = api.getCurrentChapterProduction(project.id, chapter.id)
        .catch((caught: unknown) => {
          if (caught instanceof ApiError && caught.status === 404) return null
          throw caught
        })
      try {
        const [digest, jobs, restored] = await Promise.all([digestPromise, jobsPromise, productionPromise])
        const next = restored ?? await api.createChapterProduction(project.id, chapter.id, {
          expected_chapter_revision: chapter.revision,
          expected_chapter_content_sha256: digest,
        })
        if (stopped) return
        setSnapshot(next)
        setOutlineDraft(viewOutline(chapter, currentOutline(next)))
        const recoverable = jobs
          .filter((job) => (
            job.chapter_id === chapter.id
            && productionWorkflows.has(job.workflow)
            && (activeJobStates.has(job.state) || retryableJobStates.has(job.state))
          ))
          .sort((left, right) => right.updated_at.localeCompare(left.updated_at))[0]
        setActiveJob(recoverable ?? null)
      } catch (caught) {
        if (!stopped) setError(productionError(caught))
      } finally {
        if (!stopped) setLoading(false)
      }
    }
    void load()
    return () => { stopped = true }
  }, [chapter, project.id])

  useEffect(() => {
    closeRef.current?.focus()
    const backdrop = backdropRef.current
    const parent = backdrop?.parentElement
    if (!backdrop || !parent) return undefined
    const previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const hiddenSiblings = Array.from(parent.children)
      .filter((element): element is HTMLElement => element instanceof HTMLElement && element !== backdrop)
      .map((element) => ({
        element,
        ariaHidden: element.getAttribute('aria-hidden'),
        inert: element.inert,
      }))
    for (const { element } of hiddenSiblings) {
      element.inert = true
      element.setAttribute('aria-hidden', 'true')
    }
    return () => {
      document.body.style.overflow = previousBodyOverflow
      for (const { element, ariaHidden, inert } of hiddenSiblings) {
        element.inert = inert
        if (ariaHidden === null) element.removeAttribute('aria-hidden')
        else element.setAttribute('aria-hidden', ariaHidden)
      }
    }
  }, [])

  useEffect(() => {
    function keepFocusInside(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        if (pending) {
          setPending(null)
          closeRef.current?.focus()
        } else {
          onClose()
        }
        return
      }
      if (event.key !== 'Tab') return
      const dialog = dialogRef.current
      if (!dialog) return
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
      )).filter((element) => !element.hidden && !element.closest('[hidden]'))
      const first = focusable[0]
      const last = focusable.at(-1)
      if (!first || !last) {
        event.preventDefault()
        dialog.focus()
        return
      }
      const active = document.activeElement
      if (event.shiftKey && (active === first || !dialog.contains(active))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (active === last || !dialog.contains(active))) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', keepFocusInside)
    return () => window.removeEventListener('keydown', keepFocusInside)
  }, [onClose, pending])

  useEffect(() => {
    if (pending) previewTitleRef.current?.focus()
  }, [pending])

  const activeJobId = activeJob?.id ?? null
  const activeJobState = activeJob?.state ?? null

  useEffect(() => {
    if (!activeJobId || !activeJobState || !activeJobStates.has(activeJobState) || !productionId) return undefined
    const jobId = activeJobId
    const currentProductionId = productionId
    let stopped = false
    let timer: number | undefined
    async function poll() {
      try {
        const job = await api.getJob(jobId)
        if (stopped) return
        setActiveJob(job)
        if (job.state === 'succeeded') {
          if (job.workflow === 'chapter_production_outline') {
            await api.getChapterProductionOutlineJobResult(currentProductionId, job.id)
          } else if (job.workflow === 'chapter_production_draft') {
            await api.getChapterProductionDraftJobResult(currentProductionId, job.id)
          } else {
            const completed = await refreshSnapshot(currentProductionId)
            if (job.workflow === 'chapter_production_rewrite') {
              const candidate = completed.candidates.find((item) => item.current_version.source_job_id === job.id)
              if (!candidate) throw new Error('改写任务已完成，但尚未找到对应候选版本。')
              await api.getChapterProductionRewriteJobResult(currentProductionId, candidate.id, job.id)
            } else if (job.workflow === 'chapter_production_review') {
              const review = completed.reviews.find((item) => item.source_job_id === job.id)
              if (!review) throw new Error('审校任务已完成，但尚未找到对应审校结果。')
              await api.getChapterProductionCandidateReviewJobResult(currentProductionId, review.candidate_id, job.id)
            }
          }
          await refreshSnapshot(currentProductionId)
          if (!stopped) {
            setActiveJob(null)
            setNotice('任务已完成，结果已进入候选区。')
          }
          return
        }
        if (retryableJobStates.has(job.state)) {
          setError(job.error_message ?? '生成任务已中断，可从断点继续。')
          return
        }
        timer = window.setTimeout(poll, 700)
      } catch (caught) {
        if (!stopped) setError(productionError(caught))
      }
    }
    void poll()
    return () => {
      stopped = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [activeJobId, activeJobState, productionId, refreshSnapshot])

  function replaceOutline(updated: ChapterOutlineCandidate) {
    setSnapshot((current) => current ? {
      ...current,
      outlines: current.outlines.some((item) => item.id === updated.id)
        ? current.outlines.map((item) => item.id === updated.id ? updated : item)
        : [...current.outlines, updated],
    } : current)
    setOutlineDraft(viewOutline(chapter, updated))
  }

  function replaceCandidate(updated: ChapterDraftCandidate) {
    setSnapshot((current) => current ? {
      ...current,
      candidates: current.candidates.some((item) => item.id === updated.id)
        ? current.candidates.map((item) => item.id === updated.id ? updated : item)
        : [...current.candidates, updated],
    } : current)
  }

  async function saveOutline(nextOutline: ChapterProductionOutline) {
    if (!productionId || !outlineCandidate) throw new Error('先生成一份章纲候选，再保存作者调整。')
    const updated = await api.updateChapterProductionOutline(productionId, outlineCandidate.id, {
      expected_outline_revision: outlineCandidate.current_version.revision,
      expected_outline_content_sha256: outlineCandidate.current_version.content_sha256,
      content: apiOutline(chapter, outlineCandidate, nextOutline),
    })
    replaceOutline(updated)
    return updated
  }

  async function prepareGeneration() {
    if (!productionId) throw new Error('单章生产状态尚未准备完成。')
    setError(null)
    setNotice(null)
    if (!outlineCandidate) {
      const input: GenerateChapterOutlineInput = {
        author_intent: authorIntent.trim(),
        token_budget: Math.min(tokenBudget, 8_000),
        label: 'AI 章纲',
      }
      setPending({ action: { kind: 'outline', input }, preview: await api.previewChapterProductionOutline(productionId, input) })
      setUnknownCostConfirmed(false)
      return
    }

    const desired = apiOutline(chapter, outlineCandidate, outlineDraft)
    const savedContent = outlineCandidate.current_version.content
    let usableOutline = outlineCandidate
    if (JSON.stringify(desired) !== JSON.stringify(savedContent)) {
      usableOutline = await saveOutline(outlineDraft)
    }
    const guard = {
      outline_candidate_id: usableOutline.id,
      expected_outline_revision: usableOutline.current_version.revision,
      expected_outline_content_sha256: usableOutline.current_version.content_sha256,
    }
    const check = await api.checkChapterProductionPreflight(productionId, usableOutline.id, guard)
    setSnapshot((current) => current ? {
      ...current,
      preflight_checks: [check, ...current.preflight_checks.filter((item) => item.id !== check.id)],
    } : current)
    if (!check.passed) throw new Error('写前检查未通过，正文模型没有被调用。')
    const input: GenerateChapterDraftInput = {
      ...guard,
      author_intent: authorIntent.trim(),
      token_budget: tokenBudget,
      label: `AI 正文候选 ${(snapshot?.candidates.length ?? 0) + 1}`,
    }
    setPending({ action: { kind: 'draft', input }, preview: await api.previewChapterProductionDraft(productionId, input) })
    setUnknownCostConfirmed(false)
  }

  async function confirmPreview() {
    if (!pending || !productionId || busyAction) return
    if (pending.preview.estimated_cost_microusd === null && !unknownCostConfirmed) return
    setBusyAction('confirm-preview')
    setError(null)
    try {
      const status = await api.getAiStatus()
      if (pending.preview.profile_id && pending.preview.profile_id !== status.profile_id) {
        await aiCredentialStore.activateSaved(pending.preview.profile_id)
      }
      const confirmation = {
        context_packet_id: pending.preview.context_packet_id,
        context_packet_sha256: pending.preview.context_packet_sha256,
        confirm_external_processing: true,
        confirm_unknown_cost: pending.preview.estimated_cost_microusd === null,
        max_estimated_cost_microusd: pending.preview.estimated_cost_microusd,
      }
      let job: Job
      if (pending.action.kind === 'outline') {
        job = await api.startChapterProductionOutlineJob(productionId, {
          ...pending.action.input, ...confirmation,
        })
      } else if (pending.action.kind === 'draft') {
        job = await api.startChapterProductionDraftJob(productionId, {
          ...pending.action.input, ...confirmation,
        })
      } else if (pending.action.kind === 'rewrite') {
        job = await api.startChapterProductionRewriteJob(
          productionId,
          pending.action.candidateId,
          { ...pending.action.input, ...confirmation },
        )
      } else {
        job = await api.startChapterProductionCandidateReviewJob(
          productionId,
          pending.action.candidateId,
          { ...pending.action.input, ...confirmation },
        )
      }
      setActiveJob(job)
      setPending(null)
      setNotice('任务已进入本地队列，关闭或刷新页面也不会丢失。')
    } catch (caught) {
      setError(productionError(caught))
    } finally {
      setBusyAction(null)
    }
  }

  async function persistCandidateText(request: SaveCandidateRequest): Promise<ChapterDraftCandidate> {
    if (!productionId || !snapshot) throw new Error('候选状态尚未准备完成。')
    const candidate = snapshot.candidates.find((item) => item.id === request.candidateId)
    if (!candidate) throw new Error('候选已不在当前生产轮次。')
    const edit = candidateEdit(candidate.current_version.content, request.authorText)
    if (!edit) return candidate
    const selected = candidate.current_version.content.slice(edit.start, edit.end)
    const updated = await api.editChapterProductionCandidate(productionId, candidate.id, {
      expected_candidate_revision: candidate.current_version.revision,
      expected_candidate_content_sha256: candidate.current_version.content_sha256,
      selection: {
        start_char: edit.start,
        end_char: edit.end,
        selected_text_sha256: await sha256Text(selected),
      },
      replacement: edit.replacement,
    })
    replaceCandidate(updated)
    return updated
  }

  async function prepareRewrite(request: SelectionInstructionRequest) {
    if (!productionId) throw new Error('候选状态尚未准备完成。')
    const saved = await persistCandidateText({
      candidateId: request.candidateId,
      candidateRevision: request.candidateRevision,
      baseText: '',
      authorText: request.currentText,
      lockedRanges: request.lockedRanges,
    })
    const selectedText = saved.current_version.content.slice(request.selection.start, request.selection.end)
    const input: RegenerateChapterSelectionInput = {
      expected_candidate_revision: saved.current_version.revision,
      expected_candidate_content_sha256: saved.current_version.content_sha256,
      selection: {
        start_char: request.selection.start,
        end_char: request.selection.end,
        selected_text_sha256: await sha256Text(selectedText),
      },
      intent: 'custom',
      custom_instruction: request.instruction,
      token_budget: Math.min(tokenBudget, 8_000),
    }
    const preview = await api.previewChapterProductionRewrite(productionId, saved.id, input)
    setPending({ action: { kind: 'rewrite', candidateId: saved.id, input }, preview })
    setUnknownCostConfirmed(false)
  }

  async function lockSelection(request: LockChangeRequest) {
    if (!productionId || !snapshot) throw new Error('候选状态尚未准备完成。')
    const candidate = snapshot.candidates.find((item) => item.id === request.candidateId)
    if (!candidate) throw new Error('候选已不在当前生产轮次。')
    const selected = candidate.current_version.content.slice(request.range.start, request.range.end)
    await api.lockChapterProductionSelection(productionId, candidate.id, {
      expected_candidate_revision: candidate.current_version.revision,
      expected_candidate_content_sha256: candidate.current_version.content_sha256,
      selection: {
        start_char: request.range.start,
        end_char: request.range.end,
        selected_text_sha256: await sha256Text(selected),
      },
    })
    await refreshSnapshot(productionId)
  }

  async function unlockSelection(request: LockChangeRequest & { lockId?: string }) {
    if (!productionId || !snapshot || !request.lockId) throw new Error('该锁定尚未同步，请刷新后重试。')
    const candidate = snapshot.candidates.find((item) => item.id === request.candidateId)
    if (!candidate) throw new Error('候选已不在当前生产轮次。')
    await api.unlockChapterProductionSelection(productionId, candidate.id, request.lockId, {
      expected_candidate_revision: candidate.current_version.revision,
      expected_candidate_content_sha256: candidate.current_version.content_sha256,
    })
    await refreshSnapshot(productionId)
  }

  async function undoCandidate(request: UndoRequest) {
    if (!productionId || !snapshot) throw new Error('候选状态尚未准备完成。')
    const candidate = snapshot.candidates.find((item) => item.id === request.candidateId)
    if (!candidate) throw new Error('候选已不在当前生产轮次。')
    replaceCandidate(await api.undoChapterProductionCandidate(productionId, candidate.id, {
      expected_candidate_revision: candidate.current_version.revision,
      expected_candidate_content_sha256: candidate.current_version.content_sha256,
      target_version_id: null,
    }))
  }

  async function mergeCandidates(request: MergeCandidatesRequest) {
    if (!productionId || !snapshot) throw new Error('候选状态尚未准备完成。')
    const sources = snapshot.candidates.filter((candidate) => request.candidateIds.includes(candidate.id))
    if (sources.length < 2) throw new Error('至少选择两份当前候选才能合并。')
    const merged = await api.mergeChapterProductionCandidates(productionId, {
      sources: sources.map((candidate) => ({
        candidate_id: candidate.id,
        candidate_version_id: candidate.current_version.id,
        candidate_revision: candidate.current_version.revision,
        candidate_content_sha256: candidate.current_version.content_sha256,
        start_char: 0,
        end_char: candidate.current_version.content.length,
        selected_text_sha256: candidate.current_version.content_sha256,
      })),
      label: '作者选择合并候选',
      separator: '\n\n',
    })
    replaceCandidate(merged)
  }

  async function prepareReview(request: UndoRequest) {
    if (!productionId || !snapshot) throw new Error('候选状态尚未准备完成。')
    const candidate = snapshot.candidates.find((item) => item.id === request.candidateId)
    if (!candidate) throw new Error('候选已不在当前生产轮次。')
    const input: ReviewChapterCandidateInput = {
      expected_candidate_revision: candidate.current_version.revision,
      expected_candidate_content_sha256: candidate.current_version.content_sha256,
      token_budget: 16_000,
    }
    setPending({
      action: { kind: 'review', candidateId: candidate.id, input },
      preview: await api.previewChapterProductionCandidateReview(productionId, candidate.id, input),
    })
    setUnknownCostConfirmed(false)
  }

  function stableDecisionKey(identity: string): string {
    const existing = decisionKeys.current.get(identity)
    if (existing) return existing
    const next = idempotencyKey('chapter-production')
    decisionKeys.current.set(identity, next)
    return next
  }

  async function adoptCandidate(request: AdoptChapterCandidateRequest) {
    if (!productionId || !snapshot) throw new Error('候选状态尚未准备完成。')
    const candidate = await persistCandidateText({
      candidateId: request.candidateId,
      candidateRevision: request.candidateRevision,
      baseText: '',
      authorText: request.authorText,
      lockedRanges: request.lockedRanges,
    })
    const chapterDigest = await sha256Text(chapter.content)
    const candidateSelection = request.candidateSelection ? {
      start_char: request.candidateSelection.start,
      end_char: request.candidateSelection.end,
      selected_text_sha256: await sha256Text(request.candidateSelection.selectedText),
    } : null
    const chapterSelection = request.chapterSelection ? {
      start_char: request.chapterSelection.start,
      end_char: request.chapterSelection.end,
      selected_text_sha256: await sha256Text(request.chapterSelection.selectedText),
    } : null
    const identity = `${candidate.id}:${candidate.current_version.revision}:${chapter.revision}:${request.mode}`
    await api.adoptChapterProductionCandidate(productionId, candidate.id, {
      expected_candidate_revision: candidate.current_version.revision,
      expected_candidate_content_sha256: candidate.current_version.content_sha256,
      expected_chapter_revision: chapter.revision,
      expected_chapter_content_sha256: chapterDigest,
      mode: request.mode,
      candidate_selection: candidateSelection,
      chapter_selection: chapterSelection,
      idempotency_key: stableDecisionKey(identity),
    })
    const updatedChapter = await api.getChapter(chapter.id)
    onChapterChanged(updatedChapter)
    await refreshSnapshot(productionId)
    setNotice(request.mode === 'whole' ? '候选已采用为本章正文。' : '候选选区已通过版本门禁并入正文。')
  }

  async function rejectCandidate(request: { candidateId: string; reason: string }) {
    if (!productionId || !snapshot) throw new Error('候选状态尚未准备完成。')
    const candidate = snapshot.candidates.find((item) => item.id === request.candidateId)
    if (!candidate) throw new Error('候选已不在当前生产轮次。')
    await api.rejectChapterProductionCandidate(productionId, candidate.id, {
      expected_candidate_revision: candidate.current_version.revision,
      expected_candidate_content_sha256: candidate.current_version.content_sha256,
      reason: request.reason,
      idempotency_key: stableDecisionKey(`${candidate.id}:${candidate.current_version.revision}:reject`),
    })
    await refreshSnapshot(productionId)
    setNotice('拒绝决定已记录，正式正文没有改变。')
  }

  async function recoverConflict(request: { authorText: string }) {
    setRecoveryText(request.authorText)
    const latest = await api.getChapter(chapter.id)
    onChapterChanged(latest)
    const digest = await sha256Text(latest.content)
    const next = await api.createChapterProduction(project.id, latest.id, {
      expected_chapter_revision: latest.revision,
      expected_chapter_content_sha256: digest,
    })
    setSnapshot(next)
    setOutlineDraft(viewOutline(latest, currentOutline(next)))
    setPending(null)
    setActiveJob(null)
    setNotice('已按最新正文开启新一轮；旧候选编辑保留在下方恢复区。')
  }

  async function cancelJob() {
    if (!activeJob || busyAction) return
    setBusyAction('cancel-job')
    try {
      setActiveJob(await api.cancelJob(activeJob.id))
    } catch (caught) {
      setError(productionError(caught))
    } finally {
      setBusyAction(null)
    }
  }

  async function retryJob() {
    if (!activeJob || busyAction) return
    setBusyAction('retry-job')
    setError(null)
    try {
      setActiveJob(await api.retryJob(activeJob.id))
    } catch (caught) {
      setError(productionError(caught))
    } finally {
      setBusyAction(null)
    }
  }

  return (
    <div ref={backdropRef} className="chapter-production-dialog-backdrop">
      <section ref={dialogRef} className="chapter-production-dialog" role="dialog" aria-modal="true" aria-labelledby="chapter-production-dialog-title" tabIndex={-1}>
        <header className="chapter-production-dialog-bar">
          <div>
            <span>CHAPTER PRODUCTION</span>
            <strong id="chapter-production-dialog-title">本章候选生产台</strong>
          </div>
          <button ref={closeRef} type="button" aria-label="关闭单章生产工作台" onClick={onClose}>×</button>
        </header>

        <div className="chapter-production-dialog-content">
          <section className="chapter-production-command-strip" aria-label="本章 AI 生产设置">
            <label>
              本章创作意图（可选）
              <textarea
                value={authorIntent}
                rows={2}
                maxLength={1000}
                placeholder="例如：保留事实，让主角付出更具体的代价"
                onChange={(event) => { setAuthorIntent(event.target.value); setPending(null) }}
              />
            </label>
            <label>
              上下文预算
              <select value={tokenBudget} onChange={(event) => { setTokenBudget(Number(event.target.value)); setPending(null) }}>
                <option value={8000}>8,000 Token · 精简</option>
                <option value={16000}>16,000 Token · 标准</option>
                <option value={24000}>24,000 Token · 长篇推荐</option>
                <option value={48000}>48,000 Token · 大上下文</option>
              </select>
            </label>
            <div>
              <span>生产轮次</span>
              <strong>{snapshot ? `${snapshot.production.state} · v${snapshot.production.revision}` : '正在读取'}</strong>
            </div>
          </section>

          {activeJob ? (
            <section className="chapter-production-job" role="status" aria-live="polite">
              <div>
                <strong>{activeJob.current_step || '任务已进入本地队列'}</strong>
                <span>{activeJob.progress_current} / {activeJob.progress_total || '—'}</span>
              </div>
              <progress value={activeJob.progress_current} max={Math.max(activeJob.progress_total, 1)} />
              <div>
                {activeJobStates.has(activeJob.state) ? (
                  <button type="button" disabled={Boolean(busyAction)} onClick={() => { void cancelJob() }}>停止任务</button>
                ) : retryableJobStates.has(activeJob.state) ? (
                  <button type="button" disabled={Boolean(busyAction)} onClick={() => { void retryJob() }}>从断点继续</button>
                ) : null}
                <button type="button" onClick={onOpenTaskCenter}>在任务中心查看</button>
              </div>
            </section>
          ) : null}

          {pending ? (
            <section className="chapter-production-outbound" aria-labelledby="chapter-production-preview-title">
              <header>
                <div>
                  <p className="section-kicker">OUTBOUND CHECK</p>
                  <h3 id="chapter-production-preview-title" ref={previewTitleRef} tabIndex={-1}>发送前确认</h3>
                </div>
                <strong>{pending.preview.profile_name} · {pending.preview.model}</strong>
              </header>
              <p>{pending.preview.content_scope}</p>
              <ul aria-label="本次外发数据类型">
                {pending.preview.data_types.map((item) => <li key={item}>{item}</li>)}
              </ul>
              <dl>
                <div><dt>上下文字符</dt><dd>{pending.preview.character_count.toLocaleString('zh-CN')}</dd></div>
                <div><dt>预计输入</dt><dd>{pending.preview.estimated_input_tokens.toLocaleString('zh-CN')} Token</dd></div>
                <div><dt>预计输出</dt><dd>{pending.preview.estimated_output_tokens.toLocaleString('zh-CN')} Token</dd></div>
                <div><dt>预计费用</dt><dd>{pending.preview.estimated_cost_microusd === null ? '当前线路未配置价格' : `约 US$ ${(pending.preview.estimated_cost_microusd / 1_000_000).toFixed(4)}`}</dd></div>
              </dl>
              <small>上下文包 {pending.preview.context_packet_id.slice(0, 12)} · {pending.preview.context_compiler_version}</small>
              {pending.preview.estimated_cost_microusd === null ? (
                <label className="chapter-production-unknown-cost">
                  <input type="checkbox" checked={unknownCostConfirmed} onChange={(event) => setUnknownCostConfirmed(event.target.checked)} />
                  我知道该线路费用未知，仍要启动这一次
                </label>
              ) : null}
              <footer>
                <button type="button" onClick={() => setPending(null)} disabled={Boolean(busyAction)}>返回修改</button>
                <button
                  type="button"
                  className="chapter-production-confirm"
                  disabled={Boolean(busyAction) || (pending.preview.estimated_cost_microusd === null && !unknownCostConfirmed)}
                  onClick={() => { void confirmPreview() }}
                >
                  {busyAction === 'confirm-preview' ? '正在启动…' : '确认外发与费用，开始任务'}
                </button>
              </footer>
            </section>
          ) : null}

          {error ? <p className="chapter-production-dialog-error" role="alert">{error}</p> : null}
          {notice ? <p className="chapter-production-dialog-notice" role="status">{notice}</p> : null}

          {loading ? (
            <div className="chapter-production-dialog-loading" role="status">正在恢复本章的章纲、候选和任务进度…</div>
          ) : snapshot ? (
            <ChapterProductionWorkbench
              chapterTitle={chapter.title}
              chapterRevision={chapter.revision}
              officialText={chapter.content}
              outline={outlineDraft}
              preflight={preflight}
              candidates={candidates}
              initialFocus={initialFocus}
              isGenerating={Boolean(activeJobStates.has(activeJob?.state ?? '') || pending || busyAction)}
              conflict={hasConflict ? {
                latestChapterRevision: chapter.revision,
                message: `这一轮基于正文 v${snapshot.production.base_chapter_revision}，当前已是 v${chapter.revision}。`,
              } : null}
              onGenerate={() => withProductionError(prepareGeneration)}
              onOutlineChange={setOutlineDraft}
              onOutlineSave={outlineCandidate ? (nextOutline) => withProductionError(async () => {
                await saveOutline(nextOutline)
              }) : undefined}
              onCandidateSave={(request) => withProductionError(async () => {
                await persistCandidateText(request)
              })}
              onSelectionInstruction={(request) => withProductionError(() => prepareRewrite(request))}
              onLockChange={(request) => withProductionError(() => lockSelection(request))}
              onUnlock={(request) => withProductionError(() => unlockSelection(request))}
              onUndo={(request) => withProductionError(() => undoCandidate(request))}
              onMergeCandidates={(request) => withProductionError(() => mergeCandidates(request))}
              onReview={(request) => withProductionError(() => prepareReview(request))}
              onAdopt={(request) => withProductionError(() => adoptCandidate(request))}
              onReject={(request) => withProductionError(() => rejectCandidate(request))}
              onRefreshConflict={(request) => withProductionError(() => recoverConflict({ authorText: request.authorText }))}
            />
          ) : null}

          {recoveryText ? (
            <details className="chapter-production-recovery" open>
              <summary>旧候选作者编辑 · 仅供恢复</summary>
              <p>已按最新正文开启新一轮；这段文字不会自动写入新候选。</p>
              <textarea value={recoveryText} readOnly aria-label="旧候选作者编辑恢复副本" />
            </details>
          ) : null}
        </div>
      </section>
    </div>
  )
}
