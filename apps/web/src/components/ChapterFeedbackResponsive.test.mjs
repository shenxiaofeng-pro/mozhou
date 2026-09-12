// @vitest-environment node
import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const styles = readFileSync(new globalThis.URL('../styles.css', import.meta.url), 'utf8')

describe('chapter feedback responsive layout', () => {
  it('keeps long evidence and candidate fields inside shrinkable tracks', () => {
    expect(styles).toMatch(/\.chapter-feedback-panel\s*{[^}]*min-width:\s*0/s)
    expect(styles).toMatch(/\.chapter-feedback-candidate\s*{[^}]*min-width:\s*0/s)
    expect(styles).toMatch(/\.chapter-feedback-evidence p\s*{[^}]*overflow-wrap:\s*anywhere[^}]*white-space:\s*pre-wrap/s)
    expect(styles).toMatch(/\.chapter-feedback-editor,[\s\S]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/s)
  })

  it('stacks decisions, editors, status headings and submit actions at 760px', () => {
    const guardStart = styles.indexOf('/* M35 cascade guard')
    const start = styles.lastIndexOf('@media (max-width: 760px)', guardStart)
    expect(start).toBeGreaterThanOrEqual(0)
    const mobile = styles.slice(start, guardStart)

    for (const selector of [
      '.chapter-feedback-section-heading',
      '.chapter-feedback-candidate > header',
      '.chapter-feedback-choice',
      '.chapter-feedback-editor',
      '.chapter-feedback-fields',
      '.chapter-feedback-submit',
    ]) {
      expect(mobile).toContain(selector)
    }
    expect(mobile).toMatch(/\.chapter-feedback-candidate-meta,[\s\S]*\.chapter-feedback-submit\s*{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s)
  })
})
