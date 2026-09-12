import type { ContextPacket } from '@mozhou/contracts'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { CreativeContextPreflight } from './CreativeContextPreflight'

const packet: ContextPacket = {
  id: 'packet-1',
  project_id: 'project-1',
  chapter_id: 'chapter-1',
  chapter_revision: 3,
  task_type: 'chapter_draft',
  purpose: 'draft',
  subject: { kind: 'chapter', id: 'chapter-1', revision: 3, content_sha256: 'a'.repeat(64) },
  profile_fingerprint_sha256: 'b'.repeat(64),
  dependency_snapshot: {
    schema_version: 1,
    topic: { id: 'topic-1', revision: 2, content_sha256: 'c'.repeat(64) },
    writing_pattern_profile: { id: 'profile-1', revision: 0, content_sha256: 'b'.repeat(64) },
    writing_pattern_source_availability: 'source_verified',
    base_blueprint: { id: 'blueprint-1', revision: 4, content_sha256: 'd'.repeat(64) },
    subject_sha256: 'a'.repeat(64),
  },
  dependency_fingerprint_sha256: 'e'.repeat(64),
  blocking_reasons: [],
  compiler_version: 'creative-context-v2',
  token_budget: 8_000,
  used_tokens: 6_000,
  overflow_tokens: 0,
  packet_sha256: 'f'.repeat(64),
  source_fingerprint_sha256: '0'.repeat(64),
  rendered_context: '{}',
  items: [],
  tier_usage: [],
  conflict_notes: [],
  created_at: '2026-09-12T00:00:00Z',
}

afterEach(cleanup)

describe('CreativeContextPreflight', () => {
  it('explains purpose, budget, required profile and readiness without exposing ids', () => {
    render(<CreativeContextPreflight packet={packet} />)

    expect(screen.getByRole('heading', { name: '本次创作上下文' })).toBeVisible()
    expect(screen.getByText('完整章节候选')).toBeVisible()
    expect(screen.getByText('写作模式已固定')).toBeVisible()
    expect(screen.getByText(/6,000 \/ 8,000 Token/)).toBeVisible()
    expect(screen.getByText('上下文已就绪')).toBeVisible()
    expect(screen.queryByText('profile-1')).not.toBeInTheDocument()
    expect(screen.queryByText('chapter-1')).not.toBeInTheDocument()
    expect(screen.queryByText('eeeeeeee')).not.toBeInTheDocument()
  })

  it('turns compiler blockers and overflow into an explicit non-submittable state', () => {
    render(<CreativeContextPreflight packet={{
      ...packet,
      profile_fingerprint_sha256: null,
      dependency_snapshot: {
        ...packet.dependency_snapshot,
        writing_pattern_profile: null,
        writing_pattern_source_availability: null,
      },
      blocking_reasons: ['writing_pattern_profile_required', 'topic_changed'],
      overflow_tokens: 1_200,
    }} />)

    expect(screen.getByText('暂不能提交')).toBeVisible()
    expect(screen.getByText('缺少已启用的写作模式，请先完成写作配方。')).toBeVisible()
    expect(screen.getByText('选题已变化，请刷新并重新预检。')).toBeVisible()
    expect(screen.getByText(/超出预算 1,200 Token/)).toBeVisible()
  })
})
