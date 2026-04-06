import { test, expect, expectSuccess, uniqueSku, uniqueGstin } from './fixtures';

const LEDGER_EMAIL = 'buyer@example.com';

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
  await expect(page.locator('h1')).toContainText('Create ledger', { timeout: 10_000 });

  await page.fill('#ledger-name', ledgerName);
  await page.fill('#ledger-address', '1 Email Test Road');
  await page.fill('#ledger-gst', uniqueGstin());
  await page.fill('#ledger-phone', '+91 9999999999');
  await page.fill('#ledger-email', LEDGER_EMAIL);
  await page.click('button:has-text("Create ledger")');
  await expect(page.locator('h1')).toContainText('Ledger master', { timeout: 10_000 });
  await expectSuccess(page, 'Ledger created');

  // Navigate to the ledger view page
  await page.fill('#ledger-search', ledgerName);
  await page.waitForTimeout(500);
  const row = page.locator('.table-row', { hasText: ledgerName });
  await expect(row).toBeVisible({ timeout: 10_000 });
  await row.locator('button:has-text("View")').click();
  await expect(page.locator('h1')).toContainText(ledgerName, { timeout: 10_000 });
}

test.describe('Send Email Modal', () => {
  test.describe('Send Reminder — from ledger view', () => {
    test('opens with correct title and pre-filled fields', async ({ authedPage: page }) => {
      const ledgerName = `EmailLedger-${Date.now().toString(36)}`;
      await createLedgerAndNavigateToView(page, ledgerName);

      await page.click('button:has-text("Send Reminder")');

      const modal = page.locator('[role="dialog"][aria-labelledby="send-email-title"]');
      await expect(modal).toBeVisible({ timeout: 5_000 });

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

      await page.click('button:has-text("Send Reminder")');
      const modal = page.locator('[role="dialog"][aria-labelledby="send-email-title"]');
      await expect(modal).toBeVisible({ timeout: 5_000 });

      await modal.locator('button:has-text("Cancel")').click();
      await expect(modal).not.toBeVisible({ timeout: 5_000 });
    });

    test('Escape key closes the modal', async ({ authedPage: page }) => {
      const ledgerName = `EmailLedger-${Date.now().toString(36)}`;
      await createLedgerAndNavigateToView(page, ledgerName);

      await page.click('button:has-text("Send Reminder")');
      const modal = page.locator('[role="dialog"][aria-labelledby="send-email-title"]');
      await expect(modal).toBeVisible({ timeout: 5_000 });

      await page.keyboard.press('Escape');
      await expect(modal).not.toBeVisible({ timeout: 5_000 });
    });

    test('Send button is disabled when To field is cleared', async ({ authedPage: page }) => {
      const ledgerName = `EmailLedger-${Date.now().toString(36)}`;
      await createLedgerAndNavigateToView(page, ledgerName);

      await page.click('button:has-text("Send Reminder")');
      const modal = page.locator('[role="dialog"][aria-labelledby="send-email-title"]');
      await expect(modal).toBeVisible({ timeout: 5_000 });

      // Clear the To field
      await modal.locator('#email-to').clear();
      await expect(modal.locator('button:has-text("Send Email")')).toBeDisabled();
    });

    test('Send button is enabled when To field has a value', async ({ authedPage: page }) => {
      const ledgerName = `EmailLedger-${Date.now().toString(36)}`;
      await createLedgerAndNavigateToView(page, ledgerName);

      await page.click('button:has-text("Send Reminder")');
      const modal = page.locator('[role="dialog"][aria-labelledby="send-email-title"]');
      await expect(modal).toBeVisible({ timeout: 5_000 });

      // To is pre-filled, so Send should be enabled
      await expect(modal.locator('button:has-text("Send Email")')).toBeEnabled();
    });

    test('fields are editable', async ({ authedPage: page }) => {
      const ledgerName = `EmailLedger-${Date.now().toString(36)}`;
      await createLedgerAndNavigateToView(page, ledgerName);

      await page.click('button:has-text("Send Reminder")');
      const modal = page.locator('[role="dialog"][aria-labelledby="send-email-title"]');
      await expect(modal).toBeVisible({ timeout: 5_000 });

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
      await page.fill('#inventory-quantity', '20');
      await page.click('button:has-text("Apply adjustment")');
      await expectSuccess(page, 'Inventory updated');

      // Create ledger with email
      await page.click('[href="/ledgers"]');
      await page.click('button:has-text("Create ledger")');
      await expect(page.locator('h1')).toContainText('Create ledger', { timeout: 10_000 });
      await page.fill('#ledger-name', ledgerName);
      await page.fill('#ledger-address', '99 Invoice Email Rd');
      await page.fill('#ledger-gst', uniqueGstin());
      await page.fill('#ledger-phone', '+91 8888888888');
      await page.fill('#ledger-email', LEDGER_EMAIL);
      await page.click('button:has-text("Create ledger")');
      await expectSuccess(page, 'Ledger created');

      // Create invoice
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
      await page.locator('[id^="invoice-quantity-"]').first().fill('1');
      await page.click('button:has-text("Create invoice")');
      await expectSuccess(page, 'invoice created');

      // Open preview of the first invoice matching the ledger
      const invoiceRow = page.locator('.invoice-row', { hasText: ledgerName }).first();
      await expect(invoiceRow).toBeVisible({ timeout: 10_000 });
      await invoiceRow.locator('button:has-text("Preview")').click();

      const preview = page.locator('.modal-panel--invoice-preview');
      await expect(preview).toBeVisible({ timeout: 5_000 });

      return { preview, ledgerName };
    }

    test('Email Invoice button opens modal with correct title', async ({ authedPage: page }) => {
      const { preview } = await seedAndOpenInvoicePreview(page);

      await preview.locator('button:has-text("Email Invoice")').click();

      const emailModal = page.locator('[role="dialog"][aria-labelledby="send-email-title"]');
      await expect(emailModal).toBeVisible({ timeout: 5_000 });
      await expect(emailModal.locator('#send-email-title')).toContainText('Email Invoice');

      // Subject contains "Invoice"
      const subject = await emailModal.locator('#email-subject').inputValue();
      expect(subject).toContain('Invoice');
    });

    test('Cancel closes the email modal, leaving invoice preview open', async ({ authedPage: page }) => {
      const { preview } = await seedAndOpenInvoicePreview(page);

      await preview.locator('button:has-text("Email Invoice")').click();
      const emailModal = page.locator('[role="dialog"][aria-labelledby="send-email-title"]');
      await expect(emailModal).toBeVisible({ timeout: 5_000 });

      await emailModal.locator('button:has-text("Cancel")').click();
      await expect(emailModal).not.toBeVisible({ timeout: 5_000 });

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
      await page.fill('#inventory-quantity', '10');
      await page.click('button:has-text("Apply adjustment")');
      await expectSuccess(page, 'Inventory updated');

      // Create ledger with email
      await page.click('[href="/ledgers"]');
      await page.click('button:has-text("Create ledger")');
      await expect(page.locator('h1')).toContainText('Create ledger', { timeout: 10_000 });
      await page.fill('#ledger-name', ledgerName);
      await page.fill('#ledger-address', '55 Statement Rd');
      await page.fill('#ledger-gst', uniqueGstin());
      await page.fill('#ledger-phone', '+91 7777777700');
      await page.fill('#ledger-email', LEDGER_EMAIL);
      await page.click('button:has-text("Create ledger")');
      await expectSuccess(page, 'Ledger created');

      // Create an invoice so the statement has entries
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
      await page.locator('[id^="invoice-quantity-"]').first().fill('1');
      await page.click('button:has-text("Create invoice")');
      await expectSuccess(page, 'invoice created');

      // Navigate to ledger view
      await page.click('[href="/ledgers"]');
      await page.waitForTimeout(500);
      await page.fill('#ledger-search', ledgerName);
      await page.waitForTimeout(500);
      const row = page.locator('.table-row', { hasText: ledgerName });
      await expect(row).toBeVisible({ timeout: 10_000 });
      await row.locator('button:has-text("View")').click();
      await expect(page.locator('h1')).toContainText(ledgerName, { timeout: 10_000 });

      // Wait for statement to load with today's date range (default)
      await page.waitForTimeout(1_000);

      // Open statement preview — button only shows when entries exist
      await page.click('button:has-text("Preview / PDF")');
      const statementPreview = page.locator('.modal-panel--invoice-preview');
      await expect(statementPreview).toBeVisible({ timeout: 5_000 });

      return statementPreview;
    }

    test('Email Statement button opens modal with correct title', async ({ authedPage: page }) => {
      const statementPreview = await seedAndOpenStatementPreview(page);

      await statementPreview.locator('button:has-text("Email Statement")').click();

      const emailModal = page.locator('[role="dialog"][aria-labelledby="send-email-title"]');
      await expect(emailModal).toBeVisible({ timeout: 5_000 });
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
      await expect(emailModal).toBeVisible({ timeout: 5_000 });

      await emailModal.locator('button:has-text("Cancel")').click();
      await expect(emailModal).not.toBeVisible({ timeout: 5_000 });

      // Statement preview should still be visible
      await expect(statementPreview).toBeVisible();
    });
  });
});
