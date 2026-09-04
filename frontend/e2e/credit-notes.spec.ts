import {
  test,
  expect,
  expectSuccess,
  uniqueSku,
  uniqueGstin,
  selectComboboxOption,
  clickNavLink,
  createProduct,
  catalogueSearch,
  catalogueRow,
} from './fixtures';

/**
 * Credit notes, both directions.
 *
 * The purchase side is the supplier's own credit note recorded on our side —
 * under s.34 CGST we issue nothing, so what is entered here is their number
 * and date, and the note must move stock the other way from a sales return.
 */
test.describe('Credit notes', () => {
  const timeout = Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000');

  async function seed(page: import('@playwright/test').Page) {
    const sku = uniqueSku();
    const productName = `CN-Prod ${sku}`;
    const ledgerName = `CN-Supplier-${Date.now().toString(36)}`;

    await clickNavLink(page, '/catalogue');
    await createProduct(page, { sku, name: productName, price: '100', gstRate: '18' });

    await clickNavLink(page, '/ledgers');
    await page.click('button:has-text("Create ledger")');
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '12 Supply Lane');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 5555555555');
    await page.click('button:has-text("Create ledger")');
    await expectSuccess(page, 'Ledger created');

    return { sku, productName, ledgerName };
  }

  async function createInvoice(
    page: import('@playwright/test').Page,
    { sku, ledgerName, voucherType, quantity }:
      { sku: string; ledgerName: string; voucherType: 'sales' | 'purchase'; quantity: string },
  ) {
    await clickNavLink(page, '/invoices');
    await page.waitForTimeout(500);
    await page.selectOption('#invoice-voucher-type', voucherType);
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);

    const productInputId =
      (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId, sku);
    await page.locator('[id^="invoice-quantity-"]').first().fill(quantity);

    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, 'invoice created');

    // The PDF preview opens over the shell and swallows nav clicks.
    const preview = page.locator('.modal-overlay[aria-labelledby="invoice-preview-title"]');
    if (await preview.isVisible()) {
      // The only way out is the icon button in the panel header — it carries
      // title="Close" and an aria-label, but no text.
      await preview.getByTitle('Close').click();
      await expect(preview).not.toBeVisible({ timeout });
    }
  }

  async function stockOf(page: import('@playwright/test').Page, sku: string) {
    await clickNavLink(page, '/catalogue');
    await catalogueSearch(page).fill(sku);
    const row = catalogueRow(page, sku);
    await expect(row).toBeVisible({ timeout });
    const stock = row.getByTitle(/^Adjust stock for /);
    return Number((await stock.textContent())?.replace(/[^\d.-]/g, '') || '0');
  }

  test('records a supplier credit note and takes the stock back out', async ({ authedPage: page }) => {
    const { sku, ledgerName } = await seed(page);
    await createInvoice(page, { sku, ledgerName, voucherType: 'purchase', quantity: '10' });

    expect(await stockOf(page, sku)).toBe(10);

    await clickNavLink(page, '/credit-notes');
    await page.selectOption('#credit-note-direction', 'inward');
    await selectComboboxOption(page, 'credit-note-ledger', ledgerName);

    // Their document, not ours — this is what reconciles against GSTR-2B.
    await page.fill('#credit-note-supplier-number', 'SUP/CN/E2E');
    await page.fill('#credit-note-supplier-date', '2026-09-01');

    await page.locator('label:has(input[type="checkbox"])').first().click();
    await page.locator('input[type="number"]').first().fill('4');

    await page.click('button:has-text("Record Supplier Credit Note")');
    await expectSuccess(page, 'SUP/CN/E2E recorded as');

    // Our own DN number, kept out of the outward credit note series.
    const card = page.locator('.panel', { hasText: 'SUP/CN/E2E' }).first();
    await expect(card).toContainText('Purchase');
    await expect(card).toContainText(/DN-/);

    // The goods went back, so stock falls rather than rises.
    expect(await stockOf(page, sku)).toBe(6);
  });

  test('the purchase tab offers only purchase invoices', async ({ authedPage: page }) => {
    const { sku, ledgerName } = await seed(page);
    await createInvoice(page, { sku, ledgerName, voucherType: 'purchase', quantity: '10' });
    await createInvoice(page, { sku, ledgerName, voucherType: 'sales', quantity: '2' });

    await clickNavLink(page, '/credit-notes');
    await selectComboboxOption(page, 'credit-note-ledger', ledgerName);

    // Sales tab: one invoice, the sale.
    await expect(page.getByText(/1 active sales invoices for this ledger/)).toBeVisible({ timeout });

    await page.selectOption('#credit-note-direction', 'inward');
    await expect(page.getByText(/1 active purchase invoices for this ledger/)).toBeVisible({ timeout });
  });

  test('the supplier fields only exist on the purchase tab', async ({ authedPage: page }) => {
    await clickNavLink(page, '/credit-notes');
    await expect(page.locator('#credit-note-supplier-number')).toBeHidden();

    await page.selectOption('#credit-note-direction', 'inward');
    await expect(page.locator('#credit-note-supplier-number')).toBeVisible({ timeout });

    await page.selectOption('#credit-note-direction', 'outward');
    await expect(page.locator('#credit-note-supplier-number')).toBeHidden();
  });
});
