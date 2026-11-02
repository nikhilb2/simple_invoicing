import { readFileSync } from 'node:fs';
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
} from './fixtures';

/**
 * GSTR-1 from the invoice form to the file the portal receives.
 *
 * The seller is in Karnataka (29). Each test works in a random past month and
 * compares the file before and after, because B2CS and the HSN summary add up
 * every sale in a month and the database outlives a single run.
 */
test.describe('GSTR-1 filing', () => {
  const timeout = Number(process.env.E2E_EXPECT_TIMEOUT_MS || '5000');
  const HOME_STATE = '29';
  const BIHAR = '10';

  type Gstr1File = {
    fp: string;
    b2cs?: { sply_ty: string; pos: string; rt: number; txval: number; iamt: number; camt: number; samt: number }[];
    b2cl?: { pos: string; inv: { inum: string; itms: { itm_det: Record<string, number> }[] }[] }[];
    cdnur?: { typ: string; nt_num: string }[];
    hsn?: { hsn_b2b?: { hsn_sc: string; txval: number }[]; hsn_b2c?: { hsn_sc: string; txval: number }[] };
    doc_issue?: { doc_det: { doc_num: number; docs: { from: string; to: string }[] }[] };
  };

  /** A whole past month from May 2025, the first return with the B2B/B2C HSN split. */
  function randomPastMonth() {
    const index = Math.floor(Math.random() * 12); // May 2025 to April 2026
    const start = new Date(2025, 4 + index, 1);
    const end = new Date(2025, 5 + index, 0);
    const pad = (n: number) => String(n).padStart(2, '0');
    const prefix = `${start.getFullYear()}-${pad(start.getMonth() + 1)}`;
    return {
      from: `${prefix}-01`,
      to: `${prefix}-${pad(end.getDate())}`,
      day: (d: number) => `${prefix}-${pad(d)}`,
      fp: `${pad(start.getMonth() + 1)}${start.getFullYear()}`,
    };
  }

  async function ensureKarnatakaSeller(page: Page) {
    await page.goto('/settings/company');
    await expect(page.locator('#company-name')).toBeVisible({ timeout });
    await page.fill('#company-name', 'E2E Test Company Pvt Ltd');
    await page.fill('#company-address', '42 Playwright Avenue, Bangalore');
    await page.fill('#company-gst', uniqueGstin(HOME_STATE));
    await page.fill('#company-phone', '+91 8080808080');
    await page.selectOption('#company-currency', 'INR');
    await page.click('button:has-text("Save company details")');
    await expectSuccess(page, 'Company profile saved');
  }

  async function createLedger(page: Page, gstin?: string) {
    const name = `G1-Ledger-${uniqueSku()}`;
    await clickNavLink(page, '/ledgers');
    await page.click('button:has-text("Create ledger")');
    await page.fill('#ledger-name', name);
    await page.fill('#ledger-address', '12 Market Road');
    if (gstin) await page.fill('#ledger-gst', gstin);
    await page.fill('#ledger-phone', '+91 5555555555');
    await page.click('button:has-text("Create ledger")');
    await expectSuccess(page, 'Ledger created');
    return name;
  }

  async function createStockedProduct(page: Page, price: string) {
    const sku = uniqueSku();
    await clickNavLink(page, '/catalogue');
    await createProduct(page, {
      sku,
      name: `G1-Prod ${sku}`,
      price,
      gstRate: '18',
      openingQuantity: '50',
      hsnSac: '84713010',
    });
    return sku;
  }

  async function openInvoiceForm(page: Page, ledger: string, sku: string) {
    await clickNavLink(page, '/invoices');
    await page.waitForTimeout(500);
    await page.selectOption('#invoice-voucher-type', 'sales');
    await selectComboboxOption(page, 'invoice-ledger', ledger);
    const productInputId =
      (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
    await selectComboboxOption(page, productInputId, sku);
  }

  /** Submits the open invoice form and returns the invoice the API saved. */
  async function submitInvoice(page: Page) {
    const [response] = await Promise.all([
      page.waitForResponse((r) => /\/api\/invoices\/$/.test(new URL(r.url()).pathname) && r.request().method() === 'POST'),
      page.click('button:has-text("Create invoice")'),
    ]);
    expect(response.status()).toBe(200);
    await expectSuccess(page, 'invoice created');

    const preview = page.locator('.modal-overlay[aria-labelledby="invoice-preview-title"]');
    if (await preview.isVisible()) {
      await preview.getByTitle('Close').click();
      await expect(preview).not.toBeVisible({ timeout });
    }
    return response.json();
  }

  /** Returns one unit of the ledger's first invoice, on a note with this date. */
  async function createNote(page: Page, ledger: string, date: string) {
    await clickNavLink(page, '/credit-notes');
    await selectComboboxOption(page, 'credit-note-ledger', ledger);
    await page.fill('#credit-note-date', date);
    await page.locator('label:has(input[type="checkbox"])').first().click();
    await page.locator('input[type="number"]').first().fill('1');
    const [response] = await Promise.all([
      page.waitForResponse((r) => /\/api\/credit-notes\/$/.test(new URL(r.url()).pathname) && r.request().method() === 'POST'),
      page.getByRole('button', { name: 'Create Credit Note' }).click(),
    ]);
    expect(response.status()).toBe(201);
    const note = await response.json();
    expect(note.credit_note_date.slice(0, 10)).toBe(date);
    return note;
  }

  async function downloadFile(page: Page, from: string, to: string): Promise<Gstr1File> {
    await page.goto('/gstr1');
    await page.fill('#gstr1-from', from);
    await page.fill('#gstr1-to', to);
    await page.getByRole('button', { name: 'Skip validation' }).click();

    const exportJson = page.getByRole('button', { name: 'Export JSON' });
    await expect(exportJson).toBeEnabled({ timeout });
    const [download] = await Promise.all([page.waitForEvent('download'), exportJson.click()]);
    return JSON.parse(readFileSync(await download.path(), 'utf-8'));
  }

  function b2csRow(file: Gstr1File, supplyType: string, state: string) {
    return file.b2cs?.find((row) => row.sply_ty === supplyType && row.pos === state && row.rt === 18);
  }

  test.beforeEach(async ({ authedPage: page }) => {
    await ensureKarnatakaSeller(page);
  });

  test('a sale to an unregistered buyer in another state is IGST, filed under that state', async ({ authedPage: page }) => {
    const month = randomPastMonth();
    const ledger = await createLedger(page);
    const sku = await createStockedProduct(page, '1000');
    const before = await downloadFile(page, month.from, month.to);

    await openInvoiceForm(page, ledger, sku);
    const placeOfSupply = page.locator('#invoice-place-of-supply');
    await expect(placeOfSupply).toHaveValue(HOME_STATE);
    await expect(page.getByText(/CGST 9%/).first()).toBeVisible({ timeout });

    await placeOfSupply.selectOption(BIHAR);
    await expect(page.getByText(/IGST 18%/).first()).toBeVisible({ timeout });

    await page.fill('#invoice-date', month.day(10));
    const invoice = await submitInvoice(page);
    expect(invoice.place_of_supply).toBe(BIHAR);
    expect(invoice.igst_amount).toBe(180);
    expect(invoice.cgst_amount).toBe(0);

    const after = await downloadFile(page, month.from, month.to);
    expect(after.fp).toBe(month.fp);
    const row = b2csRow(after, 'INTER', BIHAR);
    expect(row).toBeTruthy();
    const previous = b2csRow(before, 'INTER', BIHAR);
    expect(row!.txval).toBeCloseTo((previous?.txval ?? 0) + 1000, 2);
    expect(row!.iamt).toBeCloseTo((previous?.iamt ?? 0) + 180, 2);
    expect(row!.camt).toBeCloseTo(previous?.camt ?? 0, 2);
    expect(JSON.stringify(after.doc_issue)).toContain('"doc_num":1');
    expect(after.hsn?.hsn_b2c?.some((r) => r.hsn_sc === '84713010')).toBe(true);
  });

  test('a large interstate sale goes to B2CL and a small note on it to CDNUR', async ({ authedPage: page }) => {
    const month = randomPastMonth();
    const ledger = await createLedger(page);
    const sku = await createStockedProduct(page, '100000');

    await openInvoiceForm(page, ledger, sku);
    await page.locator('#invoice-place-of-supply').selectOption(BIHAR);
    await page.fill('#invoice-date', month.day(5));
    const invoice = await submitInvoice(page);

    const file = await downloadFile(page, month.from, month.to);
    const b2cl = file.b2cl?.find((group) => group.pos === BIHAR);
    const filed = b2cl?.inv.find((entry) => entry.inum === invoice.invoice_number);
    expect(filed).toBeTruthy();
    expect(filed!.itms[0].itm_det.iamt).toBe(18000);
    expect(filed!.itms[0].itm_det).not.toHaveProperty('camt');

    const note = await createNote(page, ledger, month.day(20));

    const withNote = await downloadFile(page, month.from, month.to);
    const cdnur = withNote.cdnur?.find((entry) => entry.nt_num === note.credit_note_number);
    expect(cdnur?.typ).toBe('B2CL');
  });

  test('a backdated credit note is filed on its own date and reduces B2CS and Table 12', async ({ authedPage: page }) => {
    const month = randomPastMonth();
    const ledger = await createLedger(page);
    const sku = await createStockedProduct(page, '1000');

    await openInvoiceForm(page, ledger, sku);
    await page.locator('[id^="invoice-quantity-"]').first().fill('3');
    await page.fill('#invoice-date', month.day(5));
    await submitInvoice(page);

    const before = await downloadFile(page, month.from, month.to);

    const note = await createNote(page, ledger, month.day(20));

    const after = await downloadFile(page, month.from, month.to);
    expect(after.cdnur?.some((entry) => entry.nt_num === note.credit_note_number) ?? false).toBe(false);
    expect(b2csRow(after, 'INTRA', HOME_STATE)!.txval).toBeCloseTo(b2csRow(before, 'INTRA', HOME_STATE)!.txval - 1000, 2);
    const hsn = (file: Gstr1File) => file.hsn?.hsn_b2c?.find((r) => r.hsn_sc === '84713010')?.txval ?? 0;
    expect(hsn(after)).toBeCloseTo(hsn(before) - 1000, 2);
    expect(JSON.stringify(after.doc_issue?.doc_det.find((d) => d.doc_num === 5))).toContain(note.credit_note_number);
  });

  test('the page opens on one whole month and refuses a range that is not a return period', async ({ authedPage: page }) => {
    await page.goto('/gstr1');

    const from = await page.locator('#gstr1-from').inputValue();
    const to = await page.locator('#gstr1-to').inputValue();
    expect(from.endsWith('-01')).toBe(true);
    expect(to.slice(0, 7)).toBe(from.slice(0, 7));

    await page.fill('#gstr1-from', '2026-04-01');
    await page.fill('#gstr1-to', '2027-03-31');
    await page.getByRole('button', { name: 'Validate & proceed' }).click();

    await expect(page.getByRole('cell', { name: /is not a return period/ })).toBeVisible({ timeout });
    await expect(page.getByText('✕ Invalid')).toBeVisible({ timeout });
  });

  test('the place of supply follows the ledger, and only a sale has one', async ({ authedPage: page }) => {
    const unregistered = await createLedger(page);
    const registered = await createLedger(page, uniqueGstin('27'));
    await page.goto('/invoices');
    await page.waitForTimeout(500);

    await selectComboboxOption(page, 'invoice-ledger', unregistered);
    const placeOfSupply = page.locator('#invoice-place-of-supply');
    await placeOfSupply.selectOption(BIHAR);
    await expect(placeOfSupply).toHaveValue(BIHAR);

    // The pick was for that buyer, and must not follow the user to another one.
    await selectComboboxOption(page, 'invoice-ledger', registered);
    await expect(placeOfSupply).toHaveValue('27');

    await page.selectOption('#invoice-voucher-type', 'purchase');
    await expect(placeOfSupply).toBeHidden();
  });
});
