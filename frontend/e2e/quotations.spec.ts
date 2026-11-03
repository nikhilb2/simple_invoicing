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

/**
 * The same walk, checked against the books rather than the list: what a quotation
 * is allowed to touch, what a conversion must touch exactly once, and what a failed
 * conversion must leave alone. Setup and readings go through the API; the pages
 * under test are driven as a person would.
 */
test.describe('Quotations and the books', () => {
  type Reply = { status: number; json: any; text: string };

  async function call(page: Page, method: string, path: string, body?: unknown): Promise<Reply> {
    return page.evaluate(
      async ({ method, path, body }) => {
        const response = await fetch(`/api${path}`, {
          method,
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('token')}` },
          body: body === undefined ? undefined : JSON.stringify(body),
        });
        const text = await response.text();
        let json: any = null;
        try { json = JSON.parse(text); } catch { /* not JSON */ }
        return { status: response.status, json, text };
      },
      { method, path, body },
    );
  }

  async function must(page: Page, method: string, path: string, body?: unknown) {
    const reply = await call(page, method, path, body);
    expect(reply.status, `${method} ${path}: ${reply.text}`).toBe(200);
    return reply.json;
  }

  async function world(page: Page, stock = 50) {
    const stamp = uniqueSku();
    const product = await must(page, 'POST', '/products/', {
      sku: `${stamp}-B`, name: `QB-Prod ${stamp}`, hsn_sac: '84713010', price: 100, gst_rate: 18,
      maintain_inventory: true, initial_quantity: stock,
    });
    const ledger = await must(page, 'POST', '/ledgers/', {
      name: `QB-Cust-${stamp}`, address: '12 Buyer Street, Mumbai 400001', gst: uniqueGstin('27'), phone_number: '+91 5555555555',
    });
    return { product, ledger };
  }

  const quoteBody = (
    w: { product: { id: number; sku: string }; ledger: { id: number } },
    documentType: 'quotation' | 'proforma',
    quantity: number,
  ) => ({
    document_type: documentType,
    ledger_id: w.ledger.id,
    items: [{ product_id: w.product.id, quantity, unit_price: 90 }],
  });

  const RANGE = 'from_date=2020-01-01&to_date=2035-01-01';

  /** Every surface that reads invoices or stock, as the text the API returns. */
  async function readBooks(page: Page, w: { product: { id: number; sku: string }; ledger: { id: number } }) {
    const paths = [
      '/dashboard/metrics',
      `/analytics/sales-by-month?${RANGE}`,
      `/analytics/sales-by-product?${RANGE}`,
      `/analytics/profit-loss?${RANGE}`,
      '/invoices/?page_size=100',
      '/invoices/export',
      '/invoices/dues',
      '/invoices/dues/ageing',
      `/ledgers/day-book?${RANGE}`,
      `/ledgers/${w.ledger.id}/statement?${RANGE}`,
      `/ledgers/tax-ledger/?${RANGE}`,
      `/ledgers/tax-ledger/gstr1/summary?${RANGE}`,
      `/ledgers/tax-ledger/gstr1/export-json?${RANGE}`,
      `/ledgers/tax-ledger/gstr1/export-csv?${RANGE}`,
      '/inventory/?page_size=100',
      `/products/with-inventory?search=${encodeURIComponent(w.product.sku)}`,
      '/payments/',
    ];
    const books: Record<string, string> = {};
    for (const path of paths) {
      // Whatever it answers, status and body: GSTR-1 JSON refuses a period holding
      // an invoice without HSN, which other specs leave behind, and a refusal that
      // does not move is as good a reading as a file that does not.
      const reply = await call(page, 'GET', path);
      expect(reply.status, path).toBeLessThan(500);
      books[path] = `${reply.status} ${reply.text}`;
    }
    const series: Array<{ voucher_type: string; next_sequence: number }> = await must(page, 'GET', '/invoice-series/');
    const next = (type: string) => series.find((row) => row.voucher_type === type)!.next_sequence;
    const stock = await must(page, 'GET', `/products/with-inventory?search=${encodeURIComponent(w.product.sku)}`);
    const rows: any[] = Array.isArray(stock) ? stock : stock.items;
    const invoices = await must(page, 'GET', '/invoices/?page_size=1');
    return {
      books,
      salesNext: next('sales'),
      quotationNext: next('quotation'),
      proformaNext: next('proforma'),
      invoiceCount: invoices.total as number,
      stockOf: rows.find((row) => row.id === w.product.id).current_stock as number,
    };
  }

  const changed = (before: Record<string, string>, after: Record<string, string>) =>
    Object.keys(before).filter((path) => before[path] !== after[path]);

  test('creating, editing and moving quotations changes no figure; converting changes each by one invoice', async ({ authedPage: page }) => {
    test.setTimeout(120_000);
    const w = await world(page);
    const before = await readBooks(page, w);

    const quotation = await must(page, 'POST', '/quotations/', quoteBody(w, 'quotation', 3));
    const proforma = await must(page, 'POST', '/quotations/', quoteBody(w, 'proforma', 2));
    await must(page, 'PUT', `/quotations/${quotation.id}`, { ledger_id: w.ledger.id, items: [{ product_id: w.product.id, quantity: 4, unit_price: 90 }] });
    await must(page, 'POST', `/quotations/${proforma.id}/status`, { status: 'accepted' });
    await must(page, 'POST', `/quotations/${proforma.id}/duplicate`);

    const drafted = await readBooks(page, w);
    expect(changed(before.books, drafted.books)).toEqual([]);
    expect(drafted.salesNext).toBe(before.salesNext);
    expect(drafted.invoiceCount).toBe(before.invoiceCount);
    expect(drafted.stockOf).toBe(before.stockOf);
    // Their own numbers moved, and nothing else's.
    expect(drafted.quotationNext).toBe(before.quotationNext + 1);
    expect(drafted.proformaNext).toBe(before.proformaNext + 2);

    // The reports pages agree: the ledger's statement lists no entry for them.
    await page.goto(`/ledgers/${w.ledger.id}`);
    await expect(page.locator('h1')).toContainText(w.ledger.name);
    await expect(page.locator('#statement-from')).toBeVisible();
    await expect(page.getByText(quotation.quotation_number)).toHaveCount(0);
    await expect(page.getByText(proforma.quotation_number)).toHaveCount(0);

    // Converting is the one event that moves everything, once.
    await page.goto('/quotations');
    await page.locator('tr', { hasText: quotation.quotation_number }).getByRole('button', { name: 'Convert to invoice' }).click();
    await expect(page.getByTestId('quotation-conversion-banner')).toContainText(quotation.quotation_number);
    await page.click('button:has-text("Create invoice")');
    await expectSuccess(page, `created from ${quotation.quotation_number}`);

    const converted = await readBooks(page, w);
    expect(converted.invoiceCount).toBe(before.invoiceCount + 1);
    expect(converted.salesNext).toBe(before.salesNext + 1);
    expect(converted.stockOf).toBe(before.stockOf - 4);
    expect(converted.quotationNext).toBe(drafted.quotationNext);
    // Each report that reads invoices moved; the ones that cannot see an invoice did not.
    const moved = changed(before.books, converted.books);
    for (const path of [
      '/dashboard/metrics', `/analytics/sales-by-month?${RANGE}`, `/analytics/sales-by-product?${RANGE}`,
      '/invoices/?page_size=100', '/invoices/export', '/invoices/dues', `/ledgers/day-book?${RANGE}`,
      `/ledgers/${w.ledger.id}/statement?${RANGE}`, `/ledgers/tax-ledger/?${RANGE}`,
      `/ledgers/tax-ledger/gstr1/summary?${RANGE}`, `/ledgers/tax-ledger/gstr1/export-csv?${RANGE}`,
      '/inventory/?page_size=100', `/products/with-inventory?search=${encodeURIComponent(w.product.sku)}`,
    ]) {
      expect(moved, `${path} should show the new invoice`).toContain(path);
    }
    expect(moved).not.toContain('/payments/');

    // Cancelling the invoice reopens the quotation and puts the stock back.
    const live = (await must(page, 'GET', `/quotations/${quotation.id}`));
    expect(live.status).toBe('converted');
    const cancelled = await call(page, 'DELETE', `/invoices/${live.converted_invoice_id}`);
    expect(cancelled.status, cancelled.text).toBe(200);
    expect((await must(page, 'GET', `/quotations/${quotation.id}`)).status).toBe('open');
    expect((await readBooks(page, w)).stockOf).toBe(before.stockOf);
  });

  test('a quotation and a proforma say they are not tax invoices, show no payment QR, and share logged out', async ({ authedPage: page, browser }) => {
    test.setTimeout(90_000);
    const w = await world(page);
    const quotation = await must(page, 'POST', '/quotations/', quoteBody(w, 'quotation', 3));
    const proforma = await must(page, 'POST', '/quotations/', quoteBody(w, 'proforma', 2));
    const baseURL = test.info().project.use.baseURL as string;

    for (const [quote, bankDetails] of [[quotation, false], [proforma, true]] as const) {
      // The owner's PDF downloads as a PDF.
      const pdf = await page.evaluate(async (id) => {
        const response = await fetch(`/api/quotations/${id}/pdf`, { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } });
        const bytes = new Uint8Array(await response.arrayBuffer());
        return { status: response.status, type: response.headers.get('content-type'), magic: String.fromCharCode(...bytes.slice(0, 4)) };
      }, quote.id);
      expect(pdf).toEqual({ status: 200, type: 'application/pdf', magic: '%PDF' });

      const link = await must(page, 'POST', '/share/', { resource_type: 'quotation', resource_id: quote.id });
      const token = link.token as string;

      // Opened by someone with no login at all.
      const stranger = await browser.newContext({ baseURL });
      try {
        const shared = await stranger.newPage();
        await shared.goto(`/s/${token}`);
        await expect(shared.getByText('This is not a tax invoice').first()).toBeVisible();
        await expect(shared.locator('[class*="recap-upi"]')).toHaveCount(0);
        await expect(shared.locator('a[href^="upi:"], img[src^="data:image"]')).toHaveCount(0);

        // The document behind the PDF, which the share page links to.
        const document = await (await stranger.request.get(`/s/${token}/document.html`)).text();
        expect(document).toContain('This is not a tax invoice');
        expect(document).not.toMatch(/upi:\/\/|data:image|scan to pay|pay by upi/i);
        if (bankDetails) expect(document).toMatch(/bank details/i);
        else expect(document).not.toMatch(/bank details/i);

        const sharedPdf = await stranger.request.get(`/s/${token}/pdf`);
        expect(sharedPdf.status()).toBe(200);
        expect(sharedPdf.headers()['content-type']).toContain('application/pdf');
      } finally {
        await stranger.close();
      }
    }
  });

  test('a conversion opened before the quotation was edited is refused, and the quotation stays open', async ({ authedPage: page }) => {
    test.setTimeout(60_000);
    const w = await world(page);
    const quotation = await must(page, 'POST', '/quotations/', quoteBody(w, 'quotation', 2));
    const before = await readBooks(page, w);

    await page.goto('/quotations');
    await page.locator('tr', { hasText: quotation.quotation_number }).getByRole('button', { name: 'Convert to invoice' }).click();
    await expect(page.getByTestId('quotation-conversion-banner')).toContainText(quotation.quotation_number);

    // Another tab edits the quotation while this draft is open.
    await new Promise((done) => setTimeout(done, 1_100));
    await must(page, 'PUT', `/quotations/${quotation.id}`, { ledger_id: w.ledger.id, items: [{ product_id: w.product.id, quantity: 5, unit_price: 90 }] });

    await page.click('button:has-text("Create invoice")');
    await expect(page.getByTestId('quotation-conversion-out-of-date')).toBeVisible();
    await expect(page.locator('.toast--error')).toContainText('was changed after this conversion was opened');

    const after = await readBooks(page, w);
    expect(after.invoiceCount).toBe(before.invoiceCount);
    expect(after.salesNext).toBe(before.salesNext);
    expect(after.stockOf).toBe(before.stockOf);
    expect((await must(page, 'GET', `/quotations/${quotation.id}`)).status).toBe('open');
  });

  test('a second conversion of the same quotation gets the 409 naming the existing invoice', async ({ authedPage: page }) => {
    test.setTimeout(60_000);
    const w = await world(page);
    const quotation = await must(page, 'POST', '/quotations/', quoteBody(w, 'quotation', 1));
    const draft = await must(page, 'GET', `/quotations/${quotation.id}/conversion-draft`);
    const first = await call(page, 'POST', `/quotations/${quotation.id}/convert`, draft.invoice);
    expect(first.status, first.text).toBe(200);
    const second = await call(page, 'POST', `/quotations/${quotation.id}/convert`, draft.invoice);
    expect(second.status).toBe(409);
    expect(second.json.detail).toMatchObject({
      code: 'quotation_already_converted',
      invoice_number: first.json.invoice_number,
      invoice_id: first.json.id,
    });
    expect(second.json.detail.message).toContain(first.json.invoice_number);
  });

  test('a conversion that cannot be done leaves the quotation open and the invoice number unused', async ({ authedPage: page }) => {
    test.setTimeout(90_000);
    const w = await world(page, 5);
    const short = await must(page, 'POST', '/quotations/', quoteBody(w, 'quotation', 8));
    const before = await readBooks(page, w);

    // Through the page: it warns about the shortfall, and the save is refused.
    await page.goto('/quotations');
    await page.locator('tr', { hasText: short.quotation_number }).getByRole('button', { name: 'Convert to invoice' }).click();
    await expect(page.getByTestId('quotation-conversion-banner').locator('[data-warning="stock_shortfall"]')).toBeVisible();
    await page.click('button:has-text("Create invoice")');
    await expect(page.locator('.toast--error')).toContainText('Insufficient inventory');

    // A serial-tracked product with no serials on the conversion is refused by the server too.
    const stamp = uniqueSku();
    const phone = await must(page, 'POST', '/products/', {
      sku: `${stamp}-S`, name: `QB-Phone ${stamp}`, price: 500, gst_rate: 18,
      track_serials: true, maintain_inventory: true, initial_quantity: 0,
    });
    const imeis = [0, 1].map((index) => `${Date.now().toString().slice(-11)}${stamp.slice(-2)}1${index}`);
    await must(page, 'POST', '/invoices/', {
      ledger_id: w.ledger.id, voucher_type: 'purchase',
      items: [{ product_id: phone.id, quantity: 2, unit_price: 300, serial_numbers: imeis }],
    });
    const tracked = await must(page, 'POST', '/quotations/', {
      document_type: 'quotation', ledger_id: w.ledger.id, items: [{ product_id: phone.id, quantity: 2, unit_price: 500 }],
    });
    const mid = await readBooks(page, w);
    const draft = await must(page, 'GET', `/quotations/${tracked.id}/conversion-draft`);
    const refused = await call(page, 'POST', `/quotations/${tracked.id}/convert`, draft.invoice);
    expect(refused.status).toBe(400);
    expect(refused.text).toContain('serial');

    const after = await readBooks(page, w);
    expect(after.salesNext).toBe(before.salesNext);
    expect(after.salesNext).toBe(mid.salesNext);
    expect(after.invoiceCount).toBe(before.invoiceCount + 1); // only the serial purchase above, a purchase invoice
    expect(after.stockOf).toBe(before.stockOf);
    for (const quote of [short, tracked]) {
      expect((await must(page, 'GET', `/quotations/${quote.id}`)).status).toBe('open');
    }
  });

  test('restore rules: a cancelled quotation stays cancelled, a declined one reopens, a converted one is closed', async ({ authedPage: page }) => {
    test.setTimeout(60_000);
    const w = await world(page);
    const cancelled = await must(page, 'POST', '/quotations/', quoteBody(w, 'quotation', 1));
    await must(page, 'POST', `/quotations/${cancelled.id}/cancel`, {});
    for (const status of ['open', 'accepted', 'declined']) {
      expect((await call(page, 'POST', `/quotations/${cancelled.id}/status`, { status })).status).toBe(400);
    }
    expect((await call(page, 'PUT', `/quotations/${cancelled.id}`, { ledger_id: w.ledger.id, items: [{ product_id: w.product.id, quantity: 2, unit_price: 90 }] })).status).toBe(400);
    expect((await call(page, 'GET', `/quotations/${cancelled.id}/conversion-draft`)).status).toBe(409);

    const declined = await must(page, 'POST', '/quotations/', quoteBody(w, 'quotation', 1));
    await must(page, 'POST', `/quotations/${declined.id}/status`, { status: 'declined' });
    expect((await call(page, 'GET', `/quotations/${declined.id}/conversion-draft`)).status).toBe(400);
    expect((await must(page, 'POST', `/quotations/${declined.id}/status`, { status: 'open' })).status).toBe('open');

    const converted = await must(page, 'POST', '/quotations/', quoteBody(w, 'proforma', 1));
    const draft = await must(page, 'GET', `/quotations/${converted.id}/conversion-draft`);
    await must(page, 'POST', `/quotations/${converted.id}/convert`, draft.invoice);
    expect((await call(page, 'POST', `/quotations/${converted.id}/status`, { status: 'open' })).status).toBe(400);
    const cancelConverted = await call(page, 'POST', `/quotations/${converted.id}/cancel`, {});
    expect(cancelConverted.status).toBe(400);
    expect(cancelConverted.text).toContain('Cancel the invoice first');
  });
});
