import { test, expect, uniqueSku, uniqueGstin, selectComboboxOption, clickNavLink } from './fixtures';

/**
 * Serial / IMEI scanning.
 *
 * These specs drive the composer the way the shop floor does: a hardware
 * scanner is a keyboard that types a whole code in a few milliseconds and then
 * (usually) sends Enter, so every scan here is `keyboard.type(code, {delay: 5})`
 * rather than `fill()`. One case deliberately sends no Enter at all, to hold the
 * 120 ms silence fallback — the path a scanner with no suffix configured takes.
 */
test.describe('Serial scanning', () => {
  const EXPECT_TIMEOUT_MS = Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000');

  type Page = import('@playwright/test').Page;

  type SeededProduct = { id: number; sku: string; name: string; label: string };
  type SeededInvoice = { id: number; invoice_number: string | null };
  type ScanSeed = {
    /** Serial-tracked handset — the product every scan test registers or sells. */
    phone: SeededProduct;
    /** Non-tracked accessory, reached by its SKU through the scan fallback. */
    accessory: SeededProduct;
    ledgerId: number;
    ledgerName: string;
  };

  // ---------------------------------------------------------------------------
  // Seeding
  // ---------------------------------------------------------------------------

  /**
   * Seeds through the API, from inside the page, reusing the session the
   * `authedPage` fixture already established — same pattern as the financial
   * year lookup in fy-invoice-series.spec.ts, with the `X-Company-Id` header
   * the axios client sends so the rows land in the active company.
   *
   * The composer has no UI for creating a serial-tracked product or for
   * registering stock without composing an invoice, so the alternative would be
   * driving three screens per test.
   */
  async function apiRequest<T>(page: Page, method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
    return await page.evaluate(
      async ({ method, path, body }) => {
        const token = localStorage.getItem('token');
        const companyId = localStorage.getItem('active_company_id');
        const headers: Record<string, string> = { 'Content-Type': 'application/json' };
        if (token) headers.Authorization = `Bearer ${token}`;
        if (companyId) headers['X-Company-Id'] = companyId;

        const response = await fetch(`/api${path}`, {
          method,
          headers,
          body: body === undefined ? undefined : JSON.stringify(body),
        });
        const text = await response.text();
        if (!response.ok) {
          throw new Error(`${method} /api${path} -> ${response.status} ${text}`);
        }
        return text ? JSON.parse(text) : null;
      },
      { method, path, body },
    );
  }

  /**
   * IMEIs for one test: 15 digits, unique per run, so re-running a suite never
   * collides with a serial an earlier run registered (a serial number is unique
   * within a company for all time, unlike a SKU which tests can re-use).
   */
  function uniqueImeis(count: number): string[] {
    const base = `${Date.now().toString().slice(-11)}${Math.floor(Math.random() * 100).toString().padStart(2, '0')}`;
    return Array.from({ length: count }, (_, index) => `${base}${index.toString().padStart(2, '0')}`);
  }

  /**
   * A tracked handset, a non-tracked accessory and a ledger to invoice against.
   *
   * Names matter twice over. The composer loads the first 500 products and
   * ledgers by name, so a name sorting late would leave the seeded rows out of
   * the combobox (and out of `hasTrackedProducts`, which is what renders the
   * scan bar at all). And the accessory is named to sort *before* the handset,
   * so the line the composer seeds itself is never the handset — otherwise
   * "the scan filled the product in" could pass without the scan doing it.
   */
  async function seedScanData(page: Page): Promise<ScanSeed> {
    const stamp = uniqueSku();
    const phoneSku = `${stamp}-PH`;
    const accessorySku = `${stamp}-AC`;
    const phoneName = `Inv-Scan Phone ${stamp}`;
    const accessoryName = `Inv-Scan Case ${stamp}`;

    const phone = await apiRequest<{ id: number }>(page, 'POST', '/products/', {
      sku: phoneSku,
      name: phoneName,
      price: 64999,
      gst_rate: 18,
      track_serials: true,
      maintain_inventory: true,
      initial_quantity: 0,
    });

    const accessory = await apiRequest<{ id: number }>(page, 'POST', '/products/', {
      sku: accessorySku,
      name: accessoryName,
      price: 499,
      gst_rate: 18,
      maintain_inventory: true,
      initial_quantity: 25,
    });

    const ledgerName = `AA-Scan-Ledger-${Date.now().toString(36)}`;
    const ledger = await apiRequest<{ id: number }>(page, 'POST', '/ledgers/', {
      name: ledgerName,
      address: '12 Scan Street',
      gst: uniqueGstin(),
      phone_number: '+91 5555555555',
    });

    return {
      phone: { id: phone.id, sku: phoneSku, name: phoneName, label: `${phoneName} (${phoneSku})` },
      accessory: { id: accessory.id, sku: accessorySku, name: accessoryName, label: `${accessoryName} (${accessorySku})` },
      ledgerId: ledger.id,
      ledgerName,
    };
  }

  /** Books the serials in on a purchase, the only way stock becomes scannable. */
  async function receiveSerials(page: Page, seed: ScanSeed, serials: string[]): Promise<SeededInvoice> {
    return await apiRequest<SeededInvoice>(page, 'POST', '/invoices/', {
      ledger_id: seed.ledgerId,
      voucher_type: 'purchase',
      items: [
        {
          product_id: seed.phone.id,
          quantity: serials.length,
          unit_price: 50000,
          serial_numbers: serials,
        },
      ],
    });
  }

  /** Sells them straight back out, so a later scan meets a sold unit. */
  async function sellSerials(page: Page, seed: ScanSeed, serials: string[]): Promise<SeededInvoice> {
    return await apiRequest<SeededInvoice>(page, 'POST', '/invoices/', {
      ledger_id: seed.ledgerId,
      voucher_type: 'sales',
      items: [
        {
          product_id: seed.phone.id,
          quantity: serials.length,
          unit_price: 64999,
          serial_numbers: serials,
        },
      ],
    });
  }

  /** The label the sold-serial message names an invoice by. */
  function invoiceLabel(invoice: SeededInvoice) {
    return invoice.invoice_number ?? `#${invoice.id}`;
  }

  // ---------------------------------------------------------------------------
  // Scanning
  // ---------------------------------------------------------------------------

  const scanInput = (page: Page) => page.locator('#scan-bar-input');
  /** The aria-live strip under the box — the operator's only running record. */
  const scanFeed = (page: Page) => page.getByRole('list', { name: 'Recent scans' });
  const scanEntries = (page: Page) => scanFeed(page).getByRole('listitem');

  async function openComposer(page: Page, voucherType: 'sales' | 'purchase') {
    await clickNavLink(page, '/invoices');
    await page.waitForTimeout(500);
    await page.selectOption('#invoice-voucher-type', voucherType);
    await expect(scanInput(page)).toBeVisible({ timeout: 10_000 });
  }

  /** The composer's first line-item, whichever id it happens to carry. */
  async function firstProductInputId(page: Page) {
    return (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
  }

  async function focusScanBar(page: Page) {
    await scanInput(page).click();
    await expect(scanInput(page)).toBeFocused();
  }

  /**
   * One trigger pull. Types the whole code fast into whatever holds focus — a
   * scanner does not click first — then sends Enter unless the caller is
   * exercising the no-suffix scanner, whose code is submitted by the 120 ms
   * silence timer instead.
   *
   * Waits on the feedback strip rather than on a spinner: a scan is finished
   * when it has said what it did. The strip keeps the last five entries, so
   * bursts here stay well under that.
   */
  async function scan(page: Page, code: string, options: { enter?: boolean } = {}) {
    const entries = scanEntries(page);
    const before = await entries.count();
    expect(before).toBeLessThan(5);

    await page.keyboard.type(code, { delay: 5 });
    if (options.enter !== false) {
      await page.keyboard.press('Enter');
    }

    await expect(entries).toHaveCount(before + 1, { timeout: 10_000 });
  }

  /** Newest first — the strip prepends. */
  const lastScan = (page: Page) => scanEntries(page).first();

  test('purchase: three scanned IMEIs make one line of qty 3 with a chip each', async ({ authedPage: page }) => {
    const seed = await seedScanData(page);
    const imeis = uniqueImeis(3);

    await openComposer(page, 'purchase');
    await selectComboboxOption(page, 'invoice-ledger', seed.ledgerName);
    await selectComboboxOption(page, await firstProductInputId(page), seed.phone.sku);

    // Purchase mode registers into a line, and says which one it is aiming at.
    await expect(page.getByText(`Scanning into: Line 1 · ${seed.phone.name}`)).toBeVisible();

    await focusScanBar(page);
    await scan(page, imeis[0]);
    await scan(page, imeis[1]);
    // Third handset arrives from a scanner with no Enter suffix configured:
    // nothing is pressed, the 120 ms silence timer submits it.
    await scan(page, imeis[2], { enter: false });

    await expect(lastScan(page)).toContainText('qty 3');

    // Three units, one line — not three lines.
    await expect(page.locator('.line-item')).toHaveCount(1);

    const quantity = page.locator('[id^="invoice-quantity-"]').first();
    await expect(quantity).toHaveValue('3');
    await expect(quantity).toBeDisabled();

    await expect(page.getByText('Serials (3)')).toBeVisible();
    for (const imei of imeis) {
      await expect(page.getByRole('button', { name: `Remove serial ${imei}` })).toBeVisible();
    }
  });

  test('sales: a known in-stock IMEI adds its product line without touching the product combobox', async ({ authedPage: page }) => {
    const seed = await seedScanData(page);
    const [imei] = uniqueImeis(1);
    await receiveSerials(page, seed, [imei]);

    await openComposer(page, 'sales');
    await selectComboboxOption(page, 'invoice-ledger', seed.ledgerName);

    const productInput = page.locator('[id^="invoice-product-"]').first();
    // The composer seeds its own first line; whatever it chose, it is not the
    // handset, so anything the handset gets on this line came from the scan.
    await expect(productInput).not.toHaveValue(seed.phone.label);

    await focusScanBar(page);
    await scan(page, imei);

    await expect(lastScan(page)).toContainText(seed.phone.name);
    await expect(productInput).toHaveValue(seed.phone.label);

    await expect(page.locator('.line-item')).toHaveCount(1);
    const quantity = page.locator('[id^="invoice-quantity-"]').first();
    await expect(quantity).toHaveValue('1');
    await expect(quantity).toBeDisabled();
    await expect(page.getByRole('button', { name: `Remove serial ${imei}` })).toBeVisible();
  });

  test('the same serial scanned twice reports "already added" instead of duplicating the line', async ({ authedPage: page }) => {
    const seed = await seedScanData(page);
    const [imei] = uniqueImeis(1);
    await receiveSerials(page, seed, [imei]);

    await openComposer(page, 'sales');
    await selectComboboxOption(page, 'invoice-ledger', seed.ledgerName);

    await focusScanBar(page);
    await scan(page, imei);

    const line = page.locator('.line-item').first();
    // Wait out the first scan's flash, so the second one flashing is visible as
    // a new event rather than the tail of the old one.
    await expect(line).not.toHaveAttribute('data-flash', 'on', { timeout: 5_000 });

    await scan(page, imei);

    await expect(lastScan(page)).toContainText('Already added to line 1');
    // The line it is already on lights up, since nothing else changed on screen.
    await expect(line).toHaveAttribute('data-flash', 'on');

    await expect(page.locator('.line-item')).toHaveCount(1);
    await expect(page.getByText('Serials (1)')).toBeVisible();
    await expect(page.getByRole('button', { name: `Remove serial ${imei}` })).toHaveCount(1);
    await expect(page.locator('[id^="invoice-quantity-"]').first()).toHaveValue('1');
  });

  test('an unknown code is refused and left in the box, selected for a retype', async ({ authedPage: page }) => {
    const seed = await seedScanData(page);
    const unknown = `ZZ${uniqueImeis(1)[0]}`;

    await openComposer(page, 'sales');
    await selectComboboxOption(page, 'invoice-ledger', seed.ledgerName);

    await focusScanBar(page);
    await scan(page, unknown);

    await expect(lastScan(page)).toContainText(unknown);
    await expect(lastScan(page)).toContainText(/no product or serial number found|not in stock/i);

    // Nothing was added on the strength of a code nobody recognises.
    await expect(page.locator('.line-item')).toHaveCount(1);
    await expect(page.getByRole('button', { name: /^Remove serial / })).toHaveCount(0);

    // A misread is retyped over, not appended to: the code stays put and comes
    // back selected, so the next keystroke replaces it.
    await expect(scanInput(page)).toHaveValue(unknown);
    await expect(scanInput(page)).toBeFocused();
    const selection = await scanInput(page).evaluate((element: HTMLInputElement) => ({
      start: element.selectionStart,
      end: element.selectionEnd,
      length: element.value.length,
    }));
    expect(selection).toEqual({ start: 0, end: unknown.length, length: unknown.length });
  });

  test('a sold IMEI is refused, naming the invoice it went out on', async ({ authedPage: page }) => {
    const seed = await seedScanData(page);
    const [imei] = uniqueImeis(1);
    await receiveSerials(page, seed, [imei]);
    const salesInvoice = await sellSerials(page, seed, [imei]);

    await openComposer(page, 'sales');
    await selectComboboxOption(page, 'invoice-ledger', seed.ledgerName);

    await focusScanBar(page);
    await scan(page, imei);

    await expect(lastScan(page)).toContainText(`Already sold on ${invoiceLabel(salesInvoice)}`);
    await expect(lastScan(page).getByRole('link', { name: 'Open invoice' })).toBeVisible();

    // Refused, so the handset never reaches a line.
    await expect(page.getByRole('button', { name: `Remove serial ${imei}` })).toHaveCount(0);
    await expect(page.locator('.line-item')).toHaveCount(1);
    await expect(scanInput(page)).toHaveValue(imei);
  });

  test("an accessory's product SKU falls through to the product and increments its line", async ({ authedPage: page }) => {
    const seed = await seedScanData(page);

    await openComposer(page, 'sales');
    await selectComboboxOption(page, 'invoice-ledger', seed.ledgerName);

    await focusScanBar(page);
    // No serial answers to this code, so the lookup falls through to the SKU —
    // one scanning rhythm covers handsets and the cases sold beside them.
    await scan(page, seed.accessory.sku);

    await expect(lastScan(page)).toContainText(seed.accessory.name);
    const productInput = page.locator('[id^="invoice-product-"]').first();
    await expect(productInput).toHaveValue(seed.accessory.label);

    const quantity = page.locator('[id^="invoice-quantity-"]').first();
    // Not serial-tracked, so the quantity stays the operator's to edit.
    await expect(quantity).toBeEnabled();
    const afterFirst = Number(await quantity.inputValue());
    expect(afterFirst).toBeGreaterThan(0);

    await scan(page, seed.accessory.sku);

    // Second unit of the same accessory: the same line counts up.
    await expect(quantity).toHaveValue(String(afterFirst + 1));
    await expect(page.locator('.line-item')).toHaveCount(1);
    await expect(page.getByText('Serials (', { exact: false })).toHaveCount(0);
  });

  test('submit is blocked on the line itself when a tracked line has no serials', async ({ authedPage: page }) => {
    const seed = await seedScanData(page);

    await openComposer(page, 'sales');
    await selectComboboxOption(page, 'invoice-ledger', seed.ledgerName);
    await selectComboboxOption(page, await firstProductInputId(page), seed.phone.sku);

    await expect(page.getByText('Serials (0)')).toBeVisible();
    await page.click('button:has-text("Create invoice")');

    // Stated on the line that is short, not thrown at the top of the page.
    const blocker = page.getByRole('alert').filter({
      hasText: 'This product is serial tracked — scan or add at least one serial before saving.',
    });
    await expect(blocker).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
    await expect(page.locator('.toast')).toHaveCount(0);

    // Still composing, with the caret already where the fix is.
    await expect(page.locator('h1')).toContainText('Invoice composer');
    await expect(scanInput(page)).toBeFocused();
  });

  test('the scan box keeps focus across consecutive scans', async ({ authedPage: page }) => {
    const seed = await seedScanData(page);
    const imeis = uniqueImeis(2);
    await receiveSerials(page, seed, imeis);

    await openComposer(page, 'sales');
    await selectComboboxOption(page, 'invoice-ledger', seed.ledgerName);

    // The one and only click on the scan box: from here a real scanner fires
    // both handsets with nothing in between.
    await focusScanBar(page);
    await expect(page.getByText('Scan mode')).toBeVisible();

    await scan(page, imeis[0]);
    await expect(scanInput(page)).toBeFocused();
    await expect(scanInput(page)).toHaveValue('');
    await expect(page.getByText('Scan mode')).toBeVisible();

    await scan(page, imeis[1]);
    await expect(scanInput(page)).toBeFocused();
    await expect(scanInput(page)).toHaveValue('');

    await expect(page.locator('[id^="invoice-quantity-"]').first()).toHaveValue('2');
    for (const imei of imeis) {
      await expect(page.getByRole('button', { name: `Remove serial ${imei}` })).toBeVisible();
    }
  });
});
