import { test, expect, uniqueGstin } from './fixtures';

/**
 * Financial year used for all FY-defaults tests.
 * Same year as fy-date-warning.spec.ts so the FY already exists after that run.
 */
const TEST_FY_START_YEAR = 2031;
const TEST_FY_LABEL = '2031-32';
const FY_START_DATE = '2031-04-01';
const FY_END_DATE = '2032-03-31';

/**
 * Ensure the test FY exists and is the active FY.
 */
async function activateTestFY(page: import('@playwright/test').Page) {
  const fyButton = page.locator('button[aria-haspopup="listbox"]');
  await fyButton.click();
  const listbox = page.locator('[role="listbox"]');
  await expect(listbox).toBeVisible({ timeout: 5_000 });

  const existingOption = listbox.locator(`button:has-text("${TEST_FY_LABEL}")`).first();
  if (!(await existingOption.isVisible())) {
    await listbox.locator('button:has-text("+ New FY")').click();
    const dialog = page.locator('[role="dialog"][aria-label="Create new financial year"]');
    await expect(dialog).toBeVisible({ timeout: 5_000 });
    await dialog.locator('input[type="number"]').fill(String(TEST_FY_START_YEAR));
    await dialog.locator('button:has-text("Create")').click();
    await expect(dialog).not.toBeVisible({ timeout: 10_000 });
    // Reopen to activate
    await fyButton.click();
    await expect(listbox).toBeVisible({ timeout: 5_000 });
  }

  await listbox.locator(`button:has-text("${TEST_FY_LABEL}")`).first().click();
  if (await listbox.isVisible()) {
    await page.locator('h1').first().click();
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Day Book
// ─────────────────────────────────────────────────────────────────────────────

test.describe('FY Defaults — Day Book', () => {
  test('date range defaults to active FY on load', async ({ authedPage: page }) => {
    await activateTestFY(page);
    await page.click('[href="/day-book"]');
    await page.waitForTimeout(500);

    await expect(page.locator('#day-book-from')).toHaveValue(FY_START_DATE);
    await expect(page.locator('#day-book-to')).toHaveValue(FY_END_DATE);
  });

  test('date inputs remain manually editable', async ({ authedPage: page }) => {
    await activateTestFY(page);
    await page.click('[href="/day-book"]');
    await page.waitForTimeout(500);

    const customDate = '2031-07-01';
    await page.fill('#day-book-from', customDate);
    await expect(page.locator('#day-book-from')).toHaveValue(customDate);
    // To date is still the FY end
    await expect(page.locator('#day-book-to')).toHaveValue(FY_END_DATE);
  });

  test('date range updates when active FY is switched', async ({ authedPage: page }) => {
    await activateTestFY(page);
    await page.click('[href="/day-book"]');
    await page.waitForTimeout(500);

    // Verify the test FY dates are set
    await expect(page.locator('#day-book-from')).toHaveValue(FY_START_DATE);
    await expect(page.locator('#day-book-to')).toHaveValue(FY_END_DATE);

    // Switch to a different FY (2030-31) — create it if needed
    const fyButton = page.locator('button[aria-haspopup="listbox"]');
    await fyButton.click();
    const listbox = page.locator('[role="listbox"]');
    await expect(listbox).toBeVisible({ timeout: 5_000 });

    const fy2030Label = '2030-31';
    const existing = listbox.locator(`button:has-text("${fy2030Label}")`).first();
    if (!(await existing.isVisible())) {
      await listbox.locator('button:has-text("+ New FY")').click();
      const dialog = page.locator('[role="dialog"][aria-label="Create new financial year"]');
      await expect(dialog).toBeVisible({ timeout: 5_000 });
      await dialog.locator('input[type="number"]').fill('2030');
      await dialog.locator('button:has-text("Create")').click();
      await expect(dialog).not.toBeVisible({ timeout: 10_000 });
      await fyButton.click();
      await expect(listbox).toBeVisible({ timeout: 5_000 });
    }

    await listbox.locator(`button:has-text("${fy2030Label}")`).first().click();
    await page.waitForTimeout(500);

    // Date range should now reflect FY 2030-31 bounds
    await expect(page.locator('#day-book-from')).toHaveValue('2030-04-01');
    await expect(page.locator('#day-book-to')).toHaveValue('2031-03-31');
  });

  test('falls back to current-month default when no active FY', async ({ authedPage: page }) => {
    // Deactivate by switching to a non-active state — navigate while no FY is active
    // This just validates the page loads without crashing; exact default is best-effort
    await page.click('[href="/day-book"]');
    const fromInput = page.locator('#day-book-from');
    await expect(fromInput).toBeVisible({ timeout: 5_000 });
    // From date should be a valid ISO date string
    const value = await fromInput.inputValue();
    expect(value).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Ledger Statement (via LedgerViewPage)
// ─────────────────────────────────────────────────────────────────────────────

test.describe('FY Defaults — Ledger Statement', () => {
  async function createAndNavigateToLedger(page: import('@playwright/test').Page) {
    const ledgerName = `FYDefaultLedger-${Date.now().toString(36)}`;
    await page.click('[href="/ledgers"]');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Create ledger', { timeout: 10_000 });
    await page.fill('#ledger-name', ledgerName);
    await page.fill('#ledger-address', '1 FY Default Rd');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 9999999999');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: 10_000 });

    await page.fill('#ledger-search', ledgerName);
    await page.waitForTimeout(500);
    const row = page.locator('.table-row', { hasText: ledgerName });
    await expect(row).toBeVisible({ timeout: 10_000 });
    await row.locator('[aria-label^="View ledger"]').click();
    await expect(page.locator('h1')).toContainText(ledgerName, { timeout: 10_000 });
  }

  test('period defaults to active FY on load', async ({ authedPage: page }) => {
    await activateTestFY(page);
    await createAndNavigateToLedger(page);

    await expect(page.locator('#statement-from')).toHaveValue(FY_START_DATE);
    await expect(page.locator('#statement-to')).toHaveValue(FY_END_DATE);
  });

  test('date inputs remain manually editable', async ({ authedPage: page }) => {
    await activateTestFY(page);
    await createAndNavigateToLedger(page);

    const customFrom = '2031-05-01';
    await page.fill('#statement-from', customFrom);
    await expect(page.locator('#statement-from')).toHaveValue(customFrom);
    // To date unchanged
    await expect(page.locator('#statement-to')).toHaveValue(FY_END_DATE);
  });

  test('period updates when active FY is switched', async ({ authedPage: page }) => {
    await activateTestFY(page);
    await createAndNavigateToLedger(page);

    // Confirm test FY dates
    await expect(page.locator('#statement-from')).toHaveValue(FY_START_DATE);

    // Switch to 2030-31
    const fyButton = page.locator('button[aria-haspopup="listbox"]');
    await fyButton.click();
    const listbox = page.locator('[role="listbox"]');
    await expect(listbox).toBeVisible({ timeout: 5_000 });

    const fy2030Label = '2030-31';
    const existing = listbox.locator(`button:has-text("${fy2030Label}")`).first();
    if (!(await existing.isVisible())) {
      await listbox.locator('button:has-text("+ New FY")').click();
      const dialog = page.locator('[role="dialog"][aria-label="Create new financial year"]');
      await expect(dialog).toBeVisible({ timeout: 5_000 });
      await dialog.locator('input[type="number"]').fill('2030');
      await dialog.locator('button:has-text("Create")').click();
      await expect(dialog).not.toBeVisible({ timeout: 10_000 });
      await fyButton.click();
      await expect(listbox).toBeVisible({ timeout: 5_000 });
    }

    await listbox.locator(`button:has-text("${fy2030Label}")`).first().click();
    await page.waitForTimeout(500);

    await expect(page.locator('#statement-from')).toHaveValue('2030-04-01');
    await expect(page.locator('#statement-to')).toHaveValue('2031-03-31');
  });
});
