import { test, expect } from './fixtures';

test.describe('Sidebar', () => {
  // 1. Sidebar visible on desktop
  test('sidebar is visible on desktop viewport', async ({ authedPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await expect(page.locator('.sidebar')).toBeVisible();
  });

  // 2. Active link highlighted
  test('active nav link is highlighted on current route', async ({ authedPage: page }) => {
    await page.goto('/invoices');
    await expect(page.locator('.sidebar__link--active[href="/invoices"]')).toBeVisible();
  });

  // 3. All nav groups present
  test('sidebar renders Management and Settings groups', async ({ authedPage: page }) => {
    await expect(page.locator('.sidebar__group-label', { hasText: 'Management' })).toBeVisible();
    await expect(page.locator('.sidebar__group-label', { hasText: 'Settings' })).toBeVisible();
  });

  // 4. User email visible in footer
  test('sidebar footer shows user email', async ({ authedPage: page }) => {
    await expect(page.locator('.sidebar__user-email')).toBeVisible();
    const email = await page.locator('.sidebar__user-email').textContent();
    expect(email?.trim().length).toBeGreaterThan(0);
  });

  // 5. FY switcher in sidebar
  test('FY switcher section visible in sidebar', async ({ authedPage: page }) => {
    await expect(page.locator('.sidebar').getByText('Financial Year')).toBeVisible();
    await expect(page.locator('button[aria-haspopup="listbox"]')).toBeVisible();
  });

  // 6. Sidebar persists across page navigation
  test('sidebar stays visible when navigating between pages', async ({ authedPage: page }) => {
    await page.click('[href="/products"]');
    await expect(page.locator('.sidebar')).toBeVisible();
    await page.click('[href="/invoices"]');
    await expect(page.locator('.sidebar')).toBeVisible();
  });
});
