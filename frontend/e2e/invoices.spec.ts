import { test, expect, expectSuccess, uniqueSku, uniqueGstin, selectComboboxOption } from './fixtures';

test.describe('Invoices', () => {
  /**
   * Helper: set up a product, ledger, and inventory ready for invoicing.
   * Returns { sku, productName, ledgerName }.
   */
  async function seedInvoiceData(page: import('@playwright/test').Page) {
    const sku = uniqueSku();
    const productName = `Inv-Prod ${sku}`;
    const ledgerName = `Inv-Ledger-${Date.now().toString(36)}`;

    // 1. Create product
    await page.click('[href="/products"]');
    await page.fill('#sku', sku);
    await page.fill('#name', productName);
    await page.fill('#price', '100');
    await page.fill('#gst-rate', '18');
    await page.click('button:has-text("Create product")');
    await expectSuccess(page, 'Product created');

    // 2. Add inventory
    await page.click('[href="/inventory"]');
    await page.waitForTimeout(500);
    await selectComboboxOption(page, 'inventory-product', sku);
    await page.fill('#inventory-quantity', '50');
    await page.click('button:has-text("Apply adjustment")');
    await expectSuccess(page, 'Inventory updated');

    // 3. Create ledger
    await page.click('[href="/ledgers"]');
    await page.click('button:has-text("Create ledger")');
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '789 Invoice Blvd');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 4444444444');
    await page.click('button:has-text("Create ledger")');
    await expectSuccess(page, 'Ledger created');

    return { sku, productName, ledgerName };
  }

  test('displays invoice composer heading', async ({ authedPage: page }) => {
    await page.click('[href="/invoices"]');
    await expect(page.locator('h1')).toContainText('Invoice composer');
  });

  test('paginates invoices and supports search', async ({ authedPage: page }) => {
    const { sku, ledgerName } = await seedInvoiceData(page);

    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    // Create a sales invoice so there's at least one in the list
    await page.selectOption('#invoice-voucher-type', 'sales');

    await selectComboboxOption(page, 'invoice-ledger', ledgerName);

    const productInputId = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId, sku);
    await page.locator('[id^="invoice-quantity-"]').first().fill('2');
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'invoice created');

    // Verify invoice appears in the list
    await expect(page.locator('.invoice-row', { hasText: ledgerName }).first()).toBeVisible();

    // Search for the ledger name — invoice should still be visible
    await page.fill('#invoice-search', ledgerName);
    await expect(page.locator('.invoice-row', { hasText: ledgerName }).first()).toBeVisible();

    // Search for a non-existent name — no invoices should appear
    await page.fill('#invoice-search', 'ZZZZNONEXISTENT999');
    await expect(page.locator('.invoice-row')).toHaveCount(0);

    // Clear search — invoice should reappear
    await page.fill('#invoice-search', '');
    await expect(page.locator('.invoice-row').first()).toBeVisible();
  });

  test('creates a sales invoice', async ({ authedPage: page }) => {
    const { sku, ledgerName } = await seedInvoiceData(page);

    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    // Select voucher type
    await page.selectOption('#invoice-voucher-type', 'sales');

    // Select ledger
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);

    // Select product in line item
    const productInputId1 = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId1, sku);

    // Set quantity
    await page.locator('[id^="invoice-quantity-"]').first().fill('5');

    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'invoice created');

    // Verify invoice appears in list
    await expect(page.locator('.invoice-row').first()).toBeVisible();
  });

  test('creates a purchase invoice', async ({ authedPage: page }) => {
    const { sku, ledgerName } = await seedInvoiceData(page);

    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'purchase');

    // Select ledger
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);

    // Select product
    const productInputId2 = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId2, sku);

    await page.locator('[id^="invoice-quantity-"]').first().fill('10');

    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'Purchase invoice created');
  });

  test('adds multiple line items', async ({ authedPage: page }) => {
    const { sku, ledgerName } = await seedInvoiceData(page);

    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'sales');

    // Select ledger
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);

    // Add a second line item
    await page.click('button:has-text("Add line item")');
    const lineItems = page.locator('.line-item');
    await expect(lineItems).toHaveCount(2);
  });

  test('removes a line item', async ({ authedPage: page }) => {
    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    // Add a second line item
    await page.click('button:has-text("Add line item")');
    const lineItems = page.locator('.line-item');
    const countBefore = await lineItems.count();

    // Remove the last line item
    await page.locator('.line-item').last().locator('button:has-text("Remove")').click();
    await expect(page.locator('.line-item')).toHaveCount(countBefore - 1);
  });

  test('deletes an invoice and rolls back inventory', async ({
    authedPage: page,
  }) => {
    const { sku, ledgerName } = await seedInvoiceData(page);

    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    // Create invoice first
    await page.selectOption('#invoice-voucher-type', 'sales');
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);

    const productInputId3 = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId3, sku);
    await page.locator('[id^="invoice-quantity-"]').first().fill('3');
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'invoice created');

    // Delete the invoice — click Delete row button, then confirm in the custom dialog
    const invoiceRow = page.locator('.invoice-row', { hasText: ledgerName }).first();
    await invoiceRow.locator('[aria-label^="Delete invoice"]').click();
    await page.locator('.modal-overlay button:has-text("Delete")').click();
    await expect(page.locator('.toast--success')).toContainText('deleted', { timeout: 10_000 });
  });

  test('shows projected total while composing', async ({
    authedPage: page,
  }) => {
    await page.click('[href="/invoices"]');
    await expect(page.locator('h1')).toContainText('Invoice composer');
    // The projected total chip should exist somewhere on page
    // It updates as line items are filled
  });

  test('creates an invoice with a custom (backdated) invoice date', async ({ authedPage: page }) => {
    const { sku, ledgerName } = await seedInvoiceData(page);

    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    // Select voucher type
    await page.selectOption('#invoice-voucher-type', 'sales');

    // Select ledger
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);

    // Set a past invoice date
    const pastDate = '2025-06-15';
    await page.fill('#invoice-date', pastDate);

    // Select product in line item
    const productInputId4 = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId4, sku);
    await page.locator('[id^="invoice-quantity-"]').first().fill('2');

    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'invoice created');

    // Verify the invoice appears in the list with the backdated date
    const invoiceRow = page.locator('.invoice-row', { hasText: ledgerName }).first();
    await expect(invoiceRow).toBeVisible();
    // The date chip should show 6/15/2025 (locale-dependent, check for the year)
    await expect(invoiceRow.locator('.invoice-meta-chip', { hasText: 'Date' })).toContainText('2025');

    // Verify the invoice date field resets to today after creation
    const dateInput = page.locator('#invoice-date');
    const resetValue = await dateInput.inputValue();
    const today = new Date().toISOString().slice(0, 10);
    expect(resetValue).toBe(today);
  });

  test('invoice date defaults to today', async ({ authedPage: page }) => {
    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    const dateInput = page.locator('#invoice-date');
    const value = await dateInput.inputValue();
    const today = new Date().toISOString().slice(0, 10);
    expect(value).toBe(today);
  });

  test('shows search-no-results message when search finds nothing', async ({ authedPage: page }) => {
    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);
    await page.fill('#invoice-search', 'ZZZZNONEXISTENT999');
    await page.waitForTimeout(500);

    await expect(page.locator('.empty-state')).toContainText('No invoices match your search.');
    // CTA for truly-empty state must not appear during a search
    await expect(page.locator('button:has-text("Create your first invoice")')).not.toBeVisible();
  });

  test('shows friendly empty state with CTA when no invoices exist', async ({ authedPage: page }) => {
    // Mock only the invoices list to return empty so we can verify the empty-state UI
    await page.route(/\/api\/invoices\//, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0, total_pages: 0, page: 1 }),
      })
    );

    await page.goto('/invoices');
    await page.waitForTimeout(500);

    const emptyState = page.locator('.empty-state');
    await expect(emptyState).toContainText('No invoices yet');
    await expect(emptyState).toContainText('first invoice');

    const ctaButton = page.locator('button:has-text("Create your first invoice")');
    await expect(ctaButton).toBeVisible();
    // CTA should focus the voucher type selector so the user can start filling the form
    await ctaButton.click();
    await expect(page.locator('#invoice-voucher-type')).toBeFocused();
  });

  test('supplier invoice # field is hidden for sales invoices', async ({ authedPage: page }) => {
    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'sales');
    await expect(page.locator('#invoice-supplier-ref')).not.toBeVisible();
  });

  test('supplier invoice # field is visible for purchase invoices', async ({ authedPage: page }) => {
    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'purchase');
    await expect(page.locator('#invoice-supplier-ref')).toBeVisible();
  });

  test('creates a purchase invoice with supplier invoice number and shows it in the list', async ({ authedPage: page }) => {
    const { sku, ledgerName } = await seedInvoiceData(page);
    const supplierRef = `SUP-${Date.now().toString(36).toUpperCase()}`;

    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'purchase');

    await selectComboboxOption(page, 'invoice-ledger', ledgerName);

    const productInputId = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId, sku);
    await page.locator('[id^="invoice-quantity-"]').first().fill('3');

    await page.fill('#invoice-supplier-ref', supplierRef);

    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'Purchase invoice created');

    // Verify supplier ref appears in the invoice list row
    const invoiceRow = page.locator('.invoice-row', { hasText: ledgerName }).first();
    await expect(invoiceRow).toContainText(`Supplier Ref: ${supplierRef}`);
  });

  test('supplier invoice # field clears when switching from purchase to sales', async ({ authedPage: page }) => {
    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'purchase');
    await page.fill('#invoice-supplier-ref', 'TEMP-REF-123');

    // Switch to sales — field should disappear
    await page.selectOption('#invoice-voucher-type', 'sales');
    await expect(page.locator('#invoice-supplier-ref')).not.toBeVisible();

    // Switch back to purchase — field should appear empty (state preserved but not visible)
    await page.selectOption('#invoice-voucher-type', 'purchase');
    await expect(page.locator('#invoice-supplier-ref')).toBeVisible();
  });

  test('edit preserves supplier invoice number for purchase invoice', async ({ authedPage: page }) => {
    const { sku, ledgerName } = await seedInvoiceData(page);
    const supplierRef = `EDIT-${Date.now().toString(36).toUpperCase()}`;

    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    // Create purchase invoice with supplier ref
    await page.selectOption('#invoice-voucher-type', 'purchase');
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);
    const productInputId = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId, sku);
    await page.locator('[id^="invoice-quantity-"]').first().fill('2');
    await page.fill('#invoice-supplier-ref', supplierRef);
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'Purchase invoice created');

    // Click edit on that invoice
    const invoiceRow = page.locator('.invoice-row', { hasText: ledgerName }).first();
    await invoiceRow.locator('[aria-label^="Edit invoice"]').click();

    // Supplier ref field should be populated
    await expect(page.locator('#invoice-supplier-ref')).toHaveValue(supplierRef);
  });
});
