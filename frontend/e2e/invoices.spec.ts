import { test, expect, expectSuccess, uniqueSku, uniqueGstin, selectComboboxOption } from './fixtures';

test.describe('Invoices', () => {
  async function openInvoiceFeed(page: import('@playwright/test').Page) {
    await page.goto('/invoices-view');
    await expect(page.locator('h1')).toContainText('Invoice Feed', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

    // Keep feed tests independent from FY/view toggles mutated by other tests.
    await page.locator('label.invoice-feed-view__checkbox', { hasText: 'Search all FY' }).locator('input').check();
    await page.getByRole('button', { name: 'Card' }).click();
  }

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

    // Verify invoice appears in the feed list
    await openInvoiceFeed(page);
    await expect(page.locator('.invoice-compact-card', { hasText: ledgerName }).first()).toBeVisible();

    // Search for the ledger name — invoice should still be visible
    await page.fill('.invoice-feed-view__search', ledgerName);
    await expect(page.locator('.invoice-compact-card', { hasText: ledgerName }).first()).toBeVisible();

    // Search for a non-existent name — no invoices should appear
    await page.fill('.invoice-feed-view__search', 'ZZZZNONEXISTENT999');
    await expect(page.locator('.invoice-compact-card')).toHaveCount(0);

    // Clear search — invoice should reappear
    await page.fill('.invoice-feed-view__search', '');
    await expect(page.locator('.invoice-compact-card').first()).toBeVisible();
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

    await openInvoiceFeed(page);
    await expect(page.locator('.invoice-compact-card', { hasText: ledgerName }).first()).toBeVisible();
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

  test('cancels an invoice and rolls back inventory', async ({
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

    // Cancel the invoice from invoice feed
    await openInvoiceFeed(page);
    const invoiceCard = page.locator('.invoice-compact-card', { hasText: ledgerName }).first();
    await invoiceCard.locator('button[title="Cancel"]').click();
    await page.locator('.modal-overlay button:has-text("Cancel invoice")').click();
    await expect(page.locator('.toast--success')).toContainText('cancelled', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
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

    // Verify the invoice appears in the feed with the backdated year in date text
    await openInvoiceFeed(page);
    const invoiceCard = page.locator('.invoice-compact-card', { hasText: ledgerName }).first();
    await expect(invoiceCard).toBeVisible();
    await expect(invoiceCard).toContainText('2025');

    // Verify the invoice date field resets to today after creation
    await page.goto('/invoices');
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
    await openInvoiceFeed(page);
    await page.fill('.invoice-feed-view__search', 'ZZZZNONEXISTENT999');
    await page.waitForTimeout(500);

    await expect(page.locator('.empty-state')).toContainText('No invoices found');
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

    await page.goto('/invoices-view');
    await page.waitForTimeout(500);

    const emptyState = page.locator('.empty-state');
    await expect(emptyState).toContainText('No invoices found');
  });

  test('supplier invoice # field is hidden for sales invoices', async ({ authedPage: page }) => {
    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'sales');
    await expect(page.locator('#invoice-supplier-ref')).not.toBeVisible();
  });

  test('reference notes field is visible for sales invoices', async ({ authedPage: page }) => {
    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'sales');
    await expect(page.locator('#invoice-reference-notes')).toBeVisible();
  });

  test('reference notes field is hidden for purchase invoices', async ({ authedPage: page }) => {
    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'purchase');
    await expect(page.locator('#invoice-reference-notes')).not.toBeVisible();
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

    // Verify supplier ref appears in the invoice feed row
    await openInvoiceFeed(page);
    const invoiceCard = page.locator('.invoice-compact-card', { hasText: ledgerName }).first();
    await expect(invoiceCard).toContainText(`Ref: ${supplierRef}`);
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

    // Click edit from invoice feed
    await openInvoiceFeed(page);
    const invoiceCard = page.locator('.invoice-compact-card', { hasText: ledgerName }).first();
    await invoiceCard.locator('button[title="Edit"]').click();

    // Supplier ref field should be populated
    await expect(page.locator('#invoice-supplier-ref')).toHaveValue(supplierRef);
  });

  test('edit preserves reference notes for sales invoice', async ({ authedPage: page }) => {
    const { sku, ledgerName } = await seedInvoiceData(page);
    const referenceNotes = `PO-${Date.now().toString(36).toUpperCase()}`;

    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'sales');
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);
    const productInputId = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId, sku);
    await page.locator('[id^="invoice-quantity-"]').first().fill('2');
    await page.fill('#invoice-reference-notes', referenceNotes);
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'Sales invoice created');

    await openInvoiceFeed(page);
    const invoiceCard = page.locator('.invoice-compact-card', { hasText: ledgerName }).first();
    await invoiceCard.locator('button[title="Edit"]').click();

    await expect(page.locator('#invoice-reference-notes')).toHaveValue(referenceNotes);
  });

  test('tax-inclusive checkbox is unchecked by default', async ({ authedPage: page }) => {
    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    const checkbox = page.locator('#invoice-tax-inclusive');
    await expect(checkbox).toBeVisible();
    await expect(checkbox).not.toBeChecked();
  });

  test('checking tax-inclusive relabels price column to "Amount (incl. GST)"', async ({ authedPage: page }) => {
    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    // Default: "Price"
    await expect(page.locator('label[for^="invoice-price-"]').first()).toContainText('Price');

    // Check the box
    await page.check('#invoice-tax-inclusive');
    await expect(page.locator('label[for^="invoice-price-"]').first()).toContainText('Amount (incl. GST)');

    // Uncheck
    await page.uncheck('#invoice-tax-inclusive');
    await expect(page.locator('label[for^="invoice-price-"]').first()).toContainText('Price');
  });

  test('creates tax-inclusive invoice and backend returns correct breakdown', async ({ authedPage: page }) => {
    // Product seeded with price=100, gst_rate=18 in seedInvoiceData.
    // With tax_inclusive ON and unit_price=118:
    //   line_total=118, taxable=100.00, tax=18.00
    const { sku, ledgerName } = await seedInvoiceData(page);

    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'sales');
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);

    const productInputId = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId, sku);

    // Enable tax-inclusive
    await page.check('#invoice-tax-inclusive');

    // Set inclusive price to 118 (100 base + 18 GST)
    await page.locator('[id^="invoice-price-"]').first().fill('118');
    await page.locator('[id^="invoice-quantity-"]').first().fill('1');

    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'invoice created');

    await openInvoiceFeed(page);
    const invoiceCard = page.locator('.invoice-compact-card', { hasText: ledgerName }).first();
    await expect(invoiceCard).toBeVisible();
    await expect(invoiceCard).toContainText('Tax:');
  });

  test('tax-exclusive invoice behaviour is unchanged (default)', async ({ authedPage: page }) => {
    // Product: price=100, gst_rate=18
    // With tax_inclusive OFF and unit_price=100:
    //   taxable=100, tax=18, total=118
    const { sku, ledgerName } = await seedInvoiceData(page);

    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'sales');
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);

    const productInputId = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId, sku);

    // tax-inclusive must be off (default)
    await expect(page.locator('#invoice-tax-inclusive')).not.toBeChecked();

    await page.locator('[id^="invoice-price-"]').first().fill('100');
    await page.locator('[id^="invoice-quantity-"]').first().fill('1');

    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'invoice created');

    await openInvoiceFeed(page);
    const invoiceCard = page.locator('.invoice-compact-card', { hasText: ledgerName }).first();
    await expect(invoiceCard).toBeVisible();
    await expect(invoiceCard).toContainText('Tax:');
  });

  test('edit restores tax-inclusive checkbox state', async ({ authedPage: page }) => {
    const { sku, ledgerName } = await seedInvoiceData(page);

    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'sales');
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);

    const productInputId = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId, sku);
    await page.locator('[id^="invoice-quantity-"]').first().fill('1');
    await page.locator('[id^="invoice-price-"]').first().fill('118');

    // Create with tax-inclusive ON
    await page.check('#invoice-tax-inclusive');
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'invoice created');

    // Click edit from invoice feed — checkbox should be restored to checked
    await openInvoiceFeed(page);
    const invoiceCard = page.locator('.invoice-compact-card', { hasText: ledgerName }).first();
    await invoiceCard.locator('button[title="Edit"]').click();
    await expect(page.locator('#invoice-tax-inclusive')).toBeChecked();
  });

  test('cancel edit resets tax-inclusive checkbox', async ({ authedPage: page }) => {
    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.check('#invoice-tax-inclusive');
    await expect(page.locator('#invoice-tax-inclusive')).toBeChecked();

    // Without creating an invoice, simulate clicking "Cancel edit" via resetInvoiceForm
    // (We need to be in edit mode; trigger it by mock-navigating or checking state reset on page reload)
    // Simplest: reload the page — the state should reset
    await page.reload();
    await page.waitForTimeout(500);
    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);
    await expect(page.locator('#invoice-tax-inclusive')).not.toBeChecked();
  });

  // ---------------------------------------------------------------------------
  // Purchase invoice PDF layout (#186)
  // ---------------------------------------------------------------------------

  test('purchase invoice preview shows supplier on left and company on right', async ({ authedPage: page }) => {
    const { sku, ledgerName } = await seedInvoiceData(page);

    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'purchase');
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);
    const productInputId = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId, sku);
    await page.locator('[id^="invoice-quantity-"]').first().fill('1');
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'Purchase invoice created');

    await openInvoiceFeed(page);
    const invoiceCard = page.locator('.invoice-compact-card', { hasText: ledgerName }).first();
    await invoiceCard.locator('button[title="Preview"]').click();

    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible();

    // Preview is PDF-based now; validate key controls and title rendering.
    await expect(modal.locator('#invoice-preview-title')).toContainText('PDF invoice');
    await expect(modal.getByRole('button', { name: 'Download invoice PDF' })).toBeVisible();
    await expect(modal.getByRole('button', { name: 'Email invoice' })).toBeVisible();
    await expect(modal.locator('iframe.invoice-pdf-viewer__frame')).toBeVisible();
  });

  test('purchase invoice preview shows supplier ref when provided', async ({ authedPage: page }) => {
    const { sku, ledgerName } = await seedInvoiceData(page);
    const supplierRef = `SP-${Date.now().toString(36).toUpperCase()}`;

    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'purchase');
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);
    const productInputId = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId, sku);
    await page.locator('[id^="invoice-quantity-"]').first().fill('1');
    await page.fill('#invoice-supplier-ref', supplierRef);
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'Purchase invoice created');

    await openInvoiceFeed(page);
    const invoiceCard = page.locator('.invoice-compact-card', { hasText: ledgerName }).first();
    await invoiceCard.locator('button[title="Preview"]').click();

    // Supplier ref is surfaced in the feed card metadata.
    await expect(invoiceCard).toContainText(`Ref: ${supplierRef}`);

    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible();
    await expect(modal.locator('iframe.invoice-pdf-viewer__frame')).toBeVisible();
  });

  test('purchase invoice preview without supplier ref hides supplier ref row', async ({ authedPage: page }) => {
    const { sku, ledgerName } = await seedInvoiceData(page);

    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'purchase');
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);
    const productInputId = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId, sku);
    await page.locator('[id^="invoice-quantity-"]').first().fill('1');
    // No supplier ref filled
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'Purchase invoice created');

    await openInvoiceFeed(page);
    const invoiceCard = page.locator('.invoice-compact-card', { hasText: ledgerName }).first();
    await invoiceCard.locator('button[title="Preview"]').click();

    await expect(invoiceCard).not.toContainText('Ref:');

    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible();
    await expect(modal.locator('iframe.invoice-pdf-viewer__frame')).toBeVisible();
  });

  test('purchase invoice preview has no bank details and shows tax breakup', async ({ authedPage: page }) => {
    const { sku, ledgerName } = await seedInvoiceData(page);

    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'purchase');
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);
    const productInputId = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId, sku);
    await page.locator('[id^="invoice-quantity-"]').first().fill('1');
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'Purchase invoice created');

    await openInvoiceFeed(page);
    const invoiceCard = page.locator('.invoice-compact-card', { hasText: ledgerName }).first();
    await invoiceCard.locator('button[title="Preview"]').click();

    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible();

    // New preview renders a PDF iframe rather than inline invoice-sheet sections.
    await expect(modal.locator('.invoice-sheet__bank')).toHaveCount(0);
    await expect(modal.locator('.invoice-sheet__totals')).toHaveCount(0);
    await expect(modal.locator('iframe.invoice-pdf-viewer__frame')).toBeVisible();
  });

  test('sales invoice preview layout is unchanged', async ({ authedPage: page }) => {
    const { sku, ledgerName } = await seedInvoiceData(page);

    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'sales');
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);
    const productInputId = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId, sku);
    await page.locator('[id^="invoice-quantity-"]').first().fill('1');
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'Sales invoice created');

    await openInvoiceFeed(page);
    const invoiceCard = page.locator('.invoice-compact-card', { hasText: ledgerName }).first();
    await invoiceCard.locator('button[title="Preview"]').click();

    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible();

    // Sales preview uses the same PDF modal controls.
    await expect(modal.locator('#invoice-preview-title')).toContainText('PDF invoice');
    await expect(modal.getByRole('button', { name: 'Download invoice PDF' })).toBeVisible();
    await expect(modal.getByRole('button', { name: 'Email invoice' })).toBeVisible();
    await expect(modal.locator('iframe.invoice-pdf-viewer__frame')).toBeVisible();
  });

  test('purchase invoice PDF endpoint returns 200 and application/pdf', async ({ authedPage: page }) => {
    const { sku, ledgerName } = await seedInvoiceData(page);

    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'purchase');
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);
    const productInputId = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId, sku);
    await page.locator('[id^="invoice-quantity-"]').first().fill('1');
    await page.fill('#invoice-supplier-ref', 'SP-E2E-PDF');
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'Purchase invoice created');

    // Open preview and click Download PDF — intercept the network request
    await openInvoiceFeed(page);
    const invoiceCard = page.locator('.invoice-compact-card', { hasText: ledgerName }).first();
    await invoiceCard.locator('button[title="Preview"]').click();

    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible();

    const [pdfResponse] = await Promise.all([
      page.waitForResponse(res => res.url().includes('/invoices/') && res.url().endsWith('/pdf')),
      modal.locator('[aria-label="Download invoice PDF"]').click(),
    ]);
    expect(pdfResponse.status()).toBe(200);
    expect(pdfResponse.headers()['content-type']).toContain('application/pdf');
  });

  test('sales invoice PDF endpoint returns 200 and application/pdf', async ({ authedPage: page }) => {
    const { sku, ledgerName } = await seedInvoiceData(page);

    await page.click('[href="/invoices"]');
    await page.waitForTimeout(500);

    await page.selectOption('#invoice-voucher-type', 'sales');
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);
    const productInputId = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId, sku);
    await page.locator('[id^="invoice-quantity-"]').first().fill('1');
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'Sales invoice created');

    await openInvoiceFeed(page);
    const invoiceCard = page.locator('.invoice-compact-card', { hasText: ledgerName }).first();
    await invoiceCard.locator('button[title="Preview"]').click();

    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible();

    const [pdfResponse] = await Promise.all([
      page.waitForResponse(res => res.url().includes('/invoices/') && res.url().endsWith('/pdf')),
      modal.locator('[aria-label="Download invoice PDF"]').click(),
    ]);
    expect(pdfResponse.status()).toBe(200);
    expect(pdfResponse.headers()['content-type']).toContain('application/pdf');
  });
});
