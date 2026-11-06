import { readFileSync } from 'node:fs';
import type { Page } from '@playwright/test';
import { test, expect, uniqueSku, uniqueGstin } from './fixtures';

// Needs the demo seed (make seed-demo): it opens the newest invoice in the feed,
// which the seed makes an active sales invoice with an interstate buyer.
test.describe('E-Way Bill form', () => {
  test.beforeEach(async ({ authedPage: page }) => {
    // Other specs add invoices of their own (purchase ones, and sales ones for
    // products with no HSN), which would otherwise be the newest in the feed and
    // either have no e-way bill or be blocked. Find a seeded sales invoice that
    // can generate one and search the feed for it.
    const invoiceNumber = await page.evaluate(async () => {
      const headers = { Authorization: `Bearer ${localStorage.getItem('token')}` };
      const list = await (await fetch('/api/invoices/?voucher_type=sales&page_size=50', { headers })).json();
      for (const inv of list.items ?? list) {
        const pre = await (await fetch(`/api/invoices/${inv.id}/eway-bill/precheck`, { headers })).json();
        if (!pre.item_validation?.length) return inv.invoice_number as string;
      }
      return null;
    });
    expect(invoiceNumber).toBeTruthy();
    await page.goto('/invoices-view');
    await page.getByPlaceholder(/Search invoice no/).fill(invoiceNumber!);
    await page.getByTitle('Preview').first().click();
    const preview = page.locator('.modal-panel--invoice-preview');
    await expect(preview).toBeVisible({ timeout: 10_000 });
    await preview.getByRole('button', { name: /e-way bill/i }).click();
    await expect(page.locator('[aria-labelledby="eway-bill-title"]')).toBeVisible({ timeout: 10_000 });
  });

  test('says what is wrong with bad details, against each field', async ({ authedPage: page }) => {
    const modal = page.locator('[aria-labelledby="eway-bill-title"]');
    await modal.locator('[name=seller_gstin]').fill('NOT-A-GSTIN');
    await modal.locator('[name=buyer_pincode]').fill('');
    await modal.locator('[name=vehicle_number]').fill('XX');
    await modal.getByRole('button', { name: 'Generate JSON' }).click();

    await expect(modal.locator('#eway-seller_gstin-note')).toContainText('Seller GSTIN format is invalid');
    await expect(modal.locator('#eway-buyer_pincode-note')).toHaveText('Buyer PIN code is required.');
    await expect(modal.locator('#eway-vehicle_number-note')).toContainText('Vehicle number format is invalid');
    await expect(modal).not.toContainText('status code');
  });

  test("explains FastAPI's own validation errors too", async ({ authedPage: page }) => {
    const modal = page.locator('[aria-labelledby="eway-bill-title"]');
    await modal.locator('[name=distance_km]').fill('1.5');
    await modal.getByRole('button', { name: 'Generate JSON' }).click();

    await expect(modal.locator('#eway-distance_km-note')).toHaveText('Distance km must be a whole number.');
    await expect(modal).not.toContainText('status code');
  });
});

/**
 * The file the portal's bulk upload takes, and who may make it. These make their
 * own product, ledger and invoices, so they depend on nothing the seed holds
 * beyond a company with e-way bills turned on.
 */
test.describe('E-Way Bill file and rules', () => {
  type Reply = { status: number; json: any; text: string };
  const MODAL = '[aria-labelledby="eway-bill-title"]';

  async function call(page: Page, method: string, path: string, body?: unknown, token?: string): Promise<Reply> {
    return page.evaluate(
      async ({ method, path, body, token }) => {
        const response = await fetch(`/api${path}`, {
          method,
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token ?? localStorage.getItem('token')}` },
          body: body === undefined ? undefined : JSON.stringify(body),
        });
        const text = await response.text();
        let json: any = null;
        try { json = JSON.parse(text); } catch { /* not JSON */ }
        return { status: response.status, json, text };
      },
      { method, path, body, token },
    );
  }

  async function must(page: Page, method: string, path: string, body?: unknown) {
    const reply = await call(page, method, path, body);
    expect(reply.status, `${method} ${path}: ${reply.text}`).toBe(200);
    return reply.json;
  }

  async function setup(page: Page) {
    const stamp = uniqueSku();
    const product = await must(page, 'POST', '/products/', {
      sku: `${stamp}-E`, name: `EW-Prod ${stamp}`, hsn_sac: '00841301', price: 100, gst_rate: 18,
      unit: 'Pieces', maintain_inventory: true, initial_quantity: 100,
    });
    const ledger = await must(page, 'POST', '/ledgers/', {
      name: `EW-Cust-${stamp}`, address: '12 Buyer Street, Mumbai 400001', gst: uniqueGstin('27'), phone_number: '+91 5555555555',
    });
    return { product, ledger };
  }

  async function sale(page: Page, w: { product: { id: number }; ledger: { id: number } }, extra: object = {}) {
    return must(page, 'POST', '/invoices/', {
      ledger_id: w.ledger.id, voucher_type: 'sales',
      items: [{ product_id: w.product.id, quantity: 3, unit_price: 90 }],
      ...extra,
    });
  }

  async function openPreview(page: Page, invoiceNumber: string) {
    await page.goto('/invoices-view');
    await page.getByPlaceholder(/Search invoice no/).fill(invoiceNumber);
    await page.locator('.invoice-compact-card', { hasText: invoiceNumber }).first().getByTitle('Preview').click();
    const preview = page.locator('.modal-panel--invoice-preview');
    await expect(preview).toBeVisible({ timeout: 10_000 });
    return preview;
  }

  async function openForm(page: Page, invoiceNumber: string) {
    const preview = await openPreview(page, invoiceNumber);
    await preview.getByRole('button', { name: /e-way bill/i }).click();
    const modal = page.locator(MODAL);
    await expect(modal).toBeVisible({ timeout: 10_000 });
    await expect(modal.locator('[name=seller_gstin]')).not.toHaveValue('');
    return modal;
  }

  /** Other specs rename and replace the active company, which can leave it without a PIN code. */
  async function fillSellerPin(modal: ReturnType<Page['locator']>) {
    const pin = modal.locator('[name=seller_pincode]');
    if ((await pin.inputValue()) === '') await pin.fill('560029');
  }

  test('a valid form downloads a file the portal takes, and the saved transporter fills in next time', async ({ authedPage: page }) => {
    test.setTimeout(90_000);
    const w = await setup(page);
    const invoice = await sale(page, w);
    const modal = await openForm(page, invoice.invoice_number);

    const transporterName = `Fast Cargo ${uniqueSku()}`;
    await fillSellerPin(modal);
    await modal.locator('[name=vehicle_number]').fill('KA01AB1234');
    await modal.locator('[name=distance_km]').fill('120');
    await modal.locator('[name=transporter_name]').fill(transporterName);
    await modal.locator('[name=transporter_gstin]').fill(uniqueGstin('29'));
    await modal.getByLabel(/Save as default transporter/).check();

    const downloading = page.waitForEvent('download', (file) => file.suggestedFilename().endsWith('.json'));
    await modal.getByRole('button', { name: 'Generate JSON' }).click();
    const download = await downloading;
    expect(download.suggestedFilename()).toBe(`EWB_${invoice.invoice_number}.json`);
    const file = JSON.parse(readFileSync((await download.path())!, 'utf8'));

    expect(file.billLists).toHaveLength(1);
    const bill = file.billLists[0];
    const item = bill.itemList[0];
    // Pieces is not a portal unit: the portal's own code for it is NOS.
    expect(item.qtyUnit).toBe('NOS');
    // The portal wants PINs as numbers and HSN as text, zeros kept.
    expect(bill.toPincode).toBe(400001);
    expect(bill.fromPincode).toEqual(expect.any(Number));
    expect(item.hsnCode).toBe('00841301');
    expect(bill.mainHsnCode).toBe('00841301');
    // The totals add up, and are the invoice's own.
    const tax = bill.cgstValue + bill.sgstValue + bill.igstValue;
    expect(bill.totalValue).toBeCloseTo(270, 2);
    expect(bill.totalValue + tax + bill.cessValue + bill.TotNonAdvolVal + bill.OthValue).toBeCloseTo(bill.totInvValue, 2);
    expect(bill.totInvValue).toBeCloseTo(Number(invoice.total_amount), 2);
    expect(item.taxableAmount).toBeCloseTo(bill.totalValue, 2);
    expect(bill.docNo).toBe(invoice.invoice_number);
    expect(bill.vehicleNo).toBe('KA01AB1234');
    const done = page.getByText('E-Way Bill JSON generated');
    await expect(done).toBeVisible();
    await expect(done).not.toContainText('status code');

    // The transporter was saved as the default and fills the next form.
    const second = await sale(page, w);
    const next = await openForm(page, second.invoice_number);
    await expect(next.locator('[name=transporter_name]')).toHaveValue(transporterName);
    await expect(next.locator('#eway-transporter-select')).toBeVisible();
  });

  test('a shipping address on the invoice pre-fills where the goods are delivered', async ({ authedPage: page }) => {
    test.setTimeout(60_000);
    const w = await setup(page);
    const invoice = await sale(page, w, {
      shipping_address_same_as_billing: false,
      new_shipping_address: { label: 'Warehouse', address: 'Warehouse 9\nPune\n411001' },
    });
    const modal = await openForm(page, invoice.invoice_number);
    await expect(modal.locator('[name=buyer_address_1]')).toHaveValue('Warehouse 9');
    await expect(modal.locator('[name=buyer_pincode]')).toHaveValue('411001');
    await expect(modal.locator('[name=transaction_type]')).toHaveValue('2');
  });

  test('purchase invoices, cancelled invoices and quotations offer no e-way bill, and the server refuses too', async ({ authedPage: page }) => {
    test.setTimeout(90_000);
    const w = await setup(page);
    const purchase = await must(page, 'POST', '/invoices/', {
      ledger_id: w.ledger.id, voucher_type: 'purchase',
      items: [{ product_id: w.product.id, quantity: 1, unit_price: 50 }],
    });
    const preview = await openPreview(page, purchase.invoice_number);
    await expect(preview.getByRole('button', { name: /e-way/i })).toHaveCount(0);
    for (const route of ['precheck', 'generate']) {
      const reply = route === 'precheck'
        ? await call(page, 'GET', `/invoices/${purchase.id}/eway-bill/precheck`)
        : await call(page, 'POST', `/invoices/${purchase.id}/eway-bill/generate`, {});
      expect(reply.status).toBe(400);
      expect(reply.json.detail).toBe('E-Way Bill is only available for Sales invoices.');
    }

    // A quotation and a proforma are not invoices: no menu entry, and no route.
    for (const documentType of ['quotation', 'proforma']) {
      const quote = await must(page, 'POST', '/quotations/', {
        document_type: documentType, ledger_id: w.ledger.id, items: [{ product_id: w.product.id, quantity: 1, unit_price: 90 }],
      });
      await page.goto('/quotations');
      await page.locator('tr', { hasText: quote.quotation_number }).getByRole('button', { name: quote.quotation_number }).click();
      const dialog = page.getByRole('dialog', { name: /Quotation|Proforma/ });
      await expect(dialog).toBeVisible();
      await expect(dialog.getByRole('button', { name: /e-way/i })).toHaveCount(0);
      expect((await call(page, 'GET', `/quotations/${quote.id}/eway-bill/precheck`)).status).toBe(404);
    }

    const cancelled = await sale(page, w);
    await must(page, 'DELETE', `/invoices/${cancelled.id}`);
    expect((await call(page, 'GET', `/invoices/${cancelled.id}/eway-bill/precheck`)).status).toBe(400);
  });

  test('a company with e-way bills turned off cannot generate one, and a company update that omits the eway fields keeps them', async ({ authedPage: page }) => {
    test.setTimeout(90_000);
    const w = await setup(page);
    const invoice = await sale(page, w);
    const company = await must(page, 'GET', '/company/');
    const { id: _id, logo_path: _logo, has_logo: _hasLogo, logo: _logoData, created_at: _created, updated_at: _updated, logo_url: _logoUrl, ...editable } = company;
    const eway = ['eway_enabled', 'eway_local_threshold', 'eway_interstate_threshold', 'eway_always_show_button'] as const;

    try {
      // Omitting every eway_* field leaves what was stored.
      const withoutEway = Object.fromEntries(Object.entries(editable).filter(([key]) => !(eway as readonly string[]).includes(key)));
      await must(page, 'PUT', '/company/', { ...editable, eway_local_threshold: 12345, eway_interstate_threshold: 23456, eway_always_show_button: false });
      const kept = await must(page, 'PUT', '/company/', withoutEway);
      expect(kept).toMatchObject({
        eway_enabled: true, eway_local_threshold: 12345, eway_interstate_threshold: 23456, eway_always_show_button: false,
      });
      expect(await must(page, 'GET', '/company/')).toMatchObject({ eway_local_threshold: 12345, eway_interstate_threshold: 23456 });

      // Turned off: no button, and the server says why in words.
      await must(page, 'PUT', '/company/', { ...editable, eway_enabled: false });
      const settings = page.waitForResponse((res) => res.url().endsWith('/eway-bill/settings'));
      const preview = await openPreview(page, invoice.invoice_number);
      expect((await (await settings).json()).eway_enabled).toBe(false);
      await expect(preview.getByRole('button', { name: /e-way/i })).toHaveCount(0);
      for (const reply of [
        await call(page, 'GET', `/invoices/${invoice.id}/eway-bill/precheck`),
        await call(page, 'POST', `/invoices/${invoice.id}/eway-bill/generate`, {}),
      ]) {
        expect(reply.status).toBe(400);
        expect(reply.json.detail).toContain('turned off for this company');
      }
    } finally {
      await must(page, 'PUT', '/company/', {
        ...editable, eway_enabled: company.eway_enabled, eway_local_threshold: company.eway_local_threshold,
        eway_interstate_threshold: company.eway_interstate_threshold, eway_always_show_button: company.eway_always_show_button,
      });
    }
  });

  test('staff can generate a bill but cannot edit or save a transporter', async ({ authedPage: page, browser }) => {
    test.setTimeout(90_000);
    const w = await setup(page);
    const invoice = await sale(page, w);
    const stamp = uniqueSku().toLowerCase();
    const email = `ewb-staff-${stamp}@example.com`;
    await must(page, 'POST', '/users/', { email, full_name: 'EWB Staff', password: 'Staff@12345', role: 'staff' });
    const transporter = await must(page, 'POST', '/eway-bill/transporters', {
      transporter_name: `Admin Cargo ${stamp}`, transporter_gstin: '', transport_mode: '1', vehicle_type: 'R', is_default: false,
    });

    const login = await call(page, 'POST', '/auth/login', { email, password: 'Staff@12345' });
    expect(login.status, login.text).toBe(200);
    const token = login.json.access_token as string;
    expect((await call(page, 'GET', '/eway-bill/transporters', undefined, token)).status).toBe(200);
    expect((await call(page, 'POST', '/eway-bill/transporters', { transporter_name: 'Nope' }, token)).status).toBe(403);
    expect((await call(page, 'PUT', `/eway-bill/transporters/${transporter.id}`, { transporter_name: 'Renamed' }, token)).status).toBe(403);
    expect((await call(page, 'DELETE', `/eway-bill/transporters/${transporter.id}`, undefined, token)).status).toBe(403);
    const form = (await call(page, 'GET', `/invoices/${invoice.id}/eway-bill/precheck`, undefined, token)).json.form_data;
    const valid = { ...form, seller_pincode: form.seller_pincode || '560029', buyer_pincode: '400001', vehicle_number: 'KA01AB1234', distance_km: 50 };
    const generated = await call(page, 'POST', `/invoices/${invoice.id}/eway-bill/generate`, valid, token);
    expect(generated.status, generated.text).toBe(200);
    const saving = await call(page, 'POST', `/invoices/${invoice.id}/eway-bill/generate`, { ...valid, transporter_name: 'Sneaky', save_transporter: true }, token);
    expect(saving.status).toBe(403);
    expect(saving.json.detail).toBe('Only an admin or manager can save a transporter.');
    expect((await must(page, 'GET', '/eway-bill/transporters')).some((t: { transporter_name: string }) => t.transporter_name === 'Renamed' || t.transporter_name === 'Sneaky')).toBe(false);

    // On the page, a staff member gets the form without the save option.
    const baseURL = test.info().project.use.baseURL as string;
    const context = await browser.newContext({ baseURL });
    try {
      const staff = await context.newPage();
      await staff.goto('/login');
      await staff.fill('#email', email);
      await staff.fill('#password', 'Staff@12345');
      await staff.getByRole('button', { name: 'Sign in', exact: true }).click();
      await expect(staff).toHaveURL('/');
      const modal = await openForm(staff, invoice.invoice_number);
      await expect(modal.getByRole('button', { name: 'Generate JSON' })).toBeVisible();
      await expect(modal.getByLabel(/Save as default transporter/)).toHaveCount(0);
    } finally {
      await context.close();
    }
  });

  test('an invoice converted from a quotation can generate an e-way bill', async ({ authedPage: page }) => {
    test.setTimeout(90_000);
    const w = await setup(page);
    const quote = await must(page, 'POST', '/quotations/', {
      document_type: 'proforma', ledger_id: w.ledger.id, items: [{ product_id: w.product.id, quantity: 2, unit_price: 90 }],
    });
    const draft = await must(page, 'GET', `/quotations/${quote.id}/conversion-draft`);
    const invoice = await must(page, 'POST', `/quotations/${quote.id}/convert`, draft.invoice);

    const modal = await openForm(page, invoice.invoice_number);
    await fillSellerPin(modal);
    await modal.locator('[name=vehicle_number]').fill('KA01AB1234');
    await modal.locator('[name=distance_km]').fill('80');
    const downloading = page.waitForEvent('download', (file) => file.suggestedFilename().endsWith('.json'));
    await modal.getByRole('button', { name: 'Generate JSON' }).click();
    const file = JSON.parse(readFileSync((await (await downloading).path())!, 'utf8'));
    expect(file.billLists[0].docNo).toBe(invoice.invoice_number);
    expect(file.billLists[0].itemList[0].hsnCode).toBe('00841301');
  });
});
