import { test, expect, clickNavLink } from './fixtures';

/**
 * The GSTR-3B worksheet, against whatever books the test database holds.
 *
 * Assertions are about what the page must always do, not about particular
 * figures: say what it is, show a source on rows, follow the period, refuse a
 * period that is not a return period, and download what it shows.
 */
const JUNE = { from: '2026-06-01', to: '2026-06-30' };
const QUARTER = { from: '2026-04-01', to: '2026-06-30' };

async function setPeriod(page: import('@playwright/test').Page, from: string, to: string) {
  await page.fill('#gstr3b-from', from);
  await page.fill('#gstr3b-to', to);
}

test.describe('GSTR-3B worksheet', () => {
  test.beforeEach(async ({ authedPage }) => {
    await clickNavLink(authedPage, '/gstr3b');
    await expect(authedPage).toHaveURL(/\/gstr3b$/);
  });

  test('says it is an estimate and not a filing', async ({ authedPage: page }) => {
    await expect(page.getByRole('heading', { name: 'GSTR-3B worksheet', level: 1 })).toBeVisible();
    const notice = page.getByRole('note');
    await expect(notice).toContainText('Worksheet, not a return.');
    await expect(notice).toContainText('estimate from your own books');
    await expect(notice).toContainText('not a filing');
    await expect(notice).toContainText('take precedence');
  });

  test('lays out warnings and tables with a source on the rows', async ({ authedPage: page }) => {
    await setPeriod(page, JUNE.from, JUNE.to);
    await expect(page.getByTestId('gstr3b-period')).toContainText('June 2026');

    await expect(page.getByRole('heading', { name: 'Why this may not match the portal' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Known limits' })).toBeVisible();

    const taxed = page.locator('tr[data-row="3.1a"]');
    await expect(taxed).toContainText('From books');

    const untracked = page.locator('tr[data-row="3.1b"]');
    await expect(untracked.locator('.worksheet-source')).toHaveText('Not tracked');
    await expect(page.locator('tr[data-row="3.2-unregistered"] .worksheet-source')).toHaveText('Not tracked');

    await expect(page.locator('[data-section="3.2"]')).toContainText('place of supply');
    await expect(page.locator('[data-section="5"]')).toContainText('5.1');
    await expect(page.locator('[data-section="5"]')).toContainText('portal');
    await expect(page.locator('[data-section="6.1"]')).toContainText('Payable in cash');

    // No JSON export, here or anywhere on the page.
    await expect(page.getByRole('button', { name: /JSON/ })).toHaveCount(0);
  });

  test('follows the period and never shows the old one', async ({ authedPage: page }) => {
    await setPeriod(page, JUNE.from, JUNE.to);
    await expect(page.getByTestId('gstr3b-period')).toContainText('June 2026');
    await expect(page.getByTestId('gstr3b-period')).toContainText('monthly');

    await setPeriod(page, QUARTER.from, QUARTER.to);
    await expect(page.getByTestId('gstr3b-period')).toContainText('Apr-Jun 2026');
    await expect(page.getByTestId('gstr3b-period')).toContainText('quarterly');
  });

  test('refuses a period that is not a month or a quarter without asking the server', async ({ authedPage: page }) => {
    await setPeriod(page, JUNE.from, JUNE.to);
    await expect(page.getByTestId('gstr3b-period')).toBeVisible();

    const requests: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/gstr3b/worksheet')) requests.push(request.url());
    });

    await page.fill('#gstr3b-to', '2026-06-20');
    await expect(page.getByRole('alert').filter({ hasText: 'one calendar month or one quarter' })).toBeVisible();
    await expect(page.getByTestId('gstr3b-period')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Export CSV' })).toBeDisabled();
    expect(requests).toEqual([]);
  });

  test('the period presets land on whole periods', async ({ authedPage: page }) => {
    await page.getByRole('button', { name: 'Last quarter' }).click();
    await expect(page.getByTestId('gstr3b-period')).toContainText('quarterly');
    await page.getByRole('button', { name: 'Last month', exact: true }).click();
    await expect(page.getByTestId('gstr3b-period')).toContainText('monthly');
  });

  test('downloads the CSV and PDF for the period on screen', async ({ authedPage: page }) => {
    await setPeriod(page, JUNE.from, JUNE.to);
    await expect(page.getByTestId('gstr3b-period')).toContainText('June 2026');

    const [csv] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: 'Export CSV' }).click(),
    ]);
    expect(csv.suggestedFilename()).toBe('gstr3b_worksheet_2026-06-01_2026-06-30.csv');

    const [pdf] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: 'Export PDF' }).click(),
    ]);
    expect(pdf.suggestedFilename()).toBe('gstr3b_worksheet_2026-06-01_2026-06-30.pdf');
  });
});
