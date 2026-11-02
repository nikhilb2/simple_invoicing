import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const profiles = [
  { locale: 'en-US', timezoneId: 'UTC', timestamp: '05-03-2026 14:07' },
  { locale: 'de-DE', timezoneId: 'America/Los_Angeles', timestamp: '05-03-2026 06:07' },
  { locale: 'hi-IN', timezoneId: 'Asia/Kolkata', timestamp: '05-03-2026 19:37' },
];

for (const profile of profiles) {
  test.describe(`${profile.locale} / ${profile.timezoneId}`, () => {
    test.use({ locale: profile.locale, timezoneId: profile.timezoneId });

    test.beforeEach(async ({ page }) => {
      // This suite renders the real frontend against synthetic API responses.
      // It does not use a real account or require a running backend.
      await page.addInitScript(() => localStorage.setItem('token', 'date-display-fixture'));
      await page.clock.setFixedTime(new Date('2026-03-05T12:00:00Z'));
      await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
        const url = new URL(route.request().url());
        const pathname = url.pathname.replace(/\/$/, '');
        const company = { id: 1, name: 'Date display fixture', currency_code: 'INR', is_active: true };
        const responses: Record<string, unknown> = {
          '/api/auth/me': { id: 1, email: 'dates@example.test', role: 'admin', active_company_id: 1 },
          '/api/company': company,
          '/api/company/companies': [company],
          '/api/company/companies/capability': { can_create_company: false },
          '/api/financial-years': [
            { id: 1, label: '2025-26', start_date: '2025-04-01', end_date: '2026-03-31', is_active: true },
          ],
          '/api/marketplace/connection': { status: 'disconnected' },
          '/api/ledgers/day-book': {
            from_date: '2026-03-01', to_date: '2026-03-05', total_debit: 100, total_credit: 0,
            financial_year_id: 1, fy_label: '2025-26',
            entries: [{
              entry_id: 1, entry_type: 'invoice', date: '2026-03-05', voucher_type: 'sales',
              reference_number: 'INV-1', ledger_name: 'Sample customer', particulars: 'Example sale',
              debit: 100, credit: 0,
            }],
          },
          '/api/email-logs': {
            page: 1, page_size: 20, total: 1, total_pages: 1,
            items: [{
              id: 1, company_id: 1, to_email: 'customer@example.test', cc: null,
              subject: 'Fixture invoice', email_type: 'invoice', reference_id: 1,
              status: 'sent', error_message: null, sent_by_user_id: 1,
              sent_at: '2026-03-05T14:07:42Z',
            }],
          },
        };
        if (pathname === '/api/ledgers/day-book/csv') {
          await route.fulfill({ contentType: 'text/csv', body: 'date\n2026-03-05\n' });
        } else if (pathname in responses) {
          await route.fulfill({ json: responses[pathname] });
        } else {
          await route.fulfill({ status: 404, json: { detail: 'No fixture for this endpoint' } });
        }
      });
    });

    test('uses DD-MM-YYYY in the register and keeps date inputs and exports ISO', async ({ page }, testInfo) => {
      await page.goto('/day-book');
      await expect(page.locator('.register__day').getByText('05-03-2026', { exact: true })).toBeVisible();
      await expect(page.locator('.register__row .register__date')).toHaveText('05-03-2026');

      await page.getByLabel('From', { exact: true }).fill('2026-03-01');
      await page.getByLabel('To', { exact: true }).fill('2026-03-05');
      await expect(page.getByLabel('From', { exact: true })).toHaveValue('2026-03-01');
      await expect(page.getByLabel('To', { exact: true })).toHaveValue('2026-03-05');

      const request = page.waitForRequest((r) => new URL(r.url()).pathname === '/api/ledgers/day-book/csv');
      const download = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Export CSV' }).click();
      const url = new URL((await request).url());
      expect(url.searchParams.get('from_date')).toBe('2026-03-01');
      expect(url.searchParams.get('to_date')).toBe('2026-03-05');
      const csv = await download;
      expect(csv.suggestedFilename()).toBe('day_book_2026-03-01_2026-03-05.csv');
      await csv.saveAs(testInfo.outputPath('day-book.csv'));
      expect(readFileSync(testInfo.outputPath('day-book.csv'), 'utf8')).toBe('date\n2026-03-05\n');
      const screenshot = testInfo.outputPath('day-book.png');
      await page.screenshot({ path: screenshot, fullPage: true });
      await testInfo.attach('Day book display', { path: screenshot, contentType: 'image/png' });
    });

    test('uses DD-MM-YYYY HH:mm for timestamps in local time', async ({ page }, testInfo) => {
      await page.goto('/day-book');
      await page.locator('.sidebar__link--settings').click();
      // Enter through the SPA once the admin-only link is available, so the
      // initial asynchronous role hydration cannot redirect a deep link.
      await page.locator('aside.settings-nav a[href="/settings/email-history"]').click();
      await expect(page.getByText('Fixture invoice', { exact: true })).toBeVisible();
      await expect(page.getByText(`${profile.timestamp} · Invoice`, { exact: true })).toBeVisible();
      const screenshot = testInfo.outputPath('email-history.png');
      await page.screenshot({ path: screenshot, fullPage: true });
      await testInfo.attach('Email history display', { path: screenshot, contentType: 'image/png' });
    });
  });
}
