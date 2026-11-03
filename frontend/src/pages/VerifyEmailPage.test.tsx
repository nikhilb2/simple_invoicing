import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

const secret = vi.hoisted(() => ({ token: 'verification-test-token' as string | null }));
vi.mock('../lib/urlSecrets', () => ({ readUrlSecret: () => secret.token }));

import VerifyEmailPage from './VerifyEmailPage';

function render() {
  return renderToStaticMarkup(<MemoryRouter><VerifyEmailPage /></MemoryRouter>);
}

describe('VerifyEmailPage', () => {
  it('asks the mailbox owner for a name before confirming the account', () => {
    secret.token = 'verification-test-token';
    const html = render();
    expect(html).toContain('<label for="full-name">Your name</label>');
    const nameInput = html.match(/<input[^>]*id="full-name"[^>]*>/)?.[0];
    expect(nameInput).toBeDefined();
    expect(nameInput).toContain('required=""');
    expect(nameInput).toContain('autoComplete="name"');
    expect(nameInput).toContain('maxLength="120"');
    expect(nameInput).toContain('value=""');
  });

  it('keeps a missing-token link on the resend screen', () => {
    secret.token = null;
    const html = render();
    expect(html).toContain('This verification link is missing its token.');
    expect(html).toContain('Resend verification email');
    expect(html).not.toContain('id="full-name"');
  });
});
