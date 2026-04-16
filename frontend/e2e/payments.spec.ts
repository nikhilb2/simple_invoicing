import { test, expect, expectSuccess, uniqueGstin } from './fixtures';

async function setStatementRangeToCurrentMonth(page: import('@playwright/test').Page) {
  const today = new Date();
  const startOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
  await page.locator('#statement-from').fill(startOfMonth.toISOString().split('T')[0]);
  await page.locator('#statement-to').fill(today.toISOString().split('T')[0]);
}

test.describe('Payments (Receipt / Payment)', () => {
  test('records a receipt and verifies it appears in the ledger statement', async ({ authedPage: page }) => {
    // 1. Create a ledger
    const ledgerName = `PayLedger-${Date.now().toString(36)}`;
    await page.click('[href="/ledgers"]');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Create ledger', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '789 Payment Ave');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 7777777777');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expectSuccess(page, 'Ledger created');

    // 2. Navigate to ledger view
    await page.fill('#ledger-search', ledgerName);
    await page.waitForTimeout(500);
    const row = page.locator('.table-row', { hasText: ledgerName });
    await expect(row).toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await row.locator('[aria-label^="View ledger"]').click();
    await expect(page.locator('h1')).toContainText(ledgerName, { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

    // 3. Open payment form
    await page.click('button:has-text("Record Receipt / Payment")');
    const modal = page.locator('.modal-overlay');
    await expect(modal).toBeVisible({ timeout: 5_000 });

    // 4. Fill in receipt details
    await modal.locator('#pay-type').selectOption('receipt');
    await modal.locator('#pay-amount').fill('15000');
    await modal.locator('#pay-mode').selectOption('bank');
    await modal.locator('#pay-ref').fill('TXN-E2E-001');
    await modal.locator('#pay-notes').fill('E2E test receipt');

    // 5. Submit
    await modal.locator('button:has-text("Save")').click();
    await expect(modal).not.toBeVisible({ timeout: 5_000 });

    // 6. Refresh statement context and verify receipt entry appears
    await page.reload();
    await setStatementRangeToCurrentMonth(page);
    await page.waitForTimeout(1_000);
    const receiptEntry = page.locator('.invoice-row').filter({ hasText: /receipt/i });
    await expect(receiptEntry.first()).toBeVisible({ timeout: 10_000 });
    await expect(receiptEntry.first()).toContainText('Cr');

    // 7. Receipt entries should NOT have a View button (only invoices do)
    await expect(receiptEntry.first().locator('button:has-text("View")')).toHaveCount(0);
  });

  test('records a payment and verifies it appears in the ledger statement', async ({ authedPage: page }) => {
    // 1. Create a ledger
    const ledgerName = `PayOutLedger-${Date.now().toString(36)}`;
    await page.click('[href="/ledgers"]');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Create ledger', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '321 Outflow St');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 8888888888');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expectSuccess(page, 'Ledger created');

    // 2. Navigate to ledger view
    await page.fill('#ledger-search', ledgerName);
    await page.waitForTimeout(500);
    const row = page.locator('.table-row', { hasText: ledgerName });
    await expect(row).toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await row.locator('[aria-label^="View ledger"]').click();
    await expect(page.locator('h1')).toContainText(ledgerName, { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

    // 3. Open payment form and record a payment (money paid out)
    await page.click('button:has-text("Record Receipt / Payment")');
    const modal = page.locator('.modal-overlay');
    await expect(modal).toBeVisible({ timeout: 5_000 });

    await modal.locator('#pay-type').selectOption('payment');
    await modal.locator('#pay-amount').fill('8500.50');
    await modal.locator('#pay-mode').selectOption('upi');
    await modal.locator('#pay-ref').fill('UPI-E2E-002');

    await modal.locator('button:has-text("Save")').click();
    await expect(modal).not.toBeVisible({ timeout: 5_000 });

    // 4. Refresh statement context and verify payment entry appears as Debit
    await page.reload();
    await setStatementRangeToCurrentMonth(page);
    await page.waitForTimeout(1_000);
    const paymentEntry = page.locator('.invoice-row').filter({ hasText: /payment/i });
    await expect(paymentEntry.first()).toBeVisible({ timeout: 10_000 });
    await expect(paymentEntry.first()).toContainText('Dr');
  });

  test('payment form validates amount greater than zero', async ({ authedPage: page }) => {
    // 1. Create a ledger
    const ledgerName = `ValLedger-${Date.now().toString(36)}`;
    await page.click('[href="/ledgers"]');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Create ledger', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '999 Validate Blvd');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 9999999999');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expectSuccess(page, 'Ledger created');

    // 2. Navigate to ledger view and open form
    await page.fill('#ledger-search', ledgerName);
    await page.waitForTimeout(500);
    const row = page.locator('.table-row', { hasText: ledgerName });
    await expect(row).toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await row.locator('[aria-label^="View ledger"]').click();
    await expect(page.locator('h1')).toContainText(ledgerName, { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

    await page.click('button:has-text("Record Receipt / Payment")');
    const modal = page.locator('.modal-overlay');
    await expect(modal).toBeVisible({ timeout: 5_000 });

    // 3. Try to submit with zero amount — HTML5 validation should prevent it
    await modal.locator('#pay-amount').fill('0');
    await modal.locator('button:has-text("Save")').click();

    // The form has min="0.01" so the browser validation prevents submission.
    // Verify modal is still open (form was not submitted).
    await expect(modal).toBeVisible();

    // 4. Modal should still be open
    await expect(modal).toBeVisible();
  });
});
