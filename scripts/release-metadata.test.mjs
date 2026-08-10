import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'

import {
  blockedLicenses,
  checksumRows,
  mergeSbomComponents,
  noticeText,
} from './release-metadata.mjs'

test('merges release components without leaking installation paths', () => {
  const components = mergeSbomComponents(
    [{
      type: 'library',
      name: 'react',
      version: '19.2.8',
      purl: 'pkg:npm/react@19.2.8',
      licenses: [{ expression: 'MIT' }],
      properties: [{ name: 'mozhou:ecosystem', value: 'npm' }],
    }],
    [{
      type: 'library',
      name: 'fastapi',
      version: '0.141.1',
      purl: 'pkg:pypi/fastapi@0.141.1',
      properties: [{ name: 'mozhou:ecosystem', value: 'pypi' }],
    }],
  )

  assert.equal(components.length, 2)
  const notice = noticeText(components)
  assert.match(notice, /react@19\.2\.8 — MIT/)
  assert.doesNotMatch(notice, /node_modules|Users|\\Users/)
})

test('blocks unreviewed strong copyleft licenses from a release', () => {
  assert.deepEqual(blockedLicenses([{
    name: 'unexpected-server',
    version: '1.0.0',
    licenses: [{ expression: 'AGPL-3.0-only' }],
  }]), ['unexpected-server@1.0.0: AGPL-3.0-only'])
  assert.deepEqual(blockedLicenses([{
    name: 'allowed-library',
    version: '1.0.0',
    licenses: [{ expression: 'MIT OR Apache-2.0' }],
  }]), [])
})

test('creates stable sha256 rows for release artifacts', () => {
  const directory = mkdtempSync(join(tmpdir(), 'mozhou-release-test-'))
  writeFileSync(join(directory, 'mozhou.dmg'), 'signed artifact fixture')

  const rows = checksumRows(directory)

  assert.deepEqual(rows, [{
    file: 'mozhou.dmg',
    bytes: 23,
    sha256: '10f1b24216e3ade5790039b782429697acc00a1910034abbe0ceae2d8dae00f3',
  }])
})
