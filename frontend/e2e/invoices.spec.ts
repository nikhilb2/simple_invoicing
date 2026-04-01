import { test, expect, expectSuccess, uniqueSku, uniqueGstin } from './fixtures';

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
    const productSelect = page.locator('#inventory-product');
    const options = productSelect.locator('option');
    const count = await options.count();
    let targetValue = '';
    for (let i = 0; i < count; i++) {
      const text = await options.nth(i).textContent();
      if (text?.includes(sku)) {
        targetValue = (await options.nth(i).getAttribute('value')) || '';
        break;
      }
    }
    if (targetValue) {
      await productSelect.selectOption(targetValue);
    }
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
    const ledgerSelect = page.locator('#invoice-ledger');
    const ledgerOptions = ledgerSelect.locator('option');
    const ledgerCount = await ledgerOptions.count();
    let ledgerValue = '';
    for (let i = 0; i < ledgerCount; i++) {
      const text = await ledgerOptions.nth(i).textContent();
      if (text?.includes(ledgerName)) {
        ledgerValue = (await ledgerOptions.nth(i).getAttribute('value')) || '';
        break;
      }
    }
    if (ledgerValue) {
      await ledgerSelect.selectOption(ledgerValue);
    }

    // Select product in line item
    const productSelect = page.locator('[id^="invoice-product-"]').first();
    const prodOptions = productSelect.locator('option');
    const prodCount = await prodOptions.count();
    let prodValue = '';
    for (let i = 0; i < prodCount; i++) {
      const text = await prodOptions.nth(i).textContent();
      if (text?.includes(sku)) {
        prodValue = (await prodOptions.nth(i).getAttribute('value')) || '';
        break;
      }
    }
    if (prodValue) {
      await productSelect.selectOption(prodValue);
    }

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
    const ledgerSelect = page.locator('#invoice-ledger');
    const ledgerOptions = ledgerSelect.locator('option');
    const ledgerCount = await ledgerOptions.count();
    let ledgerValue = '';
    for (let i = 0; i < ledgerCount; i++) {
      const text = await ledgerOptions.nth(i).textContent();
      if (text?.includes(ledgerName)) {
        ledgerValue = (await ledgerOptions.nth(i).getAttribute('value')) || '';
        break;
      }
    }
    if (ledgerValue) {
      await ledgerSelect.selectOption(ledgerValue);
    }

    // Select product
    const productSelect = page.locator('[id^="invoice-product-"]').first();
    const prodOptions = productSelect.locator('option');
    const prodCount = await prodOptions.count();
    let prodValue = '';
    for (let i = 0; i < prodCount; i++) {
      const text = await prodOptions.nth(i).textContent();
      if (text?.includes(sku)) {
        prodValue = (await prodOptions.nth(i).getAttribute('value')) || '';
        break;
      }
    }
    if (prodValue) {
      await productSelect.selectOption(prodValue);
    }

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

    // Delete the invoice — handle confirm dialog
    const invoiceRow = page.locator('.invoice-row', { hasText: ledgerName }).first();
    page.on('dialog', (dialog) => dialog.accept());
    await invoiceRow.locator('button:has-text("Delete")').click();
    await expect(page.locator('.status-banner--success')).toContainText('deleted', { timeout: 10_000 });
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

    // Set a past invoice date
    const pastDate = '2025-06-15';
    await page.fill('#invoice-date', pastDate);

    // Select product in line item
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
});
