// @vitest-environment node
import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const styles = readFileSync(new globalThis.URL('../styles.css', import.meta.url), 'utf8')
const source = styles.slice(styles.indexOf('/* M35 — continuous author route'))

describe('continuous author workflow responsive layout', () => {
  it('reserves a bounded workflow rail at desktop width and preserves visible manuscript focus', () => {
    expect(source).toMatch(/\.workspace-shell\s*{[^}]*grid-template-columns:\s*14rem minmax\(30rem,\s*1fr\) 21rem/s)
    expect(source).toMatch(/\.author-workflow-surface\s*{[^}]*min-width:\s*0[^}]*overflow:\s*auto/s)
    expect(source).toMatch(/\.manuscript:focus-visible\s*{[^}]*outline:\s*3px solid var\(--rust-light\)/s)
  })

  it('moves the route above the manuscript at 1050px and uses legible short labels at 760px', () => {
    const legacyBoundary = source.indexOf('/* M33 · One continuous')
    const tabletStart = source.indexOf('@media (max-width: 1050px)')
    const mobileStart = source.indexOf('@media (max-width: 760px)', tabletStart)
    const tablet = source.slice(tabletStart, mobileStart)
    const mobile = source.slice(mobileStart, legacyBoundary)
    const cascadeGuard = source.slice(source.indexOf('/* M35 cascade guard'))

    expect(tablet).toMatch(/\.author-workflow-surface\s*{[^}]*grid-column:\s*1 \/ -1[^}]*grid-row:\s*2/s)
    expect(tablet).toMatch(/\.author-workflow-rail nav ol\s*{[^}]*repeat\(4,\s*minmax\(0,\s*1fr\)\)/s)
    expect(mobile).toMatch(/\.author-stage-short\s*{[^}]*display:\s*inline/s)
    expect(mobile).toMatch(/\.author-workflow-rail nav strong,[\s\S]*font-size:\s*0\.75rem/s)
    expect(cascadeGuard).toMatch(/@media \(max-width: 760px\)[\s\S]*\.workspace-shell\s*{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s)
    expect(cascadeGuard).toMatch(/@media \(max-width: 760px\)[\s\S]*\.workspace-shell\s*{[^}]*grid-template-rows:\s*4rem auto minmax\(0,\s*1fr\)/s)
    expect(cascadeGuard).toMatch(/@media \(max-width: 760px\)[\s\S]*\.editor-panel\s*{[^}]*grid-column:\s*1/s)
    expect(cascadeGuard).toMatch(/\.director-drawer-trigger strong\s*{[^}]*writing-mode:\s*horizontal-tb/s)
  })
})
