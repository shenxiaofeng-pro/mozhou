// @vitest-environment node
import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const styles = readFileSync(new globalThis.URL('../styles.css', import.meta.url), 'utf8')

function mediaBlock(maxWidth) {
  const sectionStart = styles.indexOf('.creative-context-preflight')
  expect(sectionStart).toBeGreaterThanOrEqual(0)
  const start = styles.indexOf(`@media (max-width: ${maxWidth}px)`, sectionStart)
  expect(start).toBeGreaterThanOrEqual(0)
  const next = styles.indexOf('@media ', start + 1)
  return styles.slice(start, next === -1 ? undefined : next)
}

describe('creative context and plan rebase responsive layout', () => {
  it('keeps tablet target cards on shrinkable tracks at 1040px', () => {
    const tablet = mediaBlock(1040)

    expect(styles).toMatch(/\.plan-rebase-workbench\s*{[^}]*min-width:\s*0/s)
    expect(styles).toMatch(/\.plan-rebase-fields\s*{[^}]*min-width:\s*0/s)
    expect(tablet).toMatch(/\.plan-rebase-targets\s*{[^}]*repeat\(2,\s*minmax\(0,\s*1fr\)\)/s)
  })

  it('stacks summaries, editors and confirmation actions at 760px', () => {
    const mobile = mediaBlock(760)

    for (const selector of [
      '.creative-context-summary',
      '.plan-rebase-impact',
      '.plan-rebase-targets',
      '.plan-rebase-fields',
      '.plan-rebase-candidate > footer',
    ]) {
      expect(mobile).toContain(selector)
    }
    expect(mobile).toMatch(/\.creative-context-summary,[\s\S]*\.plan-rebase-candidate > footer\s*{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s)
    expect(styles).toContain('overflow-wrap: anywhere')
  })
})
