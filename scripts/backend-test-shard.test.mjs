import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import {
  BACKEND_TEST_SHARD_DEFINITIONS,
  listBackendTestFiles,
  parseCollectedBackendTestWeights,
  selectBackendTestShard,
  validateCollectedBackendTestWeights,
} from './backend-test-shard.mjs'

test('discovers sorted Python test files and ignores non-test files', () => {
  const root = mkdtempSync(join(tmpdir(), 'mozhou-backend-shards-'))
  try {
    const testsDirectory = join(root, 'services', 'api', 'tests')
    mkdirSync(testsDirectory, { recursive: true })
    for (const name of ['test_z.py', 'helper.py', 'test_a.py', 'test_notes.txt']) {
      writeFileSync(join(testsDirectory, name), '')
    }
    const nestedDirectory = join(testsDirectory, 'unit')
    mkdirSync(nestedDirectory)
    writeFileSync(join(nestedDirectory, 'test_nested.py'), '')
    writeFileSync(join(nestedDirectory, 'example_test.py'), '')
    writeFileSync(join(nestedDirectory, 'fixture.py'), '')

    assert.deepEqual(listBackendTestFiles(root), [
      join('services', 'api', 'tests', 'test_a.py'),
      join('services', 'api', 'tests', 'test_z.py'),
      join('services', 'api', 'tests', 'unit', 'example_test.py'),
      join('services', 'api', 'tests', 'unit', 'test_nested.py'),
    ])
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})

test('eight balanced shards cover every repository test file exactly once', () => {
  const files = listBackendTestFiles()
  const shards = Array.from({ length: 8 }, (_value, index) =>
    selectBackendTestShard(files, index, 8),
  )
  const flattened = shards.flat()
  const nodeidWeights = BACKEND_TEST_SHARD_DEFINITIONS.map((shard) =>
    shard.reduce((total, [_name, weight]) => total + weight, 0),
  )

  assert.equal(new Set(flattened).size, files.length)
  assert.deepEqual(flattened.toSorted(), files.toSorted())
  assert.deepEqual(nodeidWeights, [59, 58, 58, 59, 59, 58, 57, 57])
  assert.equal(nodeidWeights.reduce((total, weight) => total + weight, 0), 465)
})

test('rejects invalid indexes, counts, and incomplete file maps', () => {
  const files = listBackendTestFiles()
  assert.throws(() => selectBackendTestShard(files, -1, 8))
  assert.throws(() => selectBackendTestShard(files, 8, 8))
  assert.throws(() => selectBackendTestShard(files, 0, 0))
  assert.throws(() => selectBackendTestShard(files, 0, 4))
  assert.throws(() => selectBackendTestShard(files.slice(1), 0, 8))
  assert.throws(() => selectBackendTestShard([...files, 'test_new.py'], 0, 8))
  assert.throws(() =>
    selectBackendTestShard(
      [...files, 'services/api/tests/unit/test_nested.py'],
      0,
      8,
    ),
  )
})

test('parses pytest nodeids across platforms and rejects stale weights', () => {
  const parsed = parseCollectedBackendTestWeights(
    [
      'tests/test_ai.py::test_one',
      'tests/test_ai.py::test_two[param]',
      'services\\api\\tests\\test_api.py::test_three',
      '',
      '3 tests collected',
    ].join('\r\n'),
  )
  assert.deepEqual([...parsed], [
    ['test_ai.py', 2],
    ['test_api.py', 1],
  ])

  const files = listBackendTestFiles()
  const nodeids = BACKEND_TEST_SHARD_DEFINITIONS.flatMap((shard) =>
    shard.flatMap(([name, weight]) =>
      Array.from({ length: weight }, (_value, index) =>
        `tests/${name}::test_${index}`,
      ),
    ),
  ).join('\n')
  assert.equal(validateCollectedBackendTestWeights(files, nodeids), 465)
  assert.throws(() =>
    validateCollectedBackendTestWeights(
      files,
      nodeids.replace('tests/test_archive_api.py::test_0\n', ''),
    ),
  )
})
