import type { Page } from '@playwright/test';
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
 * Quotations and proforma invoices, from the composer to a real invoice and back.
 *
 * The walk that matters: a quotation moves no stock; converting it does, once; a
 * second conversion finds the invoice that already exists; and cancelling that
 * invoice reopens the quotation.
 */
test.describe('Quotations', () => {
  const OPENING_STOCK = '50';

  async function seed(page: Page) {
    const sku = uniqueSku();
    const productName = `QT-Prod ${sku}`;
    const ledgerName = `QT-Customer-${Date.now().toString(36)}`;

    await clickNavLink(page, '/catalogue');
    await createProduct(page, { sku, name: productName, price: '100', gstRate: '18', openingQuantity: OPENING_STOCK });

    await clickNavLink(page, '/ledgers');
    await page.click('button:has-text("Create ledger")');
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '12 Buyer Street');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 5555555555');
    await page.click('button:has-text("Create ledger")');
    await expectSuccess(page, 'Ledger created');

    return { sku, productName, ledgerName };
  }

  async function stockOf(page: Page, sku: string) {
    await clickNavLink(page, '/catalogue');
    await catalogueSearch(page).fill(sku);
    const row = catalogueRow(page, sku);
    await expect(row).toBeVisible();
    return row;
  }

  async function composeQuote(
    page: Page,
    { documentType, ledgerName, sku, quantity }:
      { documentType: 'quotation' | 'proforma'; ledgerName: string; sku: string; quantity: string },
  ) {
    await page.goto(`/invoices?new=${documentType}`);
    await expect(page.locator('#invoice-voucher-type')).toHaveValue(documentType);
    await selectComboboxOption(page, 'invoice-ledger', ledgerName);
    await selectComboboxOption(page, 'invoice-product-1', sku);
    await page.fill('#invoice-quantity-1', quantity);
    await page.fill('#invoice-price-1', '90');
    await expect(page.locator('#quotation-valid-until')).not.toHaveValue('');
    await page.click(`button:has-text("Create ${documentType === 'proforma' ? 'proforma invoice' : 'quotation'}")`);
    await expectSuccess(page, 'Stock and the books are unchanged');
    const dialog = page.getByRole('dialog', { name: /Quotation|Proforma/ });
    await expect(dialog).toBeVisible();
    const heading = await dialog.locator('#quotation-preview-title').innerText();
    await dialog.getByRole('button', { name: /Close (quotation|proforma invoice) preview/ }).click();
    return heading.trim().split(' ').pop() as string;
  }

  test('a quotation moves nothing, and a conversion moves it once', async ({ authedPage: page }) => {
    test.setTimeout(120_000);
    const { sku, ledgerName } = await seed(page);

    const quotationNumber = await composeQuote(page, { documentType: 'quotation', ledgerName, sku, quantity: '3' });
    expect(quotationNumber).toMatch(/^QT/);
    const proformaNumber = await composeQuote(page, { documentType: 'proforma', ledgerName, sku, quantity: '2' });
    expect(proformaNumber).toMatch(/^PI/);

    // Both on the list, under the right names, and stock has not moved.
    await clickNavLink(page, '/quotations');
    const quoteRow = page.locator('tr', { hasText: quotationNumber });
    await expect(quoteRow).toContainText('Quotation');
    await expect(quoteRow).toContainText('Open');
    await expect(page.locator('tr', { hasText: proformaNumber })).toContainText('Proforma invoice');
    await expect(await stockOf(page, sku)).toContainText(OPENING_STOCK);

    // Its PDF downloads.
    await clickNavLink(page, '/quotations');
    await page.locator('tr', { hasText: quotationNumber }).getByRole('button', { name: quotationNumber }).click();
    const preview = page.getByRole('dialog', { name: /Quotation/ });
    await expect(preview.locator('iframe')).toBeVisible();
    const download = page.waitForEvent('download');
    await preview.getByRole('button', { name: 'Download' }).click();
    expect((await download).suggestedFilename()).toBe(`quotation_${quotationNumber}.pdf`);
    await preview.getByRole('button', { name: 'Close quotation preview' }).click();

    // Convert through the composer, which opens filled in and locked to a sale.
    await page.locator('tr', { hasText: quotationNumber }).getByRole('button', { name: 'Convert to invoice' }).click();
    await expect(page.getByTestId('quotation-conversion-banner')).toContainText(quotationNumber);
    await expect(page.locator('#invoice-voucher-type')).toHaveValue('sales');
    await expect(page.locator('#invoice-voucher-type')).toBeDisabled();
    await expect(page.locator('#invoice-quantity-1')).toHaveValue('3');
    await expect(page.locator('#invoice-price-1')).toHaveValue('90');

    // A second tab opens the same conversion before the first one saves.
    const secondTab = await page.context().newPage();
    await secondTab.goto(page.url());
    await expect(secondTab.getByTestId('quotation-conversion-banner')).toContainText(quotationNumber);

    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, `created from ${quotationNumber}`);
    const invoiceDialog = page.getByRole('dialog', { name: /Invoice/ });
    await expect(invoiceDialog).toContainText(`Created from ${quotationNumber}`);
    const invoiceTitle = await invoiceDialog.locator('h2, h1').first().innerText();
    const invoiceNumber = invoiceTitle.match(/INV\S+/)?.[0] as string;
    expect(invoiceNumber).toBeTruthy();
    await invoiceDialog.getByRole('button', { name: /Close invoice preview/ }).click();

    // Double conversion: the second tab gets told where the invoice is.
    await secondTab.click('button:has-text("Create invoice")');
    const conflict = secondTab.getByTestId('quotation-already-converted');
    await expect(conflict).toContainText(invoiceNumber);
    await expect(conflict.getByRole('link', { name: 'Open invoice' })).toBeVisible();
    await secondTab.close();

    // Stock moved once, and the quotation closed.
    await expect(await stockOf(page, sku)).toContainText('47');
    await clickNavLink(page, '/quotations');
    const converted = page.locator('tr', { hasText: quotationNumber });
    await expect(converted).toContainText('Converted');
    await expect(converted).toContainText(invoiceNumber);
    await expect(converted.getByRole('button', { name: 'Convert to invoice' })).toHaveCount(0);

    // Cancel the invoice: stock comes back and the quotation reopens.
    await page.goto(`/invoices-view?search=${encodeURIComponent(invoiceNumber)}`);
    await page.getByRole('tab', { name: 'Card' }).click();
    const card = page.locator('.invoice-compact-card', { hasText: invoiceNumber }).first();
    await card.locator('button[title="Cancel"]').click();
    await page.click('button:has-text("Cancel invoice")');
    await expectSuccess(page, 'Invoice cancelled');

    await expect.poll(async () => {
      await page.goto('/quotations');
      return page.locator('tr', { hasText: quotationNumber }).innerText();
    }, { timeout: 15_000 }).toContain('Open');
    await expect(page.locator('tr', { hasText: quotationNumber }).getByRole('button', { name: 'Convert to invoice' })).toBeVisible();
    await expect(await stockOf(page, sku)).toContainText(OPENING_STOCK);
  });

  test('a serial-tracked line holds no serials until conversion, then needs them', async ({ authedPage: page }) => {
    test.setTimeout(60_000);
    const stamp = uniqueSku();
    const send = (method: string, path: string, body: unknown) => page.evaluate(
      async ({ method, path, body }) => {
        const response = await fetch(`/api${path}`, {
          method,
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('token')}` },
          body: JSON.stringify(body),
        });
        if (!response.ok) throw new Error(`${path} -> ${response.status} ${await response.text()}`);
        return response.json();
      },
      { method, path, body },
    );
    const imeis = [0, 1].map((index) => `${Date.now().toString().slice(-11)}${stamp.slice(-2)}0${index}`);
    const phone = await send('POST', '/products/', {
      sku: `${stamp}-PH`, name: `AA-QT Phone ${stamp}`, price: 500, gst_rate: 18,
      track_serials: true, maintain_inventory: true, initial_quantity: 0,
    });
    const ledger = await send('POST', '/ledgers/', {
      name: `AA-QT-Ledger-${stamp}`, address: '1 Scan Street', gst: uniqueGstin(), phone_number: '+91 5555555555',
    });
    await send('POST', '/invoices/', {
      ledger_id: ledger.id,
      voucher_type: 'purchase',
      items: [{ product_id: phone.id, quantity: 2, unit_price: 300, serial_numbers: imeis }],
    });

    // Quoting: quantity is the shopkeeper's to type, and no serial UI in the way.
    await page.goto('/invoices?new=quotation');
    await expect(page.locator('#invoice-voucher-type')).toHaveValue('quotation');
    await selectComboboxOption(page, 'invoice-ledger', ledger.name);
    await selectComboboxOption(page, 'invoice-product-1', phone.name);
    await expect(page.locator('#invoice-quantity-1')).toBeEnabled();
    await expect(page.locator('#scan-bar-input')).toHaveCount(0);
    await page.fill('#invoice-quantity-1', '2');
    await page.click('button:has-text("Create quotation")');
    await expectSuccess(page, 'Stock and the books are unchanged');

    const dialog = page.getByRole('dialog', { name: /Quotation/ });
    const quotationNumber = (await dialog.locator('#quotation-preview-title').innerText()).trim().split(' ').pop() as string;
    await dialog.getByRole('button', { name: 'Close quotation preview' }).click();

    // Converting: told how many to scan, blocked until they are.
    await page.goto(`/quotations?search=${encodeURIComponent(quotationNumber)}`);
    await page.locator('tr', { hasText: quotationNumber }).getByRole('button', { name: 'Convert to invoice' }).click();
    const banner = page.getByTestId('quotation-conversion-banner');
    await expect(banner.locator('[data-warning="serials_required"]')).toContainText('Scan the 2 units');
    await expect(page.locator('#invoice-quantity-1')).toBeDisabled();
    await page.click('button:has-text("Create invoice")');
    await expect(page.locator('.serial-line__message--blocking')).toBeVisible();

    await page.locator('#scan-bar-input').click();
    for (const imei of imeis) {
      await page.keyboard.type(imei, { delay: 5 });
      await page.keyboard.press('Enter');
      await expect(page.getByRole('button', { name: `Remove serial ${imei}` })).toBeVisible();
    }
    await expect(page.locator('#invoice-quantity-1')).toHaveValue('2');
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, `created from ${quotationNumber}`);
  });

  test('status moves offer only what the status allows', async ({ authedPage: page }) => {
    test.setTimeout(60_000);
    const { sku, ledgerName } = await seed(page);
    const number = await composeQuote(page, { documentType: 'quotation', ledgerName, sku, quantity: '1' });

    await clickNavLink(page, '/quotations');
    await page.locator('tr', { hasText: number }).getByRole('button', { name: number }).click();
    const preview = page.getByRole('dialog', { name: /Quotation/ });
    await preview.getByRole('button', { name: 'More actions' }).click();
    await page.getByRole('menuitem', { name: 'Mark declined' }).click();
    const statusDialog = page.getByRole('dialog', { name: /Mark declined/ });
    await statusDialog.locator('#quotation-status-note').fill('Too dear');
    await statusDialog.getByRole('button', { name: 'Mark declined' }).click();
    await expectSuccess(page, 'declined');
    await preview.getByRole('button', { name: 'Close quotation preview' }).click();

    const row = page.locator('tr', { hasText: number });
    await expect(row).toContainText('Declined');
    await expect(row.getByRole('button', { name: 'Convert to invoice' })).toHaveCount(0);
  });
});
