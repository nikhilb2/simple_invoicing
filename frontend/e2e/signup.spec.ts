import { test, expect } from '@playwright/test';

/**
 * Register -> verify -> login, against a backend in shared_hosting mode with
 * platform SMTP pointed at Mailpit. Skipped unless E2E_SIGNUP=1, because it
 * needs that backend (and the Mailpit API at E2E_MAILPIT_URL).
 */
const env = (globalThis as any).process?.env ?? {};
const MAILPIT = env.E2E_MAILPIT_URL || 'http://localhost:8025';

test.describe('Public signup', () => {
  test.skip(env.E2E_SIGNUP !== '1', 'set E2E_SIGNUP=1 with a shared_hosting backend and Mailpit');

  test('registers, verifies by email link, then signs in to company setup', async ({ page, request }) => {
    const email = `signup-${Date.now()}@example.com`;
    const password = 'Sup3rSecret!';

    await page.goto('/login');
    await page.getByRole('link', { name: 'Create account' }).click();
    await expect(page).toHaveURL(/\/register/);

    await page.fill('#full-name', 'Signup Tester');
    await page.fill('#email', email);
    await page.fill('#password', password);
    await page.click('button:has-text("Create account")');
    await expect(page.getByText('Check your email')).toBeVisible();

    // Pull the verification link out of the caught message.
    let link = '';
    await expect
      .poll(async () => {
        const list = await (await request.get(`${MAILPIT}/api/v1/search?query=to:${encodeURIComponent(email)}`)).json();
        const id = list.messages?.[0]?.ID;
        if (!id) return '';
        const msg = await (await request.get(`${MAILPIT}/api/v1/message/${id}`)).json();
        link = (msg.Text as string).match(/https?:\/\/\S*verify-email\?token=[^\s)>"]+/)?.[0] ?? '';
        return link;
      }, { timeout: 15_000 })
      .not.toBe('');

    // Follow the link on this app's origin regardless of the host in the mail.
    const { search } = new URL(link);
    await page.goto(`/verify-email${search}`);
    await expect(page.getByText('Email verified')).toBeVisible();

    await page.getByRole('link', { name: 'Continue to sign in' }).click();
    await page.fill('#email', email);
    await page.fill('#password', password);
    await page.click('button:has-text("Open dashboard")');

    // A brand-new account has no company, so it lands on setup.
    await expect(page).toHaveURL(/\/settings\/company\?setup=required/);
  });
});
