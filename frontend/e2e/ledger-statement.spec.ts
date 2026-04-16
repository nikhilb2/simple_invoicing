import { test, expect, expectSuccess, uniqueSku, uniqueGstin, selectComboboxOption } from './fixtures';

test.describe('Ledger Statement', () => {
  test('shows period statement for a ledger', async ({ authedPage: page }) => {
    // Create a ledger first via the create page
    await page.click('[href="/ledgers"]');
    await expect(page.locator('h1')).toContainText('Ledger master');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Create ledger', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

    const ledgerName = `StmtLedger-${Date.now().toString(36)}`;
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '456 Statement Rd');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 6666666666');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expectSuccess(page, 'Ledger created');

    // Click View on the created ledger to go to statement page
    await page.fill('#ledger-search', ledgerName);
    await page.waitForTimeout(500);
    const row = page.locator('.table-row', { hasText: ledgerName });
    await expect(row).toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await row.locator('[aria-label^="View ledger"]').click();
    await expect(page.locator('h1')).toContainText(ledgerName, { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

    // Check for period selection inputs
    const fromInput = page.locator('#statement-from');
    const toInput = page.locator('#statement-to');
    await expect(fromInput).toBeVisible();
    await expect(toInput).toBeVisible();

    // Set date range
    const today = new Date();
    const startOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
    await fromInput.fill(startOfMonth.toISOString().split('T')[0]);
    await toInput.fill(today.toISOString().split('T')[0]);
    await page.waitForTimeout(1_000);
  });

  test('opens invoice preview from ledger view page and shows correct values', async ({ authedPage: page }) => {
    const sku = uniqueSku();
    const productName = `LSProd ${sku}`;
    const ledgerName = `LSLedger-${Date.now().toString(36)}`;

    // 1. Create product
    await page.click('[href="/products"]');
    await page.fill('#sku', sku);
    await page.fill('#name', productName);
    await page.fill('#price', '200');
    await page.fill('#gst-rate', '18');
    await page.click('button:has-text("Create product")');
    await expectSuccess(page, 'Product created');

    // 2. Add inventory
    await page.click('[href="/inventory"]');
    await expect(page.locator('#inventory-product')).not.toBeDisabled({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await selectComboboxOption(page, 'inventory-product', sku);
    await page.fill('#inventory-quantity', '100');
    await page.click('button:has-text("Apply adjustment")');
    await expectSuccess(page, 'Inventory updated');

    // 3. Create ledger via create page
    await page.click('[href="/ledgers"]');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Create ledger', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '123 Test Street');
    const gstin = uniqueGstin();
    await page.fill('#ledger-gst', gstin);
    await page.fill('#ledger-phone', '+91 5555555555');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expectSuccess(page, 'Ledger created');

    // 4. Create a sales invoice for this ledger
    await page.click('[href="/invoices"]');
    await expect(page.locator('#invoice-ledger')).not.toBeDisabled({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await page.selectOption('#invoice-voucher-type', 'sales');
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);

    const productInputId = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId, sku);

    await page.locator('[id^="invoice-quantity-"]').first().fill('3');
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'invoice created');

    // 5. Navigate to ledger view page via the list
    await page.click('[href="/ledgers"]');
    await page.waitForTimeout(500);
    await page.fill('#ledger-search', ledgerName);
    await page.waitForTimeout(1_000);
    const ledgerRow = page.locator('.table-row', { hasText: ledgerName });
    await expect(ledgerRow).toBeVisible({ timeout: 10_000 });
    await ledgerRow.locator('[aria-label^="View ledger"]').click();
    await expect(page.locator('h1')).toContainText(ledgerName, { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

    // Set date range covering today
    const today = new Date();
    const startOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
    await page.locator('#statement-from').fill(startOfMonth.toISOString().split('T')[0]);
    await page.locator('#statement-to').fill(today.toISOString().split('T')[0]);
    await page.waitForTimeout(1_000);

    // 6. Verify entry shows in the statement, then click View
    const entryRow = page.locator('.invoice-row').filter({ hasText: /sales/i });
    await expect(entryRow.first()).toBeVisible({ timeout: 10_000 });
    await entryRow.first().locator('button:has-text("View")').click();

    // 7. Verify the invoice preview modal opens with the current PDF preview UI
    const previewModal = page.locator('.modal-panel--invoice-preview');
    await expect(previewModal).toBeVisible({ timeout: 5_000 });

    await expect(previewModal.locator('#invoice-preview-title')).toContainText('PDF invoice');
    await expect(previewModal.getByRole('button', { name: 'Download invoice PDF' })).toBeVisible();
    await expect(previewModal.getByRole('button', { name: 'Email invoice' })).toBeVisible();
    await expect(previewModal.locator('iframe.invoice-pdf-viewer__frame')).toBeVisible();

    // Close the preview
    await previewModal.locator('button:has-text("Close")').click();
    await expect(previewModal).not.toBeVisible();
  });
});
