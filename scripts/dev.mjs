import { execFile, spawn } from 'node:child_process'
import process from 'node:process'
import { pathToFileURL } from 'node:url'

export function createDevCommands(platform = process.platform) {
  const pnpm = platform === 'win32' ? 'pnpm.cmd' : 'pnpm'
  const uv = platform === 'win32' ? 'uv.exe' : 'uv'
  return [
    {
      name: 'web',
      executable: pnpm,
      args: ['--filter', '@mozhou/web', 'dev'],
    },
    {
      name: 'api',
      executable: uv,
      args: [
        'run',
        '--project',
        'services/api',
        '--no-sync',
        'uvicorn',
        'app.runtime:create_runtime_app',
        '--factory',
        '--app-dir',
        'services/api',
        '--reload',
        '--host',
        '127.0.0.1',
        '--port',
        '8765',
      ],
      env: { MOZHOU_ALLOW_INSECURE_DEV_API: '1' },
    },
  ]
}

export function startDevelopment(commands = createDevCommands()) {
  const children = new Map()
  let stopping = false

  function stopChild(child) {
    if (child.exitCode !== null || child.pid === undefined) return
    if (process.platform === 'win32') {
      execFile('taskkill.exe', ['/pid', String(child.pid), '/T', '/F'], () => {})
      return
    }
    try {
      process.kill(-child.pid, 'SIGTERM')
    } catch {
      child.kill('SIGTERM')
    }
  }

  function stopAll(exitCode) {
    if (stopping) return
    stopping = true
    for (const child of children.values()) stopChild(child)
    process.exitCode = exitCode
  }

  for (const command of commands) {
    const child = spawn(command.executable, command.args, {
      cwd: process.cwd(),
      detached: process.platform !== 'win32',
      env: { ...process.env, ...command.env },
      shell: false,
      stdio: 'inherit',
    })
    children.set(command.name, child)
    child.once('error', (error) => {
      process.stderr.write('[' + command.name + '] 无法启动：' + error.message + '\n')
      stopAll(1)
    })
    child.once('exit', (code, signal) => {
      if (stopping) return
      const reason = signal ? 'signal ' + signal : 'code ' + (code ?? 1)
      process.stderr.write(
        '[' + command.name + '] 已退出（' + reason + '），正在停止其余开发进程。\n',
      )
      stopAll(code ?? 1)
    })
  }

  process.once('SIGINT', () => stopAll(0))
  process.once('SIGTERM', () => stopAll(0))
  return { children, stopAll }
}

const entryPath = process.argv[1] ? pathToFileURL(process.argv[1]).href : ''
if (import.meta.url === entryPath) {
  const commands = process.argv.includes('--api-only')
    ? createDevCommands().filter((command) => command.name === 'api')
    : createDevCommands()
  startDevelopment(commands)
}
