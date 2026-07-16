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

  test('reset is disabled until a filter is changed', async ({ authedPage: page }) => {
    await page.goto('/analytics');
    await expect(page.getByRole('button', { name: 'Reset' })).toBeDisabled();

    await page.getByLabel('Type').selectOption('purchase');
    await expect(page.getByRole('button', { name: 'Reset' })).toBeEnabled();
  });

  test('reset clears filters back to the active financial year', async ({ authedPage: page }) => {
    await page.goto('/analytics?type=purchase&from=2026-01-01&to=2026-02-01');
    await expect(page.getByLabel('Type')).toHaveValue('purchase');

    await page.getByRole('button', { name: 'Reset' }).click();

    // Filter params are gone; the FY default is back.
    await expect(page).not.toHaveURL(/type=|from=|to=|ledger=|product=/);
    await expect(page.getByLabel('Type')).toHaveValue('sales');
    await expect(page.getByLabel('Financial Year')).not.toHaveValue('');
    await expect(page.getByRole('button', { name: 'Reset' })).toBeDisabled();
  });

  test('reset keeps you on the current tab', async ({ authedPage: page }) => {
    await page.goto('/analytics?tab=product-wise&type=purchase');
    await page.getByRole('button', { name: 'Reset' }).click();

    await expect(page).toHaveURL(/tab=product-wise/);
    await expect(page.getByRole('tab', { name: 'Product-wise Sales' })).toHaveAttribute('aria-selected', 'true');
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
