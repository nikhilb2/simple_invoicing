import { test, expect, expectSuccess, uniqueSku, uniqueGstin } from './fixtures';

test.describe('Ledger Statement', () => {
  test('shows period statement for a ledger', async ({ authedPage: page }) => {
    // Create a ledger first via the create page
    await page.click('[href="/ledgers"]');
    await expect(page.locator('h1')).toContainText('Ledger master');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Create ledger', { timeout: 10_000 });

    const ledgerName = `StmtLedger-${Date.now().toString(36)}`;
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '456 Statement Rd');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 6666666666');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: 10_000 });
    await expectSuccess(page, 'Ledger created');

    // Click View on the created ledger to go to statement page
    await page.fill('#ledger-search', ledgerName);
    await page.waitForTimeout(500);
    const row = page.locator('.table-row', { hasText: ledgerName });
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.locator('[aria-label^="View ledger"]').click();
    await expect(page.locator('h1')).toContainText(ledgerName, { timeout: 10_000 });

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
    await page.waitForTimeout(500);
    const inventorySelect = page.locator('#inventory-product');
    const invOptions = inventorySelect.locator('option');
    const invCount = await invOptions.count();
    for (let i = 0; i < invCount; i++) {
      const text = await invOptions.nth(i).textContent();
      if (text?.includes(sku)) {
        const val = (await invOptions.nth(i).getAttribute('value')) || '';
        await inventorySelect.selectOption(val);
        break;
      }
    }
    await page.fill('#inventory-quantity', '100');
    await page.click('button:has-text("Apply adjustment")');
    await expectSuccess(page, 'Inventory updated');

    // 3. Create ledger via create page
    await page.click('[href="/ledgers"]');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Create ledger', { timeout: 10_000 });
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '123 Test Street');
    const gstin = uniqueGstin();
    await page.fill('#ledger-gst', gstin);
    await page.fill('#ledger-phone', '+91 5555555555');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: 10_000 });
    await expectSuccess(page, 'Ledger created');

    // 4. Create a sales invoice for this ledger
    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);
    await page.selectOption('#invoice-voucher-type', 'sales');

    const ledgerSelect = page.locator('#invoice-ledger');
    const ledgerOptions = ledgerSelect.locator('option');
    const ledgerCount = await ledgerOptions.count();
    for (let i = 0; i < ledgerCount; i++) {
      const text = await ledgerOptions.nth(i).textContent();
      if (text?.includes(ledgerName)) {
        const val = (await ledgerOptions.nth(i).getAttribute('value')) || '';
        await ledgerSelect.selectOption(val);
        break;
      }
    }

    const productSelect = page.locator('[id^="invoice-product-"]').first();
    const prodOptions = productSelect.locator('option');
    const prodCount = await prodOptions.count();
    for (let i = 0; i < prodCount; i++) {
      const text = await prodOptions.nth(i).textContent();
      if (text?.includes(sku)) {
        const val = (await prodOptions.nth(i).getAttribute('value')) || '';
        await productSelect.selectOption(val);
        break;
      }
    }

    await page.locator('[id^="invoice-quantity-"]').first().fill('3');
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'invoice created');

    // 5. Navigate to ledger view page via the list
    await page.click('[href="/ledgers"]');
    await page.waitForTimeout(500);
    await page.fill('#ledger-search', ledgerName);
    await page.waitForTimeout(500);
    const ledgerRow = page.locator('.table-row', { hasText: ledgerName });
    await expect(ledgerRow).toBeVisible({ timeout: 10_000 });
    await ledgerRow.locator('[aria-label^="View ledger"]').click();
    await expect(page.locator('h1')).toContainText(ledgerName, { timeout: 10_000 });

    // Set date range covering today
    const today = new Date();
    const startOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
    await page.locator('#statement-from').fill(startOfMonth.toISOString().split('T')[0]);
    await page.locator('#statement-to').fill(today.toISOString().split('T')[0]);
    await page.waitForTimeout(1_000);

    // 6. Verify entry shows in the statement, then click View
    const entryRow = page.locator('.invoice-row').filter({ hasText: 'Sales' });
    await expect(entryRow.first()).toBeVisible({ timeout: 10_000 });
    await entryRow.first().locator('button:has-text("View")').click();

    // 7. Verify the invoice preview modal opens with correct values
    const previewModal = page.locator('.modal-panel--invoice-preview');
    await expect(previewModal).toBeVisible({ timeout: 5_000 });

    // Check invoice header
    await expect(previewModal.locator('#invoice-preview-title')).toContainText('Printable invoice');

    // Check bill-to section shows the ledger name
    await expect(previewModal.locator('.invoice-sheet__billto')).toContainText(ledgerName);

    // Check line items table has the product
    const tableBody = previewModal.locator('.invoice-sheet__table tbody');
    await expect(tableBody.locator('tr')).toHaveCount(1);
    await expect(tableBody).toContainText(productName);
    // Quantity should be 3
    await expect(tableBody.locator('tr').first().locator('td.right').first()).toContainText('3');

    // Check totals section
    await expect(previewModal.locator('.invoice-sheet__totals')).toContainText('Total due');

    // Close the preview
    await previewModal.locator('button:has-text("Close")').click();
    await expect(previewModal).not.toBeVisible();
  });
});
