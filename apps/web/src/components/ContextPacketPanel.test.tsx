import type { ContextPacket } from '@mozhou/contracts'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'

import { ContextPacketPanel } from './ContextPacketPanel'

const packet: ContextPacket = {
  id: '7e4dbbc5-af7d-40a5-a8ee-69322bc8b667',
  project_id: '05f14cb8-d0ed-4489-bc20-31c44c1efbba',
  chapter_id: '19c7daae-21f2-42f6-9520-daec63e4a726',
  chapter_revision: 3,
  task_type: 'chapter_draft',
  purpose: 'draft',
  subject: {
    kind: 'chapter',
    id: '19c7daae-21f2-42f6-9520-daec63e4a726',
    revision: 3,
    content_sha256: 'b'.repeat(64),
  },
  profile_fingerprint_sha256: null,
  dependency_snapshot: {
    schema_version: 1,
    topic: null,
    writing_pattern_profile: null,
    writing_pattern_source_availability: null,
    base_blueprint: null,
    subject_sha256: 'b'.repeat(64),
  },
  dependency_fingerprint_sha256: 'f'.repeat(64),
  blocking_reasons: [],
  compiler_version: 'rule-compiler-v1',
  token_budget: 8000,
  used_tokens: 6200,
  overflow_tokens: 0,
  packet_sha256: 'a'.repeat(64),
  source_fingerprint_sha256: 'b'.repeat(64),
  rendered_context: '{"items":[]}',
  items: [
    {
      id: 'hard:chapter',
      kind: 'current_chapter',
      tier: 'hard_constraint',
      label: '第 12 章章纲',
      content: '主角必须先救父亲，再争取纸厂订单。',
      token_estimate: 120,
      priority: 9980,
      required: true,
      included: true,
      directive: null,
      selection_reason: '当前章纲是直接约束',
      exclusion_reason: null,
      source_refs: [{
        kind: 'current_chapter',
        source_id: '19c7daae-21f2-42f6-9520-daec63e4a726',
        label: '第 12 章',
        chapter_id: '19c7daae-21f2-42f6-9520-daec63e4a726',
        chapter_number: 12,
        character_start: null,
        character_end: null,
        updated_at: '2026-08-10T00:00:00Z',
      }],
      conflict_notes: [],
      content_sha256: 'c'.repeat(64),
    },
    {
      id: 'fact:cash',
      kind: 'canonical_fact',
      tier: 'canon',
      label: '第 11 章正式事实',
      content: '纸厂账户只剩三万元现金。',
      token_estimate: 80,
      priority: 6011,
      required: false,
      included: true,
      directive: null,
      selection_reason: '按来源章节新近程度召回正式事实',
      exclusion_reason: null,
      source_refs: [{
        kind: 'fact',
        source_id: 'fact-cash',
        label: '第 11 章正式事实',
        chapter_id: 'chapter-11',
        chapter_number: 11,
        character_start: 220,
        character_end: 246,
        updated_at: '2026-08-10T00:00:00Z',
      }],
      conflict_notes: [],
      content_sha256: 'd'.repeat(64),
    },
    {
      id: 'future:invalid',
      kind: 'future_knowledge',
      tier: 'timeline',
      label: '未来知识 · 2008',
      content: '纸厂一定按原历史倒闭。',
      token_estimate: 70,
      priority: 6000,
      required: false,
      included: false,
      directive: null,
      selection_reason: '只召回仍标记为有效的未来知识',
      exclusion_reason: '未来知识状态为 candidate_invalid，禁止作为确定事实',
      source_refs: [{
        kind: 'future_knowledge',
        source_id: 'future-invalid',
        label: '2008 · 分歧前记忆',
        chapter_id: null,
        chapter_number: null,
        character_start: null,
        character_end: null,
        updated_at: '2026-08-10T00:00:00Z',
      }],
      conflict_notes: ['原始历史不代表分歧后仍会必然发生。'],
      content_sha256: 'e'.repeat(64),
    },
  ],
  tier_usage: [{
    tier: 'hard_constraint',
    budget_tokens: 0,
    used_tokens: 120,
    included_count: 1,
    excluded_count: 0,
  }],
  conflict_notes: ['原始历史只用于对照，不代表小说分歧后仍会必然发生。'],
  created_at: '2026-08-10T00:00:00Z',
}

afterEach(cleanup)

it('explains selected and excluded sources and protects hard constraints', async () => {
  const onSetDirective = vi.fn()
  const user = userEvent.setup()
  render(
    <ContextPacketPanel
      packet={packet}
      directives={[]}
      busy={false}
      onSetDirective={onSetDirective}
      onClearDirective={vi.fn()}
    />,
  )

  expect(screen.getByRole('heading', { name: '本次模型真正会读到什么' })).toBeVisible()
  expect(screen.getByText('硬约束 · 不可静默移除')).toBeVisible()
  expect(screen.getByText(/字符 220–246/)).toBeVisible()
  await user.click(screen.getByRole('button', { name: '本章固定' }))
  expect(onSetDirective).toHaveBeenCalledWith(packet.items[1], 'pin')

  await user.click(screen.getByText('未入选与原因 · 1'))
  expect(screen.getByText(/candidate_invalid/)).toBeVisible()
})

it('allows an author-pinned item to be cleared after it becomes required', async () => {
  const user = userEvent.setup()
  const onClearDirective = vi.fn()
  const pinnedItem = {
    ...packet.items[1],
    required: true,
    directive: 'pin' as const,
    selection_reason: '按来源章节新近程度召回正式事实；作者为本章临时固定',
  }
  render(
    <ContextPacketPanel
      packet={{ ...packet, items: [packet.items[0], pinnedItem, packet.items[2]] }}
      directives={[{
        id: 'directive-pin',
        chapter_id: packet.chapter_id!,
        project_id: packet.project_id,
        source_kind: 'fact',
        source_id: 'fact-cash',
        action: 'pin',
        revision: 0,
        created_at: '2026-08-10T00:00:00Z',
        updated_at: '2026-08-10T00:00:00Z',
      }]}
      busy={false}
      onSetDirective={vi.fn()}
      onClearDirective={onClearDirective}
    />,
  )

  await user.click(screen.getByRole('button', { name: '取消固定' }))
  expect(onClearDirective).toHaveBeenCalledWith(pinnedItem)
})

it('never renders reference titles, source text, evidence coordinates or identifiers', () => {
  const protectedItem = {
    ...packet.items[1],
    id: 'writing-pattern-profile:secret-id',
    kind: 'writing_pattern_profile' as const,
    label: '《秘密畅销书》模式',
    content: '这是绝不能出现在界面中的参考原句。',
    selection_reason: '来自《秘密畅销书》第十二章',
    source_refs: [{
      ...packet.items[1].source_refs[0],
      kind: 'writing_pattern_profile',
      source_id: 'secret-profile-id',
      label: '《秘密畅销书》证据',
      character_start: 100,
      character_end: 220,
    }],
    conflict_notes: ['秘密证据句'],
  }

  render(
    <ContextPacketPanel
      packet={{ ...packet, items: [protectedItem], conflict_notes: ['秘密作品冲突'] }}
      directives={[]}
      busy={false}
      onSetDirective={vi.fn()}
      onClearDirective={vi.fn()}
    />,
  )

  expect(screen.getByText('写作模式规则')).toBeVisible()
  expect(screen.getByText(/不会显示参考作品原文/)).toBeVisible()
  expect(screen.queryByText(/秘密畅销书/)).not.toBeInTheDocument()
  expect(screen.queryByText(/绝不能出现在/)).not.toBeInTheDocument()
  expect(screen.queryByText(/秘密证据句/)).not.toBeInTheDocument()
  expect(screen.queryByText(/秘密作品冲突/)).not.toBeInTheDocument()
  expect(screen.queryByText(/字符 100/)).not.toBeInTheDocument()
  expect(screen.queryByText(/secret-profile-id/)).not.toBeInTheDocument()
})
