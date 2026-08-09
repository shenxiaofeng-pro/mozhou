import process from 'node:process'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

export const PROTECTED_REMOTE_REFS = new Set(['refs/heads/main'])

export function protectedPushes(input) {
  return input
    .split(/\r?\n/u)
    .map((line) => line.trim().split(/\s+/u))
    .filter((fields) => fields.length >= 4 && PROTECTED_REMOTE_REFS.has(fields[2]))
    .map((fields) => fields[2])
}

export async function enforcePrePushPolicy(input = process.stdin) {
  let payload = ''
  for await (const chunk of input) {
    payload += chunk
  }

  const violations = protectedPushes(payload)
  if (violations.length === 0) {
    return 0
  }

  process.stderr.write(
    '拒绝直接推送 main。请推送功能分支，创建 Pull Request，并等待 macOS、Windows 与 security 全绿后再合并。\n',
  )
  return 1
}

const entryPoint = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : ''

if (import.meta.url === entryPoint) {
  process.exitCode = await enforcePrePushPolicy()
}
