import { test as base, expect, Page } from '@playwright/test';

/** Default admin credentials – override via env vars if needed. */
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@simple.dev';
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'Admin@123';

/**
 * Custom fixture that provides an already-authenticated page.
 * Logs in once and stores the auth token in localStorage so every
 * test starts on an authenticated session.
 */
export const test = base.extend<{ authedPage: Page }>({
  authedPage: async ({ page }, use) => {
    await page.goto('/login');
    await page.fill('#email', ADMIN_EMAIL);
    await page.fill('#password', ADMIN_PASSWORD);
    await page.click('button:has-text("Open dashboard")');
    await expect(page).toHaveURL('/', { timeout: 10_000 });
    await use(page);
  },
});

export { expect };

/** Helper: wait for a success toast to appear and contain text. */
export async function expectSuccess(page: Page, substring: string) {
  const banner = page.locator('.toast--success');
  await expect(banner).toBeVisible({ timeout: 10_000 });
  await expect(banner).toContainText(substring);
}

/** Helper: wait for an error toast to appear. */
export async function expectError(page: Page, substring?: string) {
  const banner = page.locator('.toast--error');
  await expect(banner).toBeVisible({ timeout: 10_000 });
  if (substring) {
    await expect(banner).toContainText(substring);
  }
}

/** Generate a unique SKU for test isolation. */
export function uniqueSku() {
  return `TST-${Date.now().toString(36).toUpperCase()}`;
}

/**
 * Generate a valid, unique GSTIN.
 * Format: 2 digits + 5 uppercase letters + 4 digits + 1 letter + 1 alphanumeric + Z + 1 alphanumeric
 * Example: 27ABCDE1234F1Z5
 */
export function uniqueGstin(stateCode = '27') {
  const alpha = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
  const pick = () => alpha[Math.floor(Math.random() * 26)];
  const digit = () => String(Math.floor(Math.random() * 10));
  // pos 0-1: state code, 2-6: 5 letters, 7-10: 4 digits, 11: letter, 12: alphanumeric, 13: Z, 14: alphanumeric
  return `${stateCode}${pick()}${pick()}${pick()}${pick()}${pick()}${digit()}${digit()}${digit()}${digit()}${pick()}1Z${pick()}`;
}
