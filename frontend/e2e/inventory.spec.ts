import { test, expect, expectSuccess, uniqueSku } from './fixtures';

test.describe('Inventory Management', () => {
  test('displays stock adjustments heading', async ({ authedPage: page }) => {
    await page.click('[href="/inventory"]');
    await expect(page.locator('h1')).toContainText('Stock adjustments');
  });

  test('shows stock ledger section', async ({ authedPage: page }) => {
    await page.click('[href="/inventory"]');
    await expect(page.getByText('Stock ledger')).toBeVisible();
  });

  test('adds stock to a product', async ({ authedPage: page }) => {
    // First create a product to stock
    await page.click('[href="/products"]');
    const sku = uniqueSku();
    await page.fill('#sku', sku);
    await page.fill('#name', `Inv Test ${sku}`);
    await page.fill('#price', '50');
    await page.fill('#gst-rate', '18');
    await page.click('button:has-text("Create product")');
    await expectSuccess(page, 'Product created');

    // Go to inventory
    await page.click('[href="/inventory"]');
    await page.waitForTimeout(500);

    // Select product and add stock
    const productSelect = page.locator('#inventory-product');
    // Wait for options to load
    await expect(productSelect.locator('option')).not.toHaveCount(0, {
      timeout: 5_000,
    });
    // Select by visible text that contains our product
    const options = productSelect.locator('option');
    const count = await options.count();
    let targetValue = '';
    for (let i = 0; i < count; i++) {
      const text = await options.nth(i).textContent();
      if (text?.includes(sku)) {
        targetValue = (await options.nth(i).getAttribute('value')) || '';
        break;
      }
    }
    if (targetValue) {
      await productSelect.selectOption(targetValue);
    }

    await page.fill('#inventory-quantity', '25');
    await page.click('button:has-text("Apply adjustment")');
    await expectSuccess(page, 'Inventory updated');

    // Verify product appears in ledger with the stocked quantity
    const row = page.locator('.table-row', { hasText: sku });
    await expect(row).toBeVisible();
  });

  test('deducts stock from a product', async ({ authedPage: page }) => {
    // Create a product and stock it
    await page.click('[href="/products"]');
    const sku = uniqueSku();
    await page.fill('#sku', sku);
    await page.fill('#name', `Deduct Test ${sku}`);
    await page.fill('#price', '30');
    await page.fill('#gst-rate', '12');
    await page.click('button:has-text("Create product")');
    await expectSuccess(page, 'Product created');

    // Add stock
    await page.click('[href="/inventory"]');
    await page.waitForTimeout(500);
    const productSelect = page.locator('#inventory-product');
    const options = productSelect.locator('option');
    const count = await options.count();
    let targetValue = '';
    for (let i = 0; i < count; i++) {
      const text = await options.nth(i).textContent();
      if (text?.includes(sku)) {
        targetValue = (await options.nth(i).getAttribute('value')) || '';
        break;
      }
    }
    if (targetValue) {
      await productSelect.selectOption(targetValue);
    }
    await page.fill('#inventory-quantity', '20');
    await page.click('button:has-text("Apply adjustment")');
    await expectSuccess(page, 'Inventory updated');

    // Deduct some stock
    if (targetValue) {
      await productSelect.selectOption(targetValue);
    }
    await page.fill('#inventory-quantity', '-5');
    await page.click('button:has-text("Apply adjustment")');
    await expectSuccess(page, 'Inventory updated');
  });

  test('allows negative ending balance with warning', async ({ authedPage: page }) => {
    // Create a product with no stock
    await page.click('[href="/products"]');
    const sku = uniqueSku();
    await page.fill('#sku', sku);
    await page.fill('#name', `NoBal Test ${sku}`);
    await page.fill('#price', '10');
    await page.fill('#gst-rate', '5');
    await page.click('button:has-text("Create product")');
    await expectSuccess(page, 'Product created');

    await page.click('[href="/inventory"]');
    await page.waitForTimeout(500);

    const productSelect = page.locator('#inventory-product');
    const options = productSelect.locator('option');
    const count = await options.count();
    let targetValue = '';
    for (let i = 0; i < count; i++) {
      const text = await options.nth(i).textContent();
      if (text?.includes(sku)) {
        targetValue = (await options.nth(i).getAttribute('value')) || '';
        break;
      }
    }
    if (targetValue) {
      await productSelect.selectOption(targetValue);
    }

    // Try to deduct stock when there is none
    await page.fill('#inventory-quantity', '-10');
    await page.click('button:has-text("Apply adjustment")');
    await expectSuccess(page, 'Negative inventory warning');
  });

  test('shows low stock indicator for qty <= 5', async ({
    authedPage: page,
  }) => {
    await page.click('[href="/products"]');
    const sku = uniqueSku();
    await page.fill('#sku', sku);
    await page.fill('#name', `Low Stock ${sku}`);
    await page.fill('#price', '10');
    await page.fill('#gst-rate', '5');
    await page.click('button:has-text("Create product")');
    await expectSuccess(page, 'Product created');

    // Add just 3 units
    await page.click('[href="/inventory"]');
    await page.waitForTimeout(500);
    const productSelect = page.locator('#inventory-product');
    const options = productSelect.locator('option');
    const count = await options.count();
    let targetValue = '';
    for (let i = 0; i < count; i++) {
      const text = await options.nth(i).textContent();
      if (text?.includes(sku)) {
        targetValue = (await options.nth(i).getAttribute('value')) || '';
        break;
      }
    }
    if (targetValue) {
      await productSelect.selectOption(targetValue);
    }
    await page.fill('#inventory-quantity', '3');
    await page.click('button:has-text("Apply adjustment")');
    await expectSuccess(page, 'Inventory updated');

    // Should show "Low stock" and pill--low
    const row = page.locator('.table-row', { hasText: sku });
    await expect(row.locator('.pill--low')).toBeVisible();
  });
});
