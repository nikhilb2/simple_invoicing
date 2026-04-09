import { test, expect, expectSuccess, uniqueSku, uniqueGstin, selectComboboxOption } from './fixtures';

/**
 * Helper: create a product (with stock) + ledger, navigate to /invoices, and
 * create one sales invoice.  Returns the SKU and ledger name so callers can
 * look up the row afterwards.
 */
async function createInvoicePrerequisites(page: Parameters<typeof selectComboboxOption>[0]) {
  const sku = uniqueSku();
  const ledgerName = `CancelTest-${Date.now().toString(36)}`;

  // Create product
  await page.click('[href="/products"]');
  await page.fill('#sku', sku);
  await page.fill('#name', `CancelProd ${sku}`);
  await page.fill('#price', '100');
  await page.fill('#gst-rate', '18');
  await page.click('button:has-text("Create product")');
  await expectSuccess(page, 'Product created');

  // Add inventory
  await page.click('[href="/inventory"]');
  // Wait for ProductCombobox to be enabled (products loaded)
  await expect(page.locator('#inventory-product')).not.toBeDisabled({ timeout: 10_000 });
  await selectComboboxOption(page, 'inventory-product', sku);
  await page.fill('#inventory-quantity', '50');
  await page.click('button:has-text("Apply adjustment")');
  await expectSuccess(page, 'Inventory updated');

  // Create ledger
  await page.click('[href="/ledgers"]');
  await page.click('button:has-text("Create ledger")');
  await page.fill('#ledger-name', ledgerName);
  await page.fill('#ledger-address', 'Cancel Street');
  await page.fill('#ledger-gst', uniqueGstin());
  await page.fill('#ledger-phone', '+91 9000000001');
  await page.click('button:has-text("Create ledger")');
  await expectSuccess(page, 'Ledger created');

  // Navigate to invoices and create one sales invoice
  await page.click('[href="/invoices"]');
  // Wait for LedgerCombobox to be enabled (ledgers loaded)
  await expect(page.locator('#invoice-ledger')).not.toBeDisabled({ timeout: 10_000 });
  await page.selectOption('#invoice-voucher-type', 'sales');

  await selectComboboxOption(page, 'invoice-ledger', ledgerName);

  // Select product in line 1
  await selectComboboxOption(page, 'invoice-product-1', sku);
  await page.locator('[id^="invoice-quantity-"]').first().fill('2');

  await page.click('button:has-text("Create invoice")');
  await expectSuccess(page, 'Sales invoice created');

  return { sku, ledgerName };
}

test.describe('Invoice cancellation', () => {
  test('Cancel button appears for active invoices', async ({ authedPage: page }) => {
    const { ledgerName } = await createInvoicePrerequisites(page);

    await page.click('[href="/invoices"]');
    const row = page.locator('.invoice-row', { hasText: ledgerName }).first();
    await expect(row).toBeVisible({ timeout: 10_000 });

    // Should have a Cancel button (Trash2 icon), not a Delete button label
    await expect(row.locator('button[title="Cancel invoice"]')).toBeVisible();
    // Should NOT have a Restore button
    await expect(row.locator('button[title="Restore invoice"]')).not.toBeVisible();
  });

  test('Cancelling an invoice shows Cancelled badge and hides it by default', async ({ authedPage: page }) => {
    const { ledgerName } = await createInvoicePrerequisites(page);

    await page.click('[href="/invoices"]');
    const row = page.locator('.invoice-row', { hasText: ledgerName }).first();
    await expect(row).toBeVisible({ timeout: 10_000 });

    // Click Cancel
    await row.locator('button[title="Cancel invoice"]').click();

    // Confirm in the dialog
    await expect(page.locator('.modal-overlay')).toBeVisible({ timeout: 5_000 });
    await page.click('button:has-text("Cancel invoice")');

    await expectSuccess(page, 'Invoice cancelled');

    // By default, cancelled invoices are hidden from the list
    await expect(page.locator('.invoice-row', { hasText: ledgerName })).not.toBeVisible();
  });

  test('Show Cancelled toggle reveals cancelled invoices with red badge', async ({ authedPage: page }) => {
    const { ledgerName } = await createInvoicePrerequisites(page);

    await page.click('[href="/invoices"]');
    const row = page.locator('.invoice-row', { hasText: ledgerName }).first();
    await expect(row).toBeVisible({ timeout: 10_000 });

    // Cancel the invoice
    await row.locator('button[title="Cancel invoice"]').click();
    await expect(page.locator('.modal-overlay')).toBeVisible({ timeout: 5_000 });
    await page.click('button:has-text("Cancel invoice")');
    await expectSuccess(page, 'Invoice cancelled');

    // Toggle "Show Cancelled"
    await page.click('#toggle-show-cancelled');
    await page.waitForTimeout(500);

    // Row is visible again
    const cancelledRow = page.locator('.invoice-row', { hasText: ledgerName }).first();
    await expect(cancelledRow).toBeVisible({ timeout: 10_000 });

    // Shows a red "Cancelled" badge
    await expect(cancelledRow.locator('text=Cancelled')).toBeVisible();

    // Edit button should be hidden, Restore button should be visible
    await expect(cancelledRow.locator('button[title="Restore invoice"]')).toBeVisible();
    await expect(cancelledRow.locator('button[title="Edit invoice"]')).not.toBeVisible();
    await expect(cancelledRow.locator('button[title="Cancel invoice"]')).not.toBeVisible();
  });

  test('Restoring a cancelled invoice brings it back to active', async ({ authedPage: page }) => {
    const { ledgerName } = await createInvoicePrerequisites(page);

    await page.click('[href="/invoices"]');
    const row = page.locator('.invoice-row', { hasText: ledgerName }).first();
    await expect(row).toBeVisible({ timeout: 10_000 });

    // Cancel it
    await row.locator('button[title="Cancel invoice"]').click();
    await expect(page.locator('.modal-overlay')).toBeVisible({ timeout: 5_000 });
    await page.click('button:has-text("Cancel invoice")');
    await expectSuccess(page, 'Invoice cancelled');

    // Show Cancelled
    await page.click('#toggle-show-cancelled');
    await page.waitForTimeout(500);

    const cancelledRow = page.locator('.invoice-row', { hasText: ledgerName }).first();
    await expect(cancelledRow).toBeVisible({ timeout: 10_000 });

    // Restore it
    await cancelledRow.locator('button[title="Restore invoice"]').click();
    await expectSuccess(page, 'Invoice restored');

    // Toggle back to "Hide Cancelled" mode (default)
    await page.click('#toggle-show-cancelled');
    await page.waitForTimeout(500);

    // Active invoice should be visible in the default list
    const restoredRow = page.locator('.invoice-row', { hasText: ledgerName }).first();
    await expect(restoredRow).toBeVisible({ timeout: 10_000 });

    // Should show Sales/Purchase badge, not Cancelled
    await expect(restoredRow.locator('text=Cancelled')).not.toBeVisible();
    await expect(restoredRow.locator('button[title="Cancel invoice"]')).toBeVisible();
    await expect(restoredRow.locator('button[title="Edit invoice"]')).toBeVisible();
  });

  test('Cancelled invoices still visible in Show Cancelled view across page reload', async ({ authedPage: page }) => {
    const { ledgerName } = await createInvoicePrerequisites(page);

    await page.click('[href="/invoices"]');
    const row = page.locator('.invoice-row', { hasText: ledgerName }).first();
    await expect(row).toBeVisible({ timeout: 10_000 });

    // Cancel it
    await row.locator('button[title="Cancel invoice"]').click();
    await expect(page.locator('.modal-overlay')).toBeVisible({ timeout: 5_000 });
    await page.click('button:has-text("Cancel invoice")');
    await expectSuccess(page, 'Invoice cancelled');

    // Navigate away and come back
    await page.click('[href="/products"]');
    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    // Still hidden in default view
    await expect(page.locator('.invoice-row', { hasText: ledgerName })).not.toBeVisible();

    // Toggle on
    await page.click('#toggle-show-cancelled');
    await page.waitForTimeout(500);

    await expect(page.locator('.invoice-row', { hasText: ledgerName }).first()).toBeVisible({ timeout: 10_000 });
  });
});
