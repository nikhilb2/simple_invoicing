import type { Page } from '@playwright/test';
import { test, expect } from './fixtures';

/** Pick the first option in a combobox — avoids depending on seeded names. */
async function selectFirstOption(page: Page, inputId: string) {
  await page.locator(`#${inputId}`).click();
  const option = page.locator(`#${inputId}-listbox [role="option"]`).first();
  await expect(option).toBeVisible();
  await option.click();
}

/** The clear button for a combobox, scoped to its wrapper. */
function clearButton(page: Page, inputId: string) {
  return page.locator(`#${inputId}`).locator('..').getByRole('button', { name: 'Clear selection' });
}

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

  test('customer field has no clear button until one is picked', async ({ authedPage: page }) => {
    await page.goto('/analytics');
    await expect(clearButton(page, 'analytics-ledger')).toBeHidden();

    await selectFirstOption(page, 'analytics-ledger');
    await expect(clearButton(page, 'analytics-ledger')).toBeVisible();
  });

  test('clearing the customer keeps the date range', async ({ authedPage: page }) => {
    // The point of a per-field clear: dropping a customer shouldn't cost you
    // the dates you just set.
    await page.goto('/analytics?from=2026-01-01&to=2026-02-01');
    await selectFirstOption(page, 'analytics-ledger');
    await expect(page).toHaveURL(/ledger=/);

    await clearButton(page, 'analytics-ledger').click();

    await expect(page).not.toHaveURL(/ledger=/);
    await expect(page).toHaveURL(/from=2026-01-01/);
    await expect(page).toHaveURL(/to=2026-02-01/);
    await expect(page.locator('#analytics-ledger')).toHaveValue('');
  });

  test('clearing the product keeps the other filters', async ({ authedPage: page }) => {
    await page.goto('/analytics?tab=product-wise&from=2026-01-01&to=2026-02-01');
    await selectFirstOption(page, 'analytics-product');
    await expect(page).toHaveURL(/product=/);

    await clearButton(page, 'analytics-product').click();

    await expect(page).not.toHaveURL(/product=/);
    await expect(page).toHaveURL(/from=2026-01-01/);
    await expect(page.locator('#analytics-product')).toHaveValue('');
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

  test.describe('on a phone-sized viewport', () => {
    test.use({ viewport: { width: 390, height: 844 } });

    // The reports are wider than a phone, so they scroll inside their own
    // container. If an ancestor stops constraining them the whole page starts
    // scrolling sideways instead — which is what this guards.
    for (const [name, url] of [
      ['month-wise', '/analytics'],
      ['product-wise', '/analytics?tab=product-wise'],
    ] as const) {
      test(`${name} does not scroll the page sideways`, async ({ authedPage: page }) => {
        await page.goto(url);
        await expect(page.locator('.analytics-table-scroll')).toBeVisible();

        const { doc, win } = await page.evaluate(() => ({
          doc: document.documentElement.scrollWidth,
          win: window.innerWidth,
        }));
        expect(doc).toBeLessThanOrEqual(win);
      });
    }

    test('the wide table still scrolls within its own container', async ({ authedPage: page }) => {
      await page.goto('/analytics');
      const scroller = page.locator('.analytics-table-scroll');
      await expect(scroller).toBeVisible();

      const overflows = await scroller.evaluate((el) => el.scrollWidth > el.clientWidth);
      expect(overflows).toBe(true);
    });
  });
});
