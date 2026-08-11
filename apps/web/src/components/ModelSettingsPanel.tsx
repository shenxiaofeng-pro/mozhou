import type {
  AiStatus,
  AiTaskDefault,
  AiTaskType,
  CreateModelProfileInput,
  ModelProfile,
  ProviderKind,
} from '@mozhou/contracts'
import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { aiCredentialStore, api, type AiCredentialStatus } from '../api'

interface ModelSettingsPanelProps {
  open: boolean
  status: AiStatus | null
  onClose: () => void
  onStatusChanged: (status: AiStatus) => void
}

interface ProfileForm {
  name: string
  provider: ProviderKind
  baseUrl: string
  model: string
  inputPrice: string
  outputPrice: string
}

const emptyForm: ProfileForm = {
  name: '',
  provider: 'openai',
  baseUrl: 'https://api.openai.com/v1',
  model: 'gpt-5.6',
  inputPrice: '',
  outputPrice: '',
}

const taskRoutes: Array<{ type: AiTaskType; label: string; detail: string }> = [
  { type: 'chapter_brief', label: '章纲设计', detail: '钩子、冲突和章节回报' },
  { type: 'chapter_draft', label: '正文主笔', detail: '完整章节候选稿' },
  { type: 'reference_analysis', label: '拆书萃取', detail: '分段分析与多书融合' },
  { type: 'review', label: '一致性审校', detail: '事实、人物与伏笔检查' },
  { type: 'sandbox', label: '剧情沙盘', detail: '角色行动建议与候选后果' },
  { type: 'research', label: '资料研究', detail: '带原文范围的证据候选归纳' },
  { type: 'comic_season_plan', label: '漫剧季方案', detail: '季纲与逐集大纲候选' },
  { type: 'comic_episode_script', label: '漫剧单集剧本', detail: '场次、动作与对白完整稿' },
]

function profileForm(profile: ModelProfile): ProfileForm {
  return {
    name: profile.name,
    provider: profile.provider,
    baseUrl: profile.base_url,
    model: profile.model,
    inputPrice: priceInput(profile.input_cost_microusd_per_million),
    outputPrice: priceInput(profile.output_cost_microusd_per_million),
  }
}

function priceInput(value: number | null): string {
  return value === null ? '' : String(value / 1_000_000)
}

function profileInput(form: ProfileForm): CreateModelProfileInput {
  return {
    name: form.name.trim(),
    provider: form.provider,
    base_url: form.baseUrl.trim(),
    model: form.model.trim(),
    input_cost_microusd_per_million: parsePrice(form.inputPrice),
    output_cost_microusd_per_million: parsePrice(form.outputPrice),
  }
}

function parsePrice(value: string): number | null {
  if (!value.trim()) return null
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed < 0) throw new Error('每百万 Token 价格必须是非负数')
  return Math.round(parsed * 1_000_000)
}

export function ModelSettingsPanel({
  open,
  status,
  onClose,
  onStatusChanged,
}: ModelSettingsPanelProps) {
  const [profiles, setProfiles] = useState<ModelProfile[]>([])
  const [taskDefaults, setTaskDefaults] = useState<AiTaskDefault[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [form, setForm] = useState<ProfileForm>(emptyForm)
  const [apiKey, setApiKey] = useState('')
  const [credential, setCredential] = useState<AiCredentialStatus | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const dialogRef = useRef<HTMLElement>(null)
  const selected = profiles.find((profile) => profile.id === selectedId) ?? null
  const isActive = selected !== null && status?.profile_id === selected.id
  const canSave = Boolean(form.name.trim() && form.baseUrl.trim() && form.model.trim())
  const capabilityList = useMemo(() => {
    if (!selected) return []
    const labels = [
      ['structured_output', '结构化'],
      ['streaming', '流式'],
      ['server_cancellation', '服务端取消'],
      ['usage', '用量回传'],
    ] as const
    return labels.map(([key, label]) => ({ label, enabled: selected.capabilities[key] }))
  }, [selected])

  useEffect(() => {
    if (!open) return undefined
    let stopped = false
    Promise.all([api.listAiProfiles(), api.listAiTaskDefaults()])
      .then(([items, defaults]) => {
        if (stopped) return
        setProfiles(items)
        setTaskDefaults(defaults)
        const initial = items.find((item) => item.id === status?.profile_id) ?? items[0]
        if (initial) {
          setSelectedId(initial.id)
          setForm(profileForm(initial))
        } else {
          setSelectedId(null)
          setForm(emptyForm)
          setCredential(null)
        }
      })
      .catch((caught: unknown) => {
        if (!stopped) setError(caught instanceof Error ? caught.message : '读取模型配置失败')
      })
    return () => {
      stopped = true
    }
  }, [open, status?.profile_id])

  useEffect(() => {
    if (!open || !selectedId) return undefined
    let stopped = false
    aiCredentialStore.status(selectedId)
      .then((result) => {
        if (!stopped) setCredential(result)
      })
      .catch((caught: unknown) => {
        if (!stopped) setError(caught instanceof Error ? caught.message : '读取密钥状态失败')
      })
    return () => {
      stopped = true
    }
  }, [open, selectedId])

  useEffect(() => {
    if (!open) return undefined
    function handleDialogKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose()
        return
      }
      if (event.key !== 'Tab') return
      const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled)',
      ) ?? [])
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable.at(-1)
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last?.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', handleDialogKey)
    return () => {
      window.removeEventListener('keydown', handleDialogKey)
    }
  }, [onClose, open])

  function chooseProfile(profile: ModelProfile) {
    setSelectedId(profile.id)
    setForm(profileForm(profile))
    setApiKey('')
    setError(null)
  }

  function startNewProfile() {
    setSelectedId(null)
    setForm(emptyForm)
    setCredential(null)
    setApiKey('')
    setError(null)
  }

  async function saveProfile(): Promise<ModelProfile> {
    const input = profileInput(form)
    const saved = selected
      ? await api.updateAiProfile(selected.id, { ...input, expected_revision: selected.revision })
      : await api.createAiProfile(input)
    setProfiles((current) => {
      const exists = current.some((profile) => profile.id === saved.id)
      return exists
        ? current.map((profile) => profile.id === saved.id ? saved : profile)
        : [...current, saved]
    })
    setSelectedId(saved.id)
    setForm(profileForm(saved))
    return saved
  }

  async function saveOnly() {
    if (!canSave || busy) return
    setBusy('save')
    setError(null)
    try {
      await saveProfile()
      if (isActive) onStatusChanged(await api.getAiStatus())
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '保存模型配置失败')
    } finally {
      setBusy(null)
    }
  }

  async function saveAndActivate() {
    if (!canSave || busy) return
    setBusy('activate')
    setError(null)
    try {
      const saved = await saveProfile()
      let nextCredential: AiCredentialStatus
      if (apiKey.trim()) {
        nextCredential = await aiCredentialStore.storeAndActivate(saved.id, apiKey)
      } else {
        nextCredential = await aiCredentialStore.activateSaved(saved.id)
      }
      setCredential(nextCredential)
      setApiKey('')
      onStatusChanged(await api.getAiStatus())
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '启用模型配置失败')
    } finally {
      setBusy(null)
    }
  }

  async function deleteSelected() {
    if (!selected || busy) return
    setBusy('delete')
    setError(null)
    try {
      if (credential?.stored || isActive) {
        await aiCredentialStore.delete(selected.id)
      }
      await api.deleteAiProfile(selected.id, selected.revision)
      const remaining = profiles.filter((profile) => profile.id !== selected.id)
      setProfiles(remaining)
      setTaskDefaults((current) => current.filter((item) => item.profile_id !== selected.id))
      const next = remaining[0] ?? null
      setSelectedId(next?.id ?? null)
      setForm(next ? profileForm(next) : emptyForm)
      setCredential(null)
      onStatusChanged(await api.getAiStatus())
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '删除模型配置失败')
    } finally {
      setBusy(null)
    }
  }

  async function changeTaskRoute(taskType: AiTaskType, profileId: string) {
    if (busy) return
    const current = taskDefaults.find((item) => item.task_type === taskType)
    setBusy(`route:${taskType}`)
    setError(null)
    try {
      if (!profileId) {
        if (current) await api.deleteAiTaskDefault(taskType, current.revision)
        setTaskDefaults((items) => items.filter((item) => item.task_type !== taskType))
        return
      }
      const saved = await api.setAiTaskDefault(taskType, {
        profile_id: profileId,
        expected_revision: current?.revision ?? null,
      })
      setTaskDefaults((items) => [
        ...items.filter((item) => item.task_type !== taskType),
        saved,
      ])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '更新任务线路失败')
    } finally {
      setBusy(null)
    }
  }

  if (!open) return null

  return createPortal((
    <div className="model-settings-layer">
      <button type="button" tabIndex={-1} className="model-settings-backdrop" aria-label="关闭模型设置" onClick={onClose} />
      <section ref={dialogRef} className="model-settings" role="dialog" aria-modal="true" aria-labelledby="model-settings-title">
        <header>
          <div><small>AI ROUTING DESK</small><h2 id="model-settings-title">模型线路台</h2></div>
          <button type="button" autoFocus aria-label="关闭模型设置" onClick={onClose}>×</button>
        </header>
        <p className="model-settings-lead">配置可以跟随本机工作台，密钥只留在系统凭据库，不进入作品或归档。</p>
        <div className="model-settings-grid">
          <aside className="model-profile-rail" aria-label="模型配置列表">
            <button type="button" className="model-profile-new" onClick={startNewProfile}>+ 新建线路</button>
            {profiles.map((profile) => (
              <button
                type="button"
                key={profile.id}
                data-selected={selectedId === profile.id}
                onClick={() => chooseProfile(profile)}
              >
                <span>{profile.name}</span>
                <small>{profile.provider === 'openai' ? 'OpenAI' : '兼容端点'} · {profile.model}</small>
                {status?.profile_id === profile.id ? <em>正在使用</em> : null}
              </button>
            ))}
            {profiles.length === 0 ? <p>还没有线路。先建一条，再放入密钥。</p> : null}
          </aside>

          <form className="model-profile-editor" onSubmit={(event) => { event.preventDefault(); void saveOnly() }}>
            <div className="model-route-strip">
              <span>{selected ? '编辑线路' : '新线路'}</span>
              <strong>{form.name || '未命名模型线路'}</strong>
              <small data-secure={credential?.stored === true}>
                {credential?.stored
                  ? aiCredentialStore.isSystemStoreAvailable ? '密钥已入系统凭据库' : '密钥仅留本次页面会话'
                  : aiCredentialStore.isSystemStoreAvailable ? '尚未保存密钥' : '浏览器模式：仅本次会话'}
              </small>
            </div>

            <div className="model-profile-fields">
              <label>线路名称<input value={form.name} maxLength={80} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如：长章主笔" /></label>
              <label>端点类型
                <select
                  value={form.provider}
                  onChange={(event) => {
                    const provider = event.target.value as ProviderKind
                    setForm({
                      ...form,
                      provider,
                      baseUrl: provider === 'openai' ? 'https://api.openai.com/v1' : form.baseUrl,
                    })
                  }}
                >
                  <option value="openai">OpenAI</option>
                  <option value="openai_compatible">OpenAI-compatible</option>
                </select>
              </label>
              <label className="model-base-url">API 地址<input value={form.baseUrl} maxLength={2048} disabled={form.provider === 'openai'} onChange={(event) => setForm({ ...form, baseUrl: event.target.value })} /></label>
              <label>模型名<input value={form.model} maxLength={100} onChange={(event) => setForm({ ...form, model: event.target.value })} placeholder="gpt-5.6" /></label>
              <label>输入价格 <small>$/百万 Token</small><input inputMode="decimal" value={form.inputPrice} onChange={(event) => setForm({ ...form, inputPrice: event.target.value })} placeholder="留空表示未知" /></label>
              <label>输出价格 <small>$/百万 Token</small><input inputMode="decimal" value={form.outputPrice} onChange={(event) => setForm({ ...form, outputPrice: event.target.value })} placeholder="留空表示未知" /></label>
            </div>

            {selected ? (
              <div className="model-capability-board" aria-label="端点能力">
                {capabilityList.map((capability) => (
                  <span key={capability.label} data-enabled={capability.enabled}>{capability.label}</span>
                ))}
              </div>
            ) : null}

            <fieldset className="model-task-routes">
              <legend>任务分流</legend>
              <p>不同创作任务可走不同模型；留空时跟随当前启用线路。</p>
              <div>
                {taskRoutes.map((route) => {
                  const taskDefault = taskDefaults.find((item) => item.task_type === route.type)
                  return (
                    <label key={route.type}>
                      <span><strong>{route.label}</strong><small>{route.detail}</small></span>
                      <select
                        aria-label={`${route.label}模型线路`}
                        value={taskDefault?.profile_id ?? ''}
                        disabled={busy !== null}
                        onChange={(event) => { void changeTaskRoute(route.type, event.target.value) }}
                      >
                        <option value="">跟随当前线路</option>
                        {profiles.map((profile) => (
                          <option key={profile.id} value={profile.id}>{profile.name} · {profile.model}</option>
                        ))}
                      </select>
                    </label>
                  )
                })}
              </div>
            </fieldset>

            <label className="model-secret-field">
              API Key
              <input
                type="password"
                aria-label="模型 API Key"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                autoComplete="off"
                spellCheck={false}
                placeholder={credential?.stored ? '已保存；留空可直接启用' : '只在你主动保存时进入系统凭据库'}
              />
            </label>

            <p className="model-trust-note"><strong>密钥不出舱</strong><span>{aiCredentialStore.isSystemStoreAvailable ? '前端不能读回已保存密钥；sidecar 只在执行期间持有内存副本。' : '开发模式只保存在当前页面内存；刷新即清除，不写入作品或浏览器存储。'}</span></p>
            {error ? <p className="model-settings-error" role="alert">{error}</p> : null}
            <footer>
              {selected ? <button type="button" className="model-delete" onClick={() => { void deleteSelected() }} disabled={busy !== null}>删除线路</button> : <span />}
              <button type="submit" disabled={!canSave || busy !== null}>{busy === 'save' ? '保存中…' : '只保存线路'}</button>
              <button type="button" className="model-activate" onClick={() => { void saveAndActivate() }} disabled={!canSave || busy !== null || (!apiKey.trim() && !credential?.stored)}>
                {busy === 'activate' ? '启用中…' : isActive ? '保存并重新启用' : '保存并启用'}
              </button>
            </footer>
          </form>
        </div>
      </section>
    </div>
  ), document.body)
}
