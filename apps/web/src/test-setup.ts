import '@testing-library/jest-dom/vitest'

// Node 26 exposes an unconfigured experimental localStorage. Vitest sees the
// existing key and does not replace it, so use the storage owned by its JSDOM.
const testEnvironment = globalThis as typeof globalThis & {
  jsdom?: { window: Window }
}

if (testEnvironment.jsdom) {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: testEnvironment.jsdom.window.localStorage,
  })
}
