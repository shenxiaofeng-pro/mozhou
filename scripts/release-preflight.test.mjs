import assert from 'node:assert/strict'
import { test } from 'node:test'

import { releasePreflight } from './release-preflight.mjs'

test('macOS release refuses to continue without notarization credentials', () => {
  const result = releasePreflight('darwin', {}, 'refs/tags/v0.1.0')

  assert.equal(result.ok, false)
  assert.equal(result.reason, 'missing_credentials')
  assert.ok(result.missing.includes('APPLE_CERTIFICATE'))
  assert.ok(result.missing.includes('APPLE_TEAM_ID'))
})

test('Windows release validates Azure Artifact Signing configuration', () => {
  const environment = {
    AZURE_CLIENT_ID: 'client',
    AZURE_CLIENT_SECRET: 'secret',
    AZURE_TENANT_ID: 'tenant',
    AZURE_ARTIFACT_SIGNING_ENDPOINT: 'https://eus.codesigning.azure.net',
    AZURE_ARTIFACT_SIGNING_ACCOUNT: 'mozhou-account',
    AZURE_ARTIFACT_SIGNING_PROFILE: 'public-release',
  }

  assert.equal(releasePreflight('win32', environment, 'refs/tags/v0.1.0').ok, true)
  assert.equal(releasePreflight('win32', {
    ...environment,
    AZURE_ARTIFACT_SIGNING_ACCOUNT: 'unsafe; command',
  }).reason, 'invalid_signing_configuration')
})

test('release accepts only semantic version tags', () => {
  const environment = Object.fromEntries([
    'APPLE_CERTIFICATE',
    'APPLE_CERTIFICATE_PASSWORD',
    'APPLE_SIGNING_IDENTITY',
    'APPLE_ID',
    'APPLE_PASSWORD',
    'APPLE_TEAM_ID',
  ].map((name) => [name, 'configured']))

  assert.equal(releasePreflight('darwin', environment, 'refs/heads/main').reason, 'invalid_release_tag')
  assert.equal(releasePreflight('darwin', environment, 'refs/tags/v0.1.0-rc.1').ok, true)
})
