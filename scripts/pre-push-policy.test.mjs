import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const scriptPath = fileURLToPath(new URL('./pre-push-policy.mjs', import.meta.url))

function runPolicy(input) {
  return spawnSync(process.execPath, [scriptPath], {
    encoding: 'utf8',
    input,
  })
}

test('allows feature branches and tags', () => {
  const result = runPolicy(
    'refs/heads/codex/m1 abc refs/heads/codex/m1 def\nrefs/tags/v1 abc refs/tags/v1 def\n',
  )

  assert.equal(result.status, 0)
  assert.equal(result.stderr, '')
})

test('rejects direct updates to main', () => {
  const result = runPolicy('refs/heads/main abc refs/heads/main def\n')

  assert.equal(result.status, 1)
  assert.match(result.stderr, /拒绝直接推送 main/u)
})

test('rejects deletion of main while allowing other updates in the same push', () => {
  const result = runPolicy(
    '(delete) 000 refs/heads/main def\nrefs/heads/codex/m1 abc refs/heads/codex/m1 def\n',
  )

  assert.equal(result.status, 1)
})
