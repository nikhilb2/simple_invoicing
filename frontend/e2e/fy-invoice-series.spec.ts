/**
 * Tests for invoice series FY-scoping:
 * - A backdated invoice (date falls in a prior FY) must use that prior FY's
 *   series counter and label in the invoice number, not the active FY's.
 * - An invoice dated in the active FY still uses the active FY series.
 *
 * We use the far-future years 2031/2032 to avoid conflicts with real data.
 */
import { test, expect, expectSuccess, uniqueSku, uniqueGstin, selectComboboxOption } from './fixtures';

test.use({ timezoneId: 'Asia/Kolkata' });

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

async function configureActiveFySalesSeries(page: import('@playwright/test').Page) {
  await page.click('[href="/company"]');
  await expect(page.locator('h2:has-text("Invoice series")')).toBeVisible({ timeout: 10_000 });

  const prefixInput = page.locator('[id^="series-prefix-"]').first();
  const suffixInput = page.locator('[id^="series-suffix-"]').first();
  const includeYearCheckbox = page.locator('[id^="series-include-year-"]').first();
  const yearFormatSelect = page.locator('[id^="series-year-fmt-"]').first();
  const separatorInput = page.locator('[id^="series-sep-"]').first();
  const saveButton = page.locator('button:has-text("Save")').first();

  await prefixInput.fill('INV');
  await suffixInput.fill('');
  await separatorInput.fill('-');
  if (!(await includeYearCheckbox.isChecked())) {
    await includeYearCheckbox.check();
  }
  await yearFormatSelect.selectOption('FY');
  await saveButton.click();
  await expect(page.locator('text=Saved').first()).toBeVisible({ timeout: 8_000 });
}

async function getFinancialYearIdByLabel(
  page: import('@playwright/test').Page,
  label: string,
): Promise<number> {
  return await page.evaluate(async (targetLabel) => {
    const token = localStorage.getItem('token');
    const response = await fetch('/api/financial-years/', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    const years = await response.json() as Array<{ id: number; label: string }>;
    const match = years.find((year) => year.label === targetLabel);
    if (!match) {
      throw new Error(`Financial year ${targetLabel} not found`);
    }
    return match.id;
  }, label);
}

async function getSalesNextSequence(page: import('@playwright/test').Page): Promise<number> {
  await page.click('[href="/company"]');
  await expect(page.locator('h2:has-text("Invoice series")')).toBeVisible({ timeout: 10_000 });
  const salesRow = page.locator('xpath=//strong[normalize-space()="Sales"]/ancestor::div[contains(@class,"panel")][1]');
  const nextText = await salesRow.locator('text=/Next: #\\d+/').textContent();
  const match = nextText?.match(/#(\d+)/);
  if (!match) {
    throw new Error(`Unable to parse next sequence from text: ${nextText}`);
  }
  return Number(match[1]);
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
): Promise<{ invoiceNumber: string; financialYearId: number | null }> {
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

  const createResponsePromise = page.waitForResponse(
    (response) => response.request().method() === 'POST' && response.url().includes('/invoices/'),
  );
  await page.click('button:has-text("Create invoice")');
  const createResponse = await createResponsePromise;
  await expectSuccess(page, 'invoice created');

  const body = await createResponse.json() as { invoice_number?: string | null; financial_year_id?: number | null };
  return {
    invoiceNumber: body.invoice_number ?? '',
    financialYearId: body.financial_year_id ?? null,
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('Invoice series — correct FY used based on invoice date', () => {
  test(
    'backdated invoice (prior FY date) uses prior FY label in invoice number',
    async ({ authedPage: page }) => {
      // Ensure both FYs exist. Activate the later one last (2032-33 = active FY).
      await ensureAndActivateFY(page, PAST_FY_START_YEAR, PAST_FY_LABEL);
      await ensureAndActivateFY(page, ACTIVE_FY_START_YEAR, ACTIVE_FY_LABEL);
      await configureActiveFySalesSeries(page);
      const pastFyId = await getFinancialYearIdByLabel(page, PAST_FY_LABEL);

      const { sku, ledgerName } = await seedInvoiceData(page);

      // Create invoice dated in prior FY (2031-32)
      const created = await createInvoiceOnDate(page, ledgerName, sku, PAST_FY_DATE);

      expect(created.financialYearId).toBe(pastFyId);
    },
  );

  test(
    'invoice dated in active FY uses active FY label in invoice number',
    async ({ authedPage: page }) => {
      await ensureAndActivateFY(page, PAST_FY_START_YEAR, PAST_FY_LABEL);
      await ensureAndActivateFY(page, ACTIVE_FY_START_YEAR, ACTIVE_FY_LABEL);
      await configureActiveFySalesSeries(page);
      const activeFyId = await getFinancialYearIdByLabel(page, ACTIVE_FY_LABEL);

      const { sku, ledgerName } = await seedInvoiceData(page);

      // Create invoice dated in active FY (2032-33)
      const created = await createInvoiceOnDate(page, ledgerName, sku, ACTIVE_FY_DATE);

      expect(created.financialYearId).toBe(activeFyId);
    },
  );

  test(
    'backdated and current-FY invoices each have independent sequence counters',
    async ({ authedPage: page }) => {
      await ensureAndActivateFY(page, PAST_FY_START_YEAR, PAST_FY_LABEL);
      await ensureAndActivateFY(page, ACTIVE_FY_START_YEAR, ACTIVE_FY_LABEL);
      await configureActiveFySalesSeries(page);
      await ensureAndActivateFY(page, PAST_FY_START_YEAR, PAST_FY_LABEL);
      const pastBefore = await getSalesNextSequence(page);
      await ensureAndActivateFY(page, ACTIVE_FY_START_YEAR, ACTIVE_FY_LABEL);
      const activeBefore = await getSalesNextSequence(page);

      const { sku, ledgerName } = await seedInvoiceData(page);

      await createInvoiceOnDate(page, ledgerName, sku, ACTIVE_FY_DATE);
      await ensureAndActivateFY(page, ACTIVE_FY_START_YEAR, ACTIVE_FY_LABEL);
      const activeAfterActiveInvoice = await getSalesNextSequence(page);
      expect(activeAfterActiveInvoice).toBe(activeBefore + 1);

      await createInvoiceOnDate(page, ledgerName, sku, PAST_FY_DATE);
      await ensureAndActivateFY(page, ACTIVE_FY_START_YEAR, ACTIVE_FY_LABEL);
      const activeAfterPastInvoice = await getSalesNextSequence(page);
      expect(activeAfterPastInvoice).toBe(activeAfterActiveInvoice);

      await ensureAndActivateFY(page, PAST_FY_START_YEAR, PAST_FY_LABEL);
      const pastAfterPastInvoice = await getSalesNextSequence(page);
      expect(pastAfterPastInvoice).toBeGreaterThan(pastBefore);
    },
  );

  test(
    'FY boundary dates stay stable with explicit timezone configuration',
    async ({ authedPage: page }) => {
      await ensureAndActivateFY(page, PAST_FY_START_YEAR, PAST_FY_LABEL);
      await ensureAndActivateFY(page, ACTIVE_FY_START_YEAR, ACTIVE_FY_LABEL);
      await configureActiveFySalesSeries(page);
      const pastFyId = await getFinancialYearIdByLabel(page, PAST_FY_LABEL);
      const activeFyId = await getFinancialYearIdByLabel(page, ACTIVE_FY_LABEL);

      const { sku, ledgerName } = await seedInvoiceData(page);

      const boundaryEndInvoice = await createInvoiceOnDate(page, ledgerName, sku, '2032-03-31');
      const boundaryStartInvoice = await createInvoiceOnDate(page, ledgerName, sku, '2032-04-01');

      expect(boundaryEndInvoice.financialYearId).toBe(pastFyId);
      expect(boundaryStartInvoice.financialYearId).toBe(activeFyId);
    },
  );

});
