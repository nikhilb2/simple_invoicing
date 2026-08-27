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

/**
 * Helper: create a product through the Catalogue's "New product" modal.
 *
 * The permanently-visible form the old Products page carried is gone: the
 * fields only exist while `ProductFormModal` is open and their ids are now
 * prefixed (`#product-sku`, not `#sku`). Assumes the page is already showing
 * /catalogue.
 */
export type NewProduct = {
  sku: string;
  name: string;
  price: string;
  gstRate?: string;
  purchasePrice?: string;
  reorderLevel?: string;
  /** Opening stock. After creation, stock only moves through an adjustment. */
  openingQuantity?: string;
  description?: string;
  hsnSac?: string;
};

export async function createProduct(page: Page, product: NewProduct) {
  await page.getByRole('button', { name: 'New product' }).click();

  const modal = page.getByRole('dialog', { name: 'Add a product' });
  await expect(modal).toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

  await modal.locator('#product-sku').fill(product.sku);
  await modal.locator('#product-name').fill(product.name);
  await modal.locator('#product-price').fill(product.price);
  if (product.gstRate !== undefined) await modal.locator('#product-gst').fill(product.gstRate);
  if (product.purchasePrice !== undefined) {
    await modal.locator('#product-purchase-price').fill(product.purchasePrice);
  }
  if (product.reorderLevel !== undefined) {
    await modal.locator('#product-reorder').fill(product.reorderLevel);
  }
  if (product.openingQuantity !== undefined) {
    await modal.locator('#product-initial-qty').fill(product.openingQuantity);
  }
  if (product.description !== undefined) {
    await modal.locator('#product-description').fill(product.description);
  }
  if (product.hsnSac !== undefined) await modal.locator('#product-hsn').fill(product.hsnSac);

  await modal.getByRole('button', { name: 'Create product' }).click();

  // The modal closing is the signal the POST landed; the toast names the row.
  await expectSuccess(page, `${product.name} created.`);
  await expect(modal).toBeHidden({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
}

/** The catalogue's search box, which drives `?q=` and so the visible rows. */
export function catalogueSearch(page: Page) {
  return page.getByRole('searchbox', { name: 'Search the catalogue' });
}

/**
 * Helper: the catalogue row carrying a SKU or product name, as rendered.
 *
 * Rows are real `<tr class="catalogue-row">` now rather than `.table-row`
 * divs. A row being quick-edited holds its SKU in an input, where `hasText`
 * cannot see it — reach that one through `.catalogue-row--editing` instead.
 */
export function catalogueRow(page: Page, text: string) {
  return page.locator('tr.catalogue-row', { hasText: text }).first();
}

/**
 * Helper: move a product's stock from the Catalogue.
 *
 * Stock is no longer an editable cell anywhere in the app — the quantity is a
 * button that opens `StockAdjustModal`, which posts a signed delta to
 * /inventory/adjust so the movement is on the record. A removal will not
 * submit without a reason, so one is always supplied for a negative delta.
 *
 * Assumes the page is already showing /catalogue.
 */
export async function adjustInventory(page: Page, sku: string, quantity: string, reason = 'E2E stock adjustment') {
  await catalogueSearch(page).fill(sku);
  const row = catalogueRow(page, sku);
  await expect(row).toBeVisible({ timeout: 5_000 });

  // The stock button's accessible name is the quantity it is showing, so its
  // title is what identifies it — hence getByTitle rather than getByRole.
  await row.getByTitle(/^Adjust stock for /).click();

  const modal = page.getByRole('dialog', { name: 'Adjust stock' });
  await expect(modal).toBeVisible({ timeout: 5_000 });
  await modal.locator('#stock-adjust-delta').fill(quantity);
  if (Number(quantity) < 0) await modal.locator('#stock-adjust-reason').fill(reason);

  const apply = modal.getByRole('button', { name: /^Apply stock adjustment for / });
  await expect(apply).toBeEnabled({ timeout: 5_000 });
  await apply.click();
  await expect(modal).toBeHidden({ timeout: 5_000 });
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
  '/catalogue': 'catalogue',
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
