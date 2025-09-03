import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['src/**/*.test.ts'],
    exclude: ['tests/e2e/**', 'node_modules/**', 'dist/**']
  },
  server: {
    host: '127.0.0.1'
  }
})
