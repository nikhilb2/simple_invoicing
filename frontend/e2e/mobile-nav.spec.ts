import { test, expect } from './fixtures';

const MOBILE = { width: 390, height: 844 };
const DESKTOP = { width: 1280, height: 800 };

test.describe('Mobile nav drawer', () => {
  test.beforeEach(async ({ authedPage: page }) => {
    await page.setViewportSize(MOBILE);
    await page.goto('/');
  });

  test('hides nav-panel and shows burger button on mobile', async ({
    authedPage: page,
  }) => {
    await expect(page.locator('.nav-panel')).toBeHidden();
    await expect(page.locator('.burger-btn')).toBeVisible();
  });

  test('opens drawer when burger is tapped', async ({ authedPage: page }) => {
    await expect(page.locator('.drawer-panel')).not.toBeAttached();
    await page.click('.burger-btn');
    await expect(page.locator('.drawer-panel')).toBeVisible();
  });

  test('drawer contains all nav links', async ({ authedPage: page }) => {
    await page.click('.burger-btn');
    const drawer = page.locator('.drawer-panel');
    await expect(drawer).toBeVisible();
    for (const label of [
      'Overview',
      'Products',
      'Inventory',
      'Ledgers',
      'Day Book',
      'Invoices',
      'Company',
    ]) {
      await expect(drawer.getByText(label)).toBeVisible();
    }
  });

  test('navigates and closes drawer when a nav link is tapped', async ({
    authedPage: page,
  }) => {
    await page.click('.burger-btn');
    await expect(page.locator('.drawer-panel')).toBeVisible();
    await page.locator('.drawer-panel').getByText('Products').click();
    await expect(page.locator('.drawer-panel')).not.toBeAttached();
    await expect(page.locator('h1')).toContainText('Catalog intake', {
      timeout: 5_000,
    });
  });

  test('closes drawer when backdrop is tapped', async ({ authedPage: page }) => {
    await page.click('.burger-btn');
    await expect(page.locator('.drawer-panel')).toBeVisible();
    // Click the visible portion of the backdrop (to the right of the 300px drawer)
    await page.locator('.drawer-backdrop').click({ position: { x: 360, y: 400 } });
    await expect(page.locator('.drawer-panel')).not.toBeAttached();
  });

  test('closes drawer when close button is tapped', async ({
    authedPage: page,
  }) => {
    await page.click('.burger-btn');
    await expect(page.locator('.drawer-panel')).toBeVisible();
    await page.locator('.drawer-close').click();
    await expect(page.locator('.drawer-panel')).not.toBeAttached();
  });

  test('closes drawer when Escape key is pressed', async ({
    authedPage: page,
  }) => {
    await page.click('.burger-btn');
    await expect(page.locator('.drawer-panel')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('.drawer-panel')).not.toBeAttached();
  });

  test('drawer has correct accessibility attributes', async ({
    authedPage: page,
  }) => {
    await expect(page.locator('.burger-btn')).toHaveAttribute(
      'aria-label',
      'Open navigation',
    );
    await page.click('.burger-btn');
    const drawer = page.locator('.drawer-panel');
    await expect(drawer).toHaveAttribute('role', 'dialog');
    await expect(drawer).toHaveAttribute('aria-modal', 'true');
    await expect(drawer).toHaveAttribute('aria-label', 'Navigation drawer');
  });

  test('hides burger and shows nav-panel on desktop viewport', async ({
    authedPage: page,
  }) => {
    await page.setViewportSize(DESKTOP);
    await expect(page.locator('.burger-btn')).toBeHidden();
    await expect(page.locator('.nav-panel')).toBeVisible();
  });
});
