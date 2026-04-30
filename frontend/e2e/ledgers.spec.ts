import { test, expect, expectSuccess, expectError, uniqueGstin } from './fixtures';

test.describe('Ledgers CRUD', () => {
  const uniqueName = () => `Ledger-${Date.now().toString(36)}`;

  test('displays ledger master heading', async ({ authedPage: page }) => {
    await page.click('[href="/ledgers"]');
    await expect(page.locator('h1')).toContainText('Ledger master');
  });

  test('creates a new ledger via create page', async ({ authedPage: page }) => {
    await page.click('[href="/ledgers"]');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Create ledger');

    const name = uniqueName();
    await page.fill('#ledger-name', name);
    await page.fill('#ledger-address', '123 Test Street, Mumbai');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 9876543210');
    await page.fill('#ledger-email', 'test@example.com');
    await page.click('button:has-text("Create ledger")');

    // Should redirect back to list with success message
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expectSuccess(page, 'Ledger created');
    await page.fill('#ledger-search', name);
    await page.waitForTimeout(500);
    await expect(page.locator('.table-row', { hasText: name })).toBeVisible();
  });

  test('creates ledger with bank details', async ({ authedPage: page }) => {
    await page.click('[href="/ledgers"]');
    await page.click('button:has-text("Create ledger")');

    const name = uniqueName();
    await page.fill('#ledger-name', name);
    await page.fill('#ledger-address', '456 Bank Lane, Delhi');
    await page.fill('#ledger-gst', uniqueGstin('07'));
    await page.fill('#ledger-phone', '+91 8765432109');
    await page.fill('#ledger-bank-name', 'HDFC Bank');
    await page.fill('#ledger-branch-name', 'Bandra West');
    await page.fill('#ledger-account-name', 'Test Corp');
    await page.fill('#ledger-account-number', '123456789012');
    await page.fill('#ledger-ifsc', 'HDFC0001234');
    await page.click('button:has-text("Create ledger")');

    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expectSuccess(page, 'Ledger created');
    await page.fill('#ledger-search', name);
    await page.waitForTimeout(500);
    await expect(page.locator('.table-row', { hasText: name })).toBeVisible();
  });

  test('creates and edits ledger opening balance', async ({ authedPage: page }) => {
    await page.click('[href="/ledgers"]');
    await page.click('button:has-text("Create ledger")');

    const name = uniqueName();
    await page.fill('#ledger-name', name);
    await page.fill('#ledger-address', 'Opening Balance Street');
    await page.fill('#ledger-gst', uniqueGstin('29'));
    await page.fill('#ledger-phone', '+91 7654321098');
    await page.fill('#ledger-opening-balance', '250');
    await page.click('button:has-text("Create ledger")');

    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expectSuccess(page, 'Ledger created');

    await page.fill('#ledger-search', name);
    await page.waitForTimeout(500);
    const row = page.locator('.table-row', { hasText: name });
    await expect(row).toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await row.locator('[aria-label^="Edit ledger"]').click();

    await expect(page.locator('h1')).toContainText('Edit ledger', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expect(page.locator('#ledger-opening-balance')).toHaveValue('250');
    await page.fill('#ledger-opening-balance', '-125');
    await page.click('button:has-text("Update ledger")');

    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expectSuccess(page, 'Ledger updated');

    await page.fill('#ledger-search', name);
    await page.waitForTimeout(500);
    const updatedRow = page.locator('.table-row', { hasText: name });
    await expect(updatedRow).toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await updatedRow.locator('[aria-label^="View ledger"]').click();

    await expect(page.locator('h1')).toContainText(name, { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expect(page.locator('.invoice-row', { hasText: 'Opening Balance' }).first()).toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await page.click('button:has-text("Edit Ledger")');
    await expect(page.locator('h1')).toContainText('Edit ledger', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expect(page.locator('#ledger-opening-balance')).toHaveValue('-125');
  });

  test('edits an existing ledger via edit page', async ({ authedPage: page }) => {
    await page.click('[href="/ledgers"]');
    await page.click('button:has-text("Create ledger")');
    const name = uniqueName();

    // Create
    await page.fill('#ledger-name', name);
    await page.fill('#ledger-address', 'Edit Street');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 1111111111');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expectSuccess(page, 'Ledger created');

    // Search and click Edit
    await page.fill('#ledger-search', name);
    await page.waitForTimeout(500);
    const row = page.locator('.table-row', { hasText: name });
    await expect(row).toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await row.locator('[aria-label^="Edit ledger"]').click();
    await expect(page.locator('h1')).toContainText('Edit ledger', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

    // Update the name
    const updatedName = `${name}-Updated`;
    await page.fill('#ledger-name', updatedName);
    await page.click('button:has-text("Update ledger")');

    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expectSuccess(page, 'Ledger updated');
    await page.fill('#ledger-search', updatedName);
    await page.waitForTimeout(500);
    await expect(page.locator('.table-row', { hasText: updatedName })).toBeVisible();
  });

  test('deletes a ledger', async ({ authedPage: page }) => {
    await page.click('[href="/ledgers"]');
    await page.click('button:has-text("Create ledger")');
    const name = uniqueName();

    // Create
    await page.fill('#ledger-name', name);
    await page.fill('#ledger-address', 'Delete Street');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 2222222222');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expectSuccess(page, 'Ledger created');

    // Search, then delete — click Delete row button, then confirm in the custom dialog
    await page.fill('#ledger-search', name);
    await page.waitForTimeout(500);
    const row = page.locator('.table-row', { hasText: name });
    await expect(row).toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await row.locator('[aria-label^="Delete ledger"]').click();
    await page.locator('.modal-overlay button:has-text("Delete")').click();
    await expect(page.locator('.toast--success')).toContainText('Ledger deleted', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expect(page.locator('.table-row', { hasText: name })).not.toBeVisible();
  });

  test('views a ledger and sees statement page', async ({ authedPage: page }) => {
    await page.click('[href="/ledgers"]');
    await page.click('button:has-text("Create ledger")');
    const name = uniqueName();

    // Create
    await page.fill('#ledger-name', name);
    await page.fill('#ledger-address', 'View Street');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 7777777777');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expectSuccess(page, 'Ledger created');

    // Search and click View
    await page.fill('#ledger-search', name);
    await page.waitForTimeout(500);
    const row = page.locator('.table-row', { hasText: name });
    await expect(row).toBeVisible({ timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await row.locator('[aria-label^="View ledger"]').click();

    // Should navigate to ledger view page
    await expect(page.locator('h1')).toContainText(name, { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expect(page.locator('#statement-from')).toBeVisible();
    await expect(page.locator('#statement-to')).toBeVisible();

    // Back to ledgers
    await page.click('[aria-label="Back to ledgers"]');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
  });

  test('cancel on create page returns to list', async ({ authedPage: page }) => {
    await page.click('[href="/ledgers"]');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Create ledger', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });

    await page.click('button:has-text("Cancel")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
  });

  test('searches ledgers by name', async ({ authedPage: page }) => {
    // Create two ledgers with distinct names
    const nameA = `SearchAlpha-${Date.now().toString(36)}`;
    const nameB = `SearchBeta-${Date.now().toString(36)}`;

    await page.click('[href="/ledgers"]');

    // Create first ledger
    await page.click('button:has-text("Create ledger")');
    await page.fill('#ledger-name', nameA);
    await page.fill('#ledger-address', 'Alpha Street');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 1010101010');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expectSuccess(page, 'Ledger created');

    // Create second ledger
    await page.click('button:has-text("Create ledger")');
    await page.fill('#ledger-name', nameB);
    await page.fill('#ledger-address', 'Beta Street');
    await page.fill('#ledger-gst', uniqueGstin());
    await page.fill('#ledger-phone', '+91 2020202020');
    await page.click('button:has-text("Create ledger")');
    await expect(page.locator('h1')).toContainText('Ledger master', { timeout: Number((globalThis as any).process?.env?.E2E_EXPECT_TIMEOUT_MS || '5000') });
    await expectSuccess(page, 'Ledger created');

    // Search for Alpha — should be visible
    await page.fill('#ledger-search', nameA);
    await page.waitForTimeout(500);
    await expect(page.locator('.table-row', { hasText: nameA })).toBeVisible();
    await expect(page.locator('.table-row', { hasText: nameB })).not.toBeVisible();

    // Search for Beta — should be visible
    await page.fill('#ledger-search', nameB);
    await page.waitForTimeout(500);
    await expect(page.locator('.table-row', { hasText: nameB })).toBeVisible();
    await expect(page.locator('.table-row', { hasText: nameA })).not.toBeVisible();
  });

  test('shows search-no-results message when search finds nothing', async ({ authedPage: page }) => {
    await page.click('[href="/ledgers"]');
    await page.fill('#ledger-search', 'ZZZZNONEXISTENT999');
    await page.waitForTimeout(500);

    await expect(page.locator('.empty-state')).toContainText('No ledgers match your search.');
    // CTA for truly-empty state must not appear during a search
    await expect(page.locator('button:has-text("Create First Ledger")')).not.toBeVisible();
  });

  test('shows friendly empty state with CTA that navigates to create form', async ({ authedPage: page }) => {
    // Mock the ledgers list to return empty so we can verify the empty-state UI
    await page.route(/\/api\/ledgers\//, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0, total_pages: 0, page: 1 }),
      })
    );

    await page.goto('/ledgers');

    const emptyState = page.locator('.empty-state');
    await expect(emptyState).toContainText('No ledgers registered yet');
    await expect(emptyState).toContainText('first ledger');

    const ctaButton = page.locator('button:has-text("Create First Ledger")');
    await expect(ctaButton).toBeVisible();
    // CTA should navigate to the ledger create form
    await page.unroute(/\/api\/ledgers\//); // unblock navigation target
    await ctaButton.click();
    await expect(page).toHaveURL('/ledgers/new', { timeout: 5_000 });
  });
});
