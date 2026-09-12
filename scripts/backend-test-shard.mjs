import { execFileSync } from 'node:child_process'
import { readdirSync } from 'node:fs'
import process from 'node:process'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')

// Keep the Windows runners independent and balanced. The number beside each
// file is its collected pytest nodeid count. When a new test file appears the
// exact-cover validation below fails closed until this map is deliberately
// rebalanced, so a file can never silently fall outside the required check.
export const BACKEND_TEST_SHARD_DEFINITIONS = [
  [
    ['test_archive_api.py', 27],
    ['test_provider_adapters.py', 11],
    ['test_canon_reconciliation_api.py', 8],
    ['test_context_packet_integrity.py', 6],
    ['test_author_productivity.py', 4],
    ['test_research.py', 3],
  ],
  [
    ['test_creative_context.py', 23],
    ['test_jobs.py', 11],
    ['test_canon_reconciliation.py', 8],
    ['test_sandbox_ai.py', 7],
    ['test_topic_decisions.py', 5],
    ['test_context_golden.py', 4],
  ],
  [
    ['test_api.py', 21],
    ['test_context_compiler.py', 11],
    ['test_safe_import.py', 10],
    ['test_config.py', 6],
    ['test_originality_guard.py', 6],
    ['test_four_genre_quality_golden.py', 4],
  ],
  [
    ['test_chapter_jobs.py', 20],
    ['test_sidecar.py', 12],
    ['test_beta.py', 9],
    ['test_diagnostics.py', 8],
    ['test_writing_pattern_compiler.py', 5],
    ['test_context_api.py', 3],
    ['test_m36_security_gate.py', 2],
  ],
  [
    ['test_craft_patterns.py', 20],
    ['test_writing_patterns.py', 12],
    ['test_pattern_adaptation.py', 9],
    ['test_ai.py', 7],
    ['test_pattern_adaptation_originality.py', 6],
    ['test_context_v29.py', 3],
    ['test_serial_workspace.py', 2],
  ],
  [
    ['test_database.py', 19],
    ['test_sandbox.py', 12],
    ['test_generation.py', 10],
    ['test_provider_profiles.py', 7],
    ['test_review.py', 6],
    ['test_document_formats.py', 3],
    ['test_canon_context.py', 1],
  ],
  [
    ['test_reference_lab.py', 17],
    ['test_author_navigation.py', 12],
    ['test_reference_jobs.py', 11],
    ['test_chapter_production.py', 8],
    ['test_scene_originality.py', 6],
    ['test_manuscript_directory.py', 3],
  ],
  [
    ['test_plan_rebase.py', 16],
    ['test_repository.py', 14],
    ['test_director.py', 10],
    ['test_comic_drama.py', 8],
    ['test_manuscript.py', 5],
    ['test_canon_extractor.py', 4],
  ],
]

function walkBackendTestFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) {
      return walkBackendTestFiles(path)
    }
    return entry.isFile() && /^(?:test_.*|.*_test)\.py$/.test(entry.name)
      ? [path]
      : []
  })
}

function backendTestKey(file) {
  const normalized = file.replaceAll('\\', '/')
  const marker = 'services/api/tests/'
  const markerPosition = normalized.lastIndexOf(marker)
  return markerPosition === -1
    ? normalized
    : normalized.slice(markerPosition + marker.length)
}

export function parseCollectedBackendTestWeights(output) {
  const weights = new Map()
  for (const line of output.split(/\r?\n/)) {
    const separatorPosition = line.indexOf('::')
    if (separatorPosition === -1) {
      continue
    }
    let name = backendTestKey(line.slice(0, separatorPosition).trim())
    if (name.startsWith('tests/')) {
      name = name.slice('tests/'.length)
    }
    weights.set(name, (weights.get(name) ?? 0) + 1)
  }
  return weights
}

export function validateCollectedBackendTestWeights(files, output) {
  // This call validates that the static map is also an exact file cover.
  selectBackendTestShard(files, 0, BACKEND_TEST_SHARD_DEFINITIONS.length)
  const expected = new Map(BACKEND_TEST_SHARD_DEFINITIONS.flat())
  const collected = parseCollectedBackendTestWeights(output)
  const mismatches = []
  for (const [name, weight] of expected) {
    const actual = collected.get(name)
    if (actual !== weight) {
      mismatches.push(`${name}: expected=${weight} actual=${actual ?? 'missing'}`)
    }
  }
  for (const [name, weight] of collected) {
    if (!expected.has(name)) {
      mismatches.push(`${name}: expected=unmapped actual=${weight}`)
    }
  }
  if (mismatches.length > 0) {
    throw new Error(`后端测试分片权重已失衡：${mismatches.join('；')}`)
  }
  return [...collected.values()].reduce((total, weight) => total + weight, 0)
}

export function listBackendTestFiles(root = repositoryRoot) {
  const testsDirectory = join(root, 'services', 'api', 'tests')
  return walkBackendTestFiles(testsDirectory)
    .map((file) => relative(root, file))
    .sort((left, right) => left.localeCompare(right, 'en'))
}

export function selectBackendTestShard(files, shardIndex, shardCount) {
  if (!Number.isSafeInteger(shardCount) || shardCount < 1) {
    throw new Error('shard-count 必须是正整数')
  }
  if (!Number.isSafeInteger(shardIndex) || shardIndex < 0 || shardIndex >= shardCount) {
    throw new Error('shard-index 必须落在 [0, shard-count)')
  }
  if (shardCount !== BACKEND_TEST_SHARD_DEFINITIONS.length) {
    throw new Error(`shard-count 必须是 ${BACKEND_TEST_SHARD_DEFINITIONS.length}`)
  }

  const filesByName = new Map()
  for (const file of files) {
    const name = backendTestKey(file)
    if (filesByName.has(name)) {
      throw new Error(`发现重复测试文件名：${name}`)
    }
    filesByName.set(name, file)
  }
  const expectedNames = BACKEND_TEST_SHARD_DEFINITIONS
    .flat()
    .map(([name]) => name)
  const missing = expectedNames.filter((name) => !filesByName.has(name))
  const unexpected = [...filesByName.keys()].filter(
    (name) => !expectedNames.includes(name),
  )
  if (missing.length > 0 || unexpected.length > 0) {
    throw new Error(
      `后端测试分片映射不是精确覆盖：缺少=${missing.join(',') || '无'}；新增=${unexpected.join(',') || '无'}`,
    )
  }

  return BACKEND_TEST_SHARD_DEFINITIONS[shardIndex].map(([name]) =>
    filesByName.get(name),
  )
}

function integerFlag(argumentsList, name) {
  const position = argumentsList.indexOf(name)
  if (position === -1 || position + 1 >= argumentsList.length) {
    throw new Error(`缺少 ${name}`)
  }
  const value = Number(argumentsList[position + 1])
  if (!Number.isSafeInteger(value)) {
    throw new Error(`${name} 必须是整数`)
  }
  return value
}

const entryPath = process.argv[1] ? pathToFileURL(process.argv[1]).href : ''
if (import.meta.url === entryPath) {
  const argumentsList = process.argv.slice(2)
  if (argumentsList.includes('--validate-weights')) {
    const output = execFileSync(
      'uv',
      [
        'run',
        '--project',
        'services/api',
        '--no-sync',
        'pytest',
        '-p',
        'no:cacheprovider',
        '--collect-only',
        '-q',
        'services/api/tests',
      ],
      {
        cwd: repositoryRoot,
        encoding: 'utf8',
        env: { ...process.env, PYTEST_ADDOPTS: '' },
        stdio: ['inherit', 'pipe', 'inherit'],
      },
    )
    const total = validateCollectedBackendTestWeights(
      listBackendTestFiles(),
      output,
    )
    process.stdout.write(
      `backend shard weights match pytest collection: ${total} nodeids\n`,
    )
  } else {
    const shardIndex = integerFlag(argumentsList, '--shard-index')
    const shardCount = integerFlag(argumentsList, '--shard-count')
    const selected = selectBackendTestShard(
      listBackendTestFiles(),
      shardIndex,
      shardCount,
    )
    process.stdout.write(
      `backend shard ${shardIndex + 1}/${shardCount}: ${selected.length} files\n` +
        selected.map((file) => `- ${file}`).join('\n') +
        '\n',
    )
    execFileSync(
      'uv',
      [
        'run',
        '--project',
        'services/api',
        '--no-sync',
        'pytest',
        '-p',
        'no:cacheprovider',
        '--tb=short',
        '--durations=10',
        ...selected,
      ],
      {
        cwd: repositoryRoot,
        env: { ...process.env, PYTEST_ADDOPTS: '' },
        stdio: 'inherit',
      },
    )
  }
}
