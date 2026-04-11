/**
 * Tests for invoice series FY-scoping:
 * - A backdated invoice (date falls in a prior FY) must use that prior FY's
 *   series counter and label in the invoice number, not the active FY's.
 * - An invoice dated in the active FY still uses the active FY series.
 *
 * We use the far-future years 2031/2032 to avoid conflicts with real data.
 */
import { test, expect, expectSuccess, uniqueSku, uniqueGstin, selectComboboxOption } from './fixtures';

// ── FY constants ─────────────────────────────────────────────────────────────
const PAST_FY_START_YEAR = 2031;
const PAST_FY_LABEL = '2031-32';
const PAST_FY_DATE = '2031-10-15'; // inside 2031-04-01 … 2032-03-31

const ACTIVE_FY_START_YEAR = 2032;
const ACTIVE_FY_LABEL = '2032-33';
const ACTIVE_FY_DATE = '2032-10-15'; // inside 2032-04-01 … 2033-03-31

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Ensure a financial year exists and activate it.
 * Creates the FY if missing, then clicks it to activate.
 * Clicking an FY option calls setFyDropdownOpen(false), so the dropdown is
 * always closed when this function returns — safe to call multiple times in
 * sequence.
 */
async function ensureAndActivateFY(
  page: import('@playwright/test').Page,
  startYear: number,
  label: string,
) {
  const fyButton = page.locator('button[aria-haspopup="listbox"]');
  await fyButton.click();
  const listbox = page.locator('[role="listbox"]');
  await expect(listbox).toBeVisible({ timeout: 5_000 });

  const existing = listbox.locator(`button:has-text("${label}")`).first();
  if (!(await existing.isVisible())) {
    await listbox.locator('button:has-text("+ New FY")').click();
    const dialog = page.locator('[role="dialog"][aria-label="Create new financial year"]');
    await expect(dialog).toBeVisible({ timeout: 5_000 });
    await dialog.locator('input[type="number"]').fill(String(startYear));
    await dialog.locator('button:has-text("Create")').click();
    await expect(dialog).not.toBeVisible({ timeout: 10_000 });
    // Reopen the dropdown to activate
    await fyButton.click();
    await expect(listbox).toBeVisible({ timeout: 5_000 });
  }

  // Activate by clicking the FY option — this also calls setFyDropdownOpen(false)
  await listbox.locator(`button:has-text("${label}")`).first().click();
  if (await listbox.isVisible()) {
    await page.locator('h1').first().click();
  }
}

/** Create a product + ledger + inventory seeded for invoicing. */
async function seedInvoiceData(page: import('@playwright/test').Page) {
  const sku = uniqueSku();
  const productName = `FYSeries-${sku}`;
  const ledgerName = `FYSeriesLedger-${Date.now().toString(36)}`;

  // Product
  await page.click('[href="/products"]');
  await page.fill('#sku', sku);
  await page.fill('#name', productName);
  await page.fill('#price', '100');
  await page.fill('#gst-rate', '18');
  await page.click('button:has-text("Create product")');
  await expectSuccess(page, 'Product created');

  // Inventory
  await page.click('[href="/inventory"]');
  await page.waitForTimeout(500);
  await selectComboboxOption(page, 'inventory-product', sku);
  await page.fill('#inventory-quantity', '100');
  await page.click('button:has-text("Apply adjustment")');
  await expectSuccess(page, 'Inventory updated');

  // Ledger
  await page.click('[href="/ledgers"]');
  await page.click('button:has-text("Create ledger")');
  await page.fill('#ledger-name', ledgerName);
  await page.fill('#ledger-address', '1 FY Series Rd');
  await page.fill('#ledger-gst', uniqueGstin());
  await page.fill('#ledger-phone', '+91 9999911111');
  await page.click('button:has-text("Create ledger")');
  await expectSuccess(page, 'Ledger created');

  return { sku, ledgerName };
}

/** Create an invoice with a given date and return the invoice number shown. */
async function createInvoiceOnDate(
  page: import('@playwright/test').Page,
  ledgerName: string,
  sku: string,
  invoiceDate: string,
): Promise<string> {
  await page.click('[href="/invoices"]');
  await page.waitForTimeout(500);

  await page.selectOption('#invoice-voucher-type', 'sales');
  await selectComboboxOption(page, 'invoice-ledger', ledgerName);

  const productInputId =
    (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) ??
    'invoice-product-1';
  await selectComboboxOption(page, productInputId, sku);
  await page.locator('[id^="invoice-quantity-"]').first().fill('1');

  await page.fill('#invoice-date', invoiceDate);

  await page.click('button:has-text("Create invoice")');
  await expectSuccess(page, 'invoice created');

  // Grab the invoice number from the first row in the list
  const firstRow = page.locator('.invoice-row').first();
  await expect(firstRow).toBeVisible({ timeout: 10_000 });
  const numberEl = firstRow.locator('.invoice-row__invoice-id').first();
  await expect(numberEl).toBeVisible({ timeout: 5_000 });
  const text = (await numberEl.textContent()) ?? '';
  // Strip leading "Invoice " prefix
  return text.replace(/^Invoice\s+/i, '').trim();
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('Invoice series — correct FY used based on invoice date', () => {
  test(
    'backdated invoice (prior FY date) uses prior FY label in invoice number',
    async ({ authedPage: page }) => {
      // Ensure both FYs exist. Activate the later one last (2032-33 = active FY).
      await ensureAndActivateFY(page, PAST_FY_START_YEAR, PAST_FY_LABEL);
      await ensureAndActivateFY(page, ACTIVE_FY_START_YEAR, ACTIVE_FY_LABEL);

      const { sku, ledgerName } = await seedInvoiceData(page);

      // Create invoice dated in prior FY (2031-32)
      const invoiceNumber = await createInvoiceOnDate(page, ledgerName, sku, PAST_FY_DATE);

      // The invoice number must contain the prior FY's start year (2031).
      // Works for all year formats:
      //   FY      → "RES-2031-32-0001" (contains 2031, not 2032)
      //   MM-YYYY → "RES-10-2031-0001" (contains 2031, not 2032)
      //   YYYY    → "RES-2031-0001"    (contains 2031, not 2032)
      expect(invoiceNumber).toContain(String(PAST_FY_START_YEAR));
      expect(invoiceNumber).not.toContain(String(ACTIVE_FY_START_YEAR));
    },
  );

  test(
    'invoice dated in active FY uses active FY label in invoice number',
    async ({ authedPage: page }) => {
      await ensureAndActivateFY(page, PAST_FY_START_YEAR, PAST_FY_LABEL);
      await ensureAndActivateFY(page, ACTIVE_FY_START_YEAR, ACTIVE_FY_LABEL);

      const { sku, ledgerName } = await seedInvoiceData(page);

      // Create invoice dated in active FY (2032-33)
      const invoiceNumber = await createInvoiceOnDate(page, ledgerName, sku, ACTIVE_FY_DATE);

      expect(invoiceNumber).toContain(String(ACTIVE_FY_START_YEAR));
    },
  );

  test(
    'backdated and current-FY invoices each have independent sequence counters',
    async ({ authedPage: page }) => {
      await ensureAndActivateFY(page, PAST_FY_START_YEAR, PAST_FY_LABEL);
      await ensureAndActivateFY(page, ACTIVE_FY_START_YEAR, ACTIVE_FY_LABEL);

      const { sku, ledgerName } = await seedInvoiceData(page);

      const num1 = await createInvoiceOnDate(page, ledgerName, sku, ACTIVE_FY_DATE);
      const num2 = await createInvoiceOnDate(page, ledgerName, sku, PAST_FY_DATE);
      const num3 = await createInvoiceOnDate(page, ledgerName, sku, ACTIVE_FY_DATE);

      // num1 and num3 are both in active FY — num3 sequence should be higher
      const seq = (n: string) => parseInt(n.replace(/\D+/g, '').slice(-4), 10);
      expect(seq(num3)).toBeGreaterThan(seq(num1));

      // num2 is in the prior FY — its number contains 2031, not 2032
      expect(num2).toContain(String(PAST_FY_START_YEAR));
      expect(num2).not.toContain(String(ACTIVE_FY_START_YEAR));
      // num1 and num3 are in the active FY — their numbers contain 2032
      expect(num1).toContain(String(ACTIVE_FY_START_YEAR));
    },
  );
});
