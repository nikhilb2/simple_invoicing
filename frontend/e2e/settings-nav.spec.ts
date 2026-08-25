import { test, expect } from './fixtures';

/**
 * The settings hub.
 *
 * Settings used to be seven links in the main rail; they are now one footer
 * link into /settings, which has its own sub-navigation and an overview page
 * of cards. That is three separate ways in — the footer link, a card, a
 * sub-nav chip — plus the redirects covering everywhere those pages used to
 * live, and none of them is exercised by the page specs (company.spec and
 * friends go straight to their URL now). Hence a file of its own, next to
 * sidebar.spec.ts which owns the rail itself.
 */
test.describe('Settings hub', () => {
  test('the sidebar footer link reaches the settings overview', async ({
    authedPage: page,
  }) => {
    const link = page.locator('.sidebar .sidebar__link--settings');
    await expect(link).toHaveAttribute('href', '/settings');

    await link.click();
    await expect(page).toHaveURL('/settings');
    await expect(page.locator('h1')).toContainText('Settings');
    await expect(page.locator('aside.settings-nav')).toBeVisible();
  });

  test('overview cards navigate to their settings page', async ({
    authedPage: page,
  }) => {
    await page.goto('/settings');

    // The cards exist to say what each page is *for*, so a card without its
    // one line of copy is a card that isn't doing its job.
    const card = page.locator('a.settings-card[href="/settings/shortcuts"]');
    await expect(card).toBeVisible();
    await expect(card.locator('.settings-card__copy')).not.toBeEmpty();

    await card.click();
    await expect(page).toHaveURL('/settings/shortcuts');
    await expect(page.locator('h1')).toContainText('Keyboard Shortcuts');
  });

  test('the sub-nav navigates and marks the current page active', async ({
    authedPage: page,
  }) => {
    await page.goto('/settings');
    const nav = page.locator('aside.settings-nav');

    await nav.locator('a.settings-nav__link[href="/settings/company"]').click();
    await expect(page).toHaveURL('/settings/company');
    await expect(page.locator('h1')).toContainText('Billing identity');
    await expect(
      nav.locator('a.settings-nav__link--active[href="/settings/company"]'),
    ).toBeVisible();

    // Moving on has to move the highlight with it — the sub-nav is the only
    // "where am I" cue inside settings, since the rail just says "Settings".
    await nav.locator('a.settings-nav__link[href="/settings/security"]').click();
    await expect(page).toHaveURL('/settings/security');
    await expect(page.locator('h1')).toContainText('Change password');
    await expect(nav.locator('a.settings-nav__link--active')).toHaveCount(1);
    await expect(
      nav.locator('a.settings-nav__link--active[href="/settings/security"]'),
    ).toBeVisible();

    // "All settings" walks back up to the overview.
    await nav.locator('a.settings-nav__back').click();
    await expect(page).toHaveURL('/settings');
  });
});

test.describe('Legacy settings paths', () => {
  // Bookmarks, links pasted into chats and the marketplace's own deep links
  // all still point at the pre-move URLs, so the redirects are the contract.
  const MOVED: [string, string][] = [
    ['/company', '/settings/company'],
    ['/smtp-settings', '/settings/email'],
    ['/email-history', '/settings/email-history'],
    ['/api-keys', '/settings/api-keys'],
    ['/backups', '/settings/backups'],
    ['/change-password', '/settings/security'],
    ['/shortcuts', '/settings/shortcuts'],
    ['/marketplace/settings', '/settings/marketplace'],
  ];

  for (const [from, to] of MOVED) {
    test(`${from} lands on ${to}`, async ({ authedPage: page }) => {
      await page.goto(from);
      await expect(page).toHaveURL(to);
      await expect(page.locator('aside.settings-nav')).toBeVisible();
    });
  }

  test('a legacy path keeps its query string', async ({ authedPage: page }) => {
    // ?setup=required is what CompanyRequired appends when it bounces a user
    // to the company form; losing it in the redirect would lose the reason.
    await page.goto('/company?setup=required');
    await expect(page).toHaveURL('/settings/company?setup=required');
    await expect(page.locator('h1')).toContainText('Billing identity');
  });
});
