import { test, expect, clickNavLink } from './fixtures';

/**
 * Navigation & layout tests – verify sidebar links route correctly
 * and the overall layout renders properly.
 */
test.describe('Navigation', () => {
  test('navigates to all main pages via sidebar', async ({
    authedPage: page,
  }) => {
    // The order deliberately hops between rail sections — catalogue, then a
    // top-level link, then reports, then sales. Only one section is expanded
    // at a time, so each hop closes the section the previous link lived in;
    // clickNavLink re-opens the one it needs. /company is absent because it
    // moved behind /settings and no longer has a rail link (see company.spec).
    const routes: [string, string][] = [
      ['/catalogue', 'Products & stock'],
      ['/ledgers', 'Ledger master'],
      ['/day-book', 'Day book'],
      ['/invoices', 'Invoice composer'],
      ['/', 'Operations dashboard'],
    ];

    for (const [href, heading] of routes) {
      await clickNavLink(page, href);
      await expect(page.locator('h1')).toContainText(heading, {
        timeout: 5_000,
      });
    }
  });

  test('brand link navigates to dashboard', async ({ authedPage: page }) => {
    await clickNavLink(page, '/catalogue');
    await expect(page.locator('h1')).toContainText('Products & stock');
    await page.locator('a.sidebar__brand').click();
    await expect(page.locator('h1')).toContainText('Operations dashboard');
  });

  test('shows user info in sidebar footer', async ({ authedPage: page }) => {
    await expect(page.locator('.sidebar__user-email')).toBeVisible();
  });
});
