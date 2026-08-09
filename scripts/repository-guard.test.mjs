import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import { findSecretKinds, inspectRepository, isForbiddenTrackedPath } from './repository-guard.mjs'

test('rejects user data and generated artifact paths', () => {
  assert.equal(isForbiddenTrackedPath('.mozhou-data/mozhou.db'), true)
  assert.equal(isForbiddenTrackedPath('artifacts/desktop/mozhou.dmg'), true)
  assert.equal(isForbiddenTrackedPath('apps/desktop/src-tauri/binaries/mozhou-api'), true)
  assert.equal(isForbiddenTrackedPath('draft.db'), true)
})

test('allows only documented environment templates', () => {
  assert.equal(isForbiddenTrackedPath('.env.example'), false)
  assert.equal(isForbiddenTrackedPath('apps/web/.env.tauri'), true)
  assert.equal(isForbiddenTrackedPath('.env.local'), true)
  assert.equal(isForbiddenTrackedPath('apps/web/.env.production'), true)
})

test('detects production-like secrets but permits the explicit test fixture', () => {
  assert.deepEqual(findSecretKinds('sk-test-abcdefghijklmnopqrstuvwxyz'), [])
  assert.deepEqual(findSecretKinds('sk-' + 'abcdefghijklmnopqrstuvwxyz123456'), ['OpenAI API Key'])
  assert.deepEqual(findSecretKinds('-----BEGIN ' + 'PRIVATE KEY-----'), ['private key'])
})

test('ignores an indexed file that is being deleted from the working tree', () => {
  const root = mkdtempSync(join(tmpdir(), 'mozhou-repository-guard-'))
  try {
    execFileSync('git', ['init', '--quiet'], { cwd: root })
    mkdirSync(join(root, 'docs'))
    const deletedPath = join(root, 'docs', 'obsolete.md')
    writeFileSync(deletedPath, 'obsolete')
    execFileSync('git', ['add', 'docs/obsolete.md'], { cwd: root })
    rmSync(deletedPath)

    assert.deepEqual(inspectRepository(root), [])
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})
