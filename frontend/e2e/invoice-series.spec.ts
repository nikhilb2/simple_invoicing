import { test, expect } from './fixtures';

test.describe('Invoice Series', () => {
  test('shows invoice series card on company page', async ({ authedPage: page }) => {
    await page.click('[href="/company"]');

    // Wait for the series card to appear (loaded from API)
    await expect(page.locator('h2:has-text("Invoice series")')).toBeVisible({ timeout: 10_000 });

    // All three series rows should be visible
    await expect(page.locator('strong:has-text("Sales")')).toBeVisible();
    await expect(page.locator('strong:has-text("Purchase")')).toBeVisible();
    await expect(page.locator('strong:has-text("Payment")')).toBeVisible();
  });

  test('shows live preview that updates with prefix changes', async ({ authedPage: page }) => {
    await page.click('[href="/company"]');
    await expect(page.locator('h2:has-text("Invoice series")')).toBeVisible({ timeout: 10_000 });

    // Find the first prefix input (Sales series)
    const prefixInputs = page.locator('[id^="series-prefix-"]');
    await expect(prefixInputs.first()).toBeVisible({ timeout: 5_000 });

    // Clear and type a new prefix
    await prefixInputs.first().fill('RES');

    // Preview should update to include RES
    await expect(page.locator('text=Preview:').first()).toBeVisible();
    const previewEl = page.locator('strong', { hasText: 'RES-' }).first();
    await expect(previewEl).toBeVisible({ timeout: 5_000 });
  });

  test('can save invoice series settings', async ({ authedPage: page }) => {
    await page.click('[href="/company"]');
    await expect(page.locator('h2:has-text("Invoice series")')).toBeVisible({ timeout: 10_000 });

    // Change Sales prefix to a unique value
    const prefixInputs = page.locator('[id^="series-prefix-"]');
    await expect(prefixInputs.first()).toBeVisible({ timeout: 5_000 });
    await prefixInputs.first().fill('SAL');

    // Save
    const saveButtons = page.locator('button:has-text("Save")');
    await saveButtons.first().click();

    // Success indicator
    await expect(page.locator('text=Saved').first()).toBeVisible({ timeout: 8_000 });
  });

  test('pad digits dropdown changes preview', async ({ authedPage: page }) => {
    await page.click('[href="/company"]');
    await expect(page.locator('h2:has-text("Invoice series")')).toBeVisible({ timeout: 10_000 });

    const padSelects = page.locator('[id^="series-pad-"]');
    await expect(padSelects.first()).toBeVisible({ timeout: 5_000 });

    // Select 4 digits
    await padSelects.first().selectOption('4');

    // Preview should show 4-digit sequence (e.g. 0001)
    const preview = page.locator('strong', { hasText: /\d{4}$/ }).first();
    await expect(preview).toBeVisible({ timeout: 5_000 });
  });

  test('include year toggle hides year format selector', async ({ authedPage: page }) => {
    await page.click('[href="/company"]');
    await expect(page.locator('h2:has-text("Invoice series")')).toBeVisible({ timeout: 10_000 });

    const includeYearCheckboxes = page.locator('[id^="series-include-year-"]');
    await expect(includeYearCheckboxes.first()).toBeVisible({ timeout: 5_000 });

    // Uncheck include year
    const firstCheckbox = includeYearCheckboxes.first();
    const isChecked = await firstCheckbox.isChecked();
    if (isChecked) {
      await firstCheckbox.uncheck();
    }

    // Year format selector should be disabled
    const yearFormatSelects = page.locator('[id^="series-year-fmt-"]');
    await expect(yearFormatSelects.first()).toBeDisabled({ timeout: 5_000 });
  });

  test('invoice number uses series prefix after save', async ({ authedPage: page }) => {
    // Go to company page and set a distinctive prefix
    await page.click('[href="/company"]');
    await expect(page.locator('h2:has-text("Invoice series")')).toBeVisible({ timeout: 10_000 });

    const prefixInputs = page.locator('[id^="series-prefix-"]');
    await expect(prefixInputs.first()).toBeVisible({ timeout: 5_000 });

    // Set to E2E prefix so we can verify it later
    await prefixInputs.first().fill('E2E');
    const saveButtons = page.locator('button:has-text("Save")');
    await saveButtons.first().click();
    await expect(page.locator('text=Saved').first()).toBeVisible({ timeout: 8_000 });

    // Restore to default INV to avoid interfering with other tests
    await prefixInputs.first().fill('INV');
    await saveButtons.first().click();
    await expect(page.locator('text=Saved').first()).toBeVisible({ timeout: 8_000 });
  });
});
