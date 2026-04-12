import { test, expect, expectSuccess, uniqueGstin, selectComboboxOption } from './fixtures';

test.describe('Payment Vouchers from Invoices Page', () => {
  /**
   * Helper: create a ledger and return its name.
   */
  async function createLedger(page: import('@playwright/test').Page, suffix = '') {
    const ledgerName = `PVLedger-${Date.now().toString(36)}${suffix}`;
    await page.click('[href="/ledgers"]');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Create ledger', { timeout: 10_000 });
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '1 Payment Street');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 6666666666');
    await page.click('button:has-text("Create ledger")');
    await expectSuccess(page, 'Ledger created');
    return ledgerName;
  }

  test('Payment option appears in voucher type dropdown', async ({ authedPage: page }) => {
    await page.click('[href="/invoices"]');
    await expect(page.locator('h1')).toContainText('Invoice composer', { timeout: 10_000 });
    const select = page.locator('#invoice-voucher-type');
    await expect(select.locator('option[value="payment"]')).toHaveCount(1);
  });

  test('selecting Payment type shows payment sub-form instead of line items', async ({ authedPage: page }) => {
    await page.click('[href="/invoices"]');
    await expect(page.locator('h1')).toContainText('Invoice composer', { timeout: 10_000 });

    // Before selecting payment, line items should be present
    await expect(page.locator('[id^="invoice-product-"]').first()).toBeVisible({ timeout: 5_000 });

    await page.selectOption('#invoice-voucher-type', 'payment');

    // Line items should disappear
    await expect(page.locator('[id^="invoice-product-"]')).toHaveCount(0);

    // Payment sub-form fields should appear
    await expect(page.locator('#payment-mode')).toBeVisible();
    await expect(page.locator('#payment-amount')).toBeVisible();
    await expect(page.locator('#payment-reference')).toBeVisible();

    // Tax-inclusive checkbox should be hidden for payment type
    await expect(page.locator('#invoice-tax-inclusive')).toHaveCount(0);

    // Submit button should say "Create payment voucher"
    await expect(page.locator('button:has-text("Create payment voucher")')).toBeVisible();
  });

  test('creates a payment voucher and it appears in Payment Vouchers tab', async ({ authedPage: page }) => {
    const ledgerName = await createLedger(page);

    await page.click('[href="/invoices"]');
    await expect(page.locator('h1')).toContainText('Invoice composer', { timeout: 10_000 });

    // Select Payment voucher type
    await page.selectOption('#invoice-voucher-type', 'payment');

    // Select the ledger
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);

    // Fill payment details
    await page.selectOption('#payment-mode', 'upi');
    await page.fill('#payment-reference', 'UPI-PV-E2E-001');
    await page.fill('#payment-amount', '5000');

    // Submit
    await page.click('button:has-text("Create payment voucher")');
    await expectSuccess(page, 'Payment voucher created');

    // Switch to Payment Vouchers tab
    await page.click('#tab-payments');
    await page.waitForTimeout(1_000);

    // The payment should appear in the list
    const paymentRow = page.locator('.invoice-row', { hasText: ledgerName });
    await expect(paymentRow.first()).toBeVisible({ timeout: 10_000 });

    // It should show a PAY- number
    await expect(paymentRow.first()).toContainText('PAY-');

    // It should show the mode
    await expect(paymentRow.first()).toContainText('upi');

    // It should show the reference number
    await expect(paymentRow.first()).toContainText('UPI-PV-E2E-001');

    // Amount should be displayed
    await expect(paymentRow.first()).toContainText('5,000');
  });

  test('payment number is auto-numbered with PAY prefix', async ({ authedPage: page }) => {
    const ledgerName = await createLedger(page, '-num');

    await page.click('[href="/invoices"]');
    await expect(page.locator('h1')).toContainText('Invoice composer', { timeout: 10_000 });

    await page.selectOption('#invoice-voucher-type', 'payment');
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);
    await page.selectOption('#payment-mode', 'cash');
    await page.fill('#payment-amount', '1000');

    await page.click('button:has-text("Create payment voucher")');
    await expectSuccess(page, 'Payment voucher created');

    // Check payment vouchers tab for PAY- prefix
    await page.click('#tab-payments');
    await page.waitForTimeout(1_000);

    const paymentRow = page.locator('.invoice-row', { hasText: ledgerName });
    await expect(paymentRow.first()).toBeVisible({ timeout: 10_000 });

    // Verify PAY- prefix with year and sequence pattern e.g. PAY-2026-001
    const voucherNumber = paymentRow.first().locator('.invoice-row__invoice-id');
    await expect(voucherNumber).toContainText(/PAY-\d{4}-\d+/);
  });

  test('payment number reflects saved series suffix', async ({ authedPage: page }) => {
    const ledgerName = await createLedger(page, '-suffix');

    await page.click('[href="/company"]');
    await expect(page.locator('h2:has-text("Invoice series")')).toBeVisible({ timeout: 10_000 });

    const paymentSeriesRow = page.locator('xpath=//strong[normalize-space()="Payment"]/ancestor::div[contains(@class,"panel")][1]');
    const suffixInput = paymentSeriesRow.locator('[id^="series-suffix-"]');
    await expect(suffixInput).toBeVisible({ timeout: 5_000 });
    await suffixInput.fill('/PV');
    await paymentSeriesRow.locator('button:has-text("Save")').click();
    await expect(page.locator('text=Saved').first()).toBeVisible({ timeout: 8_000 });

    await page.click('[href="/invoices"]');
    await expect(page.locator('h1')).toContainText('Invoice composer', { timeout: 10_000 });

    await page.selectOption('#invoice-voucher-type', 'payment');
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);
    await page.selectOption('#payment-mode', 'cash');
    await page.fill('#payment-amount', '1000');

    await page.click('button:has-text("Create payment voucher")');
    await expectSuccess(page, 'Payment voucher created');

    await page.click('#tab-payments');
    await page.waitForTimeout(1_000);

    const createdPaymentRow = page.locator('.invoice-row', { hasText: ledgerName });
    await expect(createdPaymentRow.first()).toBeVisible({ timeout: 10_000 });
    await expect(createdPaymentRow.first().locator('.invoice-row__invoice-id')).toContainText(/\/PV$/);

    await page.click('[href="/company"]');
    await expect(page.locator('h2:has-text("Invoice series")')).toBeVisible({ timeout: 10_000 });
    const resetPaymentSeriesRow = page.locator('xpath=//strong[normalize-space()="Payment"]/ancestor::div[contains(@class,"panel")][1]');
    await resetPaymentSeriesRow.locator('[id^="series-suffix-"]').fill('');
    await resetPaymentSeriesRow.locator('button:has-text("Save")').click();
    await expect(page.locator('text=Saved').first()).toBeVisible({ timeout: 8_000 });
  });

  test('payment amount validation prevents zero amount', async ({ authedPage: page }) => {
    const ledgerName = await createLedger(page, '-val');

    await page.click('[href="/invoices"]');
    await expect(page.locator('h1')).toContainText('Invoice composer', { timeout: 10_000 });

    await page.selectOption('#invoice-voucher-type', 'payment');
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);
    await page.selectOption('#payment-mode', 'cash');
    await page.fill('#payment-amount', '0');

    // Try clicking submit — HTML5 min="0.01" validation blocks it
    await page.click('button:has-text("Create payment voucher")');

    // Form was not submitted — no success toast, form still visible
    await expect(page.locator('#payment-amount')).toBeVisible();
    await expect(page.locator('.toast--success')).toHaveCount(0);
  });

  test('switching back to Sales from Payment restores line items', async ({ authedPage: page }) => {
    await page.click('[href="/invoices"]');
    await expect(page.locator('h1')).toContainText('Invoice composer', { timeout: 10_000 });

    // Select Payment
    await page.selectOption('#invoice-voucher-type', 'payment');
    await expect(page.locator('#payment-amount')).toBeVisible({ timeout: 3_000 });

    // Switch back to Sales
    await page.selectOption('#invoice-voucher-type', 'sales');

    // Line items should be back
    await expect(page.locator('[id^="invoice-product-"]').first()).toBeVisible({ timeout: 3_000 });

    // Payment sub-form should be gone
    await expect(page.locator('#payment-amount')).toHaveCount(0);
  });

  test('Invoices tab and Payment Vouchers tab are both visible', async ({ authedPage: page }) => {
    await page.click('[href="/invoices"]');
    await expect(page.locator('h1')).toContainText('Invoice composer', { timeout: 10_000 });

    await expect(page.locator('#tab-invoices')).toBeVisible();
    await expect(page.locator('#tab-payments')).toBeVisible();

    // Invoices tab is active by default
    const invoicesTab = page.locator('#tab-invoices');
    await expect(invoicesTab).toHaveClass(/button--primary/);
  });
});
