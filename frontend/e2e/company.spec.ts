import { test, expect, expectSuccess, uniqueGstin } from './fixtures';

test.describe('Company Profile', () => {
  // Company left the main rail in the sidebar redesign — the only way to it in
  // the UI is now Settings -> Company. This is the one test that walks that
  // path; the rest go straight to the URL, since their subject is the form.
  test('is reachable from the sidebar via Settings', async ({ authedPage: page }) => {
    await page.locator('.sidebar__link--settings').click();
    await expect(page).toHaveURL('/settings');

    await page.locator('.settings-nav__link[href="/settings/company"]').click();
    await expect(page).toHaveURL('/settings/company');
    await expect(page.locator('h1')).toContainText('Billing identity');
  });

  test('saves company profile', async ({ authedPage: page }) => {
    await page.goto('/settings/company');

    // Wait for form to be ready
    await expect(page.locator('#company-name')).toBeVisible({ timeout: 5_000 });

    await page.fill('#company-name', 'E2E Test Company Pvt Ltd');
    await page.fill('#company-address', '42 Playwright Avenue, Bangalore');
    await page.fill('#company-gst', uniqueGstin('29'));
    await page.fill('#company-phone', '+91 8080808080');
    await page.selectOption('#company-currency', 'INR');
    await page.fill('#company-email', 'e2e@testcompany.com');
    await page.fill('#company-website', 'https://testcompany.com');

    await page.click('button:has-text("Save company details")');
    await expectSuccess(
      page,
      'Company profile saved',
    );
  });

  test('saves company profile with bank details', async ({
    authedPage: page,
  }) => {
    await page.goto('/settings/company');
    await expect(page.locator('#company-name')).toBeVisible({ timeout: 5_000 });

    await page.fill('#company-name', 'Bank Details Corp');
    await page.fill('#company-address', '100 Finance Rd, Mumbai');
    await page.fill('#company-gst', uniqueGstin());
    await page.fill('#company-phone', '+91 7070707070');
    await page.fill('#company-bank-name', 'ICICI Bank');
    await page.fill('#company-branch-name', 'Andheri East');
    await page.fill('#company-account-name', 'Bank Details Corp');
    await page.fill('#company-account-number', '987654321098');
    await page.fill('#company-ifsc', 'ICIC0001234');

    await page.click('button:has-text("Save company details")');
    await expectSuccess(page, 'Company profile saved');
  });

  test('persists company data across page reloads', async ({
    authedPage: page,
  }) => {
    await page.goto('/settings/company');
    await expect(page.locator('#company-name')).toBeVisible({ timeout: 5_000 });

    const companyName = `Persist Co ${Date.now().toString(36)}`;
    await page.fill('#company-name', companyName);
    await page.fill('#company-address', 'Persist Street');
    await page.fill('#company-gst', uniqueGstin());
    await page.fill('#company-phone', '+91 6060606060');
    await page.click('button:has-text("Save company details")');
    await expectSuccess(page, 'Company profile saved');

    // Reload and verify
    await page.reload();
    await expect(page.locator('#company-name')).toBeVisible({ timeout: 5_000 });
    await expect(page.locator('#company-name')).toHaveValue(companyName);
  });

  test('currency dropdown has multiple options', async ({
    authedPage: page,
  }) => {
    await page.goto('/settings/company');
    await expect(page.locator('#company-currency')).toBeVisible({
      timeout: 5_000,
    });

    const options = page.locator('#company-currency option');
    const count = await options.count();
    expect(count).toBeGreaterThanOrEqual(3);
  });
});
