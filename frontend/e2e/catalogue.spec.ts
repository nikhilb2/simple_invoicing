import {
  test,
  expect,
  expectSuccess,
  uniqueSku,
  clickNavLink,
  createProduct,
  catalogueRow,
  catalogueSearch,
  adjustInventory,
} from './fixtures';

/**
 * The Catalogue — /catalogue, "Products & stock".
 *
 * One page in place of the three this replaces (products.spec.ts and
 * inventory.spec.ts drove /products and /inventory, which are now redirects).
 * Everything those two covered lives here, against the shapes the new page
 * actually has: real `<tr class="catalogue-row">` rows in a `<table>`, a modal
 * product form, per-row quick edit, and stock that only moves through an
 * audited adjustment.
 */
test.describe('Catalogue', () => {
  const EXPECT_TIMEOUT_MS = Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000');

  test('displays the products & stock heading', async ({ authedPage: page }) => {
    await clickNavLink(page, '/catalogue');
    await expect(page.locator('h1')).toContainText('Products & stock');
  });

  // ── Creating, editing and deleting ─────────────────────────────────────────

  test('creates a product through the new product modal', async ({ authedPage: page }) => {
    await clickNavLink(page, '/catalogue');
    const sku = uniqueSku();
    const name = `Test Product ${sku}`;

    // The form is summoned, not permanently on screen: nothing of it is in the
    // DOM until the hero button is pressed.
    await expect(page.locator('#product-sku')).toHaveCount(0);

    await createProduct(page, {
      sku,
      name,
      price: '249.99',
      gstRate: '18',
      description: 'Playwright test product',
      hsnSac: '8471',
    });

    await catalogueSearch(page).fill(sku);
    const row = catalogueRow(page, sku);
    await expect(row).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
    await expect(row.locator('.catalogue-cell__name')).toHaveText(name);
    await expect(row.locator('.catalogue-sku')).toHaveText(sku);
  });

  test('rejects a duplicate SKU without closing the modal', async ({ authedPage: page }) => {
    await clickNavLink(page, '/catalogue');
    const sku = uniqueSku();
    await createProduct(page, { sku, name: `Dup Test ${sku}`, price: '10', gstRate: '5' });

    await page.getByRole('button', { name: 'New product' }).click();
    const modal = page.getByRole('dialog', { name: 'Add a product' });
    await modal.locator('#product-sku').fill(sku);
    await modal.locator('#product-name').fill('Duplicate Attempt');
    await modal.locator('#product-price').fill('20');
    await modal.getByRole('button', { name: 'Create product' }).click();

    // Reported inside the form, and the form keeps everything that was typed.
    await expect(modal.getByRole('alert')).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
    await expect(modal).toBeVisible();
    await expect(modal.locator('#product-name')).toHaveValue('Duplicate Attempt');
  });

  test('refuses a GST rate outside 0-100', async ({ authedPage: page }) => {
    await clickNavLink(page, '/catalogue');
    const sku = uniqueSku();

    await page.getByRole('button', { name: 'New product' }).click();
    const modal = page.getByRole('dialog', { name: 'Add a product' });
    await modal.locator('#product-sku').fill(sku);
    await modal.locator('#product-name').fill(`GST Test ${sku}`);
    await modal.locator('#product-price').fill('100');
    await modal.locator('#product-gst').fill('150');
    await modal.getByRole('button', { name: 'Create product' }).click();

    // max="100" makes this a constraint violation, so the submit never leaves
    // the browser and the modal stays put with nothing created.
    const gstValid = await modal
      .locator('#product-gst')
      .evaluate((input) => (input as HTMLInputElement).checkValidity());
    expect(gstValid).toBe(false);
    await expect(modal).toBeVisible();
    await expect(page.locator('.toast--success')).toHaveCount(0);
  });

  test('quick edit saves the row it was opened on', async ({ authedPage: page }) => {
    await clickNavLink(page, '/catalogue');
    const sku = uniqueSku();
    const name = `Edit Me ${sku}`;
    await createProduct(page, { sku, name, price: '100', gstRate: '12' });

    await catalogueSearch(page).fill(sku);
    const row = catalogueRow(page, sku);
    await expect(row).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
    await row.getByRole('button', { name: `Quick edit ${name}` }).click();

    // The row itself becomes the form — one Save for the whole row.
    const editing = page.locator('tr.catalogue-row--editing');
    await expect(editing).toBeVisible();
    // Stock is not among the fields: it is rendered locked even mid-edit.
    await expect(editing.locator('.catalogue-table__locked')).toBeVisible();

    await editing.getByLabel('Product name').fill(`Updated ${sku}`);
    await editing.getByLabel('Selling price').fill('150');
    await editing.getByRole('button', { name: 'Save' }).click();

    await expectSuccess(page, `Updated ${sku} saved.`);
    await expect(page.locator('tr.catalogue-row--editing')).toHaveCount(0);
    await expect(catalogueRow(page, sku).locator('.catalogue-cell__name')).toHaveText(
      `Updated ${sku}`,
    );
  });

  test('cancelling a quick edit discards the change', async ({ authedPage: page }) => {
    await clickNavLink(page, '/catalogue');
    const sku = uniqueSku();
    const name = `Keep Me ${sku}`;
    await createProduct(page, { sku, name, price: '100', gstRate: '12' });

    await catalogueSearch(page).fill(sku);
    const row = catalogueRow(page, sku);
    await expect(row).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
    await row.getByRole('button', { name: `Quick edit ${name}` }).click();

    const editing = page.locator('tr.catalogue-row--editing');
    await editing.getByLabel('Product name').fill('Discarded name');
    await editing.getByRole('button', { name: 'Cancel' }).click();

    await expect(page.locator('tr.catalogue-row--editing')).toHaveCount(0);
    await expect(catalogueRow(page, sku).locator('.catalogue-cell__name')).toHaveText(name);

    // Nothing was sent, so the original survives a round trip to the server.
    await page.reload();
    await expect(catalogueRow(page, sku).locator('.catalogue-cell__name')).toHaveText(name, {
      timeout: EXPECT_TIMEOUT_MS,
    });
  });

  test('opens the full product form from the row and saves it', async ({ authedPage: page }) => {
    await clickNavLink(page, '/catalogue');
    const sku = uniqueSku();
    const name = `All Settings ${sku}`;
    await createProduct(page, { sku, name, price: '80', gstRate: '5' });

    await catalogueSearch(page).fill(sku);
    const row = catalogueRow(page, sku);
    await expect(row).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
    await row.getByRole('button', { name: `All settings for ${name}` }).click();

    const modal = page.getByRole('dialog', { name: `Editing ${name}` });
    await expect(modal).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
    await expect(modal.locator('#product-sku')).toHaveValue(sku);
    // Opening stock is a create-only field — an existing quantity is never
    // overwritten from this form.
    await expect(modal.locator('#product-initial-qty')).toHaveCount(0);

    await modal.locator('#product-hsn').fill('8471');
    await modal.locator('#product-purchase-price').fill('60');
    await modal.getByRole('button', { name: 'Save changes' }).click();

    await expectSuccess(page, `${name} updated.`);
    await expect(modal).toBeHidden({ timeout: EXPECT_TIMEOUT_MS });

    // Read it back rather than trusting the toast — the purchase column is
    // hidden at narrow widths, so the form is the honest place to check.
    await catalogueRow(page, sku).getByRole('button', { name: `All settings for ${name}` }).click();
    const reopened = page.getByRole('dialog', { name: `Editing ${name}` });
    await expect(reopened.locator('#product-hsn')).toHaveValue('8471');
    await expect(reopened.locator('#product-purchase-price')).toHaveValue('60');
  });

  test('deletes a product after confirmation', async ({ authedPage: page }) => {
    await clickNavLink(page, '/catalogue');
    const sku = uniqueSku();
    const name = `Delete Me ${sku}`;
    await createProduct(page, { sku, name, price: '50', gstRate: '5' });

    await catalogueSearch(page).fill(sku);
    const row = catalogueRow(page, sku);
    await expect(row).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
    await row.getByRole('button', { name: `Delete ${name}` }).click();

    const confirm = page.getByRole('dialog', { name: 'Delete product' });
    await expect(confirm).toContainText(`Delete ${name} (${sku})?`);
    await confirm.getByRole('button', { name: 'Delete', exact: true }).click();

    await expectSuccess(page, `${name} deleted.`);
    await expect(catalogueRow(page, sku)).toHaveCount(0);
  });

  // ── Stock ──────────────────────────────────────────────────────────────────

  test('moves stock only through the adjustment modal', async ({ authedPage: page }) => {
    await clickNavLink(page, '/catalogue');
    const sku = uniqueSku();
    const name = `Stock Move ${sku}`;
    await createProduct(page, { sku, name, price: '50', gstRate: '18' });

    await catalogueSearch(page).fill(sku);
    const row = catalogueRow(page, sku);
    await expect(row).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });

    // The stock cell is a button, not a field — there is nothing to type into.
    await expect(row.getByTitle(`Adjust stock for ${name}`)).toBeVisible();
    await expect(row.locator('input')).toHaveCount(0);

    await adjustInventory(page, sku, '25');
    await expectSuccess(page, `${name}: 0 → 25 (+25).`);
    await expect(catalogueRow(page, sku).locator('.catalogue-stock__value')).toHaveText('25');
  });

  test('requires a reason before removing stock', async ({ authedPage: page }) => {
    await clickNavLink(page, '/catalogue');
    const sku = uniqueSku();
    const name = `Write Off ${sku}`;
    await createProduct(page, { sku, name, price: '30', gstRate: '12', openingQuantity: '30' });

    await catalogueSearch(page).fill(sku);
    const row = catalogueRow(page, sku);
    await expect(row).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
    await row.getByTitle(`Adjust stock for ${name}`).click();

    const modal = page.getByRole('dialog', { name: 'Adjust stock' });
    await modal.locator('#stock-adjust-delta').fill('-5');

    const apply = modal.getByRole('button', { name: `Apply stock adjustment for ${name}` });
    await expect(apply).toBeDisabled();
    await expect(modal.locator('#stock-adjust-reason-hint')).toContainText('Required for a removal');

    await modal.locator('#stock-adjust-reason').fill('Damaged in transit');
    await expect(apply).toBeEnabled();
    await apply.click();

    await expectSuccess(page, `${name}: 30 → 25 (-5).`);
    await expect(catalogueRow(page, sku).locator('.catalogue-stock__value')).toHaveText('25');
  });

  test('refuses to remove more stock than is on hand', async ({ authedPage: page }) => {
    await clickNavLink(page, '/catalogue');
    const sku = uniqueSku();
    const name = `No Balance ${sku}`;
    await createProduct(page, { sku, name, price: '10', gstRate: '5' });

    await catalogueSearch(page).fill(sku);
    const row = catalogueRow(page, sku);
    await expect(row).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
    await row.getByTitle(`Adjust stock for ${name}`).click();

    const modal = page.getByRole('dialog', { name: 'Adjust stock' });
    await modal.locator('#stock-adjust-delta').fill('-10');

    // Caught before the round trip: the delta itself is impossible.
    await expect(modal.locator('#stock-adjust-delta-error')).toContainText(
      'you cannot remove more than that',
    );
    await expect(
      modal.getByRole('button', { name: `Apply stock adjustment for ${name}` }),
    ).toBeDisabled();
  });

  test('flags low stock and the Low stock tab keeps only those rows', async ({
    authedPage: page,
  }) => {
    await clickNavLink(page, '/catalogue');
    const lowSku = uniqueSku();
    const lowName = `Low Stock ${lowSku}`;
    const okSku = `${lowSku}-OK`;
    const okName = `Well Stocked ${okSku}`;

    await createProduct(page, {
      sku: lowSku,
      name: lowName,
      price: '10',
      gstRate: '5',
      reorderLevel: '5',
      openingQuantity: '3',
    });
    await createProduct(page, {
      sku: okSku,
      name: okName,
      price: '10',
      gstRate: '5',
      reorderLevel: '1',
      openingQuantity: '50',
    });

    await catalogueSearch(page).fill(lowSku);
    const lowRow = catalogueRow(page, lowName);
    await expect(lowRow).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
    await expect(lowRow.locator('.catalogue-stock')).toHaveClass(/catalogue-stock--low/);
    await expect(lowRow.locator('.catalogue-stock__flag')).toHaveText('Low');
    // The pill the old stock ledger flagged rows with is gone from the grid.
    await expect(lowRow.locator('.pill--low')).toHaveCount(0);

    await page.getByRole('tab', { name: 'Low stock' }).click();
    await expect(page).toHaveURL(/[?&]view=low/);
    await expect(catalogueRow(page, lowName)).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });

    await catalogueSearch(page).fill(okSku);
    await expect(page.locator('.empty-state')).toContainText('No products match this view.', {
      timeout: EXPECT_TIMEOUT_MS,
    });
  });

  // ── Filters in the URL ─────────────────────────────────────────────────────

  test('a filtered view survives a reload', async ({ authedPage: page }) => {
    await clickNavLink(page, '/catalogue');
    const sku = uniqueSku();
    const name = `Reload Me ${sku}`;
    // Low on purpose, so the row is still there after the view tab moves.
    await createProduct(page, {
      sku,
      name,
      price: '42',
      gstRate: '5',
      reorderLevel: '5',
      openingQuantity: '0',
    });

    await catalogueSearch(page).fill(sku);
    await expect(catalogueRow(page, sku)).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
    await page.getByRole('tab', { name: 'Low stock' }).click();
    await page.getByRole('button', { name: 'Selling', exact: true }).click();
    await page.getByRole('button', { name: 'Selling', exact: true }).click();

    await expect(page).toHaveURL(new RegExp(`[?&]q=${sku}`));
    await expect(page).toHaveURL(/[?&]view=low/);
    await expect(page).toHaveURL(/[?&]sort=price/);
    await expect(page).toHaveURL(/[?&]dir=desc/);

    await page.reload();

    // Every filter comes back from the URL — the whole reason they live there.
    await expect(catalogueSearch(page)).toHaveValue(sku);
    await expect(page.getByRole('tab', { name: 'Low stock' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await expect(page.getByRole('columnheader', { name: 'Selling', exact: true })).toHaveAttribute(
      'aria-sort',
      'descending',
    );
    await expect(catalogueRow(page, sku)).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
  });

  test('sorting marks exactly one column with aria-sort', async ({ authedPage: page }) => {
    await clickNavLink(page, '/catalogue');

    const product = page.getByRole('columnheader', { name: 'Product', exact: true });
    const stock = page.getByRole('columnheader', { name: 'Stock', exact: true });

    // Name ascending is the default the page opens on.
    await expect(product).toHaveAttribute('aria-sort', 'ascending');
    await expect(stock).not.toHaveAttribute('aria-sort', /.*/);

    await page.getByRole('button', { name: 'Product', exact: true }).click();
    await expect(product).toHaveAttribute('aria-sort', 'descending');
    await expect(page).toHaveURL(/[?&]dir=desc/);

    await page.getByRole('button', { name: 'Stock', exact: true }).click();
    await expect(stock).toHaveAttribute('aria-sort', 'ascending');
    await expect(product).not.toHaveAttribute('aria-sort', /.*/);
    await expect(page).toHaveURL(/[?&]sort=stock/);
  });

  // ── Empty states ───────────────────────────────────────────────────────────

  test('offers Clear filters when nothing matches the current view', async ({
    authedPage: page,
  }) => {
    await clickNavLink(page, '/catalogue');
    await catalogueSearch(page).fill('ZZZZNONEXISTENT999');

    const emptyState = page.locator('.empty-state');
    await expect(emptyState).toContainText('No products match this view.', {
      timeout: EXPECT_TIMEOUT_MS,
    });
    // The onboarding CTA belongs to an empty catalogue, not to an empty search.
    await expect(page.getByRole('button', { name: 'Add first product' })).toHaveCount(0);

    await page.getByRole('button', { name: 'Clear filters' }).click();
    await expect(catalogueSearch(page)).toHaveValue('');
    await expect(page.locator('tr.catalogue-row').first()).toBeVisible({
      timeout: EXPECT_TIMEOUT_MS,
    });
  });

  test('offers Add first product when the catalogue is empty', async ({ authedPage: page }) => {
    await page.route(/\/api\/products\/with-inventory/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0, page: 1, page_size: 25, total_pages: 0 }),
      }),
    );

    await page.goto('/catalogue');

    const emptyState = page.locator('.empty-state');
    await expect(emptyState).toContainText('No products yet.', { timeout: EXPECT_TIMEOUT_MS });
    await expect(page.getByRole('button', { name: 'Clear filters' })).toHaveCount(0);

    const cta = page.getByRole('button', { name: 'Add first product' });
    await expect(cta).toBeVisible();
    await cta.click();
    await expect(page.getByRole('dialog', { name: 'Add a product' })).toBeVisible();
    await expect(page.locator('#product-sku')).toBeFocused();
  });

  test('offers Try again when the catalogue fails to load', async ({ authedPage: page }) => {
    const catalogueApi = /\/api\/products\/with-inventory/;
    await page.route(catalogueApi, (route) =>
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Catalogue exploded' }),
      }),
    );

    await page.goto('/catalogue');

    await expect(page.locator('.empty-state')).toContainText('The catalogue could not be loaded.', {
      timeout: EXPECT_TIMEOUT_MS,
    });
    // A failed fetch must never be dressed up as "you have no products yet".
    await expect(page.getByRole('button', { name: 'Add first product' })).toHaveCount(0);
    await expect(page.locator('.ledger-pagination')).toHaveCount(0);

    await page.unroute(catalogueApi);
    await page.getByRole('button', { name: 'Try again' }).click();
    await expect(page.locator('tr.catalogue-row').first()).toBeVisible({
      timeout: EXPECT_TIMEOUT_MS,
    });
  });

  // ── Pagination ─────────────────────────────────────────────────────────────

  test('always reports the row range, even on a single page', async ({ authedPage: page }) => {
    await clickNavLink(page, '/catalogue');
    const sku = uniqueSku();
    await createProduct(page, { sku, name: `Paged ${sku}`, price: '10', gstRate: '5' });

    const status = page.locator('.ledger-pagination__status');
    await expect(status).toContainText(/\d+–\d+ of \d+ products/, { timeout: EXPECT_TIMEOUT_MS });
    await expect(page.getByRole('button', { name: 'Previous page' })).toBeDisabled();

    // One row is still a count worth showing — the old pagers hid themselves.
    await catalogueSearch(page).fill(sku);
    await expect(catalogueRow(page, sku)).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
    await expect(status).toHaveText('1–1 of 1 products');
    await expect(page.getByRole('button', { name: 'Next page' })).toBeDisabled();
  });

  // ── Bulk import ────────────────────────────────────────────────────────────

  test('opens the CSV import modal from the toolbar', async ({ authedPage: page }) => {
    await clickNavLink(page, '/catalogue');
    await page.getByRole('button', { name: 'Import', exact: true }).click();

    const modal = page.getByRole('dialog', { name: 'Import catalogue from CSV' });
    await expect(modal).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
    await expect(modal).toContainText('Item Code');

    await page.keyboard.press('Escape');
    await expect(modal).toBeHidden();
  });
});

/**
 * The three routes the catalogue replaced.
 *
 * /products-inventory in particular is the URL every MCP / ChatGPT product and
 * serial citation already points at, so the redirect has to carry the query
 * string across intact or every citation ever emitted breaks.
 */
test.describe('Catalogue redirects', () => {
  const EXPECT_TIMEOUT_MS = Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000');

  for (const legacy of ['/products', '/inventory', '/products-inventory']) {
    test(`${legacy} redirects to the catalogue`, async ({ authedPage: page }) => {
      await page.goto(legacy);
      await expect(page).toHaveURL('/catalogue', { timeout: EXPECT_TIMEOUT_MS });
      await expect(page.locator('h1')).toContainText('Products & stock');
    });
  }

  test('a legacy link keeps its query string across the redirect', async ({ authedPage: page }) => {
    await clickNavLink(page, '/catalogue');
    const sku = uniqueSku();
    const name = `Legacy Query ${sku}`;
    await createProduct(page, {
      sku,
      name,
      price: '15',
      gstRate: '5',
      reorderLevel: '5',
      openingQuantity: '1',
    });

    await page.goto(`/inventory?q=${sku}&view=low`);

    await expect(page).toHaveURL(`/catalogue?q=${sku}&view=low`, { timeout: EXPECT_TIMEOUT_MS });
    await expect(page.getByRole('tab', { name: 'Low stock' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await expect(catalogueRow(page, sku)).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
  });

  test('a /products-inventory?product_id= citation lands on the row', async ({
    authedPage: page,
  }) => {
    await clickNavLink(page, '/catalogue');
    const sku = uniqueSku();
    const name = `MCP Cite ${sku}`;
    await createProduct(page, { sku, name, price: '99', gstRate: '18' });

    await catalogueSearch(page).fill(sku);
    const row = catalogueRow(page, sku);
    await expect(row).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
    const rowId = await row.getAttribute('id');
    expect(rowId).toMatch(/^catalogue-row-\d+$/);
    const productId = Number(rowId!.replace('catalogue-row-', ''));

    await page.goto(`/products-inventory?product_id=${productId}`);

    await expect(page).toHaveURL(/\/catalogue/, { timeout: EXPECT_TIMEOUT_MS });
    // The page moves its own filters onto the cited record and flags the row,
    // so the citation lands on it rather than somewhere on page 7.
    const target = page.locator(`#catalogue-row-${productId}`);
    await expect(target).toBeVisible({ timeout: EXPECT_TIMEOUT_MS });
    await expect(target).toHaveClass(/deep-link-target/);
    await expect(target.locator('.catalogue-cell__name')).toHaveText(name);
    await expect(catalogueSearch(page)).toHaveValue(sku);
  });
});
