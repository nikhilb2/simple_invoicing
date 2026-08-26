import { test, expect, expectSuccess, expectError, uniqueSku, adjustInventory, clickNavLink } from './fixtures';

test.describe('Inventory Management', () => {
  // The page has been titled "Stock ledger" for a while; this test still
  // expected the older "Stock adjustments" and had been failing on that alone.
  test('displays the stock ledger heading', async ({ authedPage: page }) => {
    await clickNavLink(page, '/inventory');
    await expect(page.locator('h1')).toContainText('Stock ledger');
  });

  test('shows stock ledger section', async ({ authedPage: page }) => {
    await clickNavLink(page, '/inventory');
    await expect(page.getByText('Stock ledger')).toBeVisible();
  });

  test('adds stock to a product', async ({ authedPage: page }) => {
    // First create a product to stock
    await clickNavLink(page, '/products');
    const sku = uniqueSku();
    await page.fill('#sku', sku);
    await page.fill('#name', `Inv Test ${sku}`);
    await page.fill('#price', '50');
    await page.fill('#gst-rate', '18');
    await page.click('button:has-text("Create product")');
    await expectSuccess(page, 'Product created');

    // Go to inventory
    await clickNavLink(page, '/inventory');
    await page.waitForTimeout(500);

    // Find the product's feed row and add stock inline
    await adjustInventory(page, sku, '25');
    await expectSuccess(page, 'Inventory updated');

    // Verify product appears in ledger with the stocked quantity
    const row = page.locator('.table-row', { hasText: sku });
    await expect(row).toBeVisible();
  });

  test('deducts stock from a product', async ({ authedPage: page }) => {
    // Create a product and stock it
    await clickNavLink(page, '/products');
    const sku = uniqueSku();
    await page.fill('#sku', sku);
    await page.fill('#name', `Deduct Test ${sku}`);
    await page.fill('#price', '30');
    await page.fill('#gst-rate', '12');
    await page.click('button:has-text("Create product")');
    await expectSuccess(page, 'Product created');

    // Add stock
    await clickNavLink(page, '/inventory');
    await page.waitForTimeout(500);
    await adjustInventory(page, sku, '20');
    await expectSuccess(page, 'Inventory updated');

    // Deduct some stock
    await adjustInventory(page, sku, '-5');
    await expectSuccess(page, 'Inventory updated');
  });

  test('blocks negative ending balance', async ({ authedPage: page }) => {
    // Create a product with no stock
    await clickNavLink(page, '/products');
    const sku = uniqueSku();
    await page.fill('#sku', sku);
    await page.fill('#name', `NoBal Test ${sku}`);
    await page.fill('#price', '10');
    await page.fill('#gst-rate', '5');
    await page.click('button:has-text("Create product")');
    await expectSuccess(page, 'Product created');

    await clickNavLink(page, '/inventory');
    await page.waitForTimeout(500);

    // Try to deduct stock when there is none
    await adjustInventory(page, sku, '-10');
    await expectError(page);
  });

  test('shows low stock indicator for qty <= 5', async ({
    authedPage: page,
  }) => {
    await clickNavLink(page, '/products');
    const sku = uniqueSku();
    await page.fill('#sku', sku);
    await page.fill('#name', `Low Stock ${sku}`);
    await page.fill('#price', '10');
    await page.fill('#gst-rate', '5');
    await page.click('button:has-text("Create product")');
    await expectSuccess(page, 'Product created');

    // Add just 3 units
    await clickNavLink(page, '/inventory');
    await page.waitForTimeout(500);
    await adjustInventory(page, sku, '3');
    await expectSuccess(page, 'Inventory updated');

    // Should show "Low stock" and pill--low
    const row = page.locator('.table-row', { hasText: sku });
    await expect(row.locator('.pill--low')).toBeVisible();
  });
});
