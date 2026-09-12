import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/health': 'http://127.0.0.1:8765',
    },
  },
  test: {
    environment: 'jsdom',
    // The interaction-heavy workbench suites allocate a full JSDOM each.
    // Capping workers keeps their existing 5s assertions deterministic on CI
    // and on author machines that are running the desktop shell in parallel.
    maxWorkers: 1,
    environmentOptions: {
      jsdom: { url: 'http://127.0.0.1:5173' },
    },
    setupFiles: './src/test-setup.ts',
  },
})
