import type {
  AuthorPreferenceCandidate,
  AuthorPreferenceDimension,
  CanonCandidateDecisionInput,
  CanonDecisionAction,
  CanonDeltaCandidate,
  CanonKind,
  CanonPayload,
  CanonReconciliationSnapshot,
  Chapter,
  CharacterKnowledgeCanonPayload,
  CharacterStateCanonPayload,
  FutureKnowledgeCanonPayload,
  LocationStateCanonPayload,
  PreferenceCandidateDecisionInput,
  PreferenceScopeKind,
  ProgressionCanonPayload,
  Project,
  RelationshipCanonPayload,
  ResourceStateCanonPayload,
  StoryThreadCanonPayload,
  TimelineEventCanonPayload,
  Workspace,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { useEffect, useMemo, useRef, useState } from 'react'

import { ApiError, api } from '../api'

interface ChapterFeedbackPanelProps {
  project: Pick<Project, 'id' | 'genre'>
  chapter: Chapter
  onWorkspaceChanged: (workspace: Workspace | WorkspaceSummary) => void
}

const MAX_PENDING_POLLS = 12
const PENDING_POLL_INTERVAL_MS = 700

const canonKindLabels: Record<CanonKind, string> = {
  character_state: '人物状态',
  relationship: '人物关系',
  resource_state: '资源变化',
  location_state: '位置变化',
  character_knowledge: '角色认知',
  future_knowledge: '未来知识',
  story_thread: '伏笔线索',
  progression: '境界与能力',
  timeline_event: '时间线事件',
}

const preferenceDimensionLabels: Record<AuthorPreferenceDimension, string> = {
  pacing: '节奏',
  paragraphing: '段落组织',
  dialogue_density: '对话密度',
  narrative_distance: '叙事距离',
  tension: '张力',
  sentence_style: '句式风格',
}

const preferenceScopeLabels: Record<PreferenceScopeKind, string> = {
  project: '当前作品',
  genre: '当前题材',
  chapter: '当前章节',
}

const conflictLabels = {
  duplicate: '可能重复',
  supersedes: '将替代旧事实',
  inconsistent: '存在冲突',
} as const

interface FeedbackTextFieldProps {
  label: string
  value: string
  maxLength: number
  multiline?: boolean
  required?: boolean
  onChange: (value: string) => void
}

function FeedbackTextField({
  label,
  value,
  maxLength,
  multiline = false,
  required = false,
  onChange,
}: FeedbackTextFieldProps) {
  return (
    <label className="chapter-feedback-field" data-multiline={multiline}>
      <span>{label}</span>
      {multiline ? (
        <textarea
          value={value}
          rows={3}
          maxLength={maxLength}
          required={required}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <input
          value={value}
          maxLength={maxLength}
          required={required}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </label>
  )
}

function optionalYear(value: string): number | null {
  if (value.trim() === '') return null
  const year = Number(value)
  return Number.isInteger(year) ? year : null
}

function CanonPayloadEditor({
  kind,
  payload,
  onChange,
}: {
  kind: CanonKind
  payload: CanonPayload
  onChange: (payload: CanonPayload) => void
}) {
  if (kind === 'character_state') {
    const value = payload as CharacterStateCanonPayload
    return (
      <div className="chapter-feedback-fields">
        <FeedbackTextField label="人物" value={value.character_name} maxLength={120} required onChange={(character_name) => onChange({ ...value, character_name })} />
        <FeedbackTextField label="当前状态" value={value.state} maxLength={1_000} multiline required onChange={(state) => onChange({ ...value, state })} />
        <FeedbackTextField label="本章变化" value={value.change} maxLength={1_000} multiline required onChange={(change) => onChange({ ...value, change })} />
      </div>
    )
  }
  if (kind === 'relationship') {
    const value = payload as RelationshipCanonPayload
    return (
      <div className="chapter-feedback-fields">
        <FeedbackTextField label="关系发起方" value={value.source_name} maxLength={120} required onChange={(source_name) => onChange({ ...value, source_name })} />
        <FeedbackTextField label="关系对象" value={value.target_name} maxLength={120} required onChange={(target_name) => onChange({ ...value, target_name })} />
        <FeedbackTextField label="关系类型" value={value.relation_type} maxLength={80} required onChange={(relation_type) => onChange({ ...value, relation_type })} />
        <FeedbackTextField label="关系说明" value={value.summary} maxLength={1_000} multiline onChange={(summary) => onChange({ ...value, summary })} />
      </div>
    )
  }
  if (kind === 'resource_state') {
    const value = payload as ResourceStateCanonPayload
    return (
      <div className="chapter-feedback-fields">
        <FeedbackTextField label="资源" value={value.resource_name} maxLength={120} required onChange={(resource_name) => onChange({ ...value, resource_name })} />
        <FeedbackTextField label="归属者" value={value.owner_name} maxLength={120} onChange={(owner_name) => onChange({ ...value, owner_name })} />
        <FeedbackTextField label="增减变化" value={value.delta} maxLength={500} required onChange={(delta) => onChange({ ...value, delta })} />
        <FeedbackTextField label="变化后状态" value={value.state} maxLength={1_000} multiline required onChange={(state) => onChange({ ...value, state })} />
      </div>
    )
  }
  if (kind === 'location_state') {
    const value = payload as LocationStateCanonPayload
    return (
      <div className="chapter-feedback-fields">
        <FeedbackTextField label="人物或物件" value={value.subject_name} maxLength={120} required onChange={(subject_name) => onChange({ ...value, subject_name })} />
        <FeedbackTextField label="所在地点" value={value.location} maxLength={160} required onChange={(location) => onChange({ ...value, location })} />
        <FeedbackTextField label="移动说明" value={value.movement} maxLength={1_000} multiline required onChange={(movement) => onChange({ ...value, movement })} />
      </div>
    )
  }
  if (kind === 'character_knowledge') {
    const value = payload as CharacterKnowledgeCanonPayload
    return (
      <div className="chapter-feedback-fields">
        <FeedbackTextField label="知情角色" value={value.character_name} maxLength={120} required onChange={(character_name) => onChange({ ...value, character_name })} />
        <FeedbackTextField label="新获认知" value={value.knowledge} maxLength={1_000} multiline required onChange={(knowledge) => onChange({ ...value, knowledge })} />
      </div>
    )
  }
  if (kind === 'future_knowledge') {
    const value = payload as FutureKnowledgeCanonPayload
    return (
      <div className="chapter-feedback-fields">
        <FeedbackTextField label="持有者" value={value.holder_name} maxLength={120} required onChange={(holder_name) => onChange({ ...value, holder_name })} />
        <FeedbackTextField label="未来知识" value={value.knowledge} maxLength={500} multiline required onChange={(knowledge) => onChange({ ...value, knowledge })} />
        <label className="chapter-feedback-field">
          <span>可信程度</span>
          <select value={value.confidence} onChange={(event) => onChange({ ...value, confidence: event.target.value as FutureKnowledgeCanonPayload['confidence'] })}>
            <option value="certain">确定</option>
            <option value="likely">大概率</option>
            <option value="uncertain">不确定</option>
          </select>
        </label>
        <label className="chapter-feedback-field">
          <span>发生年份</span>
          <input type="number" min={-3_000} max={2_100} value={value.event_year ?? ''} onChange={(event) => onChange({ ...value, event_year: optionalYear(event.target.value) })} />
        </label>
      </div>
    )
  }
  if (kind === 'story_thread') {
    const value = payload as StoryThreadCanonPayload
    return (
      <div className="chapter-feedback-fields">
        <FeedbackTextField label="线索标题" value={value.title} maxLength={300} required onChange={(title) => onChange({ ...value, title })} />
        <label className="chapter-feedback-field">
          <span>线索状态</span>
          <select value={value.status} onChange={(event) => onChange({ ...value, status: event.target.value as StoryThreadCanonPayload['status'] })}>
            <option value="open">待回收</option>
            <option value="resolved">已回收</option>
            <option value="abandoned">已放弃</option>
          </select>
        </label>
        <FeedbackTextField label="线索说明" value={value.summary} maxLength={1_000} multiline onChange={(summary) => onChange({ ...value, summary })} />
      </div>
    )
  }
  if (kind === 'progression') {
    const value = payload as ProgressionCanonPayload
    return (
      <div className="chapter-feedback-fields">
        <FeedbackTextField label="成长角色" value={value.character_name} maxLength={120} required onChange={(character_name) => onChange({ ...value, character_name })} />
        <FeedbackTextField label="体系" value={value.system} maxLength={160} onChange={(system) => onChange({ ...value, system })} />
        <FeedbackTextField label="境界或能力" value={value.rank} maxLength={160} required onChange={(rank) => onChange({ ...value, rank })} />
        <FeedbackTextField label="成长变化" value={value.change} maxLength={1_000} multiline required onChange={(change) => onChange({ ...value, change })} />
      </div>
    )
  }

  const value = payload as TimelineEventCanonPayload
  return (
    <div className="chapter-feedback-fields">
      <label className="chapter-feedback-field">
        <span>时间线</span>
        <select value={value.layer} onChange={(event) => onChange({ ...value, layer: event.target.value as TimelineEventCanonPayload['layer'] })}>
          <option value="novel">小说演变</option>
          <option value="original">世界底稿</option>
        </select>
      </label>
      <label className="chapter-feedback-field">
        <span>事件年份</span>
        <input type="number" min={-3_000} max={2_100} value={value.event_year ?? ''} onChange={(event) => onChange({ ...value, event_year: optionalYear(event.target.value) })} />
      </label>
      <FeedbackTextField label="事件标题" value={value.title} maxLength={120} required onChange={(title) => onChange({ ...value, title })} />
      <FeedbackTextField label="事件摘要" value={value.summary} maxLength={1_000} multiline onChange={(summary) => onChange({ ...value, summary })} />
    </div>
  )
}

interface CanonDraft {
  action: CanonDecisionAction | null
  subjectKey: string
  summary: string
  payload: CanonPayload
  rejectionReason: string
}

interface PreferenceDraft {
  action: CanonDecisionAction | null
  scopeKind: PreferenceScopeKind
  scopeValue: string
  dimension: AuthorPreferenceDimension
  compactRule: string
  confidence: number
  rejectionReason: string
}

function initialCanonDraft(candidate: CanonDeltaCandidate): CanonDraft {
  return {
    action: null,
    subjectKey: candidate.subject_key,
    summary: candidate.summary,
    payload: { ...candidate.payload } as CanonPayload,
    rejectionReason: '',
  }
}

function initialPreferenceDraft(candidate: AuthorPreferenceCandidate): PreferenceDraft {
  return {
    action: null,
    scopeKind: candidate.scope_kind,
    scopeValue: candidate.scope_value,
    dimension: candidate.dimension,
    compactRule: candidate.compact_rule,
    confidence: candidate.confidence,
    rejectionReason: '',
  }
}

function hasText(value: string): boolean {
  return value.trim().length > 0
}

function canonPayloadIsValid(kind: CanonKind, payload: CanonPayload): boolean {
  if (kind === 'character_state') {
    const value = payload as CharacterStateCanonPayload
    return hasText(value.character_name) && hasText(value.state) && hasText(value.change)
  }
  if (kind === 'relationship') {
    const value = payload as RelationshipCanonPayload
    return hasText(value.source_name)
      && hasText(value.target_name)
      && value.source_name.trim().toLocaleLowerCase() !== value.target_name.trim().toLocaleLowerCase()
      && hasText(value.relation_type)
  }
  if (kind === 'resource_state') {
    const value = payload as ResourceStateCanonPayload
    return hasText(value.resource_name) && hasText(value.delta) && hasText(value.state)
  }
  if (kind === 'location_state') {
    const value = payload as LocationStateCanonPayload
    return hasText(value.subject_name) && hasText(value.location) && hasText(value.movement)
  }
  if (kind === 'character_knowledge') {
    const value = payload as CharacterKnowledgeCanonPayload
    return hasText(value.character_name) && hasText(value.knowledge)
  }
  if (kind === 'future_knowledge') {
    const value = payload as FutureKnowledgeCanonPayload
    return hasText(value.holder_name) && hasText(value.knowledge)
  }
  if (kind === 'story_thread') {
    return hasText((payload as StoryThreadCanonPayload).title)
  }
  if (kind === 'progression') {
    const value = payload as ProgressionCanonPayload
    return hasText(value.character_name) && hasText(value.rank) && hasText(value.change)
  }
  return hasText((payload as TimelineEventCanonPayload).title)
}

function canonDraftIsReady(candidate: CanonDeltaCandidate, draft: CanonDraft): boolean {
  if (draft.action === 'accept') return true
  if (draft.action === 'reject') return hasText(draft.rejectionReason)
  return draft.action === 'edit'
    && hasText(draft.subjectKey)
    && hasText(draft.summary)
    && canonPayloadIsValid(candidate.kind, draft.payload)
}

function CanonCandidateCard({
  candidate,
  draft,
  busy,
  onChange,
}: {
  candidate: CanonDeltaCandidate
  draft: CanonDraft
  busy: boolean
  onChange: (draft: CanonDraft) => void
}) {
  const titleId = `canon-candidate-${candidate.id}`
  const decided = candidate.state !== 'candidate'
  const stateLabel = candidate.state === 'accepted'
    ? '已写入正式设定'
    : candidate.state === 'rejected'
      ? '已拒绝'
      : candidate.state === 'stale'
        ? '已失效'
        : '待决定'

  return (
    <article className="chapter-feedback-candidate" data-state={candidate.state} aria-labelledby={titleId}>
      <header>
        <div>
          <span>{canonKindLabels[candidate.kind]}</span>
          <h5 id={titleId}>{candidate.summary}</h5>
        </div>
        <small>{stateLabel}</small>
      </header>

      <dl className="chapter-feedback-candidate-meta">
        <div><dt>归档对象</dt><dd>{candidate.subject_key}</dd></div>
        <div><dt>候选序号</dt><dd>第 {candidate.ordinal} 条</dd></div>
      </dl>

      <blockquote className="chapter-feedback-evidence">
        <p>{candidate.evidence.excerpt}</p>
        <cite>
          最终正文字符 {candidate.evidence.start_char + 1}–{candidate.evidence.end_char}
          {' · '}版本 {candidate.evidence.approval_version_id}
        </cite>
      </blockquote>

      {candidate.conflicts.length > 0 ? (
        <ul className="chapter-feedback-conflicts" aria-label="事实冲突提示">
          {candidate.conflicts.map((conflict, index) => (
            <li key={`${conflict.kind}:${index}`}>
              <strong>{conflictLabels[conflict.kind]}</strong>
              <span>{conflict.summary}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {decided ? (
        candidate.rejection_reason ? <p className="chapter-feedback-reason">拒绝原因：{candidate.rejection_reason}</p> : null
      ) : (
        <>
          <div className="chapter-feedback-choice" role="group" aria-label={`处理事实：${candidate.summary}`}>
            <button type="button" aria-pressed={draft.action === 'accept'} disabled={busy} onClick={() => onChange({ ...draft, action: 'accept' })}>接受</button>
            <button type="button" aria-pressed={draft.action === 'edit'} disabled={busy} onClick={() => onChange({ ...draft, action: 'edit' })}>编辑后接受</button>
            <button type="button" aria-pressed={draft.action === 'reject'} disabled={busy} onClick={() => onChange({ ...draft, action: 'reject' })}>拒绝</button>
          </div>

          {draft.action === 'edit' ? (
            <div className="chapter-feedback-editor" aria-label={`编辑事实：${candidate.summary}`}>
              <FeedbackTextField label="归档对象" value={draft.subjectKey} maxLength={240} required onChange={(subjectKey) => onChange({ ...draft, subjectKey })} />
              <FeedbackTextField label="事实摘要" value={draft.summary} maxLength={1_200} multiline required onChange={(summary) => onChange({ ...draft, summary })} />
              <CanonPayloadEditor kind={candidate.kind} payload={draft.payload} onChange={(payload) => onChange({ ...draft, payload })} />
            </div>
          ) : null}

          {draft.action === 'reject' ? (
            <div className="chapter-feedback-editor">
              <FeedbackTextField label="拒绝原因" value={draft.rejectionReason} maxLength={1_000} multiline required onChange={(rejectionReason) => onChange({ ...draft, rejectionReason })} />
            </div>
          ) : null}
        </>
      )}
    </article>
  )
}

function preferenceDraftIsReady(draft: PreferenceDraft): boolean {
  if (draft.action === 'accept') return true
  if (draft.action === 'reject') return hasText(draft.rejectionReason)
  return draft.action === 'edit'
    && hasText(draft.scopeValue)
    && hasText(draft.compactRule)
    && Number.isFinite(draft.confidence)
    && draft.confidence >= 0
    && draft.confidence <= 1
}

function PreferenceCandidateCard({
  candidate,
  draft,
  project,
  chapter,
  busy,
  onChange,
}: {
  candidate: AuthorPreferenceCandidate
  draft: PreferenceDraft
  project: Pick<Project, 'id' | 'genre'>
  chapter: Chapter
  busy: boolean
  onChange: (draft: PreferenceDraft) => void
}) {
  const titleId = `preference-candidate-${candidate.id}`
  const decided = candidate.state !== 'candidate'
  const stateLabel = candidate.state === 'confirmed'
    ? '已进入后续上下文'
    : candidate.state === 'rejected'
      ? '已拒绝'
      : candidate.state === 'stale'
        ? '已失效'
        : '待决定'

  function changeScope(scopeKind: PreferenceScopeKind) {
    const scopeValue = scopeKind === 'project'
      ? project.id
      : scopeKind === 'genre'
        ? project.genre
        : chapter.id
    onChange({ ...draft, scopeKind, scopeValue })
  }

  return (
    <article className="chapter-feedback-candidate chapter-feedback-preference" data-state={candidate.state} aria-labelledby={titleId}>
      <header>
        <div>
          <span>{preferenceDimensionLabels[candidate.dimension]}</span>
          <h5 id={titleId}>{candidate.compact_rule}</h5>
        </div>
        <small>{stateLabel}</small>
      </header>

      <dl className="chapter-feedback-candidate-meta">
        <div><dt>适用范围</dt><dd>{preferenceScopeLabels[candidate.scope_kind]}</dd></div>
        <div><dt>置信度</dt><dd>{Math.round(candidate.confidence * 100)}%</dd></div>
      </dl>

      {Object.keys(candidate.comparison_metrics).length > 0 ? (
        <dl className="chapter-feedback-metrics" aria-label="修改对比指标">
          {Object.entries(candidate.comparison_metrics).map(([name, value]) => (
            <div key={name}><dt>{name.replaceAll('_', ' ')}</dt><dd>{String(value)}</dd></div>
          ))}
        </dl>
      ) : null}

      {decided ? (
        candidate.rejection_reason ? <p className="chapter-feedback-reason">拒绝原因：{candidate.rejection_reason}</p> : null
      ) : (
        <>
          <div className="chapter-feedback-choice" role="group" aria-label={`处理偏好：${candidate.compact_rule}`}>
            <button type="button" aria-pressed={draft.action === 'accept'} disabled={busy} onClick={() => onChange({ ...draft, action: 'accept' })}>接受</button>
            <button type="button" aria-pressed={draft.action === 'edit'} disabled={busy} onClick={() => onChange({ ...draft, action: 'edit' })}>编辑后接受</button>
            <button type="button" aria-pressed={draft.action === 'reject'} disabled={busy} onClick={() => onChange({ ...draft, action: 'reject' })}>拒绝</button>
          </div>

          {draft.action === 'edit' ? (
            <div className="chapter-feedback-editor" aria-label={`编辑偏好：${candidate.compact_rule}`}>
              <label className="chapter-feedback-field">
                <span>适用范围</span>
                <select value={draft.scopeKind} onChange={(event) => changeScope(event.target.value as PreferenceScopeKind)}>
                  <option value="project">当前作品</option>
                  <option value="genre">当前题材</option>
                  <option value="chapter">仅当前章节</option>
                </select>
              </label>
              <label className="chapter-feedback-field">
                <span>偏好维度</span>
                <select value={draft.dimension} onChange={(event) => onChange({ ...draft, dimension: event.target.value as AuthorPreferenceDimension })}>
                  {Object.entries(preferenceDimensionLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
              <FeedbackTextField label="抽象偏好规则" value={draft.compactRule} maxLength={500} multiline required onChange={(compactRule) => onChange({ ...draft, compactRule })} />
              <label className="chapter-feedback-field">
                <span>置信度</span>
                <input type="number" min={0} max={1} step={0.05} value={draft.confidence} onChange={(event) => onChange({ ...draft, confidence: Number(event.target.value) })} />
              </label>
            </div>
          ) : null}

          {draft.action === 'reject' ? (
            <div className="chapter-feedback-editor">
              <FeedbackTextField label="拒绝原因" value={draft.rejectionReason} maxLength={1_000} multiline required onChange={(rejectionReason) => onChange({ ...draft, rejectionReason })} />
            </div>
          ) : null}
        </>
      )}
    </article>
  )
}

function idempotencyKey(prefix: string): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return `${prefix}:${crypto.randomUUID()}`
  return `${prefix}:${Date.now()}:${Math.random().toString(16).slice(2)}`
}

function mergeCanonDrafts(
  current: Record<string, CanonDraft>,
  candidates: CanonDeltaCandidate[],
): Record<string, CanonDraft> {
  return Object.fromEntries(candidates.map((candidate) => [
    candidate.id,
    current[candidate.id] ?? initialCanonDraft(candidate),
  ]))
}

function mergePreferenceDrafts(
  current: Record<string, PreferenceDraft>,
  candidates: AuthorPreferenceCandidate[],
): Record<string, PreferenceDraft> {
  return Object.fromEntries(candidates.map((candidate) => [
    candidate.id,
    current[candidate.id] ?? initialPreferenceDraft(candidate),
  ]))
}

function canonDecision(candidate: CanonDeltaCandidate, draft: CanonDraft): CanonCandidateDecisionInput | null {
  if (!draft.action || !canonDraftIsReady(candidate, draft)) return null
  if (draft.action === 'accept') {
    return { candidate_id: candidate.id, expected_revision: candidate.revision, action: 'accept' }
  }
  if (draft.action === 'reject') {
    return {
      candidate_id: candidate.id,
      expected_revision: candidate.revision,
      action: 'reject',
      rejection_reason: draft.rejectionReason.trim(),
    }
  }
  return {
    candidate_id: candidate.id,
    expected_revision: candidate.revision,
    action: 'edit',
    edited_subject_key: draft.subjectKey.trim(),
    edited_summary: draft.summary.trim(),
    edited_payload: draft.payload,
  }
}

function preferenceDecision(
  candidate: AuthorPreferenceCandidate,
  draft: PreferenceDraft,
): PreferenceCandidateDecisionInput | null {
  if (!draft.action || !preferenceDraftIsReady(draft)) return null
  if (draft.action === 'accept') {
    return { candidate_id: candidate.id, expected_revision: candidate.revision, action: 'accept' }
  }
  if (draft.action === 'reject') {
    return {
      candidate_id: candidate.id,
      expected_revision: candidate.revision,
      action: 'reject',
      rejection_reason: draft.rejectionReason.trim(),
    }
  }
  return {
    candidate_id: candidate.id,
    expected_revision: candidate.revision,
    action: 'edit',
    edited_scope_kind: draft.scopeKind,
    edited_scope_value: draft.scopeValue,
    edited_dimension: draft.dimension,
    edited_compact_rule: draft.compactRule.trim(),
    edited_confidence: draft.confidence,
  }
}

export function ChapterFeedbackPanel({
  project,
  chapter,
  onWorkspaceChanged,
}: ChapterFeedbackPanelProps) {
  const [snapshot, setSnapshot] = useState<CanonReconciliationSnapshot | null>(null)
  const [loadedChapterKey, setLoadedChapterKey] = useState<string | null>(null)
  const [canonDrafts, setCanonDrafts] = useState<Record<string, CanonDraft>>({})
  const [preferenceDrafts, setPreferenceDrafts] = useState<Record<string, PreferenceDraft>>({})
  const [pollingExhausted, setPollingExhausted] = useState(false)
  const [pollingRestart, setPollingRestart] = useState(0)
  const [busyAction, setBusyAction] = useState<'refresh' | 'retry' | 'canon' | 'preference' | 'plan' | null>(null)
  const [hasRevisionConflict, setHasRevisionConflict] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const decisionKeys = useRef(new Map<string, string>())
  const chapterKey = `${chapter.id}:${chapter.revision}`
  const activeSnapshot = loadedChapterKey === chapterKey ? snapshot : null
  const loading = chapter.status === 'approved' && loadedChapterKey !== chapterKey
  const activeError = loadedChapterKey === chapterKey ? error : null
  const activeNotice = loadedChapterKey === chapterKey ? notice : null

  const canonDecisions = useMemo(() => (
    activeSnapshot?.canon_candidates.flatMap((candidate) => {
      if (candidate.state !== 'candidate') return []
      const draft = canonDrafts[candidate.id]
      if (!draft) return []
      const decision = canonDecision(candidate, draft)
      return decision ? [decision] : []
    }) ?? []
  ), [activeSnapshot?.canon_candidates, canonDrafts])
  const preferenceDecisions = useMemo(() => (
    activeSnapshot?.preference_candidates.flatMap((candidate) => {
      if (candidate.state !== 'candidate') return []
      const draft = preferenceDrafts[candidate.id]
      if (!draft) return []
      const decision = preferenceDecision(candidate, draft)
      return decision ? [decision] : []
    }) ?? []
  ), [activeSnapshot?.preference_candidates, preferenceDrafts])
  const chosenCanonCount = activeSnapshot?.canon_candidates.filter((candidate) => (
    candidate.state === 'candidate' && Boolean(canonDrafts[candidate.id]?.action)
  )).length ?? 0
  const chosenPreferenceCount = activeSnapshot?.preference_candidates.filter((candidate) => (
    candidate.state === 'candidate' && Boolean(preferenceDrafts[candidate.id]?.action)
  )).length ?? 0
  const busy = busyAction !== null

  function rememberKey(identity: string): string {
    const existing = decisionKeys.current.get(identity)
    if (existing) return existing
    const next = idempotencyKey('canon-feedback')
    decisionKeys.current.set(identity, next)
    return next
  }

  function acceptSnapshot(next: CanonReconciliationSnapshot | null) {
    setSnapshot(next)
    setLoadedChapterKey(chapterKey)
    setCanonDrafts((current) => mergeCanonDrafts(current, next?.canon_candidates ?? []))
    setPreferenceDrafts((current) => mergePreferenceDrafts(current, next?.preference_candidates ?? []))
  }

  useEffect(() => {
    if (chapter.status !== 'approved') return undefined

    let active = true
    let timer: number | undefined
    let pendingPolls = 0

    async function load() {
      try {
        const next = await api.getLatestCanonReconciliation(project.id, chapter.id)
        if (!active) return
        setSnapshot(next)
        setLoadedChapterKey(`${chapter.id}:${chapter.revision}`)
        setCanonDrafts((current) => mergeCanonDrafts(current, next?.canon_candidates ?? []))
        setPreferenceDrafts((current) => mergePreferenceDrafts(current, next?.preference_candidates ?? []))
        setPollingExhausted(false)
        setHasRevisionConflict(false)
        setNotice(null)
        setError(null)

        if (next?.reconciliation.state !== 'pending') return
        if (pendingPolls >= MAX_PENDING_POLLS) {
          setPollingExhausted(true)
          return
        }
        pendingPolls += 1
        timer = window.setTimeout(() => { void load() }, PENDING_POLL_INTERVAL_MS)
      } catch (caught) {
        if (!active) return
        setSnapshot(null)
        setLoadedChapterKey(`${chapter.id}:${chapter.revision}`)
        setError(caught instanceof Error ? caught.message : '读取定稿回流任务失败')
      }
    }

    void load()

    return () => {
      active = false
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [chapter.id, chapter.revision, chapter.status, pollingRestart, project.id])

  async function retryReconciliation() {
    if (!activeSnapshot || activeSnapshot.reconciliation.state !== 'failed') return
    setBusyAction('retry')
    setPollingExhausted(false)
    setNotice(null)
    setError(null)
    try {
      await api.retryJob(activeSnapshot.reconciliation.job_id)
      setPollingRestart((current) => current + 1)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '重试定稿回流任务失败')
    } finally {
      setBusyAction(null)
    }
  }

  async function refreshSnapshot() {
    setBusyAction('refresh')
    setError(null)
    try {
      acceptSnapshot(await api.getLatestCanonReconciliation(project.id, chapter.id))
      setHasRevisionConflict(false)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '刷新定稿回流任务失败')
    } finally {
      setBusyAction(null)
    }
  }

  async function refreshAfterDecision(submittedCanonIds: string[], submittedPreferenceIds: string[]) {
    const [next, workspace] = await Promise.all([
      api.getLatestCanonReconciliation(project.id, chapter.id),
      api.getProjectSummary(project.id),
    ])
    if (next === null) throw new Error('定稿回流结果暂时不可用，请刷新后重试。')
    setSnapshot(next)
    setLoadedChapterKey(chapterKey)
    setCanonDrafts((current) => {
      const remaining = { ...current }
      submittedCanonIds.forEach((id) => delete remaining[id])
      return mergeCanonDrafts(remaining, next.canon_candidates)
    })
    setPreferenceDrafts((current) => {
      const remaining = { ...current }
      submittedPreferenceIds.forEach((id) => delete remaining[id])
      return mergePreferenceDrafts(remaining, next.preference_candidates)
    })
    onWorkspaceChanged(workspace)
  }

  function handleDecisionFailure(caught: unknown, fallback: string) {
    if (caught instanceof ApiError && caught.status === 409) {
      setHasRevisionConflict(true)
      setError('候选已有新版本。你的选择和编辑仍保留，请刷新后核对再提交。')
      return
    }
    setError(caught instanceof Error ? caught.message : fallback)
  }

  async function submitCanonDecisions() {
    if (
      !activeSnapshot
      || activeSnapshot.reconciliation.state !== 'ready'
      || chosenCanonCount === 0
      || canonDecisions.length !== chosenCanonCount
    ) return
    const reconciliation = activeSnapshot.reconciliation
    const identity = JSON.stringify({
      kind: 'canon',
      reconciliation: reconciliation.id,
      revision: reconciliation.revision,
      decisions: canonDecisions,
    })
    setBusyAction('canon')
    setHasRevisionConflict(false)
    setNotice(null)
    setError(null)
    try {
      await api.decideCanonReconciliation(project.id, reconciliation.id, {
        reconciliation_id: reconciliation.id,
        expected_reconciliation_revision: reconciliation.revision,
        idempotency_key: rememberKey(identity),
        canon_decisions: canonDecisions,
        preference_decisions: [],
      })
      await refreshAfterDecision(canonDecisions.map((decision) => decision.candidate_id), [])
      setNotice(`已记录 ${canonDecisions.length} 条事实决定，正式账本已刷新。`)
    } catch (caught) {
      handleDecisionFailure(caught, '事实决定提交失败')
    } finally {
      setBusyAction(null)
    }
  }

  async function submitPreferenceDecisions() {
    if (
      !activeSnapshot
      || activeSnapshot.reconciliation.state !== 'ready'
      || chosenPreferenceCount === 0
      || preferenceDecisions.length !== chosenPreferenceCount
    ) return
    const reconciliation = activeSnapshot.reconciliation
    const identity = JSON.stringify({
      kind: 'preference',
      reconciliation: reconciliation.id,
      revision: reconciliation.revision,
      decisions: preferenceDecisions,
    })
    setBusyAction('preference')
    setHasRevisionConflict(false)
    setNotice(null)
    setError(null)
    try {
      await api.decideCanonReconciliation(project.id, reconciliation.id, {
        reconciliation_id: reconciliation.id,
        expected_reconciliation_revision: reconciliation.revision,
        idempotency_key: rememberKey(identity),
        canon_decisions: [],
        preference_decisions: preferenceDecisions,
      })
      await refreshAfterDecision([], preferenceDecisions.map((decision) => decision.candidate_id))
      setNotice(`已记录 ${preferenceDecisions.length} 条偏好决定，后续上下文已刷新。`)
    } catch (caught) {
      handleDecisionFailure(caught, '偏好决定提交失败')
    } finally {
      setBusyAction(null)
    }
  }

  async function adoptRollingPlan() {
    const replenishment = activeSnapshot?.rolling_plan_replenishment
    if (!replenishment || replenishment.state !== 'candidate') return
    const identity = [
      'rolling-plan',
      replenishment.id,
      replenishment.revision,
      replenishment.plans_sha256,
    ].join(':')
    setBusyAction('plan')
    setNotice(null)
    setError(null)
    try {
      const updated = await api.adoptRollingPlanReplenishment(
        project.id,
        replenishment.id,
        replenishment.revision,
        replenishment.plans_sha256,
        rememberKey(identity),
      )
      setSnapshot((current) => current ? { ...current, rolling_plan_replenishment: updated } : current)
      onWorkspaceChanged(await api.getProjectSummary(project.id))
      setNotice(`已采用未来 ${updated.plans.length} 章滚动计划。`)
    } catch (caught) {
      handleDecisionFailure(caught, '滚动计划采用失败')
    } finally {
      setBusyAction(null)
    }
  }

  if (chapter.status !== 'approved') return null

  const reconciliationState = activeSnapshot?.reconciliation.state
  const canReview = reconciliationState === 'ready'
  const showCandidates = reconciliationState === 'ready'
    || reconciliationState === 'decided'
    || reconciliationState === 'stale'
  const statusLabel = reconciliationState === 'ready'
    ? '等待确认'
    : reconciliationState === 'decided'
      ? '审签完成'
      : reconciliationState === 'stale'
        ? '版本失效'
        : reconciliationState === 'failed'
          ? '任务失败'
          : '后台整理'
  const replenishment = activeSnapshot?.rolling_plan_replenishment ?? null

  return (
    <section
      id="director-stage-feedback"
      className="chapter-feedback-panel director-stage-target"
      aria-labelledby="chapter-feedback-title"
      tabIndex={-1}
    >
      <div className="pulse-heading">
        <h3 id="chapter-feedback-title">定稿回流审签</h3>
        <span>{statusLabel}</span>
      </div>

      {loading ? <p className="chapter-feedback-status" role="status">正在读取定稿回流任务…</p> : null}

      {!loading && activeSnapshot === null && activeError === null ? (
        <p className="chapter-feedback-status">这次定稿尚未生成事实与偏好候选。</p>
      ) : null}

      {activeSnapshot?.reconciliation.state === 'pending' ? (
        <div className="chapter-feedback-job" role="status">
          <strong>正在从最终正文整理事实与作者偏好</strong>
          <p>候选完成前不会改动正式设定或后续章节上下文。</p>
          {pollingExhausted ? (
            <div className="chapter-feedback-job-wait">
              <small>任务仍在后台运行，你可以稍后刷新结果。</small>
              <button type="button" disabled={busy} onClick={() => { void refreshSnapshot() }}>刷新结果</button>
            </div>
          ) : null}
        </div>
      ) : null}

      {activeSnapshot?.reconciliation.state === 'ready' ? (
        <p className="chapter-feedback-status" role="status">
          已生成 {activeSnapshot.canon_candidates.length} 条事实与 {activeSnapshot.preference_candidates.length} 条偏好候选。
        </p>
      ) : null}

      {activeSnapshot?.reconciliation.state === 'decided' ? (
        <p className="chapter-feedback-status">本章事实与偏好已经审签完成。</p>
      ) : null}

      {activeSnapshot?.reconciliation.state === 'stale' ? (
        <p className="chapter-feedback-warning" role="alert">正文版本已变化，这批候选只能查看，不能再写入正式设定。</p>
      ) : null}

      {activeSnapshot?.reconciliation.state === 'failed' ? (
        <div className="chapter-feedback-warning" role="alert">
          <p>{activeSnapshot.reconciliation.error_message ?? '定稿回流任务失败，请稍后重试。'}</p>
          <button type="button" disabled={busy} onClick={() => { void retryReconciliation() }}>
            {busyAction === 'retry' ? '正在重试…' : '重试定稿回流'}
          </button>
        </div>
      ) : null}

      {showCandidates && activeSnapshot ? (
        <div className="chapter-feedback-review">
          <section aria-labelledby="chapter-feedback-canon-title">
            <div className="chapter-feedback-section-heading">
              <div><small>01 · CANON</small><h4 id="chapter-feedback-canon-title">确认正式事实</h4></div>
              <span>{activeSnapshot.canon_candidates.filter((candidate) => candidate.state === 'candidate').length} 条待决定</span>
            </div>
            <p>逐条核对正文证据。只有接受或编辑后接受的项目会进入正式账本。</p>
            <div className="chapter-feedback-list">
              {activeSnapshot.canon_candidates.map((candidate) => (
                <CanonCandidateCard
                  key={`${candidate.id}:${candidate.revision}`}
                  candidate={candidate}
                  draft={canonDrafts[candidate.id] ?? initialCanonDraft(candidate)}
                  busy={busy || !canReview}
                  onChange={(draft) => setCanonDrafts((current) => ({ ...current, [candidate.id]: draft }))}
                />
              ))}
              {activeSnapshot.canon_candidates.length === 0 ? <p className="chapter-feedback-empty">最终正文没有产生新的正式事实。</p> : null}
            </div>
            {canReview && activeSnapshot.canon_candidates.some((candidate) => candidate.state === 'candidate') ? (
              <div className="chapter-feedback-submit">
                <small>{chosenCanonCount > canonDecisions.length ? '请补全已选择项目的编辑内容或拒绝原因。' : '可以先提交部分决定，其余候选会继续保留。'}</small>
                <button
                  type="button"
                  className="state-primary"
                  disabled={busy || chosenCanonCount === 0 || canonDecisions.length !== chosenCanonCount}
                  onClick={() => { void submitCanonDecisions() }}
                >{busyAction === 'canon' ? '正在写入…' : `提交 ${chosenCanonCount} 条事实决定`}</button>
              </div>
            ) : null}
          </section>

          <section aria-labelledby="chapter-feedback-preference-title">
            <div className="chapter-feedback-section-heading">
              <div><small>02 · PREFERENCE</small><h4 id="chapter-feedback-preference-title">确认作者偏好</h4></div>
              <span>{activeSnapshot.preference_candidates.filter((candidate) => candidate.state === 'candidate').length} 条待决定</span>
            </div>
            <p>这里只保留抽象写作规则，不会把历史正文差异塞进下一章上下文。</p>
            <div className="chapter-feedback-list">
              {activeSnapshot.preference_candidates.map((candidate) => (
                <PreferenceCandidateCard
                  key={`${candidate.id}:${candidate.revision}`}
                  candidate={candidate}
                  draft={preferenceDrafts[candidate.id] ?? initialPreferenceDraft(candidate)}
                  project={project}
                  chapter={chapter}
                  busy={busy || !canReview}
                  onChange={(draft) => setPreferenceDrafts((current) => ({ ...current, [candidate.id]: draft }))}
                />
              ))}
              {activeSnapshot.preference_candidates.length === 0 ? (
                <p className="chapter-feedback-empty">
                  {activeSnapshot.reconciliation.preference_skip_reason ?? '本章没有识别出需要长期保留的稳定偏好。'}
                </p>
              ) : null}
            </div>
            {canReview && activeSnapshot.preference_candidates.some((candidate) => candidate.state === 'candidate') ? (
              <div className="chapter-feedback-submit">
                <small>{chosenPreferenceCount > preferenceDecisions.length ? '请补全已选择项目的编辑内容或拒绝原因。' : '确认后只把压缩规则加入后续创作上下文。'}</small>
                <button
                  type="button"
                  className="state-primary"
                  disabled={busy || chosenPreferenceCount === 0 || preferenceDecisions.length !== chosenPreferenceCount}
                  onClick={() => { void submitPreferenceDecisions() }}
                >{busyAction === 'preference' ? '正在保存…' : `提交 ${chosenPreferenceCount} 条偏好决定`}</button>
              </div>
            ) : null}
          </section>
        </div>
      ) : null}

      {replenishment ? (
        <section className="chapter-feedback-plan" data-state={replenishment.state} aria-labelledby="chapter-feedback-plan-title">
          <div className="chapter-feedback-section-heading">
            <div><small>03 · ROLLING PLAN</small><h4 id="chapter-feedback-plan-title">补齐后续章节计划</h4></div>
            <span>{replenishment.state === 'candidate' ? '等待采用' : replenishment.state === 'adopted' ? '已采用' : '未写入'}</span>
          </div>
          {replenishment.plans.length > 0 ? (
            <ol>
              {replenishment.plans.map((plan) => (
                <li key={plan.chapter_number}>
                  <span>第 {plan.chapter_number} 章</span>
                  <strong>{plan.title}</strong>
                  <p>{plan.reader_promise}</p>
                  <small>{plan.state_change} · {plan.ending_cliffhanger}</small>
                </li>
              ))}
            </ol>
          ) : (
            <p className="chapter-feedback-empty">{replenishment.blocked_reason ?? '当前滚动计划已经覆盖未来章节，无需补充。'}</p>
          )}
          {replenishment.state === 'candidate' ? (
            <div className="chapter-feedback-submit">
              <small>计划目前只是候选；只有点击采用后才会更新正式滚动计划。</small>
              <button type="button" className="state-primary" disabled={busy} onClick={() => { void adoptRollingPlan() }}>
                {busyAction === 'plan' ? '正在采用…' : `采用未来 ${replenishment.plans.length} 章计划`}
              </button>
            </div>
          ) : null}
        </section>
      ) : null}

      {activeNotice ? <p className="chapter-feedback-notice" role="status">{activeNotice}</p> : null}

      {activeError ? (
        <div className="chapter-feedback-warning" role="alert">
          <p>{activeError}</p>
          {hasRevisionConflict ? <button type="button" disabled={busy} onClick={() => { void refreshSnapshot() }}>刷新候选并保留编辑</button> : null}
        </div>
      ) : null}
    </section>
  )
}
