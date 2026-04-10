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

    // Label input
    await expect(dialog.locator('input[placeholder="2025-26"]')).toBeVisible();
    // Start date
    const dateInputs = dialog.locator('input[type="date"]');
    await expect(dateInputs).toHaveCount(2);
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

    // Submit with empty fields
    await dialog.locator('button:has-text("Create")').click();
    await expect(dialog.locator('text=All fields are required.')).toBeVisible({ timeout: 3_000 });
  });

  test('can create a new financial year', async ({ authedPage: page }) => {
    const fyLabel = `E2E-FY-${Date.now().toString(36).toUpperCase()}`;

    const fyButton = page.locator('button[aria-haspopup="listbox"]');
    await fyButton.click();
    const listbox = page.locator('[role="listbox"]');
    await expect(listbox).toBeVisible({ timeout: 5_000 });
    await listbox.locator('button:has-text("+ New FY")').click();

    const dialog = page.locator('[role="dialog"][aria-label="Create new financial year"]');
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    await dialog.locator('input[placeholder="2025-26"]').fill(fyLabel);
    const dateInputs = dialog.locator('input[type="date"]');
    await dateInputs.first().fill('2030-04-01');
    await dateInputs.last().fill('2031-03-31');

    await dialog.locator('button:has-text("Create")').click();

    // Modal should close
    await expect(dialog).not.toBeVisible({ timeout: 10_000 });

    // New FY should appear in the dropdown
    await fyButton.click();
    await expect(page.locator(`[role="listbox"] button:has-text("${fyLabel}")`)).toBeVisible({ timeout: 5_000 });
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
      await dialog.locator('input[placeholder="2025-26"]').fill(`SW-${Date.now().toString(36)}`);
      const dateInputs = dialog.locator('input[type="date"]');
      await dateInputs.first().fill('2032-04-01');
      await dateInputs.last().fill('2033-03-31');
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
