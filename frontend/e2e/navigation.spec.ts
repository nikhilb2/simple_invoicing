import { test, expect } from './fixtures';

/**
 * Navigation & layout tests – verify sidebar links route correctly
 * and the overall layout renders properly.
 */
test.describe('Navigation', () => {
  test('navigates to all main pages via sidebar', async ({
    authedPage: page,
  }) => {
    const routes: [string, string][] = [
      ['/products', 'Catalog intake'],
      ['/inventory', 'Stock adjustments'],
      ['/ledgers', 'Ledger master'],
      ['/day-book', 'Day book'],
      ['/invoices', 'Invoice composer'],
      ['/company', 'Billing identity'],
      ['/', 'Operations dashboard'],
    ];

    for (const [href, heading] of routes) {
      await page.click(`[href="${href}"]`);
      await expect(page.locator('h1')).toContainText(heading, {
        timeout: 5_000,
      });
    }
  });

  test('brand link navigates to dashboard', async ({ authedPage: page }) => {
    await page.click('[href="/products"]');
    await expect(page.locator('h1')).toContainText('Catalog intake');
    await page.locator('a.sidebar__brand').click();
    await expect(page.locator('h1')).toContainText('Operations dashboard');
  });

  test('shows user info in sidebar footer', async ({ authedPage: page }) => {
    await expect(page.locator('.sidebar__user-email')).toBeVisible();
  });
});
