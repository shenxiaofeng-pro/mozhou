import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const requirements = {
  darwin: [
    'APPLE_CERTIFICATE',
    'APPLE_CERTIFICATE_PASSWORD',
    'APPLE_SIGNING_IDENTITY',
    'APPLE_ID',
    'APPLE_PASSWORD',
    'APPLE_TEAM_ID',
  ],
  win32: [
    'AZURE_CLIENT_ID',
    'AZURE_CLIENT_SECRET',
    'AZURE_TENANT_ID',
    'AZURE_ARTIFACT_SIGNING_ENDPOINT',
    'AZURE_ARTIFACT_SIGNING_ACCOUNT',
    'AZURE_ARTIFACT_SIGNING_PROFILE',
  ],
}

export function releasePreflight(platform, environment, gitReference = '') {
  if (!(platform in requirements)) return { ok: false, missing: [], reason: 'unsupported_platform' }
  const missing = requirements[platform].filter((name) => !environment[name]?.trim())
  if (missing.length > 0) return { ok: false, missing, reason: 'missing_credentials' }
  if (gitReference && !/^refs\/tags\/v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(gitReference)) {
    return { ok: false, missing: [], reason: 'invalid_release_tag' }
  }
  if (platform === 'win32') {
    try {
      const endpoint = new URL(environment.AZURE_ARTIFACT_SIGNING_ENDPOINT)
      if (endpoint.protocol !== 'https:' || endpoint.username || endpoint.password) {
        return { ok: false, missing: [], reason: 'invalid_signing_configuration' }
      }
    } catch {
      return { ok: false, missing: [], reason: 'invalid_signing_configuration' }
    }
    for (const name of ['AZURE_ARTIFACT_SIGNING_ACCOUNT', 'AZURE_ARTIFACT_SIGNING_PROFILE']) {
      if (!/^[A-Za-z0-9_.-]{1,100}$/.test(environment[name])) {
        return { ok: false, missing: [], reason: 'invalid_signing_configuration' }
      }
    }
  }
  return { ok: true, missing: [], reason: null }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = releasePreflight(
    process.platform,
    process.env,
    process.env.MOZHOU_RELEASE_REF ?? process.env.GITHUB_REF ?? '',
  )
  if (!result.ok) {
    const detail = result.missing.length > 0 ? `：${result.missing.join(', ')}` : ''
    process.stderr.write(`发布签名门未通过（${result.reason}）${detail}\n`)
    process.exitCode = 1
  } else {
    process.stdout.write('Release signing preflight passed.\n')
  }
}
