import { spawnSync } from 'node:child_process'
import process from 'node:process'

const repository = spawnSync('git', ['rev-parse', '--git-dir'], {
  encoding: 'utf8',
  stdio: ['ignore', 'pipe', 'ignore'],
})

if (repository.status !== 0) {
  process.stdout.write('Git hooks skipped: source is not inside a Git worktree.\n')
  process.exit(0)
}

const configured = spawnSync('git', ['config', 'core.hooksPath', '.githooks'], {
  encoding: 'utf8',
  stdio: ['ignore', 'pipe', 'pipe'],
})

if (configured.status !== 0) {
  process.stderr.write(configured.stderr || 'Unable to configure Git hooks.\n')
  process.exit(configured.status ?? 1)
}

process.stdout.write('Git hooks installed from .githooks.\n')
