import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, statSync } from 'node:fs'
import process from 'node:process'
import { pathToFileURL } from 'node:url'

const MAX_TRACKED_FILE_BYTES = 10 * 1024 * 1024
const ALLOWED_ENV_FILES = new Set(['.env.example'])
const SAFE_TEST_SECRETS = ['sk-test-abcdefghijklmnopqrstuvwxyz']

export function isForbiddenTrackedPath(filePath) {
  if (filePath.endsWith('.db') || filePath.endsWith('.db-shm') || filePath.endsWith('.db-wal')) {
    return true
  }
  if ((filePath.startsWith('.env') || filePath.includes('/.env')) && !ALLOWED_ENV_FILES.has(filePath)) {
    return true
  }
  return [
    'node_modules/',
    'artifacts/',
    '.mozhou-data/',
    'apps/desktop/src-tauri/target/',
    'apps/desktop/src-tauri/binaries/',
    'apps/desktop/src-tauri/gen/schemas/',
  ].some((prefix) => filePath === prefix.slice(0, -1) || filePath.startsWith(prefix))
}

export function findSecretKinds(text) {
  let content = text
  for (const fixture of SAFE_TEST_SECRETS) content = content.replaceAll(fixture, '')
  const findings = []
  const patterns = [
    ['OpenAI API Key', /(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}/],
    ['GitHub token', /gh[opusr]_[A-Za-z0-9]{20,}/],
    ['private key', /BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY/],
  ]
  for (const [kind, pattern] of patterns) {
    if (pattern.test(content)) findings.push(kind)
  }
  return findings
}

export function inspectRepository(root = process.cwd()) {
  const tracked = execFileSync('git', ['ls-files', '-z', '--cached', '--others', '--exclude-standard'], {
    cwd: root,
    encoding: 'utf8',
  }).split('\0').filter(Boolean)
  const findings = []

  for (const filePath of tracked) {
    const absolutePath = new URL(filePath, pathToFileURL(root + '/'))
    if (!existsSync(absolutePath)) continue
    if (isForbiddenTrackedPath(filePath)) {
      findings.push(filePath + ': forbidden tracked path')
      continue
    }
    const size = statSync(absolutePath).size
    if (size > MAX_TRACKED_FILE_BYTES) {
      findings.push(filePath + ': tracked file exceeds 10 MiB')
      continue
    }
    const content = readFileSync(absolutePath)
    if (content.includes(0)) continue
    for (const kind of findSecretKinds(content.toString('utf8'))) {
      findings.push(filePath + ': possible ' + kind)
    }
  }
  return findings
}

const entryPath = process.argv[1] ? pathToFileURL(process.argv[1]).href : ''
if (import.meta.url === entryPath) {
  const findings = inspectRepository()
  if (findings.length > 0) {
    process.stderr.write('Repository guard failed:\n' + findings.join('\n') + '\n')
    process.exitCode = 1
  } else {
    process.stdout.write('Repository guard passed.\n')
  }
}
