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
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
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
  // The rate is a choice the form insists on; a test that does not care takes 0%, as the old default did.
  const gstRate = product.gstRate ?? '0';
  if (['0', '5', '12', '18', '28', '40'].includes(gstRate)) {
    await modal.locator('#product-gst').selectOption(gstRate);
  } else {
    await modal.locator('#product-gst').selectOption({ label: 'Other rate…' });
    await modal.locator('#product-gst-other').fill(gstRate);
  }
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
 * Example: 27ABCDE1234F1Z0 (synthetic, with a valid check digit)
 */
export function uniqueGstin(stateCode = '27') {
  const alpha = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
  const pick = () => alpha[Math.floor(Math.random() * 26)];
  const digit = () => String(Math.floor(Math.random() * 10));
  // Generate the first 14 characters, then append their Luhn mod-36 check digit.
  const prefix = `${stateCode}${pick()}${pick()}${pick()}${pick()}${pick()}${digit()}${digit()}${digit()}${digit()}${pick()}1Z`;
  const alphabet = `0123456789${alpha}`;
  let total = 0;
  for (let i = 0; i < prefix.length; i++) {
    const product = alphabet.indexOf(prefix[i]) * (i % 2 === 0 ? 1 : 2);
    total += Math.floor(product / 36) + product % 36;
  }
  return prefix + alphabet[(36 - total % 36) % 36];
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
  '/quotations': 'sales',
  '/invoices-view': 'sales',
  '/invoice-dues': 'sales',
  '/credit-notes': 'sales',
  '/cash-bank': 'sales',
  '/catalogue': 'catalogue',
  '/produce-items': 'catalogue',
  '/analytics': 'reports',
  '/day-book': 'reports',
  '/tax-ledger': 'reports',
  '/gstr3b': 'reports',
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

/**
 * Helper: tick "Search all FY" on the invoice feed.
 *
 * The checkbox lives in the Filters panel, which is collapsed until the
 * "Filters" toolbar button is pressed, so it cannot be ticked straight away.
 * Assumes the page is already showing /invoices-view.
 */
export async function searchAllFY(page: Page) {
  const filters = page.getByRole('button', { name: /^Filters/ });
  if ((await filters.getAttribute('aria-expanded')) !== 'true') {
    await filters.click();
  }
  await page.locator('label.invoice-feed-view__checkbox', { hasText: 'Search all FY' }).locator('input').check();
}

/**
 * Today as YYYY-MM-DD in the browser's local zone, which is what the app's date
 * inputs default to. `new Date().toISOString()` is UTC and disagrees with it
 * for a few hours either side of midnight anywhere but UTC.
 */
export function localToday() {
  return localDateString(new Date());
}

/** A Date as YYYY-MM-DD from its local parts (never via toISOString, which is UTC). */
export function localDateString(d: Date) {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** First day of the current month as YYYY-MM-DD, in the browser's local zone. */
export function localStartOfMonth() {
  const d = new Date();
  return localDateString(new Date(d.getFullYear(), d.getMonth(), 1));
}

/** The same day one year ago as YYYY-MM-DD, in the browser's local zone. */
export function localYearAgo() {
  const d = new Date();
  return localDateString(new Date(d.getFullYear() - 1, d.getMonth(), d.getDate()));
}

let salesDataSeeded = false;

/**
 * Helper: make sure the database holds at least one product, one ledger and
 * one sales invoice dated today, by creating them through the UI.
 *
 * It does not check what already exists: the first call in each worker always
 * seeds one product, one ledger and one invoice (names are unique, so this is
 * safe on a populated database), and later calls in that worker are no-ops. The
 * flag lives in module state, so a restarted worker (for example after a test
 * failure) seeds again.
 *
 * Specs that pick "the first option" of a combobox or measure a populated
 * report table cannot assume another spec (or a demo seed) ran first: a
 * database seeded as CONTRIBUTING.md describes holds only the admin user.
 */
export async function ensureSalesData(page: Page) {
  if (salesDataSeeded) return;
  const sku = uniqueSku();
  const ledgerName = `SeedLedger-${Date.now().toString(36)}`;

  await clickNavLink(page, '/catalogue');
  await createProduct(page, { sku, name: `SeedProd ${sku}`, price: '100', gstRate: '18' });
  await adjustInventory(page, sku, '10');

  await clickNavLink(page, '/ledgers');
  await page.click('button:has-text("Create ledger")');
  await page.fill('#ledger-name', ledgerName);
  await page.fill('#ledger-address', '1 Seed Street');
  await page.fill('#ledger-gst', uniqueGstin());
  await page.fill('#ledger-phone', '+91 9000000002');
  await page.click('button:has-text("Create ledger")');
  await expectSuccess(page, 'Ledger created');

  await clickNavLink(page, '/invoices');
  await expect(page.locator('#invoice-ledger')).not.toBeDisabled({ timeout: 5_000 });
  await page.selectOption('#invoice-voucher-type', 'sales');
  await selectComboboxOption(page, 'invoice-ledger', ledgerName);
  await selectComboboxOption(page, 'invoice-product-1', sku);
  await page.locator('[id^="invoice-quantity-"]').first().fill('1');
  await page.click('button:has-text("Create invoice")');
  await expectSuccess(page, 'Sales invoice created');

  // Creating an invoice pops the PDF preview over the whole page.
  const preview = page.locator('.modal-panel--invoice-preview');
  await expect(preview).toBeVisible({ timeout: 10_000 });
  await preview.getByRole('button', { name: 'Close invoice preview' }).click();
  await expect(preview).not.toBeVisible();

  salesDataSeeded = true;
}
