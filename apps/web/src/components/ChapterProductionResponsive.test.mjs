// @vitest-environment node
import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const styles = readFileSync(new globalThis.URL('../styles.css', import.meta.url), 'utf8')

function chapterProductionStyles() {
  const start = styles.indexOf('.chapter-production-workbench')
  expect(start).toBeGreaterThanOrEqual(0)
  return styles.slice(start)
}

function mediaBlock(source, maxWidth) {
  const start = source.indexOf(`@media (max-width: ${maxWidth}px)`)
  expect(start).toBeGreaterThanOrEqual(0)
  const next = source.indexOf('@media ', start + 1)
  return source.slice(start, next === -1 ? undefined : next)
}

describe('chapter production responsive layout', () => {
  it('keeps long candidates on shrinkable tracks without page-wide overflow', () => {
    const source = chapterProductionStyles()

    expect(source).toMatch(/\.chapter-production-workbench\s*{[^}]*min-width:\s*0/s)
    expect(source).toMatch(/\.chapter-production-compare\s*{[^}]*grid-template-columns:\s*minmax\(0,[^)]+\)\s+minmax\(0,[^)]+\)/s)
    expect(source).toMatch(/\.chapter-production-copy\s*{[^}]*max-width:\s*100%/s)
    expect(source).toContain('overflow-wrap: anywhere')
  })

  it('uses two candidate columns at 1040px and stacks comparison and actions at 760px', () => {
    const source = chapterProductionStyles()
    const tablet = mediaBlock(source, 1040)
    const mobile = mediaBlock(source, 760)

    expect(tablet).toMatch(/\.chapter-production-candidate-grid\s*{[^}]*repeat\(2,\s*minmax\(0,\s*1fr\)\)/s)
    for (const selector of [
      '.chapter-production-summary',
      '.chapter-production-candidate-grid',
      '.chapter-production-compare',
      '.chapter-production-command-row',
      '.chapter-production-actions',
    ]) {
      expect(mobile).toContain(selector)
    }
    expect(mobile).toMatch(/\.chapter-production-summary,[\s\S]*\.chapter-production-actions\s*{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s)
  })
})
