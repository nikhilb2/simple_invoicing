import { test, expect, expectSuccess, uniqueSku, uniqueGstin } from './fixtures';

test.describe('Day Book', () => {
  test('displays day book heading', async ({ authedPage: page }) => {
    await page.click('[href="/day-book"]');
    await expect(page.locator('h1')).toContainText('Day book');
  });

  test('shows voucher range inputs', async ({ authedPage: page }) => {
    await page.click('[href="/day-book"]');
    await expect(page.locator('#day-book-from')).toBeVisible();
    await expect(page.locator('#day-book-to')).toBeVisible();
  });

  test('displays voucher register section', async ({ authedPage: page }) => {
    await page.click('[href="/day-book"]');
    await expect(page.getByRole('heading', { name: 'Voucher register' })).toBeVisible();
  });

  test('filters vouchers by date range', async ({ authedPage: page }) => {
    await page.click('[href="/day-book"]');

    // Set a wide date range
    const today = new Date();
    const yearAgo = new Date(today);
    yearAgo.setFullYear(yearAgo.getFullYear() - 1);

    await page.fill(
      '#day-book-from',
      yearAgo.toISOString().split('T')[0],
    );
    await page.fill('#day-book-to', today.toISOString().split('T')[0]);

    // Wait for data to load – either voucher entries or empty state
    await page.waitForTimeout(1_000);
    const hasVouchers = await page.locator('.invoice-row').count();
    const hasEmpty = await page.getByText('No vouchers found').isVisible().catch(() => false);
    expect(hasVouchers > 0 || hasEmpty).toBeTruthy();
  });

  test('shows debit and credit totals in summary', async ({
    authedPage: page,
  }) => {
    // First create an invoice so we have data
    const sku = uniqueSku();
    const ledgerName = `DB-Ledger-${Date.now().toString(36)}`;

    // Create product
    await page.click('.sidebar [href="/products"]');
    await page.fill('#sku', sku);
    await page.fill('#name', `DayBook Prod ${sku}`);
    await page.fill('#price', '200');
    await page.fill('#gst-rate', '18');
    await page.click('button:has-text("Create product")');
    await expectSuccess(page, 'Product created');

    // Add inventory
    await page.click('.sidebar [href="/inventory"]');
    await page.waitForTimeout(500);
    const productSelect = page.locator('#inventory-product');
    const options = productSelect.locator('option');
    const count = await options.count();
    for (let i = 0; i < count; i++) {
      const text = await options.nth(i).textContent();
      if (text?.includes(sku)) {
        const val = (await options.nth(i).getAttribute('value')) || '';
        await productSelect.selectOption(val);
        break;
      }
    }
    await page.fill('#inventory-quantity', '100');
    await page.click('button:has-text("Apply adjustment")');
    await expectSuccess(page, 'Inventory updated');

    // Create ledger
    await page.click('[href="/ledgers"]');
    await page.click('button:has-text("Create ledger")');
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', 'DayBook Street');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 5555555555');
    await page.click('button:has-text("Create ledger")');
    await expectSuccess(page, 'Ledger created');

    // Create a sales invoice
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
    const prodSelect = page.locator('[id^="invoice-product-"]').first();
    const prodOptions = prodSelect.locator('option');
    const prodCount = await prodOptions.count();
    for (let i = 0; i < prodCount; i++) {
      const text = await prodOptions.nth(i).textContent();
      if (text?.includes(sku)) {
        const val = (await prodOptions.nth(i).getAttribute('value')) || '';
        await prodSelect.selectOption(val);
        break;
      }
    }
    await page.locator('[id^="invoice-quantity-"]').first().fill('2');
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'invoice created');

    // Now go to Day Book
    await page.click('[href="/day-book"]');
    const today = new Date();
    const startOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
    await page.fill(
      '#day-book-from',
      startOfMonth.toISOString().split('T')[0],
    );
    await page.fill('#day-book-to', today.toISOString().split('T')[0]);
    await page.waitForTimeout(1_000);

    // Should show summary box with Dr / Cr
    await expect(page.locator('.summary-box')).toBeVisible({ timeout: 5_000 });
  });
});
