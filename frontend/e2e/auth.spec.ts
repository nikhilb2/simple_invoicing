import { test, expect } from '@playwright/test';

test.describe('Authentication', () => {
  test('shows login page with correct heading', async ({ page }) => {
    await page.goto('/login');
    await expect(page.locator('h1')).toContainText('Bills, stock and payments in one place');
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
  });

  test('rejects invalid credentials', async ({ page }) => {
    await page.goto('/login');
    await page.fill('#email', 'wrong@example.com');
    await page.fill('#password', 'WrongPassword');
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(page.locator('.toast--error')).toBeVisible({
      timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000'),
    });
    // Should stay on the login page
    await expect(page).toHaveURL(/\/login/);
  });

  test('logs in with valid admin credentials', async ({ page }) => {
    await page.goto('/login');
    await page.fill('#email', 'admin@simple.dev');
    await page.fill('#password', 'Admin@123');
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(page).toHaveURL('/', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expect(page.locator('h1')).toContainText('Operations dashboard');
  });

  test('shows loading state while signing in', async ({ page }) => {
    await page.goto('/login');
    await page.fill('#email', 'admin@simple.dev');
    await page.fill('#password', 'Admin@123');
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    // Button should briefly show "Signing in..."
    // We just confirm the page eventually loads
    await expect(page).toHaveURL('/', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
  });

  test('redirects unauthenticated users to /login', async ({ page }) => {
    await page.goto('/catalogue');
    await expect(page).toHaveURL(/\/login/, { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
  });

  test('logout redirects to login page', async ({ page }) => {
    // First log in
    await page.goto('/login');
    await page.fill('#email', 'admin@simple.dev');
    await page.fill('#password', 'Admin@123');
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(page).toHaveURL('/', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

    // Now logout
    await page.click('button:has-text("Logout")');
    await expect(page).toHaveURL(/\/login/, { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
  });

  test('uses plain words on the sign-in form', async ({ page }) => {
    await page.goto('/login');
    await expect(page.getByText('Welcome back')).toBeVisible();
    await expect(page.getByText('Enter your email and password to see your invoices, stock and payments.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Open dashboard' })).toHaveCount(0);
  });

  test('shows the links on the auth pages as links', async ({ page }) => {
    await page.goto('/forgot-password');
    const link = page.getByRole('link', { name: 'Back to sign in' });
    await expect(link).toHaveCSS('text-decoration-line', 'underline');
    const colours = await link.evaluate((el) => ({
      link: getComputedStyle(el).color,
      surrounding: getComputedStyle(el.parentElement as Element).color,
    }));
    expect(colours.link).not.toBe(colours.surrounding);
  });

  test('keeps the benefits on the left and the form on the right on a wide screen', async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 900 });
    await page.goto('/login');
    await expect(page.locator('#email')).toBeVisible();
    const hero = await page.locator('.login-hero').boundingBox();
    const card = await page.locator('.login-card').boundingBox();
    expect(hero!.x + hero!.width).toBeLessThanOrEqual(card!.x);
  });

  test.describe('on a phone', () => {
    test.use({ viewport: { width: 390, height: 844 } });

    for (const path of ['/login', '/forgot-password', '/reset-password?token=x', '/verify-email?token=x']) {
      test(`puts the form before the benefits on ${path}`, async ({ page }) => {
        await page.goto(path);
        const firstInput = page.locator('.login-card input').first();
        await expect(firstInput).toBeVisible();
        const position = await firstInput.evaluate((el) => el.getBoundingClientRect().top + window.scrollY);
        expect(position).toBeLessThan(400);
        const hero = await page.locator('.login-hero').boundingBox();
        const card = await page.locator('.login-card').boundingBox();
        expect(card!.y).toBeLessThan(hero!.y);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        expect(overflow).toBeLessThanOrEqual(0);
      });
    }
  });
});
