import { test, expect, type Page } from '@playwright/test';
import { selectComboboxOption } from './fixtures';

/**
 * The first-invoice walkthrough, start to finish, as a new owner meets it. Skipped
 * unless E2E_TOUR=1, because it needs a database with no company or invoices yet:
 * the answer it records stays on the account. Set E2E_TOUR_PHONE=1 to run it at
 * phone width, against another empty database.
 */
const env = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env ?? {};
const EMAIL = env.E2E_ADMIN_EMAIL || 'admin@simple.dev';
const PASSWORD = env.E2E_ADMIN_PASSWORD || 'Admin@123';
const SHOTS = env.E2E_TOUR_SHOTS;

async function shot(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
}

function coach(page: Page) {
  return page.getByTestId('tour-coach');
}

/**
 * The ring has to sit on the element the card is talking about, and have stopped
 * there: the page may still be scrolling the target into view.
 */
async function expectRingOn(page: Page, selector: string) {
  const target = page.locator(selector).first();
  await expect(target).toBeVisible();
  let lastY: number | null = null;
  await expect
    .poll(async () => {
      const ring = await page.getByTestId('tour-ring').boundingBox();
      const box = await target.boundingBox();
      if (!ring || !box) return false;
      const settled = lastY === box.y;
      lastY = box.y;
      return settled && Math.abs(ring.x + 4 - box.x) < 2 && Math.abs(ring.y + 4 - box.y) < 2 && Math.abs(ring.width - 8 - box.width) < 2;
    })
    .toBe(true);
}

async function savedStatus(page: Page) {
  return page.evaluate(async () => {
    const res = await fetch('/api/auth/me', { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } });
    return (await res.json()).first_invoice_tour_status;
  });
}

test.describe.serial('First invoice walkthrough', () => {
  test.skip(env.E2E_TOUR !== '1', 'set E2E_TOUR=1 against an empty database');
  if (env.E2E_TOUR_PHONE === '1') test.use({ viewport: { width: 390, height: 844 } });

  let page: Page;

  test.beforeAll(async ({ browser }) => {
    page = await (await browser.newContext(
      env.E2E_TOUR_PHONE === '1' ? { viewport: { width: 390, height: 844 } } : { viewport: { width: 1280, height: 800 } },
    )).newPage();
  });

  test('company settings stay free of the offer while a GST-registered owner fills them in', async () => {
    await page.goto('/login');
    await page.fill('#email', EMAIL);
    await page.fill('#password', PASSWORD);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 15_000 });

    await page.goto('/settings/company');
    await expect(page.locator('#company-name')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('tour-offer')).toHaveCount(0);
    await page.fill('#company-name', 'Rao Traders');
    await page.fill('#company-address', '1 MG Road, Pune');
    await page.fill('#company-gst', '27ABCDE1234F1Z0');
    await page.getByRole('button', { name: /save company details/i }).click();
    await expect(page.getByText(/saved|updated/i).first()).toBeVisible({ timeout: 10_000 });
    await page.goto('/');
  });

  test('the dashboard offers it, and skipping is remembered', async () => {
    const offer = page.getByTestId('tour-offer');
    await expect(offer).toBeVisible({ timeout: 10_000 });
    await shot(page, '01-offer');
    expect(await savedStatus(page)).toBeNull();

    await offer.getByRole('button', { name: 'Skip for now' }).click();
    await expect(offer).toHaveCount(0);
    await expect.poll(() => savedStatus(page)).toBe('skipped');

    await page.reload();
    await expect(page.locator('.get-started')).toBeVisible({ timeout: 10_000 });
    await expect(offer).toHaveCount(0);
  });

  test('it can be started again from the checklist, and left again', async () => {
    await page.getByRole('button', { name: 'Walk me through it' }).click();
    await expect(page).toHaveURL(/\/invoices$/);
    await expect(coach(page)).toContainText('Add your customer');

    await coach(page).getByRole('button', { name: 'Exit walkthrough' }).click();
    await expect(coach(page)).toHaveCount(0);
    expect(await savedStatus(page)).toBe('skipped');
  });

  test('it guides a customer through the real form', async () => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Walk me through it' }).click();
    await expect(coach(page)).toContainText('Step 1 of 4');
    await expectRingOn(page, '[data-tour="add-customer"]');
    await shot(page, '02-add-customer');

    await page.locator('[data-tour="add-customer"]').click();
    await expect(coach(page)).toContainText('Customer name');
    await expectRingOn(page, '#modal-ledger-name');
    await shot(page, '03-customer-name');

    // Stays put while typing, moves on when the field is left.
    await page.locator('#modal-ledger-name').fill('Asha Stores');
    await expect(coach(page)).toContainText('Customer name');
    await page.locator('#modal-ledger-phone').focus();
    await expect(coach(page)).toContainText('Phone number');
    await page.locator('#modal-ledger-phone').fill('9876543210');
    await page.locator('#modal-ledger-address').focus();
    await expect(coach(page)).toContainText('Address');
    await page.locator('#modal-ledger-address').fill('2 Station Road, Pune');
    await page.locator('#modal-ledger-address').blur();
    await expect(coach(page)).toContainText('Save the customer');
    await expectRingOn(page, '[data-tour="save-customer"]');
    await shot(page, '04-save-customer');

    await page.locator('[data-tour="save-customer"]').click();
    await expect(coach(page)).toContainText('Step 2 of 4');
    await expectRingOn(page, '[data-tour="add-product"]');
  });

  test('a reload picks up where it stopped', async () => {
    await page.reload();
    await expect(coach(page)).toContainText('Add what you sold', { timeout: 10_000 });
  });

  test('it guides a product through the real form', async () => {
    await page.locator('[data-tour="add-product"]').click();
    await expect(coach(page)).toContainText('Product name');
    await page.locator('#modal-product-name').fill('Canvas Bag');
    await page.locator('#modal-product-sku').focus();
    await expect(coach(page)).toContainText('SKU');
    await page.locator('#modal-product-sku').fill('BAG-01');
    await page.locator('#modal-product-price').focus();
    await page.locator('#modal-product-price').fill('1200');
    await page.locator('#modal-product-gst-rate').selectOption({ index: 1 });
    await page.locator('#modal-product-opening-stock').focus();
    await expect(coach(page)).toContainText('Opening stock');
    await expectRingOn(page, '#modal-product-opening-stock');
    await shot(page, '05-opening-stock');

    // Left at zero on purpose: the first invoice then runs out of stock.
    await page.locator('#modal-product-opening-stock').fill('0');
    await page.locator('#modal-product-opening-stock').blur();
    await expect(coach(page)).toContainText('Opening stock');
    await page.locator('[data-tour="save-product"]').click();
    await expect(coach(page)).toContainText('Step 3 of 4');
  });

  test('leaving the page offers the way back', async () => {
    await page.goto('/');
    await expect(coach(page)).toContainText('Your invoice is waiting', { timeout: 10_000 });
    await shot(page, '06-away');
    await coach(page).getByRole('button', { name: 'Back to the invoice' }).click();
    await expect(page).toHaveURL(/\/invoices$/);
    await expect(coach(page)).toContainText('Step 3 of 4');
  });

  test('it guides the invoice, a stock shortage, and saves completed', async () => {
    const ledger = await page.locator('#invoice-ledger').inputValue();
    if (!ledger) {
      await expect(coach(page)).toContainText('Choose the customer');
      await expectRingOn(page, '#invoice-ledger');
      await selectComboboxOption(page, 'invoice-ledger', 'Asha');
    }
    await expect(coach(page)).toContainText('Choose what you sold');
    await expectRingOn(page, 'input[id^="invoice-product-"]');
    await shot(page, '07-pick-product');
    const productInput = await page.locator('input[id^="invoice-product-"]').first().getAttribute('id');
    await selectComboboxOption(page, productInput as string, 'Canvas');

    await expect(coach(page)).toContainText('Step 4 of 4');
    await expectRingOn(page, '[data-tour="create-invoice"]');
    await shot(page, '08-create');
    await page.locator('[data-tour="create-invoice"]').click();

    await expect(coach(page)).toContainText('Add the missing stock');
    await expectRingOn(page, '[data-tour="add-stock"]');
    await shot(page, '09-shortage');
    expect(await savedStatus(page)).toBe('skipped');

    await page.locator('[data-tour="add-stock"]').click();
    await expect(coach(page)).toContainText('Save the stock');
    await page.locator('[data-tour="save-stock"]').click();
    await expect(coach(page)).toContainText('Create your invoice');
    await page.locator('[data-tour="create-invoice"]').click();

    await expect(coach(page)).toContainText('Your first invoice is ready', { timeout: 10_000 });
    await shot(page, '10-done');
    await expect.poll(() => savedStatus(page)).toBe('completed');

    await coach(page).getByRole('button', { name: 'Finish' }).click();
    await expect(coach(page)).toHaveCount(0);
  });

  test('it never comes back', async () => {
    await page.goto('/');
    await expect(page.locator('.stats-grid')).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(800);
    await expect(page.getByTestId('tour-offer')).toHaveCount(0);
    await expect(coach(page)).toHaveCount(0);
    expect(await savedStatus(page)).toBe('completed');
  });
});
