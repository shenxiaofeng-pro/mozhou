// @vitest-environment node
import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const styles = readFileSync(new globalThis.URL('../styles.css', import.meta.url), 'utf8')

function mediaBlock(maxWidth) {
  const sectionStart = styles.indexOf('.craft-pattern-workbench')
  expect(sectionStart).toBeGreaterThanOrEqual(0)
  const start = styles.indexOf(`@media (max-width: ${maxWidth}px)`, sectionStart)
  expect(start).toBeGreaterThanOrEqual(0)

  const next = styles.indexOf('@media ', start + 1)
  return styles.slice(start, next === -1 ? undefined : next)
}

describe('craft pattern responsive layout', () => {
  it('collapses the workbench before 1040px and keeps every grid track shrinkable', () => {
    const desktopToTablet = mediaBlock(1180)
    const tablet = mediaBlock(1040)

    expect(styles).toContain('grid-template-columns: minmax(0, 1.45fr) minmax(19rem, 0.72fr)')
    expect(styles).toContain('grid-template-columns: repeat(3, minmax(0, 1fr))')
    expect(desktopToTablet).toMatch(/\.craft-pattern-layout\s*{[^}]*grid-template-columns:\s*1fr/s)
    expect(desktopToTablet).toMatch(/\.global-pattern-list\s*{[^}]*repeat\(2,\s*minmax\(0,\s*1fr\)\)/s)
    expect(tablet).toMatch(/\.craft-asset-route\s*{[^}]*grid-template-columns:\s*1fr 1fr/s)
    expect(tablet).toMatch(/\.global-pattern-toolbar\s*{[^}]*grid-template-columns:\s*1fr 1fr/s)
  })

  it('uses one-column routes, actions, catalogs and filters at 760px', () => {
    const mobile = mediaBlock(760)

    for (const selector of [
      '.craft-asset-route',
      '.craft-operation-choices',
      '.craft-asset-list',
      '.global-pattern-list',
      '.global-pattern-toolbar',
    ]) {
      expect(mobile).toContain(selector)
    }
    expect(mobile).toMatch(/\.craft-asset-route,[\s\S]*\.global-pattern-toolbar\s*{[^}]*grid-template-columns:\s*1fr/s)
    expect(mobile).toMatch(/\.craft-asset-actions\s*{[^}]*flex-direction:\s*column/s)
    expect(styles).toMatch(/\.craft-pattern-workbench\s*{[^}]*min-width:\s*0/s)
    expect(styles).toMatch(/\.craft-asset-card\s*{[^}]*min-width:\s*0/s)
    expect(styles).toContain('overflow-wrap: anywhere')
  })
})
