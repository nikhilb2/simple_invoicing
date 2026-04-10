import { test, expect } from './fixtures';

const MOBILE = { width: 390, height: 844 };
const DESKTOP = { width: 1280, height: 800 };

test.describe('Mobile nav drawer', () => {
  test.beforeEach(async ({ authedPage: page }) => {
    await page.setViewportSize(MOBILE);
    await page.goto('/');
  });

  test('hides sidebar and shows sidebar-toggle on mobile', async ({
    authedPage: page,
  }) => {
    await expect(page.locator('.sidebar-toggle')).toBeVisible();
  });

  test('opens sidebar when toggle is tapped', async ({ authedPage: page }) => {
    await expect(page.locator('.sidebar')).not.toHaveClass(/sidebar--open/);
    await page.click('.sidebar-toggle');
    await expect(page.locator('.sidebar')).toHaveClass(/sidebar--open/);
  });

  test('sidebar contains all nav links', async ({ authedPage: page }) => {
    await page.click('.sidebar-toggle');
    const sidebar = page.locator('.sidebar');
    await expect(sidebar).toBeVisible();
    for (const label of [
      'Overview',
      'Products',
      'Inventory',
      'Ledgers',
      'Day Book',
      'Invoices',
      'Company',
    ]) {
      await expect(sidebar.getByText(label)).toBeVisible();
    }
  });

  test('navigates and closes sidebar when a nav link is tapped', async ({
    authedPage: page,
  }) => {
    await page.click('.sidebar-toggle');
    await expect(page.locator('.sidebar')).toHaveClass(/sidebar--open/);
    await page.locator('.sidebar').getByText('Products').click();
    await expect(page.locator('.sidebar')).not.toHaveClass(/sidebar--open/);
    await expect(page.locator('h1')).toContainText('Catalog intake', {
      timeout: 5_000,
    });
  });

  test('closes sidebar when backdrop is tapped', async ({ authedPage: page }) => {
    await page.click('.sidebar-toggle');
    await expect(page.locator('.sidebar-backdrop')).toBeVisible();
    await page.locator('.sidebar-backdrop').click({ position: { x: 320, y: 400 } });
    await expect(page.locator('.sidebar')).not.toHaveClass(/sidebar--open/);
  });

  test('closes sidebar when close button is tapped', async ({
    authedPage: page,
  }) => {
    await page.click('.sidebar-toggle');
    await expect(page.locator('.sidebar')).toHaveClass(/sidebar--open/);
    await page.locator('.sidebar__close').click();
    await expect(page.locator('.sidebar')).not.toHaveClass(/sidebar--open/);
  });

  test('closes sidebar when Escape key is pressed', async ({
    authedPage: page,
  }) => {
    await page.click('.sidebar-toggle');
    await expect(page.locator('.sidebar')).toHaveClass(/sidebar--open/);
    await page.keyboard.press('Escape');
    await expect(page.locator('.sidebar')).not.toHaveClass(/sidebar--open/);
  });

  test('sidebar has correct accessibility attributes', async ({
    authedPage: page,
  }) => {
    await expect(page.locator('.sidebar-toggle')).toHaveAttribute(
      'aria-label',
      'Open navigation',
    );
    await page.click('.sidebar-toggle');
    const sidebar = page.locator('.sidebar');
    await expect(sidebar).toHaveAttribute('role', 'dialog');
    await expect(sidebar).toHaveAttribute('aria-modal', 'true');
    await expect(sidebar).toHaveAttribute('aria-label', 'Navigation drawer');
  });

  test('hides sidebar-toggle on desktop viewport', async ({
    authedPage: page,
  }) => {
    await page.setViewportSize(DESKTOP);
    await expect(page.locator('.sidebar-toggle')).toBeHidden();
    await expect(page.locator('.sidebar')).toBeVisible();
  });
});
