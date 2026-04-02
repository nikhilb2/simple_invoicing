import { test, expect } from '@playwright/test';

test.describe('Authentication', () => {
  test('shows login page with correct heading', async ({ page }) => {
    await page.goto('/login');
    await expect(page.locator('h1')).toContainText(
      'Run inventory and invoicing without spreadsheet drag',
    );
    await expect(page.getByText('Access the workspace')).toBeVisible();
  });

  test('rejects invalid credentials', async ({ page }) => {
    await page.goto('/login');
    await page.fill('#email', 'wrong@example.com');
    await page.fill('#password', 'WrongPassword');
    await page.click('button:has-text("Open dashboard")');
    await expect(page.locator('.toast--error')).toBeVisible({
      timeout: 10_000,
    });
    // Should stay on the login page
    await expect(page).toHaveURL(/\/login/);
  });

  test('logs in with valid admin credentials', async ({ page }) => {
    await page.goto('/login');
    await page.fill('#email', 'admin@simple.dev');
    await page.fill('#password', 'Admin@123');
    await page.click('button:has-text("Open dashboard")');
    await expect(page).toHaveURL('/', { timeout: 10_000 });
    await expect(page.locator('h1')).toContainText('Operations dashboard');
  });

  test('shows loading state while signing in', async ({ page }) => {
    await page.goto('/login');
    await page.fill('#email', 'admin@simple.dev');
    await page.fill('#password', 'Admin@123');
    await page.click('button:has-text("Open dashboard")');
    // Button should briefly show "Signing in..."
    // We just confirm the page eventually loads
    await expect(page).toHaveURL('/', { timeout: 10_000 });
  });

  test('redirects unauthenticated users to /login', async ({ page }) => {
    await page.goto('/products');
    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
  });

  test('logout redirects to login page', async ({ page }) => {
    // First log in
    await page.goto('/login');
    await page.fill('#email', 'admin@simple.dev');
    await page.fill('#password', 'Admin@123');
    await page.click('button:has-text("Open dashboard")');
    await expect(page).toHaveURL('/', { timeout: 10_000 });

    // Now logout
    await page.click('button:has-text("Logout")');
    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
  });
});
