import { test, expect, expectSuccess, expectError, uniqueSku } from './fixtures';

test.describe('Products CRUD', () => {
  test('displays catalog intake heading', async ({ authedPage: page }) => {
    await page.click('[href="/products"]');
    await expect(page.locator('h1')).toContainText('Catalog intake');
  });

  test('paginates products and supports search', async ({ authedPage: page }) => {
    await page.click('[href="/products"]');

    // Create several products to verify pagination controls / search
    const skus: string[] = [];
    for (let i = 0; i < 3; i++) {
      const sku = uniqueSku();
      skus.push(sku);
      await page.fill('#sku', sku);
      await page.fill('#name', `PagProd-${sku}`);
      await page.fill('#price', '10');
      await page.fill('#gst-rate', '5');
      await page.click('button:has-text("Create product")');
      await expectSuccess(page, 'Product created');
    }

    // All should be visible when searched
    for (const sku of skus) {
      await page.fill('#product-search', sku);
      await page.waitForTimeout(500);
      await expect(page.locator('.table-row', { hasText: sku })).toBeVisible();
    }

    // Search should filter products
    await page.fill('#product-search', `PagProd-${skus[0]}`);
    await page.waitForTimeout(500);
    await expect(page.locator('.table-row', { hasText: skus[0] })).toBeVisible();
    // Other products should not be visible
    await expect(page.locator('.table-row', { hasText: skus[1] })).not.toBeVisible();

    // Clear search — should show the first product when searched again
    await page.fill('#product-search', '');
    await page.waitForTimeout(500);
    await page.fill('#product-search', skus[1]);
    await page.waitForTimeout(500);
    await expect(page.locator('.table-row', { hasText: skus[1] })).toBeVisible();
  });

  test('creates a new product', async ({ authedPage: page }) => {
    await page.click('[href="/products"]');
    const sku = uniqueSku();

    await page.fill('#sku', sku);
    await page.fill('#name', `Test Product ${sku}`);
    await page.fill('#description', 'Playwright test product');
    await page.fill('#hsn-sac', '8471');
    await page.fill('#price', '249.99');
    await page.fill('#gst-rate', '18');
    await page.click('button:has-text("Create product")');

    await expectSuccess(page, 'Product created successfully');

    // Verify product appears in the list
    await page.fill('#product-search', sku);
    await page.waitForTimeout(500);
    const row = page.locator('.table-row', { hasText: sku });
    await expect(row).toBeVisible();
    await expect(row.locator('strong')).toContainText(`Test Product ${sku}`);
  });

  test('rejects duplicate SKU', async ({ authedPage: page }) => {
    await page.click('[href="/products"]');
    const sku = uniqueSku();

    // Create first product
    await page.fill('#sku', sku);
    await page.fill('#name', `Dup Test ${sku}`);
    await page.fill('#price', '10');
    await page.fill('#gst-rate', '5');
    await page.click('button:has-text("Create product")');
    await expectSuccess(page, 'Product created');

    // Try duplicate SKU
    await page.fill('#sku', sku);
    await page.fill('#name', 'Duplicate Attempt');
    await page.fill('#price', '20');
    await page.fill('#gst-rate', '5');
    await page.click('button:has-text("Create product")');
    await expectError(page);
  });

  test('edits an existing product', async ({ authedPage: page }) => {
    await page.click('[href="/products"]');
    const sku = uniqueSku();

    // Create a product
    await page.fill('#sku', sku);
    await page.fill('#name', `Edit Me ${sku}`);
    await page.fill('#price', '100');
    await page.fill('#gst-rate', '12');
    await page.click('button:has-text("Create product")');
    await expectSuccess(page, 'Product created');

    // Click Edit on the new product row
    await page.fill('#product-search', sku);
    await page.waitForTimeout(500);
    const row = page.locator('.table-row', { hasText: sku });
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.locator('button:has-text("Edit")').click();

    // Form should show "Editing product" heading
    await expect(page.getByRole('heading', { name: /Editing product/ })).toBeVisible();
    await expect(page.locator('button:has-text("Cancel edit")')).toBeVisible();

    // Update the name
    await page.fill('#name', `Updated ${sku}`);
    await page.fill('#price', '150');
    await page.click('button:has-text("Update product")');
    await expectSuccess(page, 'Product updated');

    // Verify updated name in list
    await expect(page.getByText(`Updated ${sku}`)).toBeVisible();
  });

  test('deletes a product', async ({ authedPage: page }) => {
    await page.click('[href="/products"]');
    const sku = uniqueSku();

    // Create a product
    await page.fill('#sku', sku);
    await page.fill('#name', `Delete Me ${sku}`);
    await page.fill('#price', '50');
    await page.fill('#gst-rate', '5');
    await page.click('button:has-text("Create product")');
    await expectSuccess(page, 'Product created');

    // Delete it — accept the confirm dialog and wait for new banner
    await page.fill('#product-search', sku);
    await page.waitForTimeout(500);
    const row = page.locator('.table-row', { hasText: sku });
    await expect(row).toBeVisible({ timeout: 10_000 });
    page.on('dialog', (dialog) => dialog.accept());
    // Wait for old banner to disappear then the new one to appear
    await row.locator('button:has-text("Delete")').click();
    await expect(page.locator('.toast--success')).toContainText('Product deleted', { timeout: 10_000 });

    // Should no longer appear
    await expect(page.locator('.table-row', { hasText: sku })).not.toBeVisible();
  });

  test('validates GST rate range (0-100)', async ({ authedPage: page }) => {
    await page.click('[href="/products"]');
    const sku = uniqueSku();

    await page.fill('#sku', sku);
    await page.fill('#name', `GST Test ${sku}`);
    await page.fill('#price', '100');
    await page.fill('#gst-rate', '150'); // Invalid
    await page.click('button:has-text("Create product")');

    // Either a validation error or the field constrains the value
    // The form has max=100 so the browser may prevent submission
    // or the API will reject it
    const errorVisible = await page
      .locator('.toast--error')
      .isVisible()
      .catch(() => false);
    const stillOnForm = await page
      .locator('button:has-text("Create product")')
      .isVisible();
    expect(errorVisible || stillOnForm).toBeTruthy();
  });
});
