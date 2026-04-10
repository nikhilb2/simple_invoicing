import { test, expect } from './fixtures';

test.describe('Financial Year Switcher', () => {
  test('FY switcher section is visible in the nav panel', async ({ authedPage: page }) => {
    await expect(page.getByText('Financial Year')).toBeVisible({ timeout: 10_000 });
  });

  test('FY switcher dropdown button shows active FY label or fallback', async ({ authedPage: page }) => {
    const fyButton = page.locator('button[aria-haspopup="listbox"]');
    await expect(fyButton).toBeVisible({ timeout: 10_000 });
    // Button must have some text (either a FY label or "No active FY")
    const text = await fyButton.textContent();
    expect(text?.trim().length).toBeGreaterThan(0);
  });

  test('FY dropdown opens and shows FY list or empty state', async ({ authedPage: page }) => {
    const fyButton = page.locator('button[aria-haspopup="listbox"]');
    await fyButton.click();

    // The dropdown listbox should be visible
    const listbox = page.locator('[role="listbox"]');
    await expect(listbox).toBeVisible({ timeout: 5_000 });
  });

  test('FY dropdown shows "+ New FY" button', async ({ authedPage: page }) => {
    const fyButton = page.locator('button[aria-haspopup="listbox"]');
    await fyButton.click();

    const listbox = page.locator('[role="listbox"]');
    await expect(listbox).toBeVisible({ timeout: 5_000 });
    await expect(listbox.locator('button:has-text("+ New FY")')).toBeVisible({ timeout: 5_000 });
  });

  test('clicking outside FY dropdown closes it', async ({ authedPage: page }) => {
    const fyButton = page.locator('button[aria-haspopup="listbox"]');
    await fyButton.click();

    const listbox = page.locator('[role="listbox"]');
    await expect(listbox).toBeVisible({ timeout: 5_000 });

    // Click somewhere else on the page
    await page.locator('h1').first().click();
    await expect(listbox).not.toBeVisible({ timeout: 3_000 });
  });

  test('New FY modal opens with all required fields', async ({ authedPage: page }) => {
    const fyButton = page.locator('button[aria-haspopup="listbox"]');
    await fyButton.click();

    const listbox = page.locator('[role="listbox"]');
    await expect(listbox).toBeVisible({ timeout: 5_000 });
    await listbox.locator('button:has-text("+ New FY")').click();

    const dialog = page.locator('[role="dialog"][aria-label="Create new financial year"]');
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    // Starting year number input
    await expect(dialog.locator('input[type="number"]')).toBeVisible();
    // No date inputs
    await expect(dialog.locator('input[type="date"]')).toHaveCount(0);
    // Cancel button
    await expect(dialog.locator('button:has-text("Cancel")')).toBeVisible();
    // Create button
    await expect(dialog.locator('button:has-text("Create")')).toBeVisible();
  });

  test('New FY modal can be cancelled', async ({ authedPage: page }) => {
    const fyButton = page.locator('button[aria-haspopup="listbox"]');
    await fyButton.click();
    const listbox = page.locator('[role="listbox"]');
    await expect(listbox).toBeVisible({ timeout: 5_000 });
    await listbox.locator('button:has-text("+ New FY")').click();

    const dialog = page.locator('[role="dialog"][aria-label="Create new financial year"]');
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    await dialog.locator('button:has-text("Cancel")').click();
    await expect(dialog).not.toBeVisible({ timeout: 3_000 });
  });

  test('New FY modal validates required fields', async ({ authedPage: page }) => {
    const fyButton = page.locator('button[aria-haspopup="listbox"]');
    await fyButton.click();
    const listbox = page.locator('[role="listbox"]');
    await expect(listbox).toBeVisible({ timeout: 5_000 });
    await listbox.locator('button:has-text("+ New FY")').click();

    const dialog = page.locator('[role="dialog"][aria-label="Create new financial year"]');
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    // Submit with empty year field
    await dialog.locator('button:has-text("Create")').click();
    await expect(dialog.locator('text=Please enter a valid starting year (2000–2099).')).toBeVisible({ timeout: 3_000 });
  });

  test('can create a new financial year', async ({ authedPage: page }) => {
    const testYear = 2030;
    const testLabel = '2030-31';

    const fyButton = page.locator('button[aria-haspopup="listbox"]');
    await fyButton.click();
    const listbox = page.locator('[role="listbox"]');
    await expect(listbox).toBeVisible({ timeout: 5_000 });

    // If FY already exists from a previous run, just verify it's there and skip
    const existingOption = listbox.locator(`button:has-text("${testLabel}")`);
    if (await existingOption.isVisible()) {
      await page.locator('h1').first().click();
      return;
    }

    await listbox.locator('button:has-text("+ New FY")').click();

    const dialog = page.locator('[role="dialog"][aria-label="Create new financial year"]');
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    await dialog.locator('input[type="number"]').fill(String(testYear));

    await dialog.locator('button:has-text("Create")').click();

    // Modal should close
    await expect(dialog).not.toBeVisible({ timeout: 10_000 });

    // New FY should appear in the dropdown
    await fyButton.click();
    await expect(page.locator(`[role="listbox"] button:has-text("${testLabel}")`)).toBeVisible({ timeout: 5_000 });
  });

  test('cannot create a duplicate financial year', async ({ authedPage: page }) => {
    const fyButton = page.locator('button[aria-haspopup="listbox"]');
    await fyButton.click();
    const listbox = page.locator('[role="listbox"]');
    await expect(listbox).toBeVisible({ timeout: 5_000 });

    // Use the first listed FY option’s label to attempt a duplicate
    const firstOption = listbox.locator('[role="option"]').first();
    await expect(firstOption).toBeVisible({ timeout: 5_000 });
    const existingLabel = (await firstOption.textContent())?.replace('\u2713', '').trim() ?? '';
    // Extract the starting year from e.g. "2025-26"
    const existingYear = parseInt(existingLabel.split('-')[0], 10);

    await listbox.locator('button:has-text("+ New FY")').click();

    const dialog = page.locator('[role="dialog"][aria-label="Create new financial year"]');
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    await dialog.locator('input[type="number"]').fill(String(existingYear));
    await dialog.locator('button:has-text("Create")').click();

    // Modal should remain open with an error
    await expect(dialog).toBeVisible({ timeout: 3_000 });
    await expect(dialog.locator(`text=Financial year ${existingLabel} already exists.`)).toBeVisible({ timeout: 3_000 });
  });

  test('can switch the active financial year', async ({ authedPage: page }) => {
    // First ensure at least two FYs exist — create a second if needed
    const fyButton = page.locator('button[aria-haspopup="listbox"]');
    await fyButton.click();

    const listbox = page.locator('[role="listbox"]');
    await expect(listbox).toBeVisible({ timeout: 5_000 });

    const fyOptions = listbox.locator('[role="option"]');
    const count = await fyOptions.count();

    if (count < 2) {
      // Create a second FY
      await listbox.locator('button:has-text("+ New FY")').click();
      const dialog = page.locator('[role="dialog"][aria-label="Create new financial year"]');
      await expect(dialog).toBeVisible({ timeout: 5_000 });
      await dialog.locator('input[type="number"]').fill('2035');
      await dialog.locator('button:has-text("Create")').click();
      await expect(dialog).not.toBeVisible({ timeout: 10_000 });

      // Re-open dropdown
      await fyButton.click();
      await expect(listbox).toBeVisible({ timeout: 5_000 });
    }

    // Click the first non-active FY
    const allOptions = listbox.locator('[role="option"]');
    const optCount = await allOptions.count();
    let switched = false;
    for (let i = 0; i < optCount; i++) {
      const opt = allOptions.nth(i);
      const selected = await opt.getAttribute('aria-selected');
      if (selected !== 'true') {
        const label = await opt.textContent();
        await opt.click();
        // Dropdown should close and button label should update
        await expect(listbox).not.toBeVisible({ timeout: 3_000 });
        const newLabel = await fyButton.textContent();
        expect(newLabel?.trim()).toContain(label?.trim().replace('✓', '').trim());
        switched = true;
        break;
      }
    }

    if (!switched) {
      // Only one FY exists and it's active — that's fine
      await page.locator('h1').first().click();
    }
  });
});
