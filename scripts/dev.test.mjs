import assert from 'node:assert/strict'
import test from 'node:test'

import { createDevCommands } from './dev.mjs'

test('uses executable files instead of a shell pipeline on macOS', () => {
  const [web, api] = createDevCommands('darwin')

  assert.equal(web.executable, 'pnpm')
  assert.deepEqual(web.args, ['--filter', '@mozhou/web', 'dev'])
  assert.equal(api.executable, 'uv')
  assert.equal(api.args.at(-1), '8765')
  assert.ok(api.args.includes('--reload'))
  assert.ok(api.args.includes('app.runtime:create_runtime_app'))
  assert.ok(api.args.includes('--factory'))
  assert.deepEqual(api.env, { MOZHOU_ALLOW_INSECURE_DEV_API: '1' })
})

test('uses Windows command shims without changing arguments', () => {
  const [web, api] = createDevCommands('win32')

  assert.equal(web.executable, 'pnpm.cmd')
  assert.equal(api.executable, 'uv.exe')
  assert.deepEqual(api.env, { MOZHOU_ALLOW_INSECURE_DEV_API: '1' })
  assert.ok(web.args.every((value) => !value.includes('&')))
  assert.ok(api.args.every((value) => !value.includes('&')))
})
