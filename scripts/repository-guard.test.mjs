import assert from 'node:assert/strict'
import test from 'node:test'

import { findSecretKinds, isForbiddenTrackedPath } from './repository-guard.mjs'

test('rejects user data and generated artifact paths', () => {
  assert.equal(isForbiddenTrackedPath('.mozhou-data/mozhou.db'), true)
  assert.equal(isForbiddenTrackedPath('artifacts/desktop/mozhou.dmg'), true)
  assert.equal(isForbiddenTrackedPath('apps/desktop/src-tauri/binaries/mozhou-api'), true)
  assert.equal(isForbiddenTrackedPath('draft.db'), true)
})

test('allows only documented environment templates', () => {
  assert.equal(isForbiddenTrackedPath('.env.example'), false)
  assert.equal(isForbiddenTrackedPath('apps/web/.env.tauri'), false)
  assert.equal(isForbiddenTrackedPath('.env.local'), true)
  assert.equal(isForbiddenTrackedPath('apps/web/.env.production'), true)
})

test('detects production-like secrets but permits the explicit test fixture', () => {
  assert.deepEqual(findSecretKinds('sk-test-abcdefghijklmnopqrstuvwxyz'), [])
  assert.deepEqual(findSecretKinds('sk-' + 'abcdefghijklmnopqrstuvwxyz123456'), ['OpenAI API Key'])
  assert.deepEqual(findSecretKinds('-----BEGIN ' + 'PRIVATE KEY-----'), ['private key'])
})
