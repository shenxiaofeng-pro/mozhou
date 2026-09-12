import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AuthorUtilityDrawer } from './AuthorUtilityDrawer'

afterEach(cleanup)

function renderDrawer(onClose = vi.fn()) {
  return {
    onClose,
    ...render(
      <AuthorUtilityDrawer
        onClose={onClose}
        onOpenSerial={() => undefined}
        onOpenAuthorTools={() => undefined}
        onOpenWritingPatterns={() => undefined}
        onOpenResearch={() => undefined}
        onOpenTasks={() => undefined}
        onOpenComicDrama={() => undefined}
        onOpenReferences={() => undefined}
      />,
    ),
  }
}

describe('AuthorUtilityDrawer', () => {
  it('gives every auxiliary destination a clear accessible name', () => {
    renderDrawer()
    expect(screen.getByRole('dialog', { name: '辅助工具' })).toBeVisible()
    expect(screen.getByRole('button', { name: '打开作者工具台' })).toBeVisible()
    expect(screen.getByRole('button', { name: '打开拆书库' })).toBeVisible()
  })

  it('traps keyboard focus and closes on Escape', () => {
    const { onClose } = renderDrawer()
    const close = screen.getByRole('button', { name: '关闭辅助工具' })
    const last = screen.getByRole('button', { name: '打开拆书库' })
    expect(close).toHaveFocus()

    last.focus()
    fireEvent.keyDown(window, { key: 'Tab' })
    expect(close).toHaveFocus()

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
  })
})
