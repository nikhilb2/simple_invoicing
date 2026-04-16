import { test, expect, expectSuccess } from './fixtures';

test.describe('Dashboard', () => {
  test('displays stats cards after login', async ({ authedPage: page }) => {
    await expect(page.locator('h1')).toContainText('Operations dashboard');

    // Four stat cards should be visible
    await expect(page.locator('.eyebrow', { hasText: 'Catalog' })).toBeVisible();
    await expect(page.locator('.eyebrow', { hasText: 'Stock units' })).toBeVisible();
    await expect(page.locator('.eyebrow', { hasText: 'Low stock' })).toBeVisible();
    await expect(page.locator('.eyebrow', { hasText: 'Invoice value' })).toBeVisible();
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
    const links = [
      'Overview',
      'Products',
      'Inventory',
      'Ledgers',
      'Day Book',
      'Invoices',
      'Company',
    ];
    for (const label of links) {
      await expect(page.getByRole('link', { name: label })).toBeVisible();
    }
  });
});
