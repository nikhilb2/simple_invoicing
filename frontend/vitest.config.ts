import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    exclude: [
      '**/node_modules/**',
      '**/e2e/**',
      '**/*.spec.ts',   // exclude Playwright spec files
      '**/tests-e2e/**',
    ],
  },
})