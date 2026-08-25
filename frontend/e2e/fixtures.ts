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

/**
 * Which rail section owns each primary nav link.
 *
 * Mirrors PRIMARY_NAV in src/config/navigation.ts. It is duplicated rather
 * than imported because these specs drive the app over HTTP and don't build
 * against its source — if a link moves to another section, move it here too.
 * Anything absent is either a top-level rail link ('/', '/ledgers') or lives
 * behind /settings, and needs no disclosure to reach.
 */
const NAV_SECTION_BY_HREF: Record<string, string> = {
  '/invoices': 'sales',
  '/invoices-view': 'sales',
  '/invoice-dues': 'sales',
  '/credit-notes': 'sales',
  '/cash-bank': 'sales',
  '/products': 'catalogue',
  '/inventory': 'catalogue',
  '/products-inventory': 'catalogue',
  '/produce-items': 'catalogue',
  '/analytics': 'reports',
  '/day-book': 'reports',
  '/tax-ledger': 'reports',
  '/marketplace': 'marketplace',
  '/marketplace/listings': 'marketplace',
  '/marketplace/orders': 'marketplace',
};

/**
 * Helper: expand a sidebar section, unless it is already the open one.
 *
 * The rail is an accordion — exactly one section is expanded at a time and a
 * closed section's children are not rendered at all — so the toggle is only
 * clicked when it reports itself collapsed. Clicking unconditionally would
 * close a section that was already open.
 *
 * Expanded-rail only: in collapsed (`.app-shell--rail`) mode a section row is
 * a plain link and there is no disclosure button to press. On mobile, open the
 * drawer first.
 */
export async function openSidebarSection(page: Page, sectionId: string) {
  const toggle = page.locator(
    `.sidebar__section-toggle[aria-controls="nav-section-${sectionId}"]`,
  );
  const items = page.locator(`#nav-section-${sectionId}`);
  await expect(toggle).toBeVisible();

  // Wrapped in toPass rather than read once: arriving on a route auto-opens
  // *that* route's section, which can land a beat after the navigation that
  // triggered it. A single sample of aria-expanded taken in that window can be
  // of the pre-effect DOM, and the section would then be re-closed under us.
  // toPass retries the whole read-and-click, so it converges instead.
  await expect(async () => {
    if ((await toggle.getAttribute('aria-expanded')) !== 'true') {
      await toggle.click();
    }
    await expect(items).toBeVisible({ timeout: 1_000 });
  }).toPass({ timeout: 10_000 });
}

/**
 * Helper: navigate by clicking a sidebar link, expanding its owning section
 * first when the link is a section child.
 *
 * Prefer this over `page.click('[href="…"]')`. Since the sidebar redesign a
 * link is only in the DOM while its section is open, and navigating auto-opens
 * the *destination's* section — so which links exist depends on where the test
 * happens to be, which is exactly the sort of implicit state a spec shouldn't
 * carry. Scoped to `.sidebar` so an in-page link to the same route can't be
 * clicked by accident.
 */
export async function clickNavLink(page: Page, href: string) {
  const sectionId = NAV_SECTION_BY_HREF[href];
  if (sectionId) {
    await openSidebarSection(page, sectionId);
  }
  await page.locator(`.sidebar a.sidebar__link[href="${href}"]`).click();
}
