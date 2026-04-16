import { defineConfig, devices } from '@playwright/test';

const E2E_EXPECT_TIMEOUT_MS = Number(process.env.E2E_EXPECT_TIMEOUT_MS || '5000');
const E2E_TEST_TIMEOUT_MS = Number(process.env.E2E_TEST_TIMEOUT_MS || '30000');

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: 'html',
  timeout: E2E_TEST_TIMEOUT_MS,
  expect: {
    timeout: E2E_EXPECT_TIMEOUT_MS,
  },

  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: process.env.CI
    ? undefined
    : {
        command: 'npm run dev',
        url: 'http://localhost:5173',
        reuseExistingServer: true,
        timeout: E2E_TEST_TIMEOUT_MS,
      },
});
