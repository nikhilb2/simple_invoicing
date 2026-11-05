import { test, expect, type APIRequestContext, type Page } from '@playwright/test';

/**
 * Register -> verify -> signed in, against a backend in shared_hosting mode with
 * platform SMTP pointed at Mailpit. Skipped unless E2E_SIGNUP=1, because it
 * needs that backend (and the Mailpit API at E2E_MAILPIT_URL).
 */
const env = (globalThis as any).process?.env ?? {};
const MAILPIT = env.E2E_MAILPIT_URL || 'http://localhost:8025';

test.describe('Public signup', () => {
  test.skip(env.E2E_SIGNUP !== '1', 'set E2E_SIGNUP=1 with a shared_hosting backend and Mailpit');

  // Lives here because /register has no form unless this backend allows sign-up.
  test.describe('on a phone', () => {
    test.use({ viewport: { width: 390, height: 844 } });

    test('puts the sign-up form before the benefits', async ({ page }) => {
      await page.goto('/register');
      const firstInput = page.locator('.login-card input').first();
      await expect(firstInput).toBeVisible();
      const position = await firstInput.evaluate((el) => el.getBoundingClientRect().top + window.scrollY);
      expect(position).toBeLessThan(400);
    });
  });

  /** Registers an address in this browser and returns the verify-email path from the mail it was sent. */
  async function registerAndReadLink(page: Page, request: APIRequestContext, email: string) {
    await page.goto('/login');
    await page.getByRole('link', { name: 'Create account' }).click();
    await expect(page).toHaveURL(/\/register/);

    await page.fill('#full-name', 'Signup Tester');
    await page.fill('#email', email);
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
    return `/verify-email${new URL(link).search}`;
  }

  test('registers, verifies by email link, and is signed in to company setup', async ({ page, request }) => {
    const email = `signup-${Date.now()}@example.com`;
    const password = 'Sup3rSecret!';

    const verifyPath = await registerAndReadLink(page, request, email);
    await expect(page.getByRole('link', { name: 'reset your password' })).toBeVisible();

    await page.goto(verifyPath);
    await expect(page).not.toHaveURL(/token=/);
    // The name given at registration is offered, and stays the owner's to change.
    await expect(page.locator('#full-name')).toHaveValue('Signup Tester');

    // A refresh loses the link from memory and says what to do; the link still works.
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Open the link from your email' })).toBeVisible();
    await page.goto(verifyPath);
    await expect(page.locator('#full-name')).toHaveValue('Signup Tester');

    await page.fill('#password', 'password123');
    await page.click('button:has-text("Confirm email and set password")');
    await expect(page.getByText('too common')).toBeVisible();

    await page.fill('#password', password);
    await page.click('button:has-text("Confirm email and set password")');

    // A brand-new account has no company, so it lands on setup.
    await expect(page).toHaveURL(/\/settings\/company\?setup=required/);

    // The creator is an admin of the new company straight away, with no reload.
    await page.click('button:has-text("Start setup")');
    await page.fill('#company-name', 'Signup Tester Co');
    await page.fill('#company-address', '1 Test Road');
    await page.click('button:has-text("Save company details")');
    await expect(page.locator('.sidebar__user-role')).toHaveText('Admin');

    // A one-time link still works in a browser that holds a session.
    await page.goto('/reset-password?token=not-a-real-token');
    await expect(page).toHaveURL(/\/reset-password/);
  });

  test('a link opened in another browser verifies but asks for a sign-in', async ({ page, request, browser }) => {
    const email = `signup-other-${Date.now()}@example.com`;
    const password = 'Sup3rSecret!';
    const verifyPath = await registerAndReadLink(page, request, email);

    const other = await browser.newContext({ baseURL: new URL(page.url()).origin });
    const otherPage = await other.newPage();
    await otherPage.goto(verifyPath);
    await expect(otherPage.locator('#full-name')).toHaveValue('Signup Tester');
    await otherPage.fill('#password', password);
    await otherPage.click('button:has-text("Confirm email and set password")');
    await expect(otherPage.getByText('Email verified')).toBeVisible();

    await otherPage.getByRole('link', { name: 'Continue to sign in' }).click();
    await otherPage.fill('#email', email);
    await otherPage.fill('#password', password);
    await otherPage.getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(otherPage).toHaveURL(/\/settings\/company\?setup=required/);
    await other.close();
  });
});
