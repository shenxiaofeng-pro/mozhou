import type { ChangeEvent } from 'react'
import { useEffect, useRef, useState } from 'react'

export type ChapterProductionCheckState = 'passed' | 'warning' | 'blocked'
export type ChapterProductionCandidateState = 'candidate' | 'adopted' | 'rejected' | 'stale'

export interface ChapterProductionOutline {
  readerPromise: string
  openingHook: string
  stateChange: string
  emotionalPayoff: string
  endingCliffhanger: string
}

export interface ChapterProductionCheck {
  id: string
  label: string
  state: ChapterProductionCheckState
  detail: string
}

export interface ChapterProductionPreflight {
  state: 'checking' | 'ready' | 'blocked'
  checks: ChapterProductionCheck[]
  blockingReasons: string[]
}

export interface ChapterCandidateReviewItem {
  dimension: string
  state: ChapterProductionCheckState
  summary: string
}

export interface ChapterProductionTextRange {
  id?: string
  start: number
  end: number
}

export interface ChapterProductionCandidate {
  id: string
  label: string
  revision: number
  versionId?: string
  contentSha256?: string
  basedOnChapterRevision: number
  text: string
  state: ChapterProductionCandidateState
  reviewItems: ChapterCandidateReviewItem[]
  lockedRanges?: ChapterProductionTextRange[]
}

export interface ChapterProductionConflict {
  candidateId?: string
  latestChapterRevision: number
  message: string
}

export interface SelectionInstructionRequest {
  candidateId: string
  candidateRevision: number
  currentText: string
  selection: ChapterProductionTextRange & { selectedText: string }
  instruction: string
  lockedRanges: ChapterProductionTextRange[]
}

export interface LockChangeRequest {
  candidateId: string
  candidateRevision: number
  range: ChapterProductionTextRange
  lockedRanges: ChapterProductionTextRange[]
}

export interface SaveCandidateRequest {
  candidateId: string
  candidateRevision: number
  baseText: string
  authorText: string
  lockedRanges: ChapterProductionTextRange[]
}

export interface UndoRequest {
  candidateId: string
  candidateRevision: number
}

export interface MergeCandidatesRequest {
  candidateIds: string[]
  baseCandidateId: string
}

export interface AdoptChapterCandidateRequest {
  candidateId: string
  candidateRevision: number
  expectedChapterRevision: number
  authorText: string
  lockedRanges: ChapterProductionTextRange[]
  mode: 'whole' | 'partial'
  candidateSelection?: ChapterProductionTextRange & { selectedText: string }
  chapterSelection?: ChapterProductionTextRange & { selectedText: string }
}

export interface ChapterProductionWorkbenchProps {
  chapterTitle: string
  chapterRevision: number
  officialText: string
  outline: ChapterProductionOutline
  preflight: ChapterProductionPreflight
  candidates: ChapterProductionCandidate[]
  isGenerating?: boolean
  conflict?: ChapterProductionConflict | null
  onGenerate: () => void | Promise<void>
  onOutlineChange?: (outline: ChapterProductionOutline) => void
  onOutlineSave?: (outline: ChapterProductionOutline) => void | Promise<void>
  onCandidateSave?: (request: SaveCandidateRequest) => void | Promise<void>
  onSelectionInstruction?: (
    request: SelectionInstructionRequest,
  ) => void | { replacementText: string } | Promise<void | { replacementText: string }>
  onLockChange?: (request: LockChangeRequest) => void | Promise<void>
  onUnlock?: (request: LockChangeRequest & { lockId?: string }) => void | Promise<void>
  onUndo?: (request: UndoRequest) => void | Promise<void>
  onMergeCandidates?: (request: MergeCandidatesRequest) => void | Promise<void>
  onReview?: (request: UndoRequest) => void | Promise<void>
  onAdopt?: (request: AdoptChapterCandidateRequest) => void | Promise<void>
  onReject?: (request: { candidateId: string; reason: string }) => void | Promise<void>
  onRefreshConflict?: (
    request: { candidateId: string; authorText: string; latestChapterRevision: number },
  ) => void | Promise<void>
}

interface DraftSnapshot {
  text: string
  lockedRanges: ChapterProductionTextRange[]
}

interface CandidateDraft extends DraftSnapshot {
  dirty: boolean
  history: DraftSnapshot[]
  serverKey: string
}

const outlineFields: Array<{
  field: keyof ChapterProductionOutline
  label: string
  placeholder: string
}> = [
  { field: 'readerPromise', label: '读者承诺', placeholder: '这一章给读者什么明确回报？' },
  { field: 'openingHook', label: '开篇钩子', placeholder: '开场用什么问题抓住读者？' },
  { field: 'stateChange', label: '状态变化', placeholder: '人物、资源或关系如何改变？' },
  { field: 'emotionalPayoff', label: '情绪兑现', placeholder: '本章兑现什么爽感或情绪？' },
  { field: 'endingCliffhanger', label: '章末悬念', placeholder: '读者为什么必须点下一章？' },
]

const checkLabels: Record<ChapterProductionCheckState, string> = {
  passed: '通过',
  warning: '需留意',
  blocked: '阻断',
}

const candidateStateLabels: Record<ChapterProductionCandidateState, string> = {
  candidate: '候选 · 未写入正文',
  adopted: '已采用记录',
  rejected: '已拒绝',
  stale: '旧候选 · 不可采用',
}

function initialDraft(candidate: ChapterProductionCandidate): CandidateDraft {
  return {
    text: candidate.text,
    lockedRanges: candidate.lockedRanges ? [...candidate.lockedRanges] : [],
    dirty: false,
    history: [],
    serverKey: candidateServerKey(candidate),
  }
}

function candidateServerKey(candidate: ChapterProductionCandidate): string {
  return [
    candidate.revision,
    candidate.contentSha256 ?? candidate.text,
    JSON.stringify(candidate.lockedRanges ?? []),
  ].join(':')
}

function resolvedDraft(
  candidate: ChapterProductionCandidate,
  draft: CandidateDraft | undefined,
): CandidateDraft {
  if (!draft || (!draft.dirty && draft.serverKey !== candidateServerKey(candidate))) {
    return initialDraft(candidate)
  }
  return draft
}

function sameRanges(left: ChapterProductionTextRange[], right: ChapterProductionTextRange[]): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}

function mergeRanges(ranges: ChapterProductionTextRange[]): ChapterProductionTextRange[] {
  const sorted = [...ranges]
    .filter((range) => range.end > range.start)
    .sort((left, right) => left.start - right.start || left.end - right.end)
  const merged: ChapterProductionTextRange[] = []
  for (const range of sorted) {
    const previous = merged.at(-1)
    if (previous && range.start <= previous.end) {
      previous.end = Math.max(previous.end, range.end)
    } else {
      merged.push({ ...range })
    }
  }
  return merged
}

function rangeIntersects(
  changed: ChapterProductionTextRange,
  locked: ChapterProductionTextRange,
): boolean {
  if (changed.start === changed.end) {
    return changed.start > locked.start && changed.start < locked.end
  }
  return changed.start < locked.end && changed.end > locked.start
}

function changedRange(before: string, after: string): ChapterProductionTextRange & { delta: number } {
  let start = 0
  while (start < before.length && start < after.length && before[start] === after[start]) start += 1
  let beforeEnd = before.length
  let afterEnd = after.length
  while (beforeEnd > start && afterEnd > start && before[beforeEnd - 1] === after[afterEnd - 1]) {
    beforeEnd -= 1
    afterEnd -= 1
  }
  return { start, end: beforeEnd, delta: (afterEnd - start) - (beforeEnd - start) }
}

function shiftRanges(
  ranges: ChapterProductionTextRange[],
  changed: ChapterProductionTextRange & { delta: number },
): ChapterProductionTextRange[] {
  return ranges.map((range) => (
    changed.end <= range.start
      ? { start: range.start + changed.delta, end: range.end + changed.delta }
      : range
  ))
}

function selectedCandidate(
  candidates: ChapterProductionCandidate[],
  selectedId: string | null,
): ChapterProductionCandidate | null {
  return candidates.find((candidate) => candidate.id === selectedId)
    ?? candidates.find((candidate) => candidate.state === 'candidate')
    ?? candidates[0]
    ?? null
}

export function ChapterProductionWorkbench({
  chapterTitle,
  chapterRevision,
  officialText,
  outline,
  preflight,
  candidates,
  isGenerating = false,
  conflict = null,
  onGenerate,
  onOutlineChange,
  onSelectionInstruction,
  onLockChange,
  onUndo,
  onMergeCandidates,
  onAdopt,
  onReject,
  onRefreshConflict,
  onOutlineSave,
  onCandidateSave,
  onUnlock,
  onReview,
}: ChapterProductionWorkbenchProps) {
  const [outlineDraft, setOutlineDraft] = useState<ChapterProductionOutline>(() => ({ ...outline }))
  const [outlineDirty, setOutlineDirty] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(() => candidates[0]?.id ?? null)
  const [drafts, setDrafts] = useState<Record<string, CandidateDraft>>({})
  const [selection, setSelection] = useState<ChapterProductionTextRange | null>(null)
  const [instruction, setInstruction] = useState('')
  const [mergeIds, setMergeIds] = useState<string[]>([])
  const [rejectionReason, setRejectionReason] = useState('')
  const [chapterSelection, setChapterSelection] = useState<ChapterProductionTextRange | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const candidateHeadingRef = useRef<HTMLHeadingElement>(null)
  const previousCandidateCount = useRef(candidates.length)
  const editSession = useRef<{ candidateId: string; snapshot: DraftSnapshot } | null>(null)

  const activeCandidate = selectedCandidate(candidates, selectedId)
  const activeDraft = activeCandidate
    ? resolvedDraft(activeCandidate, drafts[activeCandidate.id])
    : null
  const visibleOutline = outlineDirty ? outlineDraft : outline
  const generationBlocked = preflight.state !== 'ready'
    || preflight.blockingReasons.length > 0
    || isGenerating
  const activeConflict = activeCandidate
    && conflict
    && (!conflict.candidateId || conflict.candidateId === activeCandidate.id)
    ? conflict
    : null
  const canEditCandidate = activeCandidate?.state === 'candidate'

  useEffect(() => {
    if (previousCandidateCount.current === 0 && candidates.length > 0) {
      candidateHeadingRef.current?.focus()
    }
    previousCandidateCount.current = candidates.length
  }, [candidates.length])

  function updateOutline(field: keyof ChapterProductionOutline, value: string) {
    const updated = { ...visibleOutline, [field]: value }
    setOutlineDraft(updated)
    setOutlineDirty(true)
    onOutlineChange?.(updated)
  }

  async function saveOutline() {
    if (!onOutlineSave || !outlineDirty || busy) return
    setBusy(true)
    setStatus(null)
    try {
      await onOutlineSave(visibleOutline)
      setOutlineDirty(false)
      setStatus('章纲候选已保存；正式正文没有改变。')
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : '章纲候选保存失败，当前编辑已保留。')
    } finally {
      setBusy(false)
    }
  }

  async function startGeneration() {
    if (generationBlocked || busy) return
    setBusy(true)
    setStatus(null)
    try {
      await onGenerate()
      setOutlineDirty(false)
      setStatus('已生成发送前预览；只有作者确认后才会启动模型任务。')
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : '本章候选准备失败。')
    } finally {
      setBusy(false)
    }
  }

  function chooseCandidate(candidateId: string) {
    setSelectedId(candidateId)
    setSelection(null)
    setInstruction('')
    setRejectionReason('')
    setStatus(null)
  }

  function updateActiveDraft(updater: (draft: CandidateDraft) => CandidateDraft) {
    if (!activeCandidate) return
    setDrafts((current) => ({
      ...current,
      [activeCandidate.id]: updater(resolvedDraft(activeCandidate, current[activeCandidate.id])),
    }))
  }

  function handleCandidateTextChange(event: ChangeEvent<HTMLTextAreaElement>) {
    if (!activeCandidate || !activeDraft) return
    const nextText = event.target.value
    const change = changedRange(activeDraft.text, nextText)
    if (activeDraft.lockedRanges.some((locked) => rangeIntersects(change, locked))) {
      setStatus('这次修改碰到了锁定文字，候选副本保持不变。先解除对应锁定再改。')
      return
    }
    updateActiveDraft((current) => ({
      ...current,
      text: nextText,
      lockedRanges: shiftRanges(current.lockedRanges, change),
      dirty: true,
    }))
    setStatus(null)
  }

  function beginCandidateEdit() {
    if (!activeCandidate || !activeDraft) return
    editSession.current = {
      candidateId: activeCandidate.id,
      snapshot: { text: activeDraft.text, lockedRanges: activeDraft.lockedRanges },
    }
  }

  function endCandidateEdit() {
    if (!activeCandidate || !activeDraft || editSession.current?.candidateId !== activeCandidate.id) return
    const baseline = editSession.current.snapshot
    editSession.current = null
    if (baseline.text === activeDraft.text && sameRanges(baseline.lockedRanges, activeDraft.lockedRanges)) return
    updateActiveDraft((current) => ({ ...current, history: [...current.history, baseline] }))
  }

  async function lockSelection() {
    if (!activeCandidate || !activeDraft || !selection || selection.end <= selection.start || busy) return
    const nextRanges = mergeRanges([...activeDraft.lockedRanges, selection])
    updateActiveDraft((current) => ({
      ...current,
      lockedRanges: nextRanges,
      history: current.history,
      dirty: current.dirty,
    }))
    setBusy(true)
    try {
      await onLockChange?.({
        candidateId: activeCandidate.id,
        candidateRevision: activeCandidate.revision,
        range: selection,
        lockedRanges: nextRanges,
      })
      setStatus(`已锁定 ${selection.end - selection.start} 字，后续调整会避开这里。`)
    } catch (caught) {
      updateActiveDraft((current) => ({ ...current, lockedRanges: activeDraft.lockedRanges }))
      setStatus(caught instanceof Error ? caught.message : '锁定失败，候选文字没有改变。')
    } finally {
      setBusy(false)
    }
  }

  async function unlockRange(rangeIndex: number) {
    if (!activeCandidate || !activeDraft || busy) return
    const removed = activeDraft.lockedRanges[rangeIndex]
    if (!removed) return
    const nextRanges = activeDraft.lockedRanges.filter((_, index) => index !== rangeIndex)
    updateActiveDraft((current) => ({
      ...current,
      lockedRanges: nextRanges,
      history: current.history,
      dirty: current.dirty,
    }))
    setBusy(true)
    try {
      await onUnlock?.({
        candidateId: activeCandidate.id,
        candidateRevision: activeCandidate.revision,
        range: removed,
        lockId: removed.id,
        lockedRanges: nextRanges,
      })
      setStatus('选区锁定已解除。')
    } catch (caught) {
      updateActiveDraft((current) => ({ ...current, lockedRanges: activeDraft.lockedRanges }))
      setStatus(caught instanceof Error ? caught.message : '解除锁定失败。')
    } finally {
      setBusy(false)
    }
  }

  async function runSelectionInstruction() {
    if (
      !activeCandidate || !activeDraft || !selection || selection.end <= selection.start
      || !instruction.trim() || !onSelectionInstruction || busy
    ) return
    if (activeDraft.lockedRanges.some((locked) => rangeIntersects(selection, locked))) {
      setStatus('当前选区包含锁定文字，不能生成替换候选。')
      return
    }
    setBusy(true)
    setStatus(null)
    try {
      const request: SelectionInstructionRequest = {
        candidateId: activeCandidate.id,
        candidateRevision: activeCandidate.revision,
        currentText: activeDraft.text,
        selection: {
          ...selection,
          selectedText: activeDraft.text.slice(selection.start, selection.end),
        },
        instruction: instruction.trim(),
        lockedRanges: activeDraft.lockedRanges,
      }
      const result = await onSelectionInstruction(request)
      if (result?.replacementText !== undefined) {
        const nextText = activeDraft.text.slice(0, selection.start)
          + result.replacementText
          + activeDraft.text.slice(selection.end)
        const change = {
          start: selection.start,
          end: selection.end,
          delta: result.replacementText.length - (selection.end - selection.start),
        }
        updateActiveDraft((current) => ({
          ...current,
          text: nextText,
          lockedRanges: shiftRanges(current.lockedRanges, change),
          history: [...current.history, { text: current.text, lockedRanges: current.lockedRanges }],
          dirty: true,
        }))
        setSelection({ start: selection.start, end: selection.start + result.replacementText.length })
        setStatus('选区替换已进入候选副本；正式正文没有改变。')
      } else {
        updateActiveDraft((current) => ({ ...current, dirty: false, history: [] }))
        setStatus('已准备选区改写；确认外发与费用后才会启动任务。')
      }
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : '局部候选生成失败，当前编辑已保留。')
    } finally {
      setBusy(false)
    }
  }

  async function saveActiveCandidate() {
    if (!activeCandidate || !activeDraft || !activeDraft.dirty || !onCandidateSave || busy) return
    setBusy(true)
    setStatus(null)
    try {
      await onCandidateSave({
        candidateId: activeCandidate.id,
        candidateRevision: activeCandidate.revision,
        baseText: activeCandidate.text,
        authorText: activeDraft.text,
        lockedRanges: activeDraft.lockedRanges,
      })
      updateActiveDraft((current) => ({ ...current, dirty: false, history: [] }))
      setStatus('候选修改已保存为新版本；正式正文没有改变。')
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : '候选修改保存失败，当前文字已保留。')
    } finally {
      setBusy(false)
    }
  }

  async function undoActiveDraft() {
    if (!activeCandidate || !activeDraft || busy) return
    const previous = activeDraft.history.at(-1)
    if (previous) {
      const originalLocks = activeCandidate.lockedRanges ?? []
      setDrafts((current) => ({
        ...current,
        [activeCandidate.id]: {
          text: previous.text,
          lockedRanges: previous.lockedRanges,
          history: activeDraft.history.slice(0, -1),
          dirty: previous.text !== activeCandidate.text || !sameRanges(previous.lockedRanges, originalLocks),
          serverKey: activeDraft.serverKey,
        },
      }))
      setStatus('已撤销未保存的候选修改。')
      return
    }
    if (!onUndo || activeCandidate.revision === 0) return
    setBusy(true)
    setStatus(null)
    try {
      await onUndo({ candidateId: activeCandidate.id, candidateRevision: activeCandidate.revision })
      setStatus('已恢复上一个候选版本；正式正文没有改变。')
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : '候选版本恢复失败。')
    } finally {
      setBusy(false)
    }
  }

  async function mergeCandidates() {
    if (mergeIds.length < 2 || !activeCandidate || !onMergeCandidates || busy) return
    setBusy(true)
    setStatus(null)
    try {
      await onMergeCandidates({ candidateIds: mergeIds, baseCandidateId: activeCandidate.id })
      setStatus('合并请求已提交；合并结果仍会作为新候选等待确认。')
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : '候选合并失败，现有候选保持不变。')
    } finally {
      setBusy(false)
    }
  }

  async function reviewCandidate() {
    if (!activeCandidate || !onReview || !canEditCandidate || busy) return
    setBusy(true)
    setStatus(null)
    try {
      await onReview({ candidateId: activeCandidate.id, candidateRevision: activeCandidate.revision })
      setStatus('已准备七维审校；确认外发与费用后才会启动任务。')
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : '候选审校准备失败。')
    } finally {
      setBusy(false)
    }
  }

  async function adoptCandidate(mode: 'whole' | 'partial') {
    if (!activeCandidate || !activeDraft || !onAdopt || activeConflict || !canEditCandidate || busy) return
    if (mode === 'partial' && (
      !selection || selection.end <= selection.start
      || !chapterSelection || chapterSelection.end <= chapterSelection.start
    )) {
      setStatus('局部采用前，请分别在正式正文和候选副本中选中要替换的文字。')
      return
    }
    setBusy(true)
    try {
      await onAdopt({
        candidateId: activeCandidate.id,
        candidateRevision: activeCandidate.revision,
        expectedChapterRevision: chapterRevision,
        authorText: activeDraft.text,
        lockedRanges: activeDraft.lockedRanges,
        mode,
        ...(mode === 'partial' && selection && chapterSelection ? {
          candidateSelection: {
            ...selection,
            selectedText: activeDraft.text.slice(selection.start, selection.end),
          },
          chapterSelection: {
            ...chapterSelection,
            selectedText: officialText.slice(chapterSelection.start, chapterSelection.end),
          },
        } : {}),
      })
      setStatus('采用请求已提交；只有服务端版本校验通过后才会更新正文。')
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : '候选采用失败，作者编辑已保留。')
    } finally {
      setBusy(false)
    }
  }

  async function rejectCandidate() {
    if (!activeCandidate || !onReject || !canEditCandidate || busy || !rejectionReason.trim()) return
    setBusy(true)
    try {
      await onReject({ candidateId: activeCandidate.id, reason: rejectionReason.trim() })
      setStatus('拒绝决定已记录；正式正文没有改变。')
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : '拒绝决定保存失败。')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="chapter-production-workbench" aria-labelledby="chapter-production-title">
      <header className="chapter-production-heading">
        <div>
          <p className="section-kicker">单章生产工作台</p>
          <h2 id="chapter-production-title">{chapterTitle}</h2>
          <p>章纲、写前检查、正文候选和作者决定都在这里完成。</p>
        </div>
        <span>正式正文 · 版本 {chapterRevision}</span>
      </header>

      <ol className="chapter-production-steps" aria-label="本章生产流程">
        <li data-current={candidates.length === 0}>1 · 章纲</li>
        <li data-current={candidates.length === 0}>2 · 写前检查</li>
        <li data-current={candidates.length > 0}>3 · 候选审校</li>
        <li>4 · 作者采用</li>
      </ol>

      <div className="chapter-production-summary">
        <section aria-labelledby="chapter-outline-title">
          <header>
            <div>
              <p className="section-kicker">本章意图</p>
              <h3 id="chapter-outline-title">章纲</h3>
            </div>
            <span>由作者决定</span>
          </header>
          <div className="chapter-production-outline-fields">
            {outlineFields.map(({ field, label, placeholder }) => (
              <label key={field}>
                {label}
                <textarea
                  value={visibleOutline[field]}
                  rows={2}
                  placeholder={placeholder}
                  onChange={(event) => updateOutline(field, event.target.value)}
                />
              </label>
            ))}
          </div>
          {onOutlineSave ? (
            <button
              type="button"
              className="chapter-production-outline-save"
              disabled={!outlineDirty || busy}
              onClick={() => { void saveOutline() }}
            >
              {outlineDirty ? '保存章纲候选' : '章纲候选已保存'}
            </button>
          ) : null}
        </section>

        <section className="chapter-production-preflight" data-state={preflight.state} aria-labelledby="chapter-preflight-title">
          <header>
            <div>
              <p className="section-kicker">正文模型之前</p>
              <h3 id="chapter-preflight-title">写前检查</h3>
            </div>
            <strong>{preflight.state === 'ready' ? '可以生成' : preflight.state === 'checking' ? '检查中' : '暂不可生成'}</strong>
          </header>
          <ul>
            {preflight.checks.map((check) => (
              <li key={check.id} data-state={check.state}>
                <span>{checkLabels[check.state]}</span>
                <div><strong>{check.label}</strong><small>{check.detail}</small></div>
              </li>
            ))}
          </ul>
          {preflight.blockingReasons.length > 0 ? (
            <div className="chapter-production-blockers" role="alert">
              <strong>写前检查未通过，不会调用正文模型。</strong>
              <ul>{preflight.blockingReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
            </div>
          ) : null}
        </section>
      </div>

      <section className="chapter-production-generate" aria-label="生成正文候选">
        <div>
          <strong>{isGenerating ? '正在生成候选…' : '准备好后，只需从这里开始'}</strong>
          <p id="chapter-production-generation-note">生成结果只进入候选区，不会写入正式正文。</p>
        </div>
        <button
          type="button"
          className="chapter-production-primary"
          disabled={generationBlocked || busy}
          aria-describedby="chapter-production-generation-note"
          onClick={() => { void startGeneration() }}
        >
          生成本章候选
        </button>
      </section>

      {candidates.length > 0 ? (
        <section className="chapter-production-candidates" aria-labelledby="chapter-candidates-title">
          <header>
            <div>
              <p className="section-kicker">AI 主写 · 作者裁决</p>
              <h3 id="chapter-candidates-title" ref={candidateHeadingRef} tabIndex={-1}>
                {candidates.length} 份正文候选待审校
              </h3>
            </div>
            <p>任何候选都不会自动覆盖正文。</p>
          </header>

          <div className="chapter-production-candidate-grid">
            {candidates.map((candidate) => (
              <article
                key={candidate.id}
                className="chapter-production-candidate-card"
                data-selected={candidate.id === activeCandidate?.id}
                data-state={candidate.state}
                aria-label={`${candidate.label}候选`}
              >
                <header>
                  <span>{candidateStateLabels[candidate.state]}</span>
                  <label>
                    <input
                      type="checkbox"
                      aria-label={`选择${candidate.label}参与合并`}
                      checked={mergeIds.includes(candidate.id)}
                      disabled={candidate.state !== 'candidate'}
                      onChange={() => setMergeIds((current) => (
                        current.includes(candidate.id)
                          ? current.filter((id) => id !== candidate.id)
                          : [...current, candidate.id]
                      ))}
                    />
                    合并
                  </label>
                </header>
                <h4>{candidate.label}</h4>
                <p>{candidate.text.slice(0, 88)}{candidate.text.length > 88 ? '…' : ''}</p>
                <details>
                  <summary>七维审校</summary>
                  {candidate.reviewItems.length > 0 ? (
                    <ul>
                      {candidate.reviewItems.map((item) => (
                        <li key={`${item.dimension}:${item.summary}`} data-state={item.state}>
                          <strong>{item.dimension} · {checkLabels[item.state]}</strong>
                          <span>{item.summary}</span>
                        </li>
                      ))}
                    </ul>
                  ) : <p>审校结果尚未返回。</p>}
                </details>
                <button
                  type="button"
                  aria-pressed={candidate.id === activeCandidate?.id}
                  onClick={() => chooseCandidate(candidate.id)}
                >
                  {candidate.id === activeCandidate?.id ? '正在对照' : '对照这份候选'}
                </button>
              </article>
            ))}
          </div>

          {activeCandidate && activeDraft ? (
            <div className="chapter-production-compare">
              <section aria-labelledby="official-copy-title">
                <header><h4 id="official-copy-title">当前正式正文</h4><span>只读</span></header>
                <label>
                  <span className="sr-only">当前正式正文</span>
                  <textarea
                    className="chapter-production-copy"
                    value={officialText}
                    readOnly
                    spellCheck={false}
                    onSelect={(event) => setChapterSelection({
                      start: event.currentTarget.selectionStart,
                      end: event.currentTarget.selectionEnd,
                    })}
                  />
                </label>
              </section>
              <section aria-labelledby="candidate-copy-title">
                <header><h4 id="candidate-copy-title">{activeCandidate.label}</h4><span>候选副本 · 可编辑</span></header>
                <label>
                  <span className="sr-only">编辑{activeCandidate.label}候选副本</span>
                  <textarea
                    className="chapter-production-copy"
                    aria-label={`编辑${activeCandidate.label}候选副本`}
                    value={activeDraft.text}
                    readOnly={!canEditCandidate}
                    spellCheck={false}
                    onChange={handleCandidateTextChange}
                    onFocus={beginCandidateEdit}
                    onBlur={endCandidateEdit}
                    onSelect={(event) => setSelection({
                      start: event.currentTarget.selectionStart,
                      end: event.currentTarget.selectionEnd,
                    })}
                  />
                </label>
              </section>
            </div>
          ) : null}

          {activeCandidate && activeDraft ? (
            <div className="chapter-production-edit-tools">
              {activeConflict ? (
                <div className="chapter-production-conflict" role="alert">
                  <strong>候选基于旧版本，作者编辑已保留。</strong>
                  <p>{activeConflict.message} 请刷新正文并重新检查后再决定是否采用。</p>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      void onRefreshConflict?.({
                        candidateId: activeCandidate.id,
                        authorText: activeDraft.text,
                        latestChapterRevision: activeConflict.latestChapterRevision,
                      })
                    }}
                  >
                    刷新正文并重新检查
                  </button>
                </div>
              ) : null}

              <section className="chapter-production-local-command" aria-labelledby="chapter-local-command-title">
                <header>
                  <div>
                    <h4 id="chapter-local-command-title">只改选中的一小段</h4>
                    <p>{selection && selection.end > selection.start ? `已选择 ${selection.end - selection.start} 字` : '先在候选副本中选中文字'}</p>
                  </div>
                  <button
                    type="button"
                    disabled={
                      !selection || selection.end <= selection.start || !canEditCandidate
                      || activeDraft.dirty || busy
                    }
                    onClick={lockSelection}
                  >
                    锁定当前选区
                  </button>
                </header>
                {activeDraft.lockedRanges.length > 0 ? (
                  <ul className="chapter-production-locks" aria-label="候选锁定范围">
                    {activeDraft.lockedRanges.map((range, index) => (
                      <li key={`${range.start}:${range.end}`}>
                        <span>已锁定 {range.end - range.start} 字</span>
                        <button type="button" onClick={() => unlockRange(index)} disabled={busy}>解除锁定</button>
                      </li>
                    ))}
                  </ul>
                ) : <p className="chapter-production-empty-note">尚未锁定文字。</p>}
                <div className="chapter-production-command-row">
                  <label>
                    选区局部指令
                    <input
                      value={instruction}
                      onChange={(event) => setInstruction(event.target.value)}
                      placeholder="例如：保留事实，只加强人物的压迫感"
                      disabled={!canEditCandidate || busy}
                    />
                  </label>
                  <button
                    type="button"
                    disabled={
                      !selection || selection.end <= selection.start || !instruction.trim()
                      || !onSelectionInstruction || !canEditCandidate || busy
                    }
                    onClick={() => { void runSelectionInstruction() }}
                  >
                    生成选区替换候选
                  </button>
                  <button
                    type="button"
                    disabled={
                      (activeDraft.history.length === 0 && (!onUndo || activeCandidate.revision === 0))
                      || !canEditCandidate || busy
                    }
                    onClick={() => { void undoActiveDraft() }}
                  >
                    撤销上一步候选修改
                  </button>
                  {onCandidateSave ? (
                    <button
                      type="button"
                      disabled={!activeDraft.dirty || !canEditCandidate || busy}
                      onClick={() => { void saveActiveCandidate() }}
                    >
                      {activeDraft.dirty ? '保存候选修改' : '候选修改已保存'}
                    </button>
                  ) : null}
                </div>
              </section>

              {onReview ? (
                <section className="chapter-production-review-action" aria-label="候选审校操作">
                  <div>
                    <h4>运行七维审校</h4>
                    <p>审校绑定当前候选版本，候选再改后需重新审校。</p>
                  </div>
                  <button
                    type="button"
                    disabled={!canEditCandidate || activeDraft.dirty || busy}
                    onClick={() => { void reviewCandidate() }}
                  >
                    {activeCandidate.reviewItems.length > 0 ? '重新审校此候选' : '审校此候选'}
                  </button>
                </section>
              ) : null}

              <section className="chapter-production-merge" aria-labelledby="chapter-merge-title">
                <div>
                  <h4 id="chapter-merge-title">融合多个候选的优点</h4>
                  <p>在上方至少勾选两份；结果仍是候选，不会直接拼接或覆盖正文。</p>
                </div>
                <button
                  type="button"
                  disabled={mergeIds.length < 2 || !onMergeCandidates || busy}
                  onClick={() => { void mergeCandidates() }}
                >
                  合并所选候选
                </button>
              </section>

              <section className="chapter-production-decision" aria-labelledby="chapter-decision-title">
                <div>
                  <h4 id="chapter-decision-title">作者决定</h4>
                  <p>采用会提交当前可编辑副本和锁定范围，并再次校验正文版本。</p>
                </div>
                <div className="chapter-production-reject">
                  <label>
                    拒绝原因
                    <input
                      value={rejectionReason}
                      onChange={(event) => setRejectionReason(event.target.value)}
                      disabled={!canEditCandidate || busy}
                    />
                  </label>
                  <button
                    type="button"
                    disabled={!onReject || !canEditCandidate || busy || !rejectionReason.trim()}
                    onClick={() => { void rejectCandidate() }}
                  >
                    拒绝此候选
                  </button>
                </div>
                <div className="chapter-production-actions">
                  <span>{activeDraft.dirty ? '候选含作者修改' : '候选原稿'}</span>
                  <button
                    type="button"
                    disabled={
                      !onAdopt || !canEditCandidate || Boolean(activeConflict) || busy
                      || !selection || selection.end <= selection.start
                      || !chapterSelection || chapterSelection.end <= chapterSelection.start
                    }
                    onClick={() => { void adoptCandidate('partial') }}
                  >
                    局部采用到正文选区
                  </button>
                  <button
                    type="button"
                    className="chapter-production-adopt"
                    disabled={!onAdopt || !canEditCandidate || Boolean(activeConflict) || busy}
                    onClick={() => { void adoptCandidate('whole') }}
                  >
                    确认采用这份候选
                  </button>
                </div>
              </section>
            </div>
          ) : null}
          {selection ? <span className="sr-only">已选择 {selection.end - selection.start} 字</span> : null}
        </section>
      ) : (
        <section className="chapter-production-empty" aria-label="候选区">
          <strong>候选区还是空的</strong>
          <p>完成写前检查后，从上方唯一入口生成正文候选。</p>
        </section>
      )}
      {status ? <p className="chapter-production-status" role="status">{status}</p> : null}
    </section>
  )
}
