import type {
  CraftPatternAsset,
  CraftPatternAssetSummary,
  CraftPatternItem,
  PreviewWritingPatternRecipeInput,
  WritingPatternPurpose,
  WritingPatternConflictDecisionInput,
  WritingPatternConflictResolution,
  WritingPatternLifecycleState,
  WritingPatternProfilePreview,
  WritingPatternProfileSummary,
  WritingPatternProfileVersion,
  WritingPatternRecipeEntryInput,
  WritingPatternRecipePreview,
  WritingPatternRecipePage as WritingPatternRecipePageResult,
  WritingPatternRecipeSeries,
  WritingPatternRecipeVersion,
  WritingPatternStage,
  WritingPatternStrategy,
  WorkspaceSummary,
} from '@mozhou/contracts'
import { useEffect, useMemo, useState } from 'react'

import { ApiError, api } from '../api'
import { CraftPatternAssetCard } from './CraftPatternAssetCard'
import { craftDimensionLabels } from './craftPatternLabels'

interface WritingPatternRecipePageProps {
  workspace: WorkspaceSummary
  onBack: () => void
  onOpenTopicDecision?: () => void
}

interface RecipeVersionBase {
  recipeId: string
  latestVersion: number
}

const stageOptions: Array<{ value: WritingPatternStage; label: string }> = [
  { value: 'startup', label: '开书' },
  { value: 'volume', label: '卷规划' },
  { value: 'rolling', label: '滚动规划' },
  { value: 'chapter_brief', label: '章纲' },
  { value: 'chapter_draft', label: '章稿' },
  { value: 'rewrite', label: '改写' },
  { value: 'review', label: '审校' },
]

const purposeLabels: Record<WritingPatternPurpose, string> = {
  learn: '学习它的功能',
  counterexample: '把它当反例',
}

const strategyLabels: Record<WritingPatternStrategy, string> = {
  preserve_function: '保留功能',
  transform: '转化后使用',
  avoid: '明确避免',
}

const conflictResolutionLabels: Record<WritingPatternConflictResolution, string> = {
  choose_source: '只采用一条来源规则',
  combine_as_transform: '组合后转化使用',
  exclude_all: '这一组全部排除',
}

function entryId(entry: WritingPatternRecipeEntryInput): string {
  return `${entry.asset_version_id}:${entry.dimension}:${entry.pattern_name}`
}

function shortHash(value: string): string {
  return value.slice(0, 10)
}

function lifecycleLabel(state: WritingPatternLifecycleState): string {
  return state === 'active' ? '使用中' : '已归档'
}

function recipeErrorMessage(error: ApiError): string {
  const messages: Record<string, string> = {
    topic_not_confirmed: '当前选题尚未确认，请先回到选题台完成确认。',
    topic_changed: '选题已经更新。来源矩阵已保留，请核对后重新编译。',
    preview_changed: '配方依据已经变化。来源矩阵已保留，请重新编译预览。',
    recipe_version_changed: '全局配方已有新版本。当前草稿已保留，请刷新版本后重新编译。',
    recipe_archived: '这份全局配方已归档，恢复后才能创建版本或装入作品。',
    active_profile_exists: '当前作品已有使用中的写作模式，请先归档它。',
    profile_already_archived: '这份项目模式已经归档，请使用恢复操作。',
    stale_lifecycle_revision: '状态已在别处更新，请刷新后重试。',
    unresolved_recipe_conflict: '还有冲突没有处理，不能保存配方。',
    asset_hash_mismatch: '来源模式版本已经变化，请重新选择具体技法。',
    unknown_conflict_decision: '冲突依据已经变化，请重新编译。',
    chosen_entry_not_in_conflict: '选中的来源已不在这组冲突中，请重新选择。',
  }
  return error.code ? messages[error.code] ?? error.message : error.message
}

function entryIsValid(entry: WritingPatternRecipeEntryInput): boolean {
  const rangeValid = (entry.chapter_start === null && entry.chapter_end === null)
    || (entry.chapter_start !== null && entry.chapter_end !== null && entry.chapter_end >= entry.chapter_start)
  return entry.weight >= 1
    && entry.weight <= 100
    && entry.applicable_stages.length > 0
    && rangeValid
    && !(entry.purpose === 'counterexample' && entry.strategy === 'preserve_function')
}

function RecipeEntryEditor({
  entry,
  onChange,
  onRemove,
}: {
  entry: WritingPatternRecipeEntryInput
  onChange: (entry: WritingPatternRecipeEntryInput) => void
  onRemove: () => void
}) {
  const id = entryId(entry).replace(/[^a-zA-Z0-9_-]/g, '-')
  const invalidCounterexample = entry.purpose === 'counterexample' && entry.strategy === 'preserve_function'
  const invalidRange = (entry.chapter_start === null) !== (entry.chapter_end === null)
    || (entry.chapter_start !== null && entry.chapter_end !== null && entry.chapter_end < entry.chapter_start)

  return (
    <article className="recipe-entry" data-valid={entryIsValid(entry)}>
      <header>
        <div>
          <small>{craftDimensionLabels[entry.dimension]} · 指纹 {shortHash(entry.asset_content_sha256)}</small>
          <h3>{entry.pattern_name}</h3>
        </div>
        <button type="button" onClick={onRemove} aria-label={`移除技法“${entry.pattern_name}”`}>移除</button>
      </header>
      <div className="recipe-entry-controls">
        <label>
          用途
          <select
            value={entry.purpose}
            onChange={(event) => {
              const purpose = event.target.value as WritingPatternPurpose
              onChange({
                ...entry,
                purpose,
                strategy: purpose === 'counterexample' && entry.strategy === 'preserve_function'
                  ? 'avoid'
                  : entry.strategy,
              })
            }}
          >
            {Object.entries(purposeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label>
          使用方式
          <select
            value={entry.strategy}
            aria-describedby={invalidCounterexample ? `${id}-strategy-error` : undefined}
            onChange={(event) => onChange({ ...entry, strategy: event.target.value as WritingPatternStrategy })}
          >
            {Object.entries(strategyLabels).map(([value, label]) => (
              <option key={value} value={value} disabled={entry.purpose === 'counterexample' && value === 'preserve_function'}>{label}</option>
            ))}
          </select>
        </label>
        <label>
          权重（1–100）
          <input
            type="number"
            min="1"
            max="100"
            value={entry.weight}
            onChange={(event) => onChange({ ...entry, weight: Number(event.target.value) })}
          />
        </label>
      </div>
      {invalidCounterexample ? <p id={`${id}-strategy-error`} className="recipe-field-error">反例不能选择“保留功能”。</p> : null}
      <fieldset className="recipe-stage-picker">
        <legend>适用创作阶段</legend>
        {stageOptions.map((stage) => (
          <label key={stage.value}>
            <input
              type="checkbox"
              checked={entry.applicable_stages.includes(stage.value)}
              onChange={() => onChange({
                ...entry,
                applicable_stages: entry.applicable_stages.includes(stage.value)
                  ? entry.applicable_stages.filter((value) => value !== stage.value)
                  : [...entry.applicable_stages, stage.value],
              })}
            />
            {stage.label}
          </label>
        ))}
      </fieldset>
      <div className="recipe-entry-range">
        <label>
          起始章（可选）
          <input
            type="number"
            min="1"
            value={entry.chapter_start ?? ''}
            onChange={(event) => onChange({ ...entry, chapter_start: event.target.value ? Number(event.target.value) : null })}
          />
        </label>
        <label>
          结束章（可选）
          <input
            type="number"
            min="1"
            value={entry.chapter_end ?? ''}
            aria-describedby={invalidRange ? `${id}-range-error` : undefined}
            onChange={(event) => onChange({ ...entry, chapter_end: event.target.value ? Number(event.target.value) : null })}
          />
        </label>
      </div>
      {invalidRange ? <p id={`${id}-range-error`} className="recipe-field-error">章节范围需同时填写，且结束章不能早于起始章。</p> : null}
      <label className="recipe-entry-note">
        作者备注
        <textarea
          rows={2}
          maxLength={1000}
          value={entry.note}
          placeholder="例如：只学读者预期的建立方式，不沿用事件顺序。"
          onChange={(event) => onChange({ ...entry, note: event.target.value })}
        />
      </label>
    </article>
  )
}

export function WritingPatternRecipePage({
  workspace,
  onBack,
  onOpenTopicDecision = () => undefined,
}: WritingPatternRecipePageProps) {
  const [assets, setAssets] = useState<CraftPatternAssetSummary[] | null>(null)
  const [assetDetails, setAssetDetails] = useState<Record<string, CraftPatternAsset>>({})
  const [detailLoadingId, setDetailLoadingId] = useState<string | null>(null)
  const [entries, setEntries] = useState<WritingPatternRecipeEntryInput[]>([])
  const [name, setName] = useState(`${workspace.project.title}·写作配方`)
  const [description, setDescription] = useState('')
  const [conflictDecisions, setConflictDecisions] = useState<WritingPatternConflictDecisionInput[]>([])
  const [preview, setPreview] = useState<WritingPatternRecipePreview | null>(null)
  const [previewCurrent, setPreviewCurrent] = useState(false)
  const [baseVersion, setBaseVersion] = useState<RecipeVersionBase | null>(null)
  const [recipes, setRecipes] = useState<WritingPatternRecipePageResult | null>(null)
  const [recipeOffset, setRecipeOffset] = useState(0)
  const [selectedSeries, setSelectedSeries] = useState<WritingPatternRecipeSeries | null>(null)
  const [selectedVersion, setSelectedVersion] = useState<WritingPatternRecipeVersion | null>(null)
  const [reusePreview, setReusePreview] = useState<WritingPatternProfilePreview | null>(null)
  const [profiles, setProfiles] = useState<WritingPatternProfileSummary[] | null>(null)
  const [profileDetail, setProfileDetail] = useState<WritingPatternProfileVersion | null>(null)
  const [busy, setBusy] = useState<'preview' | 'save' | 'reuse-preview' | 'reuse' | null>(null)
  const [libraryBusy, setLibraryBusy] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const topic = workspace.topic_decision
  const topicIsConfirmed = topic?.status === 'confirmed' && topic.confirmed_revision === topic.revision
  const activeAssets = useMemo(() => (assets ?? []).filter((asset) => asset.lifecycle_state === 'active'), [assets])
  const entriesValid = entries.length > 0 && entries.every(entryIsValid) && name.trim().length > 0

  useEffect(() => {
    let active = true
    Promise.allSettled([
      api.listReferenceCraftAssets(workspace.project.id),
      api.listWritingPatternRecipes({ limit: 12, offset: recipeOffset }),
      api.listWritingPatternProfiles(workspace.project.id),
    ]).then(async ([assetResult, recipeResult, profileResult]) => {
      if (!active) return
      if (assetResult.status === 'fulfilled') setAssets(assetResult.value)
      else {
        setAssets([])
        setError(assetResult.reason instanceof Error ? assetResult.reason.message : '无法读取写作模式素材')
      }
      if (recipeResult.status === 'fulfilled') setRecipes(recipeResult.value)
      else {
        setRecipes({ items: [], total: 0, limit: 12, offset: recipeOffset })
        setError(recipeResult.reason instanceof Error ? recipeResult.reason.message : '无法读取全局写作配方')
      }
      if (profileResult.status === 'fulfilled') {
        setProfiles(profileResult.value)
        const activeSummary = profileResult.value.find((profile) => profile.lifecycle_state === 'active')
        if (activeSummary) {
          try {
            const detail = await api.getWritingPatternProfile(workspace.project.id, activeSummary.id)
            if (active) setProfileDetail(detail)
          } catch (caught) {
            if (active) setError(caught instanceof Error ? caught.message : '无法读取当前写作模式')
          }
        }
      } else {
        setProfiles([])
        setError(profileResult.reason instanceof Error ? profileResult.reason.message : '无法读取项目模式快照')
      }
    })
    return () => { active = false }
  }, [recipeOffset, workspace.project.id])

  function invalidatePreview(clearDecisions = false) {
    setPreviewCurrent(false)
    if (clearDecisions) {
      setPreview(null)
      setConflictDecisions([])
    }
  }

  async function loadDetail(assetId: string) {
    if (assetDetails[assetId] || detailLoadingId) return
    setDetailLoadingId(assetId)
    setError(null)
    try {
      const detail = await api.getReferenceCraftAsset(assetId, workspace.project.id)
      setAssetDetails((current) => ({ ...current, [assetId]: detail }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '无法读取技法详情')
    } finally {
      setDetailLoadingId(null)
    }
  }

  async function refreshRecipes() {
    const page = await api.listWritingPatternRecipes({ limit: 12, offset: recipeOffset })
    setRecipes(page)
    return page
  }

  async function refreshProfiles(preferredId?: string) {
    const nextProfiles = await api.listWritingPatternProfiles(workspace.project.id)
    setProfiles(nextProfiles)
    const target = preferredId
      ? nextProfiles.find((profile) => profile.id === preferredId)
      : nextProfiles.find((profile) => profile.lifecycle_state === 'active')
    if (!target) {
      setProfileDetail(null)
      return
    }
    setProfileDetail(await api.getWritingPatternProfile(workspace.project.id, target.id))
  }

  function reportFailure(caught: unknown, fallback: string, invalidate = false) {
    if (invalidate) setPreviewCurrent(false)
    if (caught instanceof ApiError) {
      if (caught.status === 409) setReusePreview(null)
      setError(recipeErrorMessage(caught))
    } else {
      setError(caught instanceof Error ? caught.message : fallback)
    }
  }

  function addCraftItem(asset: CraftPatternAssetSummary, item: CraftPatternItem) {
    const next: WritingPatternRecipeEntryInput = {
      asset_version_id: asset.id,
      asset_content_sha256: asset.content_sha256,
      dimension: item.dimension,
      pattern_name: item.name,
      purpose: 'learn',
      strategy: 'transform',
      weight: 60,
      applicable_stages: ['startup'],
      chapter_start: null,
      chapter_end: null,
      note: '',
    }
    if (entries.some((entry) => entryId(entry) === entryId(next))) return
    setEntries((current) => [...current, next])
    invalidatePreview(true)
    setNotice(`“${item.name}”已加入来源矩阵；你可以继续调整用途和阶段。`)
  }

  function updateEntry(index: number, entry: WritingPatternRecipeEntryInput) {
    setEntries((current) => current.map((item, itemIndex) => itemIndex === index ? entry : item))
    invalidatePreview(true)
  }

  function removeEntry(index: number) {
    setEntries((current) => current.filter((_, itemIndex) => itemIndex !== index))
    invalidatePreview(true)
  }

  function requestInput(): PreviewWritingPatternRecipeInput | null {
    if (!topicIsConfirmed || !topic) return null
    return {
      name: name.trim(),
      description: description.trim(),
      expected_topic_revision: topic.revision,
      entries,
      conflict_decisions: conflictDecisions,
    }
  }

  async function compilePreview() {
    const input = requestInput()
    if (!input || !entriesValid) return
    setBusy('preview')
    setError(null)
    setNotice(null)
    try {
      const result = baseVersion
        ? await api.previewWritingPatternRecipeVersion(workspace.project.id, baseVersion.recipeId, {
          ...input,
          expected_latest_version: baseVersion.latestVersion,
        })
        : await api.previewWritingPatternRecipe(workspace.project.id, input)
      setPreview(result)
      setConflictDecisions(result.decisions)
      setPreviewCurrent(true)
    } catch (caught) {
      reportFailure(caught, '无法编译写作配方', true)
    } finally {
      setBusy(null)
    }
  }

  function updateConflictResolution(conflictKey: string, resolution: WritingPatternConflictResolution) {
    setConflictDecisions((current) => [
      ...current.filter((decision) => decision.conflict_key !== conflictKey),
      { conflict_key: conflictKey, resolution, chosen_entry_key: null },
    ])
    setPreviewCurrent(false)
  }

  function updateConflictSource(conflictKey: string, entryKey: string) {
    setConflictDecisions((current) => current.map((decision) => decision.conflict_key === conflictKey
      ? { ...decision, chosen_entry_key: entryKey || null }
      : decision))
    setPreviewCurrent(false)
  }

  async function saveRecipe() {
    const input = requestInput()
    if (!input || !preview || !previewCurrent || preview.unresolved_conflict_count > 0) return
    setBusy('save')
    setError(null)
    setNotice(null)
    try {
      const saved = baseVersion
        ? await api.createWritingPatternRecipeVersion(workspace.project.id, baseVersion.recipeId, {
          ...input,
          expected_latest_version: baseVersion.latestVersion,
          expected_preview_sha256: preview.preview_sha256,
        })
        : await api.createWritingPatternRecipe(workspace.project.id, {
          ...input,
          expected_preview_sha256: preview.preview_sha256,
        })
      setNotice(baseVersion
        ? `配方第 ${saved.version} 版已保存，旧版本保持不变。`
        : `配方第 ${saved.version} 版已保存，全局库可以复用。`)
      setBaseVersion(baseVersion ? { ...baseVersion, latestVersion: saved.version } : null)
      await refreshRecipes()
    } catch (caught) {
      reportFailure(caught, '无法保存写作配方', true)
    } finally {
      setBusy(null)
    }
  }

  async function openRecipeSeries(recipeId: string) {
    setLibraryBusy(`series:${recipeId}`)
    setError(null)
    setReusePreview(null)
    try {
      setSelectedSeries(await api.getWritingPatternRecipe(recipeId))
      setSelectedVersion(null)
    } catch (caught) {
      reportFailure(caught, '无法读取配方版本')
    } finally {
      setLibraryBusy(null)
    }
  }

  async function openRecipeVersion(versionId: string) {
    setLibraryBusy(`version:${versionId}`)
    setError(null)
    setReusePreview(null)
    try {
      setSelectedVersion(await api.getWritingPatternRecipeVersion(versionId))
    } catch (caught) {
      reportFailure(caught, '无法读取配方详情')
    } finally {
      setLibraryBusy(null)
    }
  }

  function editAsNewVersion(version: WritingPatternRecipeVersion) {
    if (!selectedSeries) return
    const latestVersion = Math.max(...selectedSeries.versions.map((item) => item.version))
    setBaseVersion({ recipeId: selectedSeries.id, latestVersion })
    setName(version.name)
    setDescription(version.description)
    setEntries(version.sources.map((source) => ({
      asset_version_id: source.asset_version_id,
      asset_content_sha256: source.asset_content_sha256,
      dimension: source.dimension,
      pattern_name: source.pattern_name,
      purpose: source.purpose,
      strategy: source.strategy,
      weight: source.weight,
      applicable_stages: source.applicable_stages,
      chapter_start: source.chapter_start,
      chapter_end: source.chapter_end,
      note: source.note,
    })))
    setConflictDecisions(version.conflict_decisions)
    setPreview(null)
    setPreviewCurrent(false)
    setNotice(`正在基于第 ${version.version} 版编配；旧版本不会被改动。`)
  }

  async function previewReuse(version: WritingPatternRecipeVersion) {
    if (!topicIsConfirmed || !topic) return
    setBusy('reuse-preview')
    setError(null)
    setNotice(null)
    try {
      setReusePreview(await api.previewWritingPatternRecipeReuse(workspace.project.id, version.id, {
        expected_recipe_content_sha256: version.content_sha256,
        expected_topic_revision: topic.revision,
      }))
    } catch (caught) {
      reportFailure(caught, '无法预览项目模式快照')
    } finally {
      setBusy(null)
    }
  }

  async function confirmReuse() {
    if (!reusePreview || !topicIsConfirmed || !topic) return
    setBusy('reuse')
    setError(null)
    setNotice(null)
    try {
      const profile = await api.reuseWritingPatternRecipe(
        workspace.project.id,
        reusePreview.recipe_version_id,
        {
          expected_recipe_content_sha256: reusePreview.recipe_content_sha256,
          expected_topic_revision: topic.revision,
          expected_preview_sha256: reusePreview.preview_sha256,
        },
      )
      setProfileDetail(profile)
      setProfiles((current) => [profile, ...(current ?? []).filter((item) => item.id !== profile.id)])
      setReusePreview(null)
      setNotice('写作模式已装入当前作品，并绑定当前确认选题。')
    } catch (caught) {
      reportFailure(caught, '无法装入写作模式')
    } finally {
      setBusy(null)
    }
  }

  async function updateRecipeLifecycle(state: WritingPatternLifecycleState) {
    if (!selectedSeries) return
    setLibraryBusy(`recipe-lifecycle:${selectedSeries.id}`)
    setError(null)
    try {
      const updated = await api.updateWritingPatternRecipeLifecycle(selectedSeries.id, {
        state,
        expected_lifecycle_revision: selectedSeries.lifecycle_revision,
      })
      setSelectedSeries(updated)
      setRecipes((current) => current ? {
        ...current,
        items: current.items.map((item) => item.id === updated.id ? {
          ...item,
          lifecycle_state: updated.lifecycle_state,
          lifecycle_revision: updated.lifecycle_revision,
          updated_at: updated.updated_at,
        } : item),
      } : current)
      setNotice(state === 'archived' ? '全局配方已归档，已有不可变版本仍可查看。' : '全局配方已恢复，可以继续创建版本或复用。')
    } catch (caught) {
      reportFailure(caught, '无法更新配方状态')
      if (caught instanceof ApiError && caught.status === 409) await refreshRecipes().catch(() => undefined)
    } finally {
      setLibraryBusy(null)
    }
  }

  async function openProfile(profileId: string) {
    setLibraryBusy(`profile:${profileId}`)
    setError(null)
    try {
      setProfileDetail(await api.getWritingPatternProfile(workspace.project.id, profileId))
    } catch (caught) {
      reportFailure(caught, '无法读取项目模式快照')
    } finally {
      setLibraryBusy(null)
    }
  }

  async function updateProfileLifecycle(state: WritingPatternLifecycleState) {
    if (!profileDetail) return
    setLibraryBusy(`profile-lifecycle:${profileDetail.id}`)
    setError(null)
    setNotice(null)
    try {
      const updated = await api.updateWritingPatternProfileLifecycle(workspace.project.id, profileDetail.id, {
        state,
        expected_lifecycle_revision: profileDetail.lifecycle_revision,
      })
      setProfileDetail(updated)
      setProfiles((current) => (current ?? []).map((profile) => profile.id === updated.id ? updated : profile))
      setNotice(state === 'archived'
        ? '模式快照已归档；后续创作不会使用它。'
        : '模式快照已恢复为当前写作模式。')
    } catch (caught) {
      reportFailure(caught, '无法更新项目模式状态')
      if (caught instanceof ApiError && caught.status === 409) await refreshProfiles(profileDetail.id).catch(() => undefined)
    } finally {
      setLibraryBusy(null)
    }
  }

  return (
    <main className="recipe-workbench">
      <header className="recipe-workbench-bar">
        <div><span aria-hidden="true">谱</span><div><small>WRITING PATTERN SCORE</small><strong>写作配方</strong></div></div>
        <button type="button" onClick={onBack}>返回正文</button>
      </header>
      <section className="recipe-workbench-hero">
        <div>
          <p>把拆书结论编成你的写作约束</p>
          <h1>先看清每条技法，再决定学什么、改什么、避开什么。</h1>
          <span>系统只提交不可变资产指纹和抽象规则选择，不把参考原文带入创作。</span>
        </div>
        <ol aria-label="写作配方四阶段">
          <li data-current={entries.length === 0}>01 查看技法</li>
          <li data-current={entries.length > 0 && !previewCurrent}>02 来源矩阵</li>
          <li data-current={previewCurrent}>03 编译冲突</li>
          <li>04 保存快照</li>
        </ol>
      </section>

      {!topicIsConfirmed ? (
        <section className="recipe-topic-gate" role="alert">
          <h2>先确认当前选题</h2>
          <p>配方必须绑定一版由作者确认的选题，避免旧方向进入后续规划。</p>
          <button type="button" onClick={onOpenTopicDecision}>去确认选题</button>
        </section>
      ) : null}
      {error ? <p className="agent-error recipe-page-message" role="alert">{error}</p> : null}
      {notice ? <p className="recipe-page-notice" role="status">{notice}</p> : null}

      <div className="recipe-workbench-layout">
        <section className="recipe-source-browser" aria-labelledby="recipe-source-heading">
          <header><div><small>01 / INSPECT</small><h2 id="recipe-source-heading">查看已保存技法</h2></div><span>{activeAssets.length} 个可用版本</span></header>
          <p>摘要不能直接加入。展开详情、核对抽象证据后，再选择具体技法。</p>
          {assets === null ? <p role="status">正在读取写作模式素材…</p> : null}
          {assets?.length === 0 ? <p className="recipe-empty">当前作品还没有模式素材，请先去拆书库完成阶段拆解或装入已有素材。</p> : null}
          <div className="recipe-source-list">
            {activeAssets.map((asset) => (
              <CraftPatternAssetCard
                key={asset.id}
                asset={asset}
                detail={assetDetails[asset.id] ?? null}
                detailLoading={detailLoadingId === asset.id}
                detailError={null}
                selectedForFusion={false}
                lifecycleBusy={false}
                onRequestDetail={() => { void loadDetail(asset.id) }}
                onToggleFusion={() => undefined}
                onLifecycleChange={() => undefined}
                showFusionSelection={false}
                showLifecycleAction={false}
                craftItemAction={{
                  label: (item) => entries.some((entry) => entry.asset_version_id === asset.id && entry.dimension === item.dimension && entry.pattern_name === item.name) ? '已加入配方' : '加入配方',
                  disabled: (item) => entries.some((entry) => entry.asset_version_id === asset.id && entry.dimension === item.dimension && entry.pattern_name === item.name),
                  onClick: (item) => addCraftItem(asset, item),
                }}
              />
            ))}
          </div>
        </section>

        <section className="recipe-matrix" aria-label="来源矩阵">
          <header><div><small>02 / SCORE</small><h2>来源矩阵</h2></div><span>{entries.length} 条技法</span></header>
          <label className="recipe-title-field">配方名称<input value={name} maxLength={120} onChange={(event) => { setName(event.target.value); invalidatePreview(true) }} /></label>
          <label className="recipe-description-field">这份配方要解决什么<textarea rows={3} maxLength={1000} value={description} onChange={(event) => { setDescription(event.target.value); invalidatePreview(true) }} /></label>
          {entries.length === 0 ? <p className="recipe-empty">展开左侧资产详情，从具体技法开始编配。</p> : (
            <div className="recipe-entry-list">
              {entries.map((entry, index) => (
                <RecipeEntryEditor
                  key={entryId(entry)}
                  entry={entry}
                  onChange={(next) => updateEntry(index, next)}
                  onRemove={() => removeEntry(index)}
                />
              ))}
            </div>
          )}
          <button
            className="recipe-primary-action"
            type="button"
            disabled={!topicIsConfirmed || !entriesValid || busy !== null}
            onClick={() => { void compilePreview() }}
          >{busy === 'preview'
              ? '正在本地编译…'
              : baseVersion ? `编译第 ${baseVersion.latestVersion + 1} 版预览` : '编译配方预览'}</button>
        </section>
      </div>

      <section className="recipe-compile" aria-labelledby="recipe-compile-heading">
        <header><div><small>03 / COMPILE</small><h2 id="recipe-compile-heading">稳定编译与冲突</h2></div><span>本地编译 · 不调用 AI</span></header>
        {!preview ? <p className="recipe-empty">完成来源矩阵后编译。系统会统一排序、核对 1–5 本来源，并指出互相冲突的规则。</p> : (
          <>
            <dl className="recipe-compile-ledger">
              <div><dt>来源作品</dt><dd>{preview.source_work_count} 本</dd></div>
              <div><dt>不可变资产</dt><dd>{preview.source_asset_count} 个</dd></div>
              <div><dt>安全依据</dt><dd>{preview.safety_basis === 'source_verified' ? '来源已核验' : '仅抽象谱系'}</dd></div>
              <div><dt>待解决冲突</dt><dd>{preview.unresolved_conflict_count}</dd></div>
            </dl>
            <p className="recipe-fingerprint">配方指纹 {shortHash(preview.recipe_content_sha256)} · 预览 {shortHash(preview.preview_sha256)}</p>
            {preview.conflicts.length > 0 ? (
              <div className="recipe-conflict-list">
                {preview.conflicts.map((conflict, index) => {
                  const decision = conflictDecisions.find((item) => item.conflict_key === conflict.conflict_key)
                  return (
                    <fieldset key={conflict.conflict_key} className="recipe-conflict">
                      <legend>冲突 {index + 1} · {craftDimensionLabels[conflict.dimension]} · {stageOptions.find((stage) => stage.value === conflict.applicable_stage)?.label}</legend>
                      <p>{conflict.reason === 'competing_preserve_rules' ? '同一阶段有多条需要保留的规则' : '同一阶段同时要求保留与避免'}</p>
                      <div>
                        {(Object.entries(conflictResolutionLabels) as Array<[WritingPatternConflictResolution, string]>).map(([value, label]) => (
                          <label key={value}>
                            <input
                              type="radio"
                              name={`conflict-${conflict.conflict_key}`}
                              checked={decision?.resolution === value}
                              onChange={() => updateConflictResolution(conflict.conflict_key, value)}
                            />
                            {label}
                          </label>
                        ))}
                      </div>
                      {decision?.resolution === 'choose_source' ? (
                        <label>
                          选择保留的来源
                          <select
                            value={decision.chosen_entry_key ?? ''}
                            onChange={(event) => updateConflictSource(conflict.conflict_key, event.target.value)}
                          >
                            <option value="">请选择</option>
                            {conflict.entry_keys.map((key) => (
                              <option key={key} value={key}>{preview.sources.find((source) => source.entry_key === key)?.pattern_name ?? shortHash(key)}</option>
                            ))}
                          </select>
                        </label>
                      ) : null}
                    </fieldset>
                  )
                })}
                <button
                  type="button"
                  disabled={busy !== null || conflictDecisions.length !== preview.conflicts.length || conflictDecisions.some((decision) => decision.resolution === 'choose_source' && !decision.chosen_entry_key)}
                  onClick={() => { void compilePreview() }}
                >重新编译冲突决定</button>
              </div>
            ) : null}
            {previewCurrent && preview.unresolved_conflict_count === 0 ? <p className="recipe-compile-ready" role="status">规则已稳定，可以保存为不可变版本。</p> : <p className="recipe-field-error">{preview.unresolved_conflict_count > 0 ? '仍有冲突需要处理。' : '冲突决定已修改，请重新编译。'}</p>}
            <button
              className="recipe-primary-action"
              type="button"
              disabled={!previewCurrent || preview.unresolved_conflict_count > 0 || busy !== null}
              onClick={() => { void saveRecipe() }}
            >{busy === 'save'
                ? '正在保存…'
                : baseVersion ? `保存为第 ${baseVersion.latestVersion + 1} 版` : '保存为全局配方'}</button>
          </>
        )}
      </section>

      <section className="recipe-library" aria-labelledby="recipe-library-heading">
        <header>
          <div><small>04 / VERSION VAULT</small><h2 id="recipe-library-heading">全局配方版本库</h2></div>
          <span>{recipes ? `${recipes.total} 个配方系列` : '正在读取'}</span>
        </header>
        <p>每次保存都会形成不可变版本。先打开具体版本看清规则，再决定编配新版本或装入当前作品。</p>
        <div className="recipe-library-layout">
          <div className="recipe-series-list">
            {recipes === null ? <p role="status">正在读取全局配方…</p> : null}
            {recipes?.items.length === 0 ? <p className="recipe-empty">还没有全局配方。上方编译通过后，可以保存第一版。</p> : null}
            {recipes?.items.map((recipe) => (
              <article key={recipe.id} data-lifecycle={recipe.lifecycle_state}>
                <header>
                  <div><small>第 {recipe.latest_version.version} 版 · {recipe.latest_version.source_work_count} 本来源</small><h3>{recipe.latest_version.name}</h3></div>
                  <span>{lifecycleLabel(recipe.lifecycle_state)}</span>
                </header>
                <p>{recipe.latest_version.description || '没有补充说明。'}</p>
                <small>内容指纹 {shortHash(recipe.latest_version.content_sha256)}</small>
                <button
                  type="button"
                  disabled={libraryBusy !== null}
                  onClick={() => { void openRecipeSeries(recipe.id) }}
                >查看配方版本</button>
              </article>
            ))}
            {recipes && recipes.total > recipes.limit ? (
              <nav className="recipe-pagination" aria-label="全局配方分页">
                <button type="button" disabled={recipeOffset === 0} onClick={() => setRecipeOffset(Math.max(0, recipeOffset - recipes.limit))}>上一页</button>
                <span>{Math.floor(recipeOffset / recipes.limit) + 1} / {Math.ceil(recipes.total / recipes.limit)}</span>
                <button type="button" disabled={recipeOffset + recipes.limit >= recipes.total} onClick={() => setRecipeOffset(recipeOffset + recipes.limit)}>下一页</button>
              </nav>
            ) : null}
          </div>

          <aside className="recipe-version-inspector" aria-label="配方版本详情">
            {!selectedSeries ? <p className="recipe-empty">选择一个配方系列，查看它的不可变版本。</p> : (
              <>
                <header>
                  <div><small>配方系列</small><h3>{selectedSeries.versions[0]?.name}</h3></div>
                  <span>{lifecycleLabel(selectedSeries.lifecycle_state)}</span>
                </header>
                <div className="recipe-version-actions">
                  {selectedSeries.versions.map((version) => (
                    <button
                      type="button"
                      key={version.id}
                      disabled={libraryBusy !== null}
                      data-selected={selectedVersion?.id === version.id}
                      onClick={() => { void openRecipeVersion(version.id) }}
                    >查看第 {version.version} 版</button>
                  ))}
                </div>
                <button
                  type="button"
                  disabled={libraryBusy !== null}
                  onClick={() => { void updateRecipeLifecycle(selectedSeries.lifecycle_state === 'active' ? 'archived' : 'active') }}
                >{selectedSeries.lifecycle_state === 'active' ? '归档配方' : '恢复配方'}</button>
              </>
            )}

            {selectedVersion ? (
              <article className="recipe-version-detail">
                <header><div><small>不可变版本 {selectedVersion.version}</small><h3>{selectedVersion.name}</h3></div><span>{selectedVersion.source_work_count} 本来源</span></header>
                <p>{selectedVersion.description || '没有补充说明。'}</p>
                <dl>
                  <div><dt>内容指纹</dt><dd>{shortHash(selectedVersion.content_sha256)}</dd></div>
                  <div><dt>来源快照</dt><dd>{shortHash(selectedVersion.source_snapshot_sha256)}</dd></div>
                  <div><dt>安全依据</dt><dd>{selectedVersion.safety_basis === 'source_verified' ? '来源已核验' : '仅抽象谱系'}</dd></div>
                  <div><dt>冲突决定</dt><dd>{selectedVersion.conflict_decisions.length}</dd></div>
                </dl>
                <div className="recipe-version-rules">
                  {selectedVersion.sources.map((source) => (
                    <section key={source.entry_key}>
                      <small>{craftDimensionLabels[source.dimension]} · {purposeLabels[source.purpose]} · {strategyLabels[source.strategy]}</small>
                      <strong>{source.pattern_name}</strong>
                      <p>{source.transferable_rule}</p>
                      <p className="recipe-risk">风险：{source.adaptation_risk}</p>
                    </section>
                  ))}
                </div>
                <div className="recipe-version-primary-actions">
                  <button
                    type="button"
                    disabled={selectedSeries?.lifecycle_state !== 'active' || busy !== null}
                    onClick={() => editAsNewVersion(selectedVersion)}
                  >基于第 {selectedVersion.version} 版编配新版本</button>
                  <button
                    type="button"
                    disabled={!topicIsConfirmed || selectedSeries?.lifecycle_state !== 'active' || busy !== null}
                    onClick={() => { void previewReuse(selectedVersion) }}
                  >{busy === 'reuse-preview' ? '正在生成预览…' : '预览装入当前作品'}</button>
                </div>
              </article>
            ) : null}

            {reusePreview ? (
              <section className="recipe-reuse-preview" aria-labelledby="recipe-reuse-heading">
                <header><div><small>PROJECT SNAPSHOT</small><h3 id="recipe-reuse-heading">即将生成项目模式快照</h3></div><span>{reusePreview.model_safe_profile.rules.length} 条安全规则</span></header>
                <p>绑定选题版本 {reusePreview.topic_revision}，仅把下列抽象规则送入后续创作上下文。</p>
                <ul>
                  {reusePreview.model_safe_profile.rules.map((rule) => (
                    <li key={`${rule.source_content_sha256}:${rule.dimension}:${rule.name}`}>
                      <strong>{rule.name}</strong>
                      <span>{craftDimensionLabels[rule.dimension]} · 权重 {(rule.weight_basis_points / 100).toFixed(0)}%</span>
                    </li>
                  ))}
                </ul>
                <small>模式指纹 {shortHash(reusePreview.profile_fingerprint_sha256)} · 预览 {shortHash(reusePreview.preview_sha256)}</small>
                <button type="button" disabled={busy !== null} onClick={() => { void confirmReuse() }}>{busy === 'reuse' ? '正在装入…' : '确认装入为当前模式'}</button>
              </section>
            ) : null}
          </aside>
        </div>
      </section>

      <section className="recipe-profile" aria-labelledby="recipe-profile-heading">
        <header>
          <div><small>PROJECT PROFILE</small><h2 id="recipe-profile-heading">当前写作模式</h2></div>
          <span>{profileDetail ? lifecycleLabel(profileDetail.lifecycle_state) : '尚未装入'}</span>
        </header>
        <p>项目快照只保留抽象可迁移规则，并固定绑定作者已确认的选题版本。</p>
        {profiles === null ? <p role="status">正在读取项目模式快照…</p> : null}
        {profiles && profiles.length > 0 ? (
          <nav className="recipe-profile-history" aria-label="项目模式历史">
            {profiles.map((profile) => (
              <button
                type="button"
                key={profile.id}
                disabled={libraryBusy !== null}
                data-selected={profileDetail?.id === profile.id}
                onClick={() => { void openProfile(profile.id) }}
              >选题 v{profile.topic_revision} · {lifecycleLabel(profile.lifecycle_state)} · {shortHash(profile.profile_fingerprint_sha256)}</button>
            ))}
          </nav>
        ) : null}
        {profiles?.length === 0 && !profileDetail ? <p className="recipe-empty">还没有项目模式。请先打开全局配方的具体版本并预览装入。</p> : null}
        {profileDetail ? (
          <article className="recipe-profile-detail" data-current={profileDetail.is_current}>
            <header>
              <div><small>选题版本 {profileDetail.topic_revision} · 编译器 {profileDetail.compiler_version}</small><h3>模式快照 {shortHash(profileDetail.profile_fingerprint_sha256)}</h3></div>
              <span>{profileDetail.is_current ? '与当前选题一致' : '依据已变化'}</span>
            </header>
            <dl>
              <div><dt>配方指纹</dt><dd>{shortHash(profileDetail.recipe_content_sha256)}</dd></div>
              <div><dt>选题指纹</dt><dd>{shortHash(profileDetail.topic_content_sha256)}</dd></div>
              <div><dt>来源快照</dt><dd>{shortHash(profileDetail.source_snapshot_sha256)}</dd></div>
              <div><dt>安全规则</dt><dd>{profileDetail.model_safe_profile.rules.length}</dd></div>
            </dl>
            <div className="recipe-profile-rules">
              {profileDetail.model_safe_profile.rules.map((rule) => (
                <section key={`${rule.source_content_sha256}:${rule.dimension}:${rule.name}`}>
                  <small>{craftDimensionLabels[rule.dimension]} · {strategyLabels[rule.strategy]} · {(rule.weight_basis_points / 100).toFixed(0)}%</small>
                  <strong>{rule.name}</strong>
                  <p>{rule.transferable_rule}</p>
                  <p className="recipe-risk">风险：{rule.adaptation_risk}</p>
                </section>
              ))}
            </div>
            <button
              type="button"
              disabled={libraryBusy !== null}
              onClick={() => { void updateProfileLifecycle(profileDetail.lifecycle_state === 'active' ? 'archived' : 'active') }}
            >{profileDetail.lifecycle_state === 'active' ? '归档当前模式' : '恢复为当前模式'}</button>
          </article>
        ) : null}
      </section>
    </main>
  )
}
