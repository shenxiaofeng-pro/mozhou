import type { ContextPacket, CreativeContextPurpose } from '@mozhou/contracts'
import { creativeContextCanSubmit } from '@mozhou/contracts'

const purposeLabels: Record<CreativeContextPurpose, string> = {
  startup: '开书方案',
  expansion: '整书展开',
  field: '蓝图局部调整',
  brief: '章节章纲',
  draft: '完整章节候选',
  candidate_review: '候选审校',
  canon_reconciliation: '正式事实核对',
  preference: '作者偏好提炼',
}

const blockerLabels: Record<string, string> = {
  writing_pattern_profile_required: '缺少已启用的写作模式，请先完成写作配方。',
  writing_pattern_profile_over_limit: '已启用的写作模式超过安全预算，请调整配方后重新预检。',
  writing_pattern_profile_stale: '写作模式已变化，请重新生成本次预检。',
  topic_not_confirmed: '选题尚未确认，请先确认选题。',
  topic_changed: '选题已变化，请刷新并重新预检。',
  blueprint_stale: '全书计划已过期，请先完成安全更新。',
  plan_stale: '创作计划已过期，请先完成安全更新。',
  context_overflow: '必要上下文超出预算，请提高预算后重新预检。',
  required_context_over_budget: '必要上下文超出预算，请提高预算后重新预检。',
  legacy_dependency_snapshot: '这是旧版上下文快照，请重新预检后再提交。',
}

function contextBlockerLabel(reason: string): string {
  return blockerLabels[reason] ?? `上下文尚未就绪：${reason.replaceAll('_', ' ')}`
}

export function CreativeContextPreflight({ packet }: { packet: ContextPacket }) {
  const usagePercent = Math.min(100, Math.round(packet.used_tokens / packet.token_budget * 100))
  const canSubmit = creativeContextCanSubmit(packet)

  return (
    <section className="creative-context-preflight" aria-labelledby="creative-context-preflight-title">
      <header>
        <div>
          <small>CREATIVE CONTEXT</small>
          <h5 id="creative-context-preflight-title">本次创作上下文</h5>
        </div>
        <strong data-ready={canSubmit}>{canSubmit ? '上下文已就绪' : '暂不能提交'}</strong>
      </header>
      <div className="creative-context-summary">
        <div><span>本次用途</span><strong>{purposeLabels[packet.purpose]}</strong></div>
        <div>
          <span>写作模式</span>
          <strong>{packet.profile_fingerprint_sha256 ? '写作模式已固定' : '本次未启用写作模式'}</strong>
          <small>{packet.dependency_snapshot.writing_pattern_source_availability === 'source_verified'
            ? '抽象规则可回到本地来源核验'
            : packet.dependency_snapshot.writing_pattern_source_availability === 'abstract_only'
              ? '仅使用已保存的抽象规则'
              : '本次上下文未引用写作配方'}</small>
        </div>
        <div><span>上下文预算</span><strong>{packet.used_tokens.toLocaleString('zh-CN')} / {packet.token_budget.toLocaleString('zh-CN')} Token</strong></div>
      </div>
      <div className="creative-context-budget" aria-label={`上下文预算使用 ${usagePercent}%`}>
        <i style={{ width: `${usagePercent}%` }} />
      </div>
      {packet.overflow_tokens > 0 ? (
        <p className="creative-context-overflow" role="status">
          必要信息超出预算 {packet.overflow_tokens.toLocaleString('zh-CN')} Token；系统没有静默丢弃。
        </p>
      ) : null}
      {packet.blocking_reasons.length > 0 ? (
        <ul className="creative-context-blockers" aria-label="提交阻断原因">
          {packet.blocking_reasons.map((reason) => <li key={reason}>{contextBlockerLabel(reason)}</li>)}
        </ul>
      ) : (
        <p className="creative-context-ready">选题、写作模式与计划版本均已绑定；提交后仍只生成候选。</p>
      )}
    </section>
  )
}
