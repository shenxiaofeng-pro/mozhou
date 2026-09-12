import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  ChapterProductionWorkbench,
  type ChapterProductionCandidate,
  type ChapterProductionPreflight,
} from './ChapterProductionWorkbench'

const readyPreflight: ChapterProductionPreflight = {
  state: 'ready',
  checks: [
    { id: 'promise', label: '读者承诺', state: 'passed', detail: '本章兑现一次公开反击。' },
    { id: 'hook', label: '开篇钩子', state: 'passed', detail: '账本在众人面前被打开。' },
    { id: 'change', label: '状态变化', state: 'passed', detail: '主角夺回议价权。' },
    { id: 'emotion', label: '情绪兑现', state: 'warning', detail: '可再加强父子和解前的阻力。' },
    { id: 'cliffhanger', label: '章末悬念', state: 'passed', detail: '竞争对手拿出第二份合同。' },
  ],
  blockingReasons: [],
}

const candidates: ChapterProductionCandidate[] = [
  {
    id: 'candidate-a',
    label: '正面交锋版',
    revision: 2,
    basedOnChapterRevision: 7,
    text: '雨声压住了院里的议论。林川翻开账本，把第一笔坏账推到桌前。',
    state: 'candidate',
    reviewItems: [
      { dimension: '钩子', state: 'passed', summary: '冲突在首段发生。' },
      { dimension: '人物', state: 'warning', summary: '父亲的迟疑还可更具体。' },
    ],
  },
  {
    id: 'candidate-b',
    label: '暗线揭示版',
    revision: 1,
    basedOnChapterRevision: 7,
    text: '仓门刚落锁，林川便发现账页少了一张。真正的对手还没有现身。',
    state: 'candidate',
    reviewItems: [{ dimension: '悬念', state: 'passed', summary: '章尾问题清楚。' }],
  },
  {
    id: 'candidate-c',
    label: '关系推进版',
    revision: 1,
    basedOnChapterRevision: 7,
    text: '父亲没有接过账本，只把仓库钥匙放在林川掌心。',
    state: 'candidate',
    reviewItems: [{ dimension: '情绪', state: 'passed', summary: '关系变化可感知。' }],
  },
]

const defaultProps = {
  chapterTitle: '第十二章 旧账新局',
  chapterRevision: 7,
  officialText: '这是作者当前正文，不会因生成候选而改变。',
  outline: {
    readerPromise: '主角第一次公开拿回主动权。',
    openingHook: '失踪的账页突然出现。',
    stateChange: '主角获得仓库控制权。',
    emotionalPayoff: '父亲开始认可主角。',
    endingCliffhanger: '竞争对手拿出第二份合同。',
  },
  preflight: readyPreflight,
  candidates,
  onGenerate: vi.fn(),
  onOutlineChange: vi.fn(),
  onSelectionInstruction: vi.fn(),
  onLockChange: vi.fn(),
  onUndo: vi.fn(),
  onMergeCandidates: vi.fn(),
  onAdopt: vi.fn(),
  onReject: vi.fn(),
  onRefreshConflict: vi.fn(),
}

afterEach(() => cleanup())

describe('ChapterProductionWorkbench', () => {
  it('has one primary generation entry and keeps every result visibly isolated as a candidate', async () => {
    const onGenerate = vi.fn()
    const { rerender } = render(
      <ChapterProductionWorkbench {...defaultProps} candidates={[]} onGenerate={onGenerate} />,
    )

    const generateButtons = screen.getAllByRole('button', { name: '生成本章候选' })
    expect(generateButtons).toHaveLength(1)
    await userEvent.click(generateButtons[0])
    expect(onGenerate).toHaveBeenCalledTimes(1)
    expect(screen.getByText('生成结果只进入候选区，不会写入正式正文。')).toBeInTheDocument()

    rerender(<ChapterProductionWorkbench {...defaultProps} onGenerate={onGenerate} />)

    await waitFor(() => expect(screen.getByRole('heading', { name: '3 份正文候选待审校' })).toHaveFocus())
    expect(screen.getAllByText('候选 · 未写入正文')).toHaveLength(3)
    expect(screen.getByDisplayValue(defaultProps.officialText)).toHaveAttribute('readonly')
  })

  it('blocks generation before required writing checks pass and does not emit a generation event', async () => {
    const onGenerate = vi.fn()
    render(
      <ChapterProductionWorkbench
        {...defaultProps}
        candidates={[]}
        onGenerate={onGenerate}
        preflight={{
          state: 'blocked',
          checks: [
            { id: 'hook', label: '开篇钩子', state: 'blocked', detail: '还没有明确开篇冲突。' },
          ],
          blockingReasons: ['先补全开篇钩子', '先明确章末悬念'],
        }}
      />,
    )

    const button = screen.getByRole('button', { name: '生成本章候选' })
    expect(button).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('写前检查未通过，不会调用正文模型')
    expect(screen.getByText('先补全开篇钩子')).toBeInTheDocument()
    await userEvent.click(button)
    expect(onGenerate).not.toHaveBeenCalled()
  })

  it('emits selection, lock, undo and multi-candidate merge events without touching official text', async () => {
    const user = userEvent.setup()
    const onSelectionInstruction = vi.fn().mockResolvedValue({ replacementText: '那本旧账册' })
    const onLockChange = vi.fn()
    const onUndo = vi.fn()
    const onMergeCandidates = vi.fn()
    render(
      <ChapterProductionWorkbench
        {...defaultProps}
        onSelectionInstruction={onSelectionInstruction}
        onLockChange={onLockChange}
        onUndo={onUndo}
        onMergeCandidates={onMergeCandidates}
      />,
    )

    const editor = screen.getByRole('textbox', { name: '编辑正面交锋版候选副本' }) as HTMLTextAreaElement
    editor.focus()
    editor.setSelectionRange(0, 2)
    fireEvent.select(editor)
    await user.click(screen.getByRole('button', { name: '锁定当前选区' }))
    expect(onLockChange).toHaveBeenLastCalledWith(expect.objectContaining({
      candidateId: 'candidate-a',
      lockedRanges: [{ start: 0, end: 2 }],
    }))
    expect(screen.getByText('已锁定 2 字')).toBeInTheDocument()

    const start = candidates[0].text.indexOf('账本')
    editor.focus()
    editor.setSelectionRange(start, start + 2)
    fireEvent.select(editor)
    await user.type(screen.getByRole('textbox', { name: '选区局部指令' }), '让道具更有年代感')
    await user.click(screen.getByRole('button', { name: '生成选区替换候选' }))

    expect(onSelectionInstruction).toHaveBeenCalledWith(expect.objectContaining({
      candidateId: 'candidate-a',
      selection: expect.objectContaining({ start, end: start + 2, selectedText: '账本' }),
      instruction: '让道具更有年代感',
    }))
    expect(editor).toHaveValue(candidates[0].text.replace('账本', '那本旧账册'))

    await user.click(screen.getByRole('button', { name: '撤销上一步候选修改' }))
    expect(editor).toHaveValue(candidates[0].text)
    expect(onUndo).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: '撤销上一步候选修改' }))
    expect(onUndo).toHaveBeenCalledWith(expect.objectContaining({ candidateId: 'candidate-a' }))

    await user.click(screen.getByRole('checkbox', { name: '选择正面交锋版参与合并' }))
    await user.click(screen.getByRole('checkbox', { name: '选择暗线揭示版参与合并' }))
    await user.click(screen.getByRole('button', { name: '合并所选候选' }))
    expect(onMergeCandidates).toHaveBeenCalledWith(expect.objectContaining({
      candidateIds: ['candidate-a', 'candidate-b'],
      baseCandidateId: 'candidate-a',
    }))
    expect(screen.getByDisplayValue(defaultProps.officialText)).toHaveValue(defaultProps.officialText)
  })

  it('keeps the author-edited copy when an old-candidate conflict arrives and blocks adoption', async () => {
    const user = userEvent.setup()
    const onAdopt = vi.fn()
    const onRefreshConflict = vi.fn()
    const { rerender } = render(
      <ChapterProductionWorkbench
        {...defaultProps}
        onAdopt={onAdopt}
        onRefreshConflict={onRefreshConflict}
      />,
    )
    const editor = screen.getByRole('textbox', { name: '编辑正面交锋版候选副本' })
    await user.clear(editor)
    await user.type(editor, '作者重新写过的开场仍须保留。')

    rerender(
      <ChapterProductionWorkbench
        {...defaultProps}
        conflict={{
          candidateId: 'candidate-a',
          latestChapterRevision: 8,
          message: '正式正文已在其他位置更新。',
        }}
        onAdopt={onAdopt}
        onRefreshConflict={onRefreshConflict}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('候选基于旧版本，作者编辑已保留')
    expect(editor).toHaveValue('作者重新写过的开场仍须保留。')
    expect(screen.getByRole('button', { name: '确认采用这份候选' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '刷新正文并重新检查' }))
    expect(onRefreshConflict).toHaveBeenCalledWith(expect.objectContaining({
      candidateId: 'candidate-a',
      authorText: '作者重新写过的开场仍须保留。',
    }))
    expect(onAdopt).not.toHaveBeenCalled()
  })

  it('exposes candidate review, rejection and explicit adoption as keyboard-reachable actions', async () => {
    const user = userEvent.setup()
    const onAdopt = vi.fn()
    const onReject = vi.fn()
    render(<ChapterProductionWorkbench {...defaultProps} onAdopt={onAdopt} onReject={onReject} />)

    const candidateCard = screen.getByRole('article', { name: '正面交锋版候选' })
    expect(within(candidateCard).getByText('七维审校')).toBeInTheDocument()
    expect(within(candidateCard).getByText('父亲的迟疑还可更具体。')).toBeInTheDocument()

    await user.tab()
    expect(document.activeElement).not.toBe(document.body)
    await user.click(screen.getByRole('button', { name: '确认采用这份候选' }))
    expect(onAdopt).toHaveBeenCalledWith(expect.objectContaining({
      candidateId: 'candidate-a',
      candidateRevision: 2,
      expectedChapterRevision: 7,
      authorText: candidates[0].text,
    }))

    await user.type(screen.getByRole('textbox', { name: '拒绝原因' }), '冲突出现得太晚')
    await user.click(screen.getByRole('button', { name: '拒绝此候选' }))
    expect(onReject).toHaveBeenCalledWith({ candidateId: 'candidate-a', reason: '冲突出现得太晚' })
  })
})
