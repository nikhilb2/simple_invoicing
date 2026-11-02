import { defineConfig } from 'vitest/config'

export default defineConfig({
  // vitest.config.ts is read instead of vite.config.ts, so the build stamp the
  // `build-version` plugin injects has to be declared again here or any module
  // reaching it fails to load under test.
  define: {
    __BUILD_VERSION__: JSON.stringify('test'),
  },
  test: {
    exclude: [
      '**/node_modules/**',
      '**/e2e/**',
      '**/*.spec.ts',   // exclude Playwright spec files
      '**/tests-e2e/**',
    ],
  },
})
