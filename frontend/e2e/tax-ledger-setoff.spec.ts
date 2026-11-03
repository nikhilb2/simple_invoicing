import { test, expect, expectSuccess, uniqueSku, uniqueGstin, selectComboboxOption, clickNavLink, createProduct, adjustInventory } from './fixtures';

/**
 * GST set-off on the Tax Ledger page (s.49A/49B, r.88A).
 *
 * Real invoices only ever carry equal CGST and SGST, so the head-by-head
 * shortfall is built from three vouchers on one day:
 *   - intrastate sale        CGST due 100, SGST due 100
 *   - intrastate purchase    CGST credit 50, SGST credit 50
 *   - interstate purchase    IGST credit 100
 * IGST credit must be used up before CGST/SGST credit, and it goes first to
 * what own-head credit cannot cover: here 50 each on CGST and SGST. Putting it
 * all on CGST would leave 50 of SGST due as cash. Cash payable must be 0.
 *
 * The ledgers' GSTIN state codes are taken from the active company, so the
 * test holds whichever company an earlier spec left selected. A company with
 * no GSTIN has no interstate supply, so there the test is skipped.
 */
test.describe('Tax ledger set-off', () => {
  // A day of its own, years before any seeded data, so the period holds nothing
  // but this test's vouchers and a rerun against the same database does not
  // add to an earlier run's totals.
  const DAY = new Date(Date.UTC(2000, 0, 1) + (Date.now() % 7000) * 86_400_000).toISOString().slice(0, 10);

  test('IGST credit pays what CGST and SGST credit cannot, leaving no cash due', async ({ authedPage: page }) => {
    // The active company's state decides which ledger is intrastate.
    const companyGst = await page.evaluate(async () => {
      const headers: Record<string, string> = { Authorization: `Bearer ${localStorage.getItem('token')}` };
      const companyId = localStorage.getItem('active_company_id');
      if (companyId) headers['X-Company-Id'] = companyId;
      const res = await fetch('/api/company/', { headers });
      return ((await res.json()).gst as string | null) ?? '';
    });
    test.skip(!/^\d{2}/.test(companyGst), 'The active company has no GSTIN, so no supply is interstate.');
    const homeState = companyGst.slice(0, 2);
    const otherState = homeState === '27' ? '29' : '27';

    const sku = uniqueSku();
    const productName = `Setoff-Prod ${sku}`;
    const suffix = Date.now().toString(36);
    const intra = `Setoff-Intra-${suffix}`;
    const inter = `Setoff-Inter-${suffix}`;

    await clickNavLink(page, '/catalogue');
    await createProduct(page, { sku, name: productName, price: '1000', gstRate: '10', purchasePrice: '1000' });
    await adjustInventory(page, sku, '50');

    await clickNavLink(page, '/ledgers');
    for (const [name, state] of [[intra, homeState], [inter, otherState]] as const) {
      await page.click('button:has-text("Create ledger")');
      await page.fill('#ledger-name', name);
      await page.fill('#ledger-address', '1 Setoff Road');
      await page.fill('#ledger-gst', uniqueGstin(state));
      await page.fill('#ledger-phone', '+91 4444444444');
      await page.click('button:has-text("Create ledger")');
      await expectSuccess(page, 'Ledger created');
    }

    async function createInvoice(voucher: 'sales' | 'purchase', ledgerName: string, quantity: string) {
      // The previous invoice's preview dialog covers the sidebar, so navigate directly.
      await page.goto('/invoices');
      await expect(page.locator('#invoice-voucher-type')).toBeVisible();
      await page.selectOption('#invoice-voucher-type', voucher);
      await selectComboboxOption(page, 'invoice-ledger', ledgerName);
      await page.fill('#invoice-date', DAY);
      const productInputId =
        (await page.locator('[id^="invoice-product-"]').first().getAttribute('id')) || 'invoice-product-1';
      await selectComboboxOption(page, productInputId, sku);
      await page.locator('[id^="invoice-quantity-"]').first().fill(quantity);
      await page.click('button:has-text("Create invoice")');
      await expectSuccess(page, 'invoice created');
    }

    await createInvoice('sales', intra, '2');
    await createInvoice('purchase', intra, '1');
    await createInvoice('purchase', inter, '1');

    await page.goto('/tax-ledger');
    await page.fill('#tax-ledger-from', DAY);
    await page.fill('#tax-ledger-to', DAY);

    const table = page.getByRole('table', { name: 'Tax payable set-off by tax head' });
    const cells = (head: string) => table.getByRole('row', { name: new RegExp(`^${head}\\b`) }).getByRole('cell');

    // Columns: output tax, input credit, set off, payable.
    await expect(cells('CGST').nth(0)).toContainText('100.00');
    await expect(cells('CGST').nth(1)).toContainText('50.00');
    await expect(cells('SGST').nth(0)).toContainText('100.00');
    await expect(cells('SGST').nth(1)).toContainText('50.00');
    await expect(cells('IGST').nth(1)).toContainText('100.00');

    // "Set off" is credit from any head spent on this head: each of CGST and
    // SGST is cleared by its own 50 plus 50 of the IGST credit.
    await expect(cells('CGST').nth(2)).toContainText('100.00');
    await expect(cells('SGST').nth(2)).toContainText('100.00');
    await expect(cells('IGST').nth(2)).toContainText(/(^|[^\d.])0\.00$/);
    await expect(cells('Total').nth(2)).toContainText('200.00');

    for (const head of ['CGST', 'SGST', 'IGST', 'Total']) {
      await expect(cells(head).nth(3)).toContainText(/(^|[^\d.])0\.00$/);
    }

    // Nothing stranded: no carry-forward note.
    await expect(page.getByText('of credit is left over and carries forward')).toHaveCount(0);
  });
});
