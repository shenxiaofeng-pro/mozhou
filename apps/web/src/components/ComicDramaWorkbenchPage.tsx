import type {
  ChapterSummary,
  ComicAiPreview,
  ComicAsset,
  ComicAuditIssue,
  ComicEpisodeOutlineDraft,
  ComicEpisodeScriptDraft,
  ComicProject,
  ComicSeasonDraft,
  ComicVersion,
  ComicWorkspace,
  Project,
} from '@mozhou/contracts'
import { useEffect, useMemo, useState } from 'react'

import { api } from '../api'

interface Props {
  project: Project
  chapters: ChapterSummary[]
  onBack: () => void
  onOpenTaskCenter: () => void
}

const approvalLabels = {
  candidate: '待确认',
  approved: '已批准',
  rejected: '已退回',
  empty: '未生成',
} as const

function latestVersion(
  workspace: ComicWorkspace,
  kind: ComicVersion['target_kind'],
  targetId: string,
): ComicVersion | null {
  return workspace.versions
    .filter((item) => item.target_kind === kind && item.target_id === targetId)
    .sort((left, right) => right.version_number - left.version_number)[0] ?? null
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export function ComicDramaWorkbenchPage({ project, chapters, onBack, onOpenTaskCenter }: Props) {
  const [projects, setProjects] = useState<ComicProject[]>([])
  const [workspace, setWorkspace] = useState<ComicWorkspace | null>(null)
  const [selectedEpisodeId, setSelectedEpisodeId] = useState<string | null>(null)
  const [preview, setPreview] = useState<ComicAiPreview | null>(null)
  const [previewKind, setPreviewKind] = useState<'season' | 'episode' | null>(null)
  const [externalConfirmed, setExternalConfirmed] = useState(false)
  const [authorDirection, setAuthorDirection] = useState('开场尽快见冲突，保留原作核心情绪')
  const [jobId, setJobId] = useState<string | null>(null)
  const [audit, setAudit] = useState<ComicAuditIssue[]>([])
  const [assets, setAssets] = useState<ComicAsset[]>([])
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({
    title: `${project.title}·漫剧第一季`,
    startIndex: 0,
    endIndex: Math.min(chapters.length - 1, 9),
    episodeCount: 8,
    duration: 90,
    aspectRatio: '9:16' as '9:16' | '16:9' | '1:1',
    artStyle: '写实国漫，电影感光影，人物造型稳定',
    adaptationMode: 'balanced' as 'faithful' | 'balanced' | 'dramatic',
    narration: '少量旁白，仅用于时空跳转和信息压缩',
    requirements: '',
  })

  useEffect(() => {
    let active = true
    api.listComicProjects(project.id).then(async (items) => {
      if (!active) return
      setProjects(items)
      if (items[0]) {
        const loaded = await api.getComicProject(items[0].id)
        if (active) setWorkspace(loaded)
      }
    }).catch((caught: unknown) => {
      if (active) setError(caught instanceof Error ? caught.message : '无法读取漫剧项目')
    }).finally(() => {
      if (active) setBusy(false)
    })
    return () => { active = false }
  }, [project.id])

  useEffect(() => {
    if (!workspace) return
    void Promise.all([
      api.getComicAudit(workspace.project.id),
      api.getComicAssets(workspace.project.id),
    ]).then(([nextAudit, nextAssets]) => {
      setAudit(nextAudit)
      setAssets(nextAssets)
    }).catch(() => undefined)
  }, [workspace])

  useEffect(() => {
    if (!jobId || !workspace) return
    const timer = window.setInterval(() => {
      void api.getJob(jobId).then(async (job) => {
        if (job.state === 'succeeded') {
          window.clearInterval(timer)
          setWorkspace(await api.getComicProject(workspace.project.id))
          setJobId(null)
          setPreview(null)
          setPreviewKind(null)
          setExternalConfirmed(false)
        } else if (['failed', 'cancelled', 'interrupted'].includes(job.state)) {
          window.clearInterval(timer)
          setJobId(null)
          setError(job.error_message ?? '漫剧生成任务未完成，可在任务中心重试')
        }
      }).catch(() => undefined)
    }, 900)
    return () => window.clearInterval(timer)
  }, [jobId, workspace])

  const selectedEpisode = workspace?.episodes.find((item) => item.id === selectedEpisodeId)
    ?? workspace?.episodes[0]
    ?? null
  const seasonVersion = workspace
    ? latestVersion(workspace, 'season', workspace.project.id)
    : null
  const outlineVersion = workspace && selectedEpisode
    ? latestVersion(workspace, 'episode_outline', selectedEpisode.id)
    : null
  const scriptVersion = workspace && selectedEpisode
    ? latestVersion(workspace, 'episode_script', selectedEpisode.id)
    : null
  const approvedCount = workspace?.episodes.filter((item) => item.script_state === 'approved').length ?? 0
  const selectedSourceCount = Math.max(0, form.endIndex - form.startIndex + 1)
  const selectedAudit = useMemo(
    () => audit.filter((item) => !selectedEpisode || item.episode_id === selectedEpisode.id),
    [audit, selectedEpisode],
  )

  async function openProject(comicProject: ComicProject) {
    setBusy(true)
    setError(null)
    try {
      setWorkspace(await api.getComicProject(comicProject.id))
      setPreview(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '无法打开漫剧项目')
    } finally {
      setBusy(false)
    }
  }

  async function createProject() {
    setBusy(true)
    setError(null)
    try {
      const sourceChapters = chapters.slice(form.startIndex, form.endIndex + 1)
      const created = await api.createComicProject(project.id, {
        title: form.title,
        source_chapter_ids: sourceChapters.map((item) => item.id),
        episode_target_count: form.episodeCount,
        episode_duration_seconds: form.duration,
        aspect_ratio: form.aspectRatio,
        art_style: form.artStyle,
        adaptation_mode: form.adaptationMode,
        narration_preference: form.narration,
        author_requirements: form.requirements,
      })
      setWorkspace(created)
      setProjects((current) => [created.project, ...current])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '无法创建漫剧项目')
    } finally {
      setBusy(false)
    }
  }

  async function inspectSeason() {
    if (!workspace) return
    setBusy(true)
    setError(null)
    try {
      setPreview(await api.previewComicSeason(workspace.project.id, authorDirection))
      setPreviewKind('season')
      setExternalConfirmed(false)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '无法预览季方案范围')
    } finally {
      setBusy(false)
    }
  }

  async function submitSeason() {
    if (!workspace || !preview || previewKind !== 'season') return
    setBusy(true)
    setError(null)
    try {
      const result = await api.submitComicSeason(workspace.project.id, {
        author_direction: authorDirection,
        expected_source_snapshot_sha256: preview.source_snapshot_sha256,
        confirm_external_processing: externalConfirmed,
        ...(preview.estimated_cost_microusd === null
          ? {}
          : { max_estimated_cost_microusd: preview.estimated_cost_microusd }),
      })
      setJobId(result.job.id)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '季方案任务提交失败')
    } finally {
      setBusy(false)
    }
  }

  async function adoptSeason() {
    if (!workspace || !seasonVersion) return
    setBusy(true)
    try {
      setWorkspace(await api.adoptComicSeason(
        workspace.project.id,
        seasonVersion.id,
        workspace.project.season_revision,
      ))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '无法采用季方案')
    } finally {
      setBusy(false)
    }
  }

  async function reviewOutline(action: 'approve' | 'reject') {
    if (!selectedEpisode || !outlineVersion) return
    setBusy(true)
    try {
      setWorkspace(await api.reviewComicOutline(
        selectedEpisode.id,
        action,
        selectedEpisode.outline_revision,
        outlineVersion.id,
      ))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '分集大纲确认失败')
    } finally {
      setBusy(false)
    }
  }

  async function inspectEpisode() {
    if (!selectedEpisode) return
    setBusy(true)
    setError(null)
    try {
      setPreview(await api.previewComicEpisode(selectedEpisode.id, authorDirection))
      setPreviewKind('episode')
      setExternalConfirmed(false)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '无法预览单集生成范围')
    } finally {
      setBusy(false)
    }
  }

  async function submitEpisode() {
    if (!selectedEpisode || !preview || previewKind !== 'episode') return
    setBusy(true)
    try {
      const result = await api.submitComicEpisode(selectedEpisode.id, {
        author_direction: authorDirection,
        expected_source_snapshot_sha256: preview.source_snapshot_sha256,
        expected_outline_revision: selectedEpisode.outline_revision,
        confirm_external_processing: externalConfirmed,
        ...(preview.estimated_cost_microusd === null
          ? {}
          : { max_estimated_cost_microusd: preview.estimated_cost_microusd }),
      })
      setJobId(result.job.id)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '单集剧本任务提交失败')
    } finally {
      setBusy(false)
    }
  }

  async function reviewScript(action: 'approve' | 'reject') {
    if (!selectedEpisode || !scriptVersion) return
    setBusy(true)
    try {
      setWorkspace(await api.reviewComicScript(
        selectedEpisode.id,
        action,
        selectedEpisode.script_revision,
        scriptVersion.id,
      ))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '单集剧本确认失败')
    } finally {
      setBusy(false)
    }
  }

  async function exportPackage(format: 'json' | 'markdown' | 'docx') {
    if (!workspace) return
    setBusy(true)
    try {
      const result = await api.exportComicProductionPackage(workspace.project.id, format)
      downloadBlob(result.blob, result.filename)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '制作包导出失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="comic-workbench">
      <header className="comic-topbar">
        <div>
          <small>MOZHOU · AI COMIC DRAMA</small>
          <h1>AI 漫剧改编</h1>
          <p>《{project.title}》 · 文字剧本与制作包，不修改小说原稿</p>
        </div>
        <div className="comic-top-actions">
          {workspace && approvedCount > 0 ? (
            <>
              <button type="button" onClick={() => { void exportPackage('markdown') }}>导出 MD</button>
              <button type="button" onClick={() => { void exportPackage('json') }}>导出 JSON</button>
              <button type="button" onClick={() => { void exportPackage('docx') }}>导出 DOCX</button>
            </>
          ) : null}
          <button type="button" onClick={onOpenTaskCenter}>任务中心</button>
          <button type="button" onClick={onBack}>返回写作</button>
        </div>
      </header>

      {error ? <p className="comic-error" role="alert">{error}</p> : null}
      {busy ? <p className="comic-working" role="status">正在整理分镜稿纸…</p> : null}

      {!workspace ? (
        <section className="comic-create-sheet">
          <div className="comic-slate-heading">
            <span>SCENE 00</span>
            <div><small>新建改编季</small><h2>先圈定一段连续小说剧情</h2></div>
          </div>
          {projects.length ? (
            <div className="comic-existing-projects">
              <h3>继续已有漫剧</h3>
              {projects.map((item) => (
                <button type="button" key={item.id} onClick={() => { void openProject(item) }}>
                  <strong>{item.title}</strong><span>{item.episode_target_count} 集 · {item.state}</span>
                </button>
              ))}
            </div>
          ) : null}
          <div className="comic-create-grid">
            <label>季名<input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label>
            <label>起始章<select value={form.startIndex} onChange={(event) => setForm({ ...form, startIndex: Number(event.target.value), endIndex: Math.max(Number(event.target.value), form.endIndex) })}>{chapters.map((chapter, index) => <option key={chapter.id} value={index}>{chapter.chapter_number}. {chapter.title}</option>)}</select></label>
            <label>结束章<select value={form.endIndex} onChange={(event) => setForm({ ...form, endIndex: Number(event.target.value) })}>{chapters.map((chapter, index) => <option key={chapter.id} value={index} disabled={index < form.startIndex}>{chapter.chapter_number}. {chapter.title}</option>)}</select></label>
            <label>目标集数<input type="number" min={1} max={100} value={form.episodeCount} onChange={(event) => setForm({ ...form, episodeCount: Number(event.target.value) })} /></label>
            <label>单集秒数<input type="number" min={30} max={300} value={form.duration} onChange={(event) => setForm({ ...form, duration: Number(event.target.value) })} /></label>
            <label>画幅<select value={form.aspectRatio} onChange={(event) => setForm({ ...form, aspectRatio: event.target.value as typeof form.aspectRatio })}><option value="9:16">9:16 竖屏</option><option value="16:9">16:9 横屏</option><option value="1:1">1:1 方屏</option></select></label>
            <label>改编强度<select value={form.adaptationMode} onChange={(event) => setForm({ ...form, adaptationMode: event.target.value as typeof form.adaptationMode })}><option value="faithful">忠实原作</option><option value="balanced">平衡改编</option><option value="dramatic">强节奏</option></select></label>
            <label className="comic-wide">画风说明<textarea value={form.artStyle} onChange={(event) => setForm({ ...form, artStyle: event.target.value })} /></label>
            <label className="comic-wide">旁白倾向<textarea value={form.narration} onChange={(event) => setForm({ ...form, narration: event.target.value })} /></label>
            <label className="comic-wide">作者要求<textarea value={form.requirements} onChange={(event) => setForm({ ...form, requirements: event.target.value })} /></label>
          </div>
          <footer>
            <p>已选连续 {selectedSourceCount} 章；创建时冻结章节 revision 与正文 SHA-256。</p>
            <button type="button" disabled={busy || !form.title.trim() || selectedSourceCount < 1} onClick={() => { void createProject() }}>建立漫剧改编季</button>
          </footer>
        </section>
      ) : (
        <div className="comic-layout">
          <aside className="comic-reel" aria-label="漫剧剧集轨">
            <header><small>EPISODE REEL</small><h2>{workspace.project.title}</h2><p>{approvedCount} / {workspace.episodes.length || workspace.project.episode_target_count} 集剧本已批准</p></header>
            {workspace.episodes.length ? workspace.episodes.map((episode) => (
              <button
                type="button"
                key={episode.id}
                data-active={episode.id === selectedEpisode?.id}
                onClick={() => { setSelectedEpisodeId(episode.id); setPreview(null) }}
              >
                <span>{String(episode.episode_number).padStart(2, '0')}</span>
                <strong>{episode.title}</strong>
                <small data-state={episode.outline_state}>纲 {approvalLabels[episode.outline_state]}</small>
                <small data-state={episode.script_state}>稿 {approvalLabels[episode.script_state]}</small>
              </button>
            )) : <p className="comic-reel-empty">季方案采用后，这里会出现逐集胶片。</p>}
          </aside>

          <section className="comic-stage">
            <header className="comic-stage-meta">
              <div><small>{workspace.project.aspect_ratio} · {workspace.project.episode_duration_seconds}s</small><h2>{selectedEpisode ? `第 ${selectedEpisode.episode_number} 集 · ${selectedEpisode.title}` : '季方案'}</h2></div>
              <span data-state={workspace.project.state}>{workspace.project.state}</span>
            </header>
            <label className="comic-direction">本轮导演要求<textarea maxLength={1000} value={authorDirection} onChange={(event) => { setAuthorDirection(event.target.value); setPreview(null) }} /></label>

            {!seasonVersion ? (
              <section className="comic-empty-stage"><span>01</span><h3>把小说剧情压成一季可拍的节奏</h3><p>模型会生成季纲和完整分集候选，但不会自动批准任何一集。</p><button type="button" disabled={busy || Boolean(jobId)} onClick={() => { void inspectSeason() }}>预览季方案范围与费用</button></section>
            ) : !workspace.episodes.length ? (
              <SeasonCard version={seasonVersion} onAdopt={() => { void adoptSeason() }} busy={busy} />
            ) : selectedEpisode && outlineVersion ? (
              <>
                <OutlineCard version={outlineVersion} />
                {selectedEpisode.outline_state === 'candidate' ? <div className="comic-approval-bar"><span>第一道批准门 · 仅确认本集大纲</span><button type="button" onClick={() => { void reviewOutline('reject') }}>退回大纲</button><button type="button" className="approve" onClick={() => { void reviewOutline('approve') }}>批准大纲</button></div> : null}
                {selectedEpisode.outline_state === 'approved' && (!scriptVersion || selectedEpisode.script_state === 'rejected') ? <section className="comic-empty-stage compact"><span>02</span><h3>{selectedEpisode.script_state === 'rejected' ? '剧本已退回，重新生成候选' : '大纲已锁定，生成完整单集剧本'}</h3><p>输出场次、可见动作、结构化对白、旁白、画面重点和资产需求。</p><button type="button" disabled={busy || Boolean(jobId)} onClick={() => { void inspectEpisode() }}>预览本集剧本范围与费用</button></section> : null}
                {scriptVersion ? <ScriptCard version={scriptVersion} /> : null}
                {selectedEpisode.script_state === 'candidate' && scriptVersion ? <div className="comic-approval-bar second"><span>第二道批准门 · 批准后才物化正式场次</span><button type="button" onClick={() => { void reviewScript('reject') }}>退回剧本</button><button type="button" className="approve" onClick={() => { void reviewScript('approve') }}>批准完整剧本</button></div> : null}
              </>
            ) : null}

            {preview ? <div className="comic-cost-card"><header><strong>{previewKind === 'season' ? '季方案外发确认' : '单集剧本外发确认'}</strong><span>{preview.profile_name} · {preview.model}</span></header><p>{preview.content_scope}</p><ul>{preview.data_types.map((item) => <li key={item}>{item}</li>)}</ul><label><input type="checkbox" checked={externalConfirmed} onChange={(event) => setExternalConfirmed(event.target.checked)} />确认向当前模型线路发送上述内容；预估费用上限 {preview.estimated_cost_microusd === null ? '未知' : `US$ ${(preview.estimated_cost_microusd / 1_000_000).toFixed(4)}`}</label><button type="button" disabled={!externalConfirmed || busy || Boolean(jobId)} onClick={() => { void (previewKind === 'season' ? submitSeason() : submitEpisode()) }}>{jobId ? '任务运行中…' : '确认并创建可恢复任务'}</button></div> : null}
          </section>

          <aside className="comic-inspector">
            <section><header><small>SCRIPT DOCTOR</small><h2>审校提示</h2></header>{selectedAudit.length ? selectedAudit.map((item) => <article key={`${item.code}-${item.episode_id}-${item.scene_number ?? 0}`} data-severity={item.severity}><strong>{item.scene_number ? `场 ${item.scene_number}` : `第 ${item.episode_number} 集`}</strong><p>{item.message}</p></article>) : <p className="comic-clear">当前没有结构性提示。</p>}</section>
            <section><header><small>ASSET BIBLE</small><h2>制作资产</h2></header>{assets.length ? assets.map((asset) => <article key={`${asset.kind}-${asset.name}`}><strong>{asset.name}</strong><span>{asset.kind} · 首见第 {asset.first_episode} 集</span><p>{asset.description}</p></article>) : <p className="comic-clear">批准一集剧本后生成资产清单。</p>}</section>
            <footer><strong>AI 生成内容</strong><p>制作包内含显式 AIGC 提示和发布前检查清单，不代替平台审核。</p></footer>
          </aside>
        </div>
      )}
    </main>
  )
}

function SeasonCard({ version, onAdopt, busy }: { version: ComicVersion; onAdopt: () => void; busy: boolean }) {
  const season = version.content as ComicSeasonDraft
  return <article className="comic-season-card"><header><span>SEASON / V{version.version_number}</span><strong data-state={version.state}>{approvalLabels[version.state]}</strong></header><h3>{season.logline}</h3><dl><div><dt>主题</dt><dd>{season.theme}</dd></div><div><dt>核心欲望</dt><dd>{season.core_desire}</dd></div><div><dt>主冲突</dt><dd>{season.main_conflict}</dd></div><div><dt>改编策略</dt><dd>{season.adaptation_strategy}</dd></div></dl><ol>{season.episode_outlines.map((episode) => <li key={episode.episode_number}><span>{String(episode.episode_number).padStart(2, '0')}</span><div><strong>{episode.title}</strong><p>{episode.opening_hook} → {episode.ending_cliffhanger}</p></div></li>)}</ol>{version.state === 'candidate' ? <button type="button" disabled={busy} onClick={onAdopt}>采用季方案，建立逐集候选</button> : null}</article>
}

function OutlineCard({ version }: { version: ComicVersion }) {
  const outline = version.content as ComicEpisodeOutlineDraft
  return <article className="comic-outline-card"><header><span>EPISODE OUTLINE / V{version.version_number}</span><strong data-state={version.state}>{approvalLabels[version.state]}</strong></header><h3>{outline.opening_hook}</h3><div className="comic-beat-line"><p><small>目标</small>{outline.episode_goal}</p><p><small>冲突</small>{outline.core_conflict}</p><p><small>反转</small>{outline.reversal}</p><p><small>兑现</small>{outline.emotional_payoff}</p><p><small>卡点</small>{outline.ending_cliffhanger}</p></div><footer><span>人物：{outline.cast.join('、') || '待定'}</span><span>地点：{outline.locations.join('、') || '待定'}</span></footer></article>
}

function ScriptCard({ version }: { version: ComicVersion }) {
  const script = version.content as ComicEpisodeScriptDraft
  return <section className="comic-script-card"><header><div><span>FULL SCRIPT / V{version.version_number}</span><h3>{script.title}</h3></div><strong data-state={version.state}>{approvalLabels[version.state]} · {script.estimated_seconds}s</strong></header>{script.scenes.map((scene) => <article key={scene.scene_number}><header><span>SC {String(scene.scene_number).padStart(2, '0')}</span><strong>{scene.interior_exterior} · {scene.location} · {scene.time_of_day}</strong><small>{scene.cast.join(' / ')}</small></header><p className="comic-action">{scene.action}</p><div className="comic-dialogue">{scene.dialogue.map((line, index) => <p key={`${line.character}-${index}`}><strong>{line.character}</strong>{line.emotion ? <em>{line.emotion}</em> : null}<span>{line.line}</span></p>)}</div>{scene.narration ? <blockquote>旁白：{scene.narration}</blockquote> : null}<footer><span>画面：{scene.visual_focus}</span><strong>场尾：{scene.ending_beat}</strong></footer></article>)}</section>
}
