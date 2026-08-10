import { execFileSync } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import {
  mkdirSync,
  readFileSync,
  readdirSync,
  statSync,
  writeFileSync,
} from 'node:fs'
import { basename, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repositoryRoot = resolve(fileURLToPath(new URL('..', import.meta.url)))
const blockedLicenseMarkers = ['AGPL', 'GPL-3', 'SSPL', 'BUSL']

function execute(command, args, options = {}) {
  const executable = process.platform === 'win32' && command === 'pnpm' ? 'pnpm.cmd' : command
  return execFileSync(executable, args, {
    cwd: repositoryRoot,
    encoding: 'utf8',
    env: process.env,
    maxBuffer: 64 * 1024 * 1024,
    ...options,
  }).trim()
}

function currentRustTarget() {
  const details = execute('rustc', ['-vV'])
  return /^host: (.+)$/m.exec(details)?.[1] ?? ''
}

function npmComponents(inventory) {
  return Object.entries(inventory).flatMap(([licenseName, entries]) =>
    entries.flatMap((entry) => entry.versions.map((version) => ({
      type: 'library',
      name: entry.name,
      version,
      purl: `pkg:npm/${encodeURIComponent(entry.name)}@${version}`,
      licenses: [{ expression: entry.license || licenseName }],
      properties: [{ name: 'mozhou:ecosystem', value: 'npm' }],
    }))),
  )
}

function rustComponents(metadata) {
  const reachableIds = new Set(metadata.resolve?.nodes.map((node) => node.id) ?? [])
  return metadata.packages
    .filter((entry) => reachableIds.has(entry.id))
    .map((entry) => ({
      type: 'library',
      name: entry.name,
      version: entry.version,
      purl: `pkg:cargo/${encodeURIComponent(entry.name)}@${entry.version}`,
      ...(entry.license ? { licenses: [{ expression: entry.license }] } : {}),
      properties: [{ name: 'mozhou:ecosystem', value: 'cargo' }],
    }))
}

export function mergeSbomComponents(...groups) {
  const components = new Map()
  for (const component of groups.flat()) {
    const ecosystem = component.properties?.find((property) => property.name === 'mozhou:ecosystem')?.value
      ?? component.purl?.split(':')[1]?.split('/')[0]
      ?? 'unknown'
    const key = `${ecosystem}:${component.name}:${component.version}`
    components.set(key, component)
  }
  return [...components.values()].sort((left, right) =>
    `${left.name}@${left.version}`.localeCompare(`${right.name}@${right.version}`, 'en'),
  )
}

export function blockedLicenses(components) {
  return components.flatMap((component) => {
    const expressions = component.licenses?.map((license) => license.expression ?? license.license?.id ?? '') ?? []
    const blocked = expressions.find((expression) =>
      blockedLicenseMarkers.some((marker) => expression.toUpperCase().includes(marker)),
    )
    return blocked ? [`${component.name}@${component.version}: ${blocked}`] : []
  })
}

export function noticeText(components) {
  const rows = components.map((component) => {
    const licenses = component.licenses?.map((license) => license.expression ?? license.license?.id)
      .filter(Boolean)
      .join(' OR ') ?? 'UNKNOWN — consult package metadata'
    return `${component.name}@${component.version} — ${licenses}`
  })
  return [
    '墨舟第三方组件声明',
    '',
    '本文件由锁定依赖生成。版权和完整许可文本以各组件随附文件及上游发布为准。',
    '',
    ...rows,
    '',
  ].join('\n')
}

function artifactFiles(directory) {
  try {
    return readdirSync(directory, { recursive: true, withFileTypes: true })
      .filter((entry) => entry.isFile())
      .map((entry) => join(entry.parentPath, entry.name))
      .filter((path) => !['SHA256SUMS.txt', 'release-record.json'].includes(basename(path)))
      .sort()
  } catch (error) {
    if (error && typeof error === 'object' && 'code' in error && error.code === 'ENOENT') return []
    throw error
  }
}

export function checksumRows(directory) {
  return artifactFiles(directory).map((path) => ({
    file: relative(directory, path).replaceAll('\\', '/'),
    bytes: statSync(path).size,
    sha256: createHash('sha256').update(readFileSync(path)).digest('hex'),
  }))
}

function commandVersion(command, args) {
  return execute(command, args).split('\n')[0].trim()
}

function generate({ outputDirectory, artifactDirectory }) {
  const npmInventory = JSON.parse(execute('pnpm', ['licenses', 'list', '--prod', '--long', '--json']))
  const pythonSbom = JSON.parse(execute('uv', [
    'export', '--project', 'services/api', '--frozen', '--no-dev',
    '--format', 'cyclonedx1.5', '--preview-features', 'sbom-export',
  ]))
  const rustTarget = currentRustTarget()
  const cargoMetadata = JSON.parse(execute('cargo', [
    'metadata', '--manifest-path', 'apps/desktop/src-tauri/Cargo.toml',
    '--locked', '--offline', '--filter-platform', rustTarget, '--format-version', '1',
  ]))
  const pythonComponents = (pythonSbom.components ?? []).map((component) => ({
    ...component,
    properties: [
      ...(component.properties ?? []),
      { name: 'mozhou:ecosystem', value: 'pypi' },
    ],
  }))
  const components = mergeSbomComponents(
    npmComponents(npmInventory),
    pythonComponents,
    rustComponents(cargoMetadata),
  )
  const disallowed = blockedLicenses(components)
  if (disallowed.length > 0) {
    throw new Error(`发现未经处置的限制性许可证：\n${disallowed.join('\n')}`)
  }

  mkdirSync(outputDirectory, { recursive: true })
  const packageManifest = JSON.parse(readFileSync(join(repositoryRoot, 'package.json'), 'utf8'))
  const generatedAt = new Date().toISOString()
  const sbom = {
    bomFormat: 'CycloneDX',
    specVersion: '1.5',
    serialNumber: `urn:uuid:${randomUUID()}`,
    version: 1,
    metadata: {
      timestamp: generatedAt,
      component: { type: 'application', name: 'mozhou', version: packageManifest.version },
      properties: [{ name: 'mozhou:rust-target', value: rustTarget }],
    },
    components,
  }
  writeFileSync(join(outputDirectory, 'mozhou.cdx.json'), `${JSON.stringify(sbom, null, 2)}\n`)
  writeFileSync(join(outputDirectory, 'NOTICE.txt'), noticeText(components))

  const checksums = checksumRows(artifactDirectory)
  writeFileSync(
    join(outputDirectory, 'SHA256SUMS.txt'),
    checksums.map((entry) => `${entry.sha256}  ${entry.file}`).join('\n') + (checksums.length ? '\n' : ''),
  )
  writeFileSync(join(outputDirectory, 'release-record.json'), `${JSON.stringify({
    format: 'mozhou-release-record',
    format_version: 1,
    version: packageManifest.version,
    source_commit: execute('git', ['rev-parse', 'HEAD']),
    generated_at: generatedAt,
    platform: process.platform,
    architecture: process.arch,
    toolchains: {
      node: process.version,
      pnpm: commandVersion('pnpm', ['--version']),
      uv: commandVersion('uv', ['--version']),
      rustc: commandVersion('rustc', ['--version']),
    },
    signature_policy: 'Developer ID + notarization on macOS; Authenticode on Windows',
    artifacts: checksums,
    sbom: 'mozhou.cdx.json',
    notice: 'NOTICE.txt',
  }, null, 2)}\n`)
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const argument = (name, fallback) => {
    const index = process.argv.indexOf(name)
    return resolve(repositoryRoot, index >= 0 ? process.argv[index + 1] : fallback)
  }
  generate({
    artifactDirectory: argument('--artifacts', 'artifacts/desktop'),
    outputDirectory: argument('--output', 'artifacts/release-metadata'),
  })
}
