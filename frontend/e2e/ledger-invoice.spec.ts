import { test, expect, expectSuccess, uniqueSku, uniqueGstin, selectComboboxOption, adjustInventory, clickNavLink } from './fixtures';

async function setStatementRangeToCurrentMonth(page: import('@playwright/test').Page) {
  const today = new Date();
  const startOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
  await page.locator('#statement-from').fill(startOfMonth.toISOString().split('T')[0]);
  await page.locator('#statement-to').fill(today.toISOString().split('T')[0]);
}

/**
 * Creating an invoice closes the create dialog and opens the PDF preview dialog.
 * Both are `.modal-overlay` role=dialog nodes, so locators must be scoped by
 * their aria-labelledby to tell them apart.
 */
function previewModal(page: import('@playwright/test').Page) {
  return page.locator('.modal-overlay[aria-labelledby="invoice-preview-title"]');
}

async function closePreview(page: import('@playwright/test').Page) {
  await previewModal(page).locator('button:has-text("Close")').click();
  await expect(previewModal(page)).not.toBeVisible({ timeout: 5_000 });
}

/**
 * The preview title reads "PDF invoice <number>". The statement rows are keyed by
 * that same reference number (the row never prints the words "sales"/"purchase"),
 * so we carry the number over to identify the entry we just created.
 */
async function readPreviewInvoiceNumber(page: import('@playwright/test').Page) {
  const title = (await previewModal(page).locator('#invoice-preview-title').innerText()).trim();
  const invoiceNumber = title.replace(/^PDF invoice\s*/i, '').trim();
  expect(invoiceNumber, 'created invoice should have a reference number').not.toBe('');
  return invoiceNumber;
}

test.describe('Create Invoice from Ledger View', () => {
  /**
   * Helper: set up a product with inventory and a ledger, then navigate to ledger view.
   */
  async function seedAndNavigateToLedger(page: import('@playwright/test').Page) {
    const sku = uniqueSku();
    const productName = `LI-Prod ${sku}`;
    const ledgerName = `LI-Ledger-${Date.now().toString(36)}`;

    // 1. Create product
    await clickNavLink(page, '/products');
    await page.fill('#sku', sku);
    await page.fill('#name', productName);
    await page.fill('#price', '500');
    await page.fill('#gst-rate', '18');
    await page.click('button:has-text("Create product")');
    await expectSuccess(page, 'Product created');

    // 2. Add inventory
    await clickNavLink(page, '/inventory');
    await page.waitForTimeout(500);
    await adjustInventory(page, sku, '100');
    await expectSuccess(page, 'Inventory updated');

    // 3. Create ledger
    await clickNavLink(page, '/ledgers');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Create ledger', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '111 Invoice Lane');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 3333333333');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expectSuccess(page, 'Ledger created');

    // 4. Navigate to ledger view – use search to find ledger in paginated list
    await page.fill('#ledger-search', ledgerName);
    await page.waitForTimeout(1_000);
    const row = page.locator('.table-row', { hasText: ledgerName });
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.locator('[aria-label^="View ledger"]').click();
    await expect(page.locator('h1')).toContainText(ledgerName, { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

    return { sku, productName, ledgerName };
  }

  test('creates a sales invoice from ledger view and sees it in statement', async ({ authedPage: page }) => {
    const { sku, ledgerName } = await seedAndNavigateToLedger(page);

    // Open the Create Invoice modal
    await page.click('[aria-label="More ledger actions"]');
    await page.click('[role="menuitem"][aria-label="Create Invoice"]');
    const modal = page.locator('.modal-overlay[aria-labelledby="create-invoice-modal-title"]');
    await expect(modal).toBeVisible({ timeout: 5_000 });

    // Verify modal title
    await expect(modal.locator('#create-invoice-modal-title')).toContainText('Create invoice');

    // Voucher type should default to sales
    await expect(modal.locator('#modal-inv-voucher-type')).toHaveValue('sales');

    // Ledger should be pre-selected (disabled)
    const ledgerSelect = modal.locator('#modal-inv-ledger');
    await expect(ledgerSelect).toBeDisabled();

    // Select product in first line item
    const productInputId = (await modal.locator('[id^="modal-inv-product-"]').first().getAttribute('id')) || 'modal-inv-product-1';
    await selectComboboxOption(page, productInputId, sku);

    // Set quantity
    await modal.locator('[id^="modal-inv-qty-"]').first().fill('2');

    // Submit
    await modal.locator('button:has-text("Create invoice")').click();
    await expect(page.locator('.toast--success')).toBeVisible({ timeout: 10_000 });
    await expect(modal).not.toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

    // The app closes the create dialog and opens the PDF preview for the new invoice.
    await expect(previewModal(page)).toBeVisible({ timeout: 10_000 });
    await expect(previewModal(page).locator('#invoice-preview-title')).toContainText('PDF invoice');
    const invoiceNumber = await readPreviewInvoiceNumber(page);

    // Close the preview; the ledger view refreshes its statement in place.
    // (Do not reload: on a fresh load the FY context resets the statement range
    // back to the active financial year and clobbers the range set below.)
    await closePreview(page);
    await setStatementRangeToCurrentMonth(page);
    await page.waitForTimeout(1_000);
    const salesEntry = page.locator('.invoice-row').filter({ hasText: invoiceNumber });
    await expect(salesEntry.first()).toBeVisible({ timeout: 10_000 });
    // A sales invoice debits the party ledger.
    await expect(salesEntry.first()).toContainText('Dr');
  });

  test('creates a purchase invoice from ledger view', async ({ authedPage: page }) => {
    const { sku } = await seedAndNavigateToLedger(page);

    // Open the Create Invoice modal
    await page.click('[aria-label="More ledger actions"]');
    await page.click('[role="menuitem"][aria-label="Create Invoice"]');
    const modal = page.locator('.modal-overlay[aria-labelledby="create-invoice-modal-title"]');
    await expect(modal).toBeVisible({ timeout: 5_000 });

    // Switch to purchase
    await modal.locator('#modal-inv-voucher-type').selectOption('purchase');

    // Select product
    const productInputId = (await modal.locator('[id^="modal-inv-product-"]').first().getAttribute('id')) || 'modal-inv-product-1';
    await selectComboboxOption(page, productInputId, sku);

    await modal.locator('[id^="modal-inv-qty-"]').first().fill('5');

    // Submit
    await modal.locator('button:has-text("Create invoice")').click();
    await expect(page.locator('.toast--success')).toBeVisible({ timeout: 10_000 });
    await expect(modal).not.toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

    // The app closes the create dialog and opens the PDF preview for the new invoice.
    await expect(previewModal(page)).toBeVisible({ timeout: 10_000 });
    await expect(previewModal(page).locator('#invoice-preview-title')).toContainText('PDF invoice');
    const invoiceNumber = await readPreviewInvoiceNumber(page);

    // Close the preview; the ledger view refreshes its statement in place.
    await closePreview(page);
    await setStatementRangeToCurrentMonth(page);
    await page.waitForTimeout(1_000);
    const purchaseEntry = page.locator('.invoice-row').filter({ hasText: invoiceNumber });
    await expect(purchaseEntry.first()).toBeVisible({ timeout: 10_000 });
    // A purchase invoice credits the party ledger.
    await expect(purchaseEntry.first()).toContainText('Cr');
  });

  test('can close modal without creating invoice', async ({ authedPage: page }) => {
    await seedAndNavigateToLedger(page);

    await page.click('[aria-label="More ledger actions"]');
    await page.click('[role="menuitem"][aria-label="Create Invoice"]');
    const modal = page.locator('.modal-overlay[aria-labelledby="create-invoice-modal-title"]');
    await expect(modal).toBeVisible({ timeout: 5_000 });

    // Click cancel
    await modal.locator('button:has-text("Cancel")').click();
    await expect(modal).not.toBeVisible({ timeout: 3_000 });
  });
});

test.describe('Ledger View Actions Dropdown', () => {
  test('dropdown opens on caret click and shows both actions', async ({ authedPage: page }) => {
    // Create a minimal ledger and navigate to its view page
    await clickNavLink(page, '/ledgers');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Create ledger', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    const ledgerName = `DropdownLedger-${Date.now().toString(36)}`;
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '1 Dropdown Rd');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 1111111111');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

    await page.fill('#ledger-search', ledgerName);
    await page.waitForTimeout(1_000);
    const row = page.locator('.table-row', { hasText: ledgerName });
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.locator('[aria-label^="View ledger"]').click();
    await expect(page.locator('h1')).toContainText(ledgerName, { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

    // Dropdown is closed initially
    await expect(page.locator('[role="menuitem"][aria-label="Send Reminder"]')).not.toBeVisible();
    await expect(page.locator('[role="menuitem"][aria-label="Create Invoice"]')).not.toBeVisible();

    // Open dropdown via caret button
    await page.click('[aria-label="More ledger actions"]');

    // Both menu items should now be visible
    await expect(page.locator('[role="menuitem"][aria-label="Send Reminder"]')).toBeVisible({ timeout: 3_000 });
    await expect(page.locator('[role="menuitem"][aria-label="Create Invoice"]')).toBeVisible({ timeout: 3_000 });
  });

  test('dropdown closes when clicking outside', async ({ authedPage: page }) => {
    await clickNavLink(page, '/ledgers');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Create ledger', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    const ledgerName = `DropdownClose-${Date.now().toString(36)}`;
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '2 Close Rd');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 2222222222');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

    await page.fill('#ledger-search', ledgerName);
    await page.waitForTimeout(1_000);
    const row = page.locator('.table-row', { hasText: ledgerName });
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.locator('[aria-label^="View ledger"]').click();
    await expect(page.locator('h1')).toContainText(ledgerName, { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

    // Open dropdown
    await page.click('[aria-label="More ledger actions"]');
    await expect(page.locator('[role="menuitem"][aria-label="Send Reminder"]')).toBeVisible({ timeout: 3_000 });

    // Click outside — click on the page heading
    await page.click('h1');
    await expect(page.locator('[role="menuitem"][aria-label="Send Reminder"]')).not.toBeVisible({ timeout: 3_000 });
  });
});
