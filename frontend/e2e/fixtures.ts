import { test as base, expect, Page } from '@playwright/test';

/** Default admin credentials – override via env vars if needed. */
const ADMIN_EMAIL = (globalThis as any).process?.env?.E2E_ADMIN_EMAIL || 'admin@simple.dev';
const ADMIN_PASSWORD = (globalThis as any).process?.env?.E2E_ADMIN_PASSWORD || 'Admin@123';

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
    await expect(page).toHaveURL('/', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await use(page);
  },
});

export { expect };

/**
 * Helper: select an option from a combobox (ProductCombobox / LedgerCombobox).
 * Clears the input, types the search text, waits for a matching listbox option,
 * then clicks it.
 */
export async function selectComboboxOption(page: Page, inputId: string, searchText: string) {
  const input = page.locator(`#${inputId}`);
  await input.click();
  await input.selectText();
  await input.fill(searchText);
  const option = page.locator(`#${inputId}-listbox [role="option"]`, { hasText: searchText }).first();
  await expect(option).toBeVisible({ timeout: 5_000 });
  await option.click();
}

/** Helper: wait for a success toast to appear and contain text. */
export async function expectSuccess(page: Page, substring: string) {
  const banner = page.locator('.toast--success').filter({ hasText: substring }).last();
  await expect(banner).toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
  await expect(banner).toContainText(substring);
}

/** Helper: wait for an error toast to appear. */
export async function expectError(page: Page, substring?: string) {
  const banner = page.locator('.toast--error');
  await expect(banner).toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
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
