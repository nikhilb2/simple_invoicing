import { test, expect, uniqueGstin, expectSuccess } from './fixtures';

/**
 * Financial year used for all warning tests.
 * Using a far-future year to avoid collisions with real / other test data.
 */
const TEST_FY_START_YEAR = 2031;
const TEST_FY_LABEL = '2031-32';
const DATE_INSIDE_FY = '2031-08-15';         // within 2031-04-01 … 2032-03-31
const DATE_OUTSIDE_FY_BEFORE = '2031-01-01'; // before FY start
const DATE_OUTSIDE_FY_AFTER = '2032-06-01';  // after FY end

/**
 * Ensure the test FY exists and is the active FY.
 * Creates it if missing, then clicks it in the nav switcher to activate it.
 */
async function activateTestFY(page: import('@playwright/test').Page) {
  const fyButton = page.locator('button[aria-haspopup="listbox"]');
  await fyButton.click();
  const listbox = page.locator('[role="listbox"]');
  await expect(listbox).toBeVisible({ timeout: 5_000 });

  const existingOption = listbox.locator(`button:has-text("${TEST_FY_LABEL}")`).first();
  if (!(await existingOption.isVisible())) {
    // Create the FY
    await listbox.locator('button:has-text("+ New FY")').click();
    const dialog = page.locator('[role="dialog"][aria-label="Create new financial year"]');
    await expect(dialog).toBeVisible({ timeout: 5_000 });
    await dialog.locator('input[type="number"]').fill(String(TEST_FY_START_YEAR));
    await dialog.locator('button:has-text("Create")').click();
    await expect(dialog).not.toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    // Reopen dropdown to activate
    await fyButton.click();
    await expect(listbox).toBeVisible({ timeout: 5_000 });
  }

  // Click the FY button to activate it
  await listbox.locator(`button:has-text("${TEST_FY_LABEL}")`).first().click();
  // Dismiss dropdown if still open
  if (await listbox.isVisible()) {
    await page.locator('h1').first().click();
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Invoice form on InvoicesPage
// ─────────────────────────────────────────────────────────────────────────────

test.describe('FY Date Warning — InvoicesPage invoice form', () => {
  test('shows warning when invoice date is before active FY start', async ({ authedPage: page }) => {
    await activateTestFY(page);
    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.fill('#invoice-date', DATE_OUTSIDE_FY_BEFORE);

    const warning = page.locator('.field-warning');
    await expect(warning).toBeVisible({ timeout: 3_000 });
    await expect(warning).toContainText('outside the active financial year');
    await expect(warning).toContainText(TEST_FY_LABEL);
  });

  test('shows warning when invoice date is after active FY end', async ({ authedPage: page }) => {
    await activateTestFY(page);
    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.fill('#invoice-date', DATE_OUTSIDE_FY_AFTER);

    await expect(page.locator('.field-warning')).toBeVisible({ timeout: 3_000 });
    await expect(page.locator('.field-warning')).toContainText('outside the active financial year');
  });

  test('warning disappears when invoice date is moved inside active FY', async ({ authedPage: page }) => {
    await activateTestFY(page);
    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    // Trigger warning
    await page.fill('#invoice-date', DATE_OUTSIDE_FY_BEFORE);
    await expect(page.locator('.field-warning')).toBeVisible({ timeout: 3_000 });

    // Move inside FY — warning should vanish
    await page.fill('#invoice-date', DATE_INSIDE_FY);
    await expect(page.locator('.field-warning')).not.toBeVisible({ timeout: 3_000 });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Create Invoice modal on LedgerViewPage
// ─────────────────────────────────────────────────────────────────────────────

test.describe('FY Date Warning — CreateInvoiceModal (LedgerView)', () => {
  async function seedLedgerAndNavigate(page: import('@playwright/test').Page) {
    const ledgerName = `FYWarnInv-${Date.now().toString(36)}`;
    await page.click('[href="/ledgers"]');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Create ledger', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '1 FY Warn Ln');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 2222222222');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expectSuccess(page, 'Ledger created');

    await page.fill('#ledger-search', ledgerName);
    await page.waitForTimeout(500);
    const row = page.locator('.table-row', { hasText: ledgerName });
    await expect(row).toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await row.locator('[aria-label^="View ledger"]').click();
    await expect(page.locator('h1')).toContainText(ledgerName, { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
  }

  test('shows warning when invoice date is outside active FY', async ({ authedPage: page }) => {
    await activateTestFY(page);
    await seedLedgerAndNavigate(page);

    await page.click('[aria-label="More ledger actions"]');
    await page.click('[role="menuitem"][aria-label="Create Invoice"]');
    const modal = page.locator('.modal-overlay');
    await expect(modal).toBeVisible({ timeout: 5_000 });

    await modal.locator('#modal-inv-date').fill(DATE_OUTSIDE_FY_BEFORE);

    await expect(modal.locator('.field-warning')).toBeVisible({ timeout: 3_000 });
    await expect(modal.locator('.field-warning')).toContainText('outside the active financial year');
    await expect(modal.locator('.field-warning')).toContainText(TEST_FY_LABEL);
  });

  test('warning disappears when invoice modal date is moved inside FY', async ({ authedPage: page }) => {
    await activateTestFY(page);
    await seedLedgerAndNavigate(page);

    await page.click('[aria-label="More ledger actions"]');
    await page.click('[role="menuitem"][aria-label="Create Invoice"]');
    const modal = page.locator('.modal-overlay');
    await expect(modal).toBeVisible({ timeout: 5_000 });

    await modal.locator('#modal-inv-date').fill(DATE_OUTSIDE_FY_BEFORE);
    await expect(modal.locator('.field-warning')).toBeVisible({ timeout: 3_000 });

    await modal.locator('#modal-inv-date').fill(DATE_INSIDE_FY);
    await expect(modal.locator('.field-warning')).not.toBeVisible({ timeout: 3_000 });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Record Payment modal on LedgerViewPage
// ─────────────────────────────────────────────────────────────────────────────

test.describe('FY Date Warning — Payment form (LedgerView)', () => {
  async function seedLedgerAndOpenPaymentModal(page: import('@playwright/test').Page) {
    const ledgerName = `FYWarnPay-${Date.now().toString(36)}`;
    await page.click('[href="/ledgers"]');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Create ledger', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '2 FY Pay Ave');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 5555555555');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expectSuccess(page, 'Ledger created');

    await page.fill('#ledger-search', ledgerName);
    await page.waitForTimeout(500);
    const row = page.locator('.table-row', { hasText: ledgerName });
    await expect(row).toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await row.locator('[aria-label^="View ledger"]').click();
    await expect(page.locator('h1')).toContainText(ledgerName, { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

    await page.click('button:has-text("Record Receipt / Payment")');
    const modal = page.locator('.modal-overlay');
    await expect(modal).toBeVisible({ timeout: 5_000 });
    return modal;
  }

  test('shows warning when payment date is before active FY start', async ({ authedPage: page }) => {
    await activateTestFY(page);
    const modal = await seedLedgerAndOpenPaymentModal(page);

    // datetime-local format: YYYY-MM-DDTHH:MM
    await modal.locator('#pay-date').fill(`${DATE_OUTSIDE_FY_BEFORE}T10:00`);

    await expect(modal.locator('.field-warning')).toBeVisible({ timeout: 3_000 });
    await expect(modal.locator('.field-warning')).toContainText('outside the active financial year');
    await expect(modal.locator('.field-warning')).toContainText(TEST_FY_LABEL);
  });

  test('shows warning when payment date is after active FY end', async ({ authedPage: page }) => {
    await activateTestFY(page);
    const modal = await seedLedgerAndOpenPaymentModal(page);

    await modal.locator('#pay-date').fill(`${DATE_OUTSIDE_FY_AFTER}T10:00`);

    await expect(modal.locator('.field-warning')).toBeVisible({ timeout: 3_000 });
    await expect(modal.locator('.field-warning')).toContainText('outside the active financial year');
  });

  test('warning disappears when payment date is moved inside FY', async ({ authedPage: page }) => {
    await activateTestFY(page);
    const modal = await seedLedgerAndOpenPaymentModal(page);

    await modal.locator('#pay-date').fill(`${DATE_OUTSIDE_FY_BEFORE}T10:00`);
    await expect(modal.locator('.field-warning')).toBeVisible({ timeout: 3_000 });

    await modal.locator('#pay-date').fill(`${DATE_INSIDE_FY}T10:00`);
    await expect(modal.locator('.field-warning')).not.toBeVisible({ timeout: 3_000 });
  });
});
