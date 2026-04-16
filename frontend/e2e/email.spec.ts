import { test, expect, expectSuccess, uniqueSku, uniqueGstin, selectComboboxOption } from './fixtures';

const LEDGER_EMAIL = 'buyer@example.com';
const EXPECT_TIMEOUT_MS = Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '2000');

/**
 * Creates a ledger with an email address and navigates to its view page.
 * Returns the ledger name.
 */
async function createLedgerAndNavigateToView(
  page: import('@playwright/test').Page,
  ledgerName: string,
) {
  await page.click('[href="/ledgers"]');
  await page.click('button:has-text("Create ledger")');
  await expect(page.locator('h1')).toContainText('Create ledger', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

  await page.fill('#ledger-name', ledgerName);
  await page.fill('#ledger-address', '1 Email Test Road');
  await page.fill('#ledger-gst', uniqueGstin());
  await page.fill('#ledger-phone', '+91 9999999999');
  await page.fill('#ledger-email', LEDGER_EMAIL);
  await page.click('button:has-text("Create ledger")');
  await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
  await expectSuccess(page, 'Ledger created');

  // Navigate to the ledger view page
  await page.fill('#ledger-search', ledgerName);
  await page.waitForTimeout(500);
  const row = page.locator('.table-row', { hasText: ledgerName });
  await expect(row).toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
  await row.locator('[aria-label^="View ledger"]').click();
  await expect(page.locator('h1')).toContainText(ledgerName, { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
}

test.describe('Send Email Modal', () => {
  test.describe('Send Reminder — from ledger view', () => {
    test('opens with correct title and pre-filled fields', async ({ authedPage: page }) => {
      const ledgerName = `EmailLedger-${Date.now().toString(36)}`;
      await createLedgerAndNavigateToView(page, ledgerName);

      await page.click('[aria-label="More ledger actions"]');
      await page.click('[role="menuitem"][aria-label="Send Reminder"]');

      const modal = page.locator('[role="dialog"][aria-labelledby="send-email-title"]');
      await expect(modal).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });

      // Title
      await expect(modal.locator('#send-email-title')).toContainText('Send Payment Reminder');

      // To field pre-filled with ledger email
      await expect(modal.locator('#email-to')).toHaveValue(LEDGER_EMAIL);

      // Subject pre-filled (contains "Payment Reminder")
      const subjectValue = await modal.locator('#email-subject').inputValue();
      expect(subjectValue).toContain('Payment Reminder');

      // CC empty by default
      await expect(modal.locator('#email-cc')).toHaveValue('');

      // Message empty by default
      await expect(modal.locator('#email-message')).toHaveValue('');
    });

    test('Cancel button closes the modal', async ({ authedPage: page }) => {
      const ledgerName = `EmailLedger-${Date.now().toString(36)}`;
      await createLedgerAndNavigateToView(page, ledgerName);

      await page.click('[aria-label="More ledger actions"]');
      await page.click('[role="menuitem"][aria-label="Send Reminder"]');
      const modal = page.locator('[role="dialog"][aria-labelledby="send-email-title"]');
      await expect(modal).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });

      await modal.locator('button:has-text("Cancel")').click();
      await expect(modal).not.toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
    });

    test('Escape key closes the modal', async ({ authedPage: page }) => {
      const ledgerName = `EmailLedger-${Date.now().toString(36)}`;
      await createLedgerAndNavigateToView(page, ledgerName);

      await page.click('[aria-label="More ledger actions"]');
      await page.click('[role="menuitem"][aria-label="Send Reminder"]');
      const modal = page.locator('[role="dialog"][aria-labelledby="send-email-title"]');
      await expect(modal).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });

      await page.keyboard.press('Escape');
      await expect(modal).not.toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
    });

    test('Send button is disabled when To field is cleared', async ({ authedPage: page }) => {
      const ledgerName = `EmailLedger-${Date.now().toString(36)}`;
      await createLedgerAndNavigateToView(page, ledgerName);

      await page.click('[aria-label="More ledger actions"]');
      await page.click('[role="menuitem"][aria-label="Send Reminder"]');
      const modal = page.locator('[role="dialog"][aria-labelledby="send-email-title"]');
      await expect(modal).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });

      // Clear the To field
      await modal.locator('#email-to').clear();
      await expect(modal.locator('button:has-text("Send Email")')).toBeDisabled();
    });

    test('Send button is enabled when To field has a value', async ({ authedPage: page }) => {
      const ledgerName = `EmailLedger-${Date.now().toString(36)}`;
      await createLedgerAndNavigateToView(page, ledgerName);

      await page.click('[aria-label="More ledger actions"]');
      await page.click('[role="menuitem"][aria-label="Send Reminder"]');
      const modal = page.locator('[role="dialog"][aria-labelledby="send-email-title"]');
      await expect(modal).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });

      // To is pre-filled, so Send should be enabled
      await expect(modal.locator('button:has-text("Send Email")')).toBeEnabled();
    });

    test('fields are editable', async ({ authedPage: page }) => {
      const ledgerName = `EmailLedger-${Date.now().toString(36)}`;
      await createLedgerAndNavigateToView(page, ledgerName);

      await page.click('[aria-label="More ledger actions"]');
      await page.click('[role="menuitem"][aria-label="Send Reminder"]');
      const modal = page.locator('[role="dialog"][aria-labelledby="send-email-title"]');
      await expect(modal).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });

      // Overwrite To
      await modal.locator('#email-to').fill('other@example.com');
      await expect(modal.locator('#email-to')).toHaveValue('other@example.com');

      // Fill CC
      await modal.locator('#email-cc').fill('cc@example.com');
      await expect(modal.locator('#email-cc')).toHaveValue('cc@example.com');

      // Edit Subject
      await modal.locator('#email-subject').fill('Custom Subject');
      await expect(modal.locator('#email-subject')).toHaveValue('Custom Subject');

      // Fill Message
      await modal.locator('#email-message').fill('Hello, please pay.');
      await expect(modal.locator('#email-message')).toHaveValue('Hello, please pay.');
    });
  });

  test.describe('Email Invoice — from invoice preview', () => {
    async function seedAndOpenInvoicePreview(page: import('@playwright/test').Page) {
      const sku = uniqueSku();
      const productName = `EmailProd-${sku}`;
      const ledgerName = `EmailInvLedger-${Date.now().toString(36)}`;

      // Create product
      await page.click('[href="/products"]');
      await page.fill('#sku', sku);
      await page.fill('#name', productName);
      await page.fill('#price', '500');
      await page.fill('#gst-rate', '18');
      await page.click('button:has-text("Create product")');
      await expectSuccess(page, 'Product created');

      // Add inventory
      await page.click('[href="/inventory"]');
      await expect(page.locator('#inventory-product')).not.toBeDisabled({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
      await selectComboboxOption(page, 'inventory-product', sku);
      await page.fill('#inventory-quantity', '20');
      await page.click('button:has-text("Apply adjustment")');
      await expectSuccess(page, 'Inventory updated');

      // Create ledger with email
      await page.click('[href="/ledgers"]');
      await page.click('button:has-text("Create ledger")');
      await expect(page.locator('h1')).toContainText('Create ledger', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
      await page.fill('#ledger-name', ledgerName);
      await page.fill('#ledger-address', '99 Invoice Email Rd');
      await page.fill('#ledger-gst', uniqueGstin());
      await page.fill('#ledger-phone', '+91 8888888888');
      await page.fill('#ledger-email', LEDGER_EMAIL);
      await page.click('button:has-text("Create ledger")');
      await expectSuccess(page, 'Ledger created');

      // Create invoice
      await page.click('[href="/invoices"]');
      await expect(page.locator('#invoice-ledger')).not.toBeDisabled({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
      await page.selectOption('#invoice-voucher-type', 'sales');
      await selectComboboxOption(page, 'invoice-ledger', ledgerName);
      const productInputId = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
      await selectComboboxOption(page, productInputId, sku);
      await page.locator('[id^="invoice-quantity-"]').first().fill('1');
      await page.click('button:has-text("Create invoice")');
      await expectSuccess(page, 'invoice created');

      // Open preview from the invoice feed view
      await page.goto('/invoices-view');
      await expect(page.locator('h1')).toContainText('Invoice Feed', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
      await page.locator('label.invoice-feed-view__checkbox', { hasText: 'Search all FY' }).locator('input').check();
      await page.getByRole('button', { name: 'Card' }).click();
      const invoiceCard = page.locator('.invoice-compact-card', { hasText: ledgerName }).first();
      await expect(invoiceCard).toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
      await invoiceCard.locator('button[title="Preview"]').click();

      const preview = page.locator('.modal-panel--invoice-preview');
      await expect(preview).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });

      return { preview, ledgerName };
    }

    test('Email Invoice button opens modal with correct title', async ({ authedPage: page }) => {
      const { preview } = await seedAndOpenInvoicePreview(page);

      await preview.locator('button:has-text("Email Invoice")').click();

      const emailModal = page.locator('[role="dialog"][aria-labelledby="send-email-title"]');
      await expect(emailModal).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
      await expect(emailModal.locator('#send-email-title')).toContainText('Email Invoice');

      // Subject contains "Invoice"
      const subject = await emailModal.locator('#email-subject').inputValue();
      expect(subject).toContain('Invoice');
    });

    test('Cancel closes the email modal, leaving invoice preview open', async ({ authedPage: page }) => {
      const { preview } = await seedAndOpenInvoicePreview(page);

      await preview.locator('button:has-text("Email Invoice")').click();
      const emailModal = page.locator('[role="dialog"][aria-labelledby="send-email-title"]');
      await expect(emailModal).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });

      await emailModal.locator('button:has-text("Cancel")').click();
      await expect(emailModal).not.toBeVisible({ timeout: EXPECT_TIMEOUT_MS });

      // Invoice preview should still be visible
      await expect(preview).toBeVisible();
    });
  });

  test.describe('Email Statement — from statement preview', () => {
    async function seedAndOpenStatementPreview(page: import('@playwright/test').Page) {
      const sku = uniqueSku();
      const ledgerName = `EmailStmtLedger-${Date.now().toString(36)}`;

      // Create product
      await page.click('[href="/products"]');
      await page.fill('#sku', sku);
      await page.fill('#name', `StmtProd-${sku}`);
      await page.fill('#price', '100');
      await page.fill('#gst-rate', '18');
      await page.click('button:has-text("Create product")');
      await expectSuccess(page, 'Product created');

      // Add inventory
      await page.click('[href="/inventory"]');
      await expect(page.locator('#inventory-product')).not.toBeDisabled({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
      await selectComboboxOption(page, 'inventory-product', sku);
      await page.fill('#inventory-quantity', '10');
      await page.click('button:has-text("Apply adjustment")');
      await expectSuccess(page, 'Inventory updated');

      // Create ledger with email
      await page.click('[href="/ledgers"]');
      await page.click('button:has-text("Create ledger")');
      await expect(page.locator('h1')).toContainText('Create ledger', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
      await page.fill('#ledger-name', ledgerName);
      await page.fill('#ledger-address', '55 Statement Rd');
      await page.fill('#ledger-gst', uniqueGstin());
      await page.fill('#ledger-phone', '+91 7777777700');
      await page.fill('#ledger-email', LEDGER_EMAIL);
      await page.click('button:has-text("Create ledger")');
      await expectSuccess(page, 'Ledger created');

      // Create an invoice so the statement has entries
      await page.click('[href="/invoices"]');
      await expect(page.locator('#invoice-ledger')).not.toBeDisabled({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
      await page.selectOption('#invoice-voucher-type', 'sales');
      await selectComboboxOption(page, 'invoice-ledger', ledgerName);
      const productInputId = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
      await selectComboboxOption(page, productInputId, sku);
      await page.locator('[id^="invoice-quantity-"]').first().fill('1');
      await page.click('button:has-text("Create invoice")');
      await expectSuccess(page, 'invoice created');

      // Navigate to ledger view
      await page.click('[href="/ledgers"]');
      await page.waitForTimeout(500);
      await page.fill('#ledger-search', ledgerName);
      await page.waitForTimeout(500);
      const row = page.locator('.table-row', { hasText: ledgerName });
      await expect(row).toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
      await row.locator('[aria-label^="View ledger"]').click();
      await expect(page.locator('h1')).toContainText(ledgerName, { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

      // Ensure the selected period definitely includes today and wait for rows.
      const today = new Date();
      const startOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
      await page.locator('#statement-from').fill(startOfMonth.toISOString().split('T')[0]);
      await page.locator('#statement-to').fill(today.toISOString().split('T')[0]);
      await expect(page.locator('.invoice-row').filter({ hasText: 'Sales' }).first()).toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

      // Open statement preview — button only shows when entries exist
      await page.click('button:has-text("Preview / PDF")');
      const statementPreview = page.locator('.modal-panel--invoice-preview');
      await expect(statementPreview).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });

      return statementPreview;
    }

    test('Email Statement button opens modal with correct title', async ({ authedPage: page }) => {
      const statementPreview = await seedAndOpenStatementPreview(page);

      await statementPreview.locator('button:has-text("Email Statement")').click();

      const emailModal = page.locator('[role="dialog"][aria-labelledby="send-email-title"]');
      await expect(emailModal).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
      await expect(emailModal.locator('#send-email-title')).toContainText('Email Statement');

      // Subject contains "Statement"
      const subject = await emailModal.locator('#email-subject').inputValue();
      expect(subject).toContain('Statement');

      // To pre-filled with the ledger email
      await expect(emailModal.locator('#email-to')).toHaveValue(LEDGER_EMAIL);
    });

    test('Cancel closes the email modal leaving statement preview open', async ({ authedPage: page }) => {
      const statementPreview = await seedAndOpenStatementPreview(page);

      await statementPreview.locator('button:has-text("Email Statement")').click();
      const emailModal = page.locator('[role="dialog"][aria-labelledby="send-email-title"]');
      await expect(emailModal).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });

      await emailModal.locator('button:has-text("Cancel")').click();
      await expect(emailModal).not.toBeVisible({ timeout: EXPECT_TIMEOUT_MS });

      // Statement preview should still be visible
      await expect(statementPreview).toBeVisible();
    });
  });
});
