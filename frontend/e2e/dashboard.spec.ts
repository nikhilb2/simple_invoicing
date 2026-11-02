import { test, expect, expectSuccess, openSidebarSection } from './fixtures';

test.describe('Dashboard', () => {
  test('displays stats cards after login', async ({ authedPage: page }) => {
    await expect(page.locator('h1')).toContainText('Operations dashboard');

    // Key metric cards should be visible
    await expect(page.locator('.eyebrow', { hasText: 'Net sales' })).toBeVisible();
    await expect(page.locator('.eyebrow', { hasText: 'Outstanding' })).toBeVisible();
    await expect(page.locator('.eyebrow', { hasText: 'Catalog' })).toBeVisible();
    await expect(page.locator('.eyebrow', { hasText: 'Low stock' })).toBeVisible();
  });

  test('shows "Backend synced" chip', async ({ authedPage: page }) => {
    await expect(page.locator('.status-chip').first()).toContainText('Backend synced', {
      timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000'),
    });
  });

  test('displays inventory pressure points panel', async ({
    authedPage: page,
  }) => {
    await expect(page.getByText('Inventory pressure points')).toBeVisible();
  });

  test('displays latest activity panel', async ({ authedPage: page }) => {
    await expect(page.getByText('Latest activity')).toBeVisible();
  });

  test('navigation links are present', async ({ authedPage: page }) => {
    const sidebar = page.locator('.sidebar');

    // The rail is two-level now: two plain links at the top, a settings link
    // in the footer, and four disclosure buttons in between. Company is gone
    // from the rail entirely — it lives behind /settings (see settings-nav).
    for (const label of ['Overview', 'Ledgers', 'Settings']) {
      await expect(sidebar.getByRole('link', { name: label, exact: true })).toBeVisible();
    }
    for (const label of ['Sales', 'Catalogue', 'Reports', 'Marketplace']) {
      await expect(sidebar.getByRole('button', { name: label, exact: true })).toBeVisible();
    }

    // The leaves are only in the DOM while their section is open, so each one
    // has to be disclosed before it can be asserted. Scoped to the sidebar and
    // exact: the dashboard's stat cards are links too, so a substring match on
    // "Products" would hit several of them.
    const sections: [string, string[]][] = [
      ['catalogue', ['Products & Stock', 'Produce Items']],
      ['reports', ['Day Book']],
      ['sales', ['Invoices']],
    ];
    for (const [sectionId, labels] of sections) {
      await openSidebarSection(page, sectionId);
      for (const label of labels) {
        await expect(sidebar.getByRole('link', { name: label, exact: true })).toBeVisible();
      }
    }
  });
});
