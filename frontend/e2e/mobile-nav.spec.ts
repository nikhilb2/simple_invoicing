import { test, expect, clickNavLink, openSidebarSection } from './fixtures';

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

  // The drawer shows the same two-level rail as the desktop sidebar, so what
  // is visible on open is the *top level*: two plain links, four section
  // toggles and the settings footer link. Leaf pages like Products live inside
  // a section and only appear once it is expanded (asserted below); Company
  // isn't in the rail at all any more — it moved behind Settings.
  test('drawer contains every top-level nav row', async ({ authedPage: page }) => {
    await page.click('.sidebar-toggle');
    const sidebar = page.locator('.sidebar');
    await expect(sidebar).toBeVisible();
    for (const label of [
      'Overview',
      'Sales',
      'Catalogue',
      'Reports',
      'Marketplace',
      'Ledgers',
      'Settings',
    ]) {
      await expect(sidebar.getByText(label, { exact: true })).toBeVisible();
    }
  });

  test('expanding a section reveals its pages in the drawer', async ({
    authedPage: page,
  }) => {
    await page.click('.sidebar-toggle');
    await expect(page.locator('.sidebar').getByText('Products')).toHaveCount(0);

    await openSidebarSection(page, 'catalogue');
    const sidebar = page.locator('.sidebar');
    for (const label of ['Products', 'Inventory', 'Produce Items']) {
      await expect(sidebar.getByText(label, { exact: true })).toBeVisible();
    }
  });

  test('navigates and closes sidebar when a nav link is tapped', async ({
    authedPage: page,
  }) => {
    await page.click('.sidebar-toggle');
    await expect(page.locator('.sidebar')).toHaveClass(/sidebar--open/);
    // Products sits under the catalogue section, so the tap has to disclose it
    // first — clickNavLink does that, and the leaf link closes the drawer.
    await clickNavLink(page, '/products');
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
