import { test, expect, expectSuccess, uniqueGstin, uniqueSku, clickNavLink, createProduct, adjustInventory, selectComboboxOption } from './fixtures';

const EXPECT_TIMEOUT = Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000');

/**
 * The share dialog opens a WhatsApp deep link in a new tab. Replacing
 * window.open keeps the browser inside the test and hands back the URL that
 * would have been opened, which is the only place the phone-number
 * normalisation is observable end to end.
 */
async function captureWindowOpen(page: import('@playwright/test').Page) {
  await page.evaluate(() => {
    (window as any).__openedUrls = [];
    window.open = (url?: string | URL) => {
      (window as any).__openedUrls.push(String(url));
      return null;
    };
  });
}

async function lastOpenedUrl(page: import('@playwright/test').Page): Promise<string> {
  return page.evaluate(() => {
    const urls = (window as any).__openedUrls as string[];
    return urls[urls.length - 1] || '';
  });
}

test.describe('Share link', () => {
  test('creates, copies, WhatsApps, revokes and recreates a statement link', async ({ authedPage: page }) => {
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);

    // A ledger with a phone in the format the app actually stores: free text
    // with a country code and spaces, which toWhatsAppNumber has to survive.
    const ledgerName = `ShareLedger-${Date.now().toString(36)}`;
    await clickNavLink(page, '/ledgers');
    await expect(page.locator('h1')).toContainText('Ledger master');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Create ledger', { timeout: EXPECT_TIMEOUT });

    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '9 Share Street');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 6666666666');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: EXPECT_TIMEOUT });
    await expectSuccess(page, 'Ledger created');

    await page.fill('#ledger-search', ledgerName);
    await page.waitForTimeout(1_000);
    const row = page.locator('.table-row', { hasText: ledgerName });
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.locator('[aria-label^="View ledger"]').click();
    await expect(page.locator('h1')).toContainText(ledgerName, { timeout: EXPECT_TIMEOUT });

    // Share sits in the split button's dropdown, beside Send Reminder.
    await page.locator('[aria-label="More ledger actions"]').click();
    await page.locator('[aria-label="Share Statement"]').click();

    // Located by the title, not by the URL field: the field disappears while
    // the link is revoked and the dialog has to stay addressable through that.
    const dialog = page.locator('.modal-panel', { has: page.locator('#share-modal-title') });
    await expect(dialog).toBeVisible({ timeout: 10_000 });

    // The link is created on open — no extra confirmation step.
    const urlField = dialog.locator('#share-link-url');
    await expect(urlField).toHaveValue(/\/s\/\S+/, { timeout: 10_000 });
    const shareUrl = await urlField.inputValue();
    const token = shareUrl.split('/s/')[1];
    expect(token).toBeTruthy();

    // A brand-new link has never been opened, and says so neutrally.
    await expect(dialog).toContainText('Not opened yet');

    // Copy shows a transient confirmation and puts the URL on the clipboard.
    await dialog.locator('[aria-label="Copy share link"]').click();
    await expect(dialog.locator('[aria-label="Copy share link"]')).toContainText('Copied');
    const clipboard = await page.evaluate(() => navigator.clipboard.readText());
    expect(clipboard).toBe(shareUrl);

    // WhatsApp opens wa.me addressed to the ledger's number, digits only, with
    // the message and the share URL in the text parameter.
    await captureWindowOpen(page);
    await dialog.locator('[aria-label="Send on WhatsApp"]').click();
    const waUrl = await lastOpenedUrl(page);
    expect(waUrl).toContain('https://wa.me/916666666666?text=');
    expect(decodeURIComponent(waUrl)).toContain(shareUrl);
    expect(decodeURIComponent(waUrl)).toContain('Account statement');

    // Revoking is behind the shared confirm dialog.
    await dialog.locator('[aria-label="Revoke share link"]').click();
    const confirm = page.getByRole('dialog', { name: 'Revoke this link?' });
    await expect(confirm).toBeVisible({ timeout: EXPECT_TIMEOUT });
    await confirm.getByRole('button', { name: 'Revoke link' }).click();

    // The dead link is gone from the dialog, not left sitting there looking live.
    await expect(dialog).toContainText('This link has been revoked', { timeout: 10_000 });
    await expect(dialog.locator('#share-link-url')).toHaveCount(0);

    // Creating a new one issues a different token; the old one stays dead.
    await dialog.getByRole('button', { name: 'Create a new share link' }).click();
    await expect(dialog.locator('#share-link-url')).toHaveValue(/\/s\/\S+/, { timeout: 10_000 });
    const newUrl = await dialog.locator('#share-link-url').inputValue();
    expect(newUrl).not.toBe(shareUrl);

    // Escape closes the share dialog itself once no confirm is stacked on it.
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
  });

  test('shares an invoice from the invoice preview header', async ({ authedPage: page }) => {
    const sku = uniqueSku();
    const productName = `ShareProd ${sku}`;
    const ledgerName = `ShareInvLedger-${Date.now().toString(36)}`;

    await clickNavLink(page, '/catalogue');
    await createProduct(page, { sku, name: productName, price: '500', gstRate: '18' });
    await adjustInventory(page, sku, '50');

    await clickNavLink(page, '/ledgers');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Create ledger', { timeout: EXPECT_TIMEOUT });
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '11 Share Lane');
    await page.fill('#ledger-gst', uniqueGstin());
    // No country code and a leading zero — the shape toWhatsAppNumber has to
    // repair before wa.me will take it.
    await page.fill('#ledger-phone', '09876543210');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: EXPECT_TIMEOUT });
    await expectSuccess(page, 'Ledger created');

    await clickNavLink(page, '/invoices');
    await expect(page.locator('#invoice-ledger')).not.toBeDisabled({ timeout: EXPECT_TIMEOUT });
    await page.selectOption('#invoice-voucher-type', 'sales');
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);
    const productInputId = (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId, sku);
    await page.locator('[id^="invoice-quantity-"]').first().fill('2');
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'invoice created');

    // The preview opens straight off creation on the invoices page.
    const preview = page.locator('.modal-panel--invoice-preview');
    await expect(preview).toBeVisible({ timeout: 10_000 });

    await captureWindowOpen(page);
    await preview.getByRole('button', { name: 'Share invoice' }).click();

    const dialog = page.locator('.modal-panel', { has: page.locator('#share-modal-title') });
    await expect(dialog).toBeVisible({ timeout: 10_000 });
    const shareUrl = await dialog.locator('#share-link-url').inputValue();
    expect(shareUrl).toContain('/s/');

    await dialog.locator('[aria-label="Send on WhatsApp"]').click();
    const waUrl = await lastOpenedUrl(page);
    // 09876543210 → leading zero dropped, ten digits left, default 91 prefixed.
    expect(waUrl).toContain('https://wa.me/919876543210?text=');
    expect(decodeURIComponent(waUrl)).toContain(shareUrl);

    // Escape closes the share dialog and leaves the preview behind it standing.
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(preview).toBeVisible();
  });
});
