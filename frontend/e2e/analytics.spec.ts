import { test, expect } from './fixtures';

test.describe('Analytics', () => {
  test('is reachable from the sidebar Analytics group', async ({ authedPage: page }) => {
    await page.click('.sidebar [href="/analytics"]');
    await expect(page).toHaveURL(/\/analytics/);
    await expect(page.locator('.page-title')).toHaveText('Analytics');
  });

  test('defaults to the month-wise tab', async ({ authedPage: page }) => {
    await page.goto('/analytics');
    await expect(page.getByRole('tab', { name: 'Month-wise Sales' })).toHaveAttribute('aria-selected', 'true');
  });

  test('switching tabs updates the URL', async ({ authedPage: page }) => {
    await page.goto('/analytics');
    await page.getByRole('tab', { name: 'Product-wise Sales' }).click();

    await expect(page).toHaveURL(/tab=product-wise/);
    await expect(page.getByRole('tab', { name: 'Product-wise Sales' })).toHaveAttribute('aria-selected', 'true');
  });

  test('deep-linking a tab opens it', async ({ authedPage: page }) => {
    await page.goto('/analytics?tab=product-wise');
    await expect(page.getByRole('tab', { name: 'Product-wise Sales' })).toHaveAttribute('aria-selected', 'true');
  });

  test('tabs are keyboard navigable', async ({ authedPage: page }) => {
    await page.goto('/analytics');
    await page.getByRole('tab', { name: 'Month-wise Sales' }).focus();
    await page.keyboard.press('ArrowRight');

    await expect(page.getByRole('tab', { name: 'Product-wise Sales' })).toHaveAttribute('aria-selected', 'true');
  });

  test('renders a chart or an empty state, never an error', async ({ authedPage: page }) => {
    await page.goto('/analytics');
    await expect(page.locator('.chart-frame svg, .empty-state').first()).toBeVisible();
  });

  test('changing the voucher type refetches and syncs the URL', async ({ authedPage: page }) => {
    await page.goto('/analytics');

    const response = page.waitForResponse((res) =>
      res.url().includes('/analytics/sales-by-month') && res.url().includes('voucher_type=purchase'),
    );
    await page.getByLabel('Type').selectOption('purchase');
    await response;

    await expect(page).toHaveURL(/type=purchase/);
  });

  test('exports month-wise CSV', async ({ authedPage: page }) => {
    await page.goto('/analytics');

    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /Export CSV/ }).click();
    const download = await downloadPromise;

    expect(download.suggestedFilename()).toMatch(/^sales_by_month_.*\.csv$/);
  });

  test('exports product-wise CSV', async ({ authedPage: page }) => {
    await page.goto('/analytics?tab=product-wise');

    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /Export CSV/ }).click();
    const download = await downloadPromise;

    expect(download.suggestedFilename()).toMatch(/^sales_by_product_.*\.csv$/);
  });
});
