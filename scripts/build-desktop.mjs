import { execFileSync } from 'node:child_process'
import { copyFileSync, mkdirSync, readdirSync, realpathSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repositoryRoot = resolve(fileURLToPath(new URL('..', import.meta.url)))
const pnpmExecutable = process.platform === 'win32' ? 'pnpm.cmd' : 'pnpm'
const tauriArguments = ['--filter', '@mozhou/desktop', 'tauri', 'build', '--ci']
const targetDirectory = process.env.CARGO_TARGET_DIR
  ?? join(realpathSync(tmpdir()), 'mozhou-tauri-target')

const bundleConfiguration = {}
if (process.platform === 'darwin' && !process.env.APPLE_SIGNING_IDENTITY) {
  bundleConfiguration.macOS = { hardenedRuntime: false, signingIdentity: '-' }
}

if (
  process.platform === 'win32'
  && process.env.AZURE_ARTIFACT_SIGNING_ENDPOINT
  && process.env.AZURE_ARTIFACT_SIGNING_ACCOUNT
  && process.env.AZURE_ARTIFACT_SIGNING_PROFILE
) {
  const endpoint = new URL(process.env.AZURE_ARTIFACT_SIGNING_ENDPOINT)
  const account = process.env.AZURE_ARTIFACT_SIGNING_ACCOUNT
  const profile = process.env.AZURE_ARTIFACT_SIGNING_PROFILE
  if (
    endpoint.protocol !== 'https:'
    || endpoint.username
    || endpoint.password
    || !/^[A-Za-z0-9_.-]{1,100}$/.test(account)
    || !/^[A-Za-z0-9_.-]{1,100}$/.test(profile)
  ) {
    throw new Error('Invalid Azure Artifact Signing configuration')
  }
  bundleConfiguration.windows = {
    signCommand: [
      'artifact-signing-cli',
      '-e', endpoint.origin,
      '-a', account,
      '-c', profile,
      '-d', 'Mozhou',
      '%1',
    ].join(' '),
  }
}

if (Object.keys(bundleConfiguration).length > 0) {
  tauriArguments.push(
    '--config',
    JSON.stringify({ bundle: bundleConfiguration }),
  )
}

execFileSync(
  pnpmExecutable,
  tauriArguments,
  {
    cwd: repositoryRoot,
    env: { ...process.env, CARGO_TARGET_DIR: targetDirectory, CI: 'true' },
    stdio: 'inherit',
  },
)

const bundleDirectory = join(targetDirectory, 'release', 'bundle')
const artifactDirectory = join(repositoryRoot, 'artifacts', 'desktop')
const installerExtensions = new Set(['.deb', '.dmg', '.exe', '.msi', '.rpm'])
const installers = readdirSync(bundleDirectory, { recursive: true, withFileTypes: true })
  .filter((entry) => entry.isFile())
  .map((entry) => join(entry.parentPath, entry.name))
  .filter((path) => installerExtensions.has(path.slice(path.lastIndexOf('.')).toLowerCase()))

mkdirSync(artifactDirectory, { recursive: true })
for (const installer of installers) {
  const outputPath = join(artifactDirectory, basename(installer))
  copyFileSync(installer, outputPath)
  process.stdout.write(`installer ready: ${outputPath}\n`)
}
