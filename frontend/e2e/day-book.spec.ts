import { test, expect, expectSuccess, uniqueSku, uniqueGstin, createProduct, adjustInventory, clickNavLink, selectComboboxOption } from './fixtures';

test.describe('Day Book', () => {
  test('displays day book heading', async ({ authedPage: page }) => {
    await clickNavLink(page, '/day-book');
    await expect(page.locator('h1')).toContainText('Day book');
  });

  test('shows voucher range inputs', async ({ authedPage: page }) => {
    await clickNavLink(page, '/day-book');
    await expect(page.locator('#day-book-from')).toBeVisible();
    await expect(page.locator('#day-book-to')).toBeVisible();
  });

  test('displays voucher register section', async ({ authedPage: page }) => {
    await clickNavLink(page, '/day-book');
    await expect(page.getByRole('heading', { name: 'Voucher register' })).toBeVisible();
  });

  test('filters vouchers by date range', async ({ authedPage: page }) => {
    await clickNavLink(page, '/day-book');

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
    const hasVouchers = await page.locator('.register__row').count();
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
    await clickNavLink(page, '/catalogue');
    await createProduct(page, { sku, name: `DayBook Prod ${sku}`, price: '200', gstRate: '18' });

    // Add inventory — same page now, through the stock adjustment modal
    await adjustInventory(page, sku, '100');

    // Create ledger
    await clickNavLink(page, '/ledgers');
    await page.click('button:has-text("Create ledger")');
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', 'DayBook Street');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 5555555555');
    await page.click('button:has-text("Create ledger")');
    await expectSuccess(page, 'Ledger created');

    // Create a sales invoice
    await clickNavLink(page, '/invoices');
    await page.waitForTimeout(500);
    await page.selectOption('#invoice-voucher-type', 'sales');

    await selectComboboxOption(page, 'invoice-ledger', ledgerName);
    await selectComboboxOption(page, 'invoice-product-1', sku);
    await page.locator('[id^="invoice-quantity-"]').first().fill('2');
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'invoice created');

    // Creating an invoice pops the PDF preview, an aria-modal dialog whose
    // overlay covers the sidebar — dismiss it before navigating by rail click.
    const previewModal = page.locator('.modal-panel--invoice-preview');
    await expect(previewModal).toBeVisible({ timeout: 10_000 });
    await previewModal.getByRole('button', { name: 'Close invoice preview' }).click();
    await expect(previewModal).not.toBeVisible();

    // Now go to Day Book
    await clickNavLink(page, '/day-book');
    const today = new Date();
    const startOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
    await page.fill(
      '#day-book-from',
      startOfMonth.toISOString().split('T')[0],
    );
    await page.fill('#day-book-to', today.toISOString().split('T')[0]);
    await page.waitForTimeout(1_000);

    // Debit and credit are now read off the scope bar's metric strip, which
    // carries the period totals whatever the register below it is filtered to.
    await expect(page.locator('.scope-bar .metric-strip')).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText('Period debit')).toBeVisible();
    await expect(page.getByText('Period credit')).toBeVisible();
  });
});
