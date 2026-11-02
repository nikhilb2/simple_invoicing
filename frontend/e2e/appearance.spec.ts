import { test, expect } from './fixtures';

const html = 'html';

test.describe('Appearance', () => {
  test('system preference follows the emulated OS scheme, live', async ({ authedPage: page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await page.goto('/settings/appearance');
    await expect(page.locator('h1')).toContainText('Appearance');
    await expect(page.locator('#theme-system')).toBeChecked();
    await expect(page.locator(html)).toHaveAttribute('data-theme', 'light');

    await page.emulateMedia({ colorScheme: 'dark' });
    await expect(page.locator(html)).toHaveAttribute('data-theme', 'dark');
  });

  test('choosing Dark persists across reload even with a light OS', async ({ authedPage: page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await page.goto('/settings/appearance');

    await page.locator('label[for="theme-dark"]').click();
    await expect(page.locator(html)).toHaveAttribute('data-theme', 'dark');
    expect(await page.evaluate(() => localStorage.getItem('theme'))).toBe('dark');

    await page.reload();
    await expect(page.locator('#theme-dark')).toBeChecked();
    await expect(page.locator(html)).toHaveAttribute('data-theme', 'dark');

    // Back to System so later tests in the same browser context are unaffected.
    await page.locator('label[for="theme-system"]').click();
    await expect(page.locator(html)).toHaveAttribute('data-theme', 'light');
  });

  test('data-theme is set before the app bundle runs (no flash)', async ({ authedPage: page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    // Runs at the start of every new document, before the page's own scripts,
    // so it records what the inline <head> script produced by the time it can
    // be observed at DOMContentLoaded's earliest point.
    await page.addInitScript(() => {
      document.addEventListener('readystatechange', () => {
        const w = window as unknown as { __firstTheme?: string | undefined };
        if (w.__firstTheme === undefined) w.__firstTheme = document.documentElement.dataset.theme ?? '';
      });
    });
    await page.goto('/settings/appearance', { waitUntil: 'commit' });
    const first = await page.evaluate(
      () => (window as unknown as { __firstTheme?: string }).__firstTheme,
    );
    expect(first).toBe('light');
    expect(await page.evaluate(() => document.documentElement.style.colorScheme)).toBe('light');
  });
});
