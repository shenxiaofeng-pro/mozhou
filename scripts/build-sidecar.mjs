import { execFileSync } from 'node:child_process'
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const temporaryRoot = mkdtempSync(join(tmpdir(), 'mozhou-sidecar-'))
const sourceName = process.platform === 'win32' ? 'mozhou-api.exe' : 'mozhou-api'
const pyinstallerArguments = [
  'run',
  '--project',
  'services/api',
  '--no-sync',
  'pyinstaller',
  '--noconfirm',
  '--clean',
  '--onefile',
  '--name',
  'mozhou-api',
  '--paths',
  'services/api',
  '--distpath',
  join(temporaryRoot, 'dist'),
  '--workpath',
  join(temporaryRoot, 'work'),
  '--specpath',
  join(temporaryRoot, 'spec'),
]

if (process.platform === 'darwin' && process.env.APPLE_SIGNING_IDENTITY) {
  pyinstallerArguments.push('--codesign-identity', process.env.APPLE_SIGNING_IDENTITY)
}
pyinstallerArguments.push('services/api/app/sidecar.py')

try {
  execFileSync(
    'uv',
    pyinstallerArguments,
    { cwd: repositoryRoot, stdio: 'inherit' },
  )

  const rustVersion = execFileSync('rustc', ['-vV'], {
    cwd: repositoryRoot,
    encoding: 'utf8',
  })
  const hostLine = rustVersion.split('\n').find((line) => line.startsWith('host: '))
  if (!hostLine) {
    throw new Error('无法从 rustc -vV 读取 host target')
  }
  const targetTriple = hostLine.slice('host: '.length).trim()
  const suffix = process.platform === 'win32' ? '.exe' : ''
  const outputDirectory = join(repositoryRoot, 'apps/desktop/src-tauri/binaries')
  const outputPath = join(outputDirectory, `mozhou-api-${targetTriple}${suffix}`)
  const sourcePath = join(temporaryRoot, 'dist', sourceName)
  if (!existsSync(sourcePath)) {
    throw new Error(`PyInstaller 未生成预期文件：${sourcePath}`)
  }

  mkdirSync(outputDirectory, { recursive: true })
  copyFileSync(sourcePath, outputPath)
  if (process.platform !== 'win32') {
    chmodSync(outputPath, 0o755)
  }
  process.stdout.write(`sidecar ready: ${outputPath}\n`)
} finally {
  rmSync(temporaryRoot, { recursive: true, force: true })
}
