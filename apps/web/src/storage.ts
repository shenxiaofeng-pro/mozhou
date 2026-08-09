const SESSION_KEY = 'mozhou:session:v1'

interface StoredSession {
  version: 1
  projectId: string
}

export function loadActiveProjectId(): string | null {
  try {
    const raw = window.localStorage.getItem(SESSION_KEY)
    if (!raw) return null
    const value: unknown = JSON.parse(raw)
    if (
      value &&
      typeof value === 'object' &&
      'version' in value &&
      value.version === 1 &&
      'projectId' in value &&
      typeof value.projectId === 'string'
    ) {
      return value.projectId
    }
  } catch {
    window.localStorage.removeItem(SESSION_KEY)
  }
  return null
}

export function saveActiveProjectId(projectId: string): void {
  const session: StoredSession = { version: 1, projectId }
  window.localStorage.setItem(SESSION_KEY, JSON.stringify(session))
}

export function clearActiveProjectId(): void {
  window.localStorage.removeItem(SESSION_KEY)
}
