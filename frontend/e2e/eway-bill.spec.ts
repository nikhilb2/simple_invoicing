import { test, expect } from './fixtures';

// Needs the demo seed (make seed-demo): it opens the newest invoice in the feed,
// which the seed makes an active sales invoice with an interstate buyer.
test.describe('E-Way Bill form', () => {
  test.beforeEach(async ({ authedPage: page }) => {
    await page.goto('/invoices-view');
    await page.getByTitle('Preview').first().click();
    const preview = page.locator('.modal-panel--invoice-preview');
    await expect(preview).toBeVisible({ timeout: 10_000 });
    await preview.getByLabel('More actions').click();
    await page.getByRole('menuitem', { name: /e-way bill/i }).click();
    await expect(page.locator('[aria-labelledby="eway-bill-title"]')).toBeVisible({ timeout: 10_000 });
  });

  test('says what is wrong with bad details, against each field', async ({ authedPage: page }) => {
    const modal = page.locator('[aria-labelledby="eway-bill-title"]');
    await modal.locator('[name=seller_gstin]').fill('NOT-A-GSTIN');
    await modal.locator('[name=buyer_pincode]').fill('');
    await modal.locator('[name=vehicle_number]').fill('XX');
    await modal.getByRole('button', { name: 'Generate JSON' }).click();

    await expect(modal.locator('#eway-seller_gstin-note')).toContainText('Seller GSTIN format is invalid');
    await expect(modal.locator('#eway-buyer_pincode-note')).toHaveText('Buyer PIN code is required.');
    await expect(modal.locator('#eway-vehicle_number-note')).toContainText('Vehicle number format is invalid');
    await expect(modal).not.toContainText('status code');
  });

  test("explains FastAPI's own validation errors too", async ({ authedPage: page }) => {
    const modal = page.locator('[aria-labelledby="eway-bill-title"]');
    await modal.locator('[name=distance_km]').fill('1.5');
    await modal.getByRole('button', { name: 'Generate JSON' }).click();

    await expect(modal.locator('#eway-distance_km-note')).toHaveText('Distance km must be a whole number.');
    await expect(modal).not.toContainText('status code');
  });
});
