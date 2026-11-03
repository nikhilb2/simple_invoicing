import { describe, expect, it } from 'vitest';
import { callbackNextPath, loginErrorMessage, oauthLoginUrl } from './authFlow';

describe('callbackNextPath', () => {
  const next = (value: string | null) =>
    callbackNextPath(new URLSearchParams(value === null ? {} : { next: value }));

  it('keeps a relative path with a single leading slash', () => {
    expect(next('/invoices?x=1')).toBe('/invoices?x=1');
  });

  it.each([
    ['https://evil.example', 'absolute URL'],
    ['//evil.example', 'protocol-relative'],
    ['/\\evil.example', 'backslash'],
    ['invoices', 'no leading slash'],
    ['javascript:alert(1)', 'script scheme'],
    ['', 'empty'],
  ])('falls back to / for %s (%s)', (value) => {
    expect(next(value)).toBe('/');
  });

  it('falls back to / when next is absent', () => {
    expect(next(null)).toBe('/');
  });
});

describe('oauthLoginUrl', () => {
  it('targets the API login endpoint with an encoded, validated next', () => {
    expect(oauthLoginUrl('google', '/oauth/consent?request_id=1')).toBe(
      '/api/auth/oauth/google/login?next=%2Foauth%2Fconsent%3Frequest_id%3D1',
    );
  });

  it('replaces an unsafe next with /', () => {
    expect(oauthLoginUrl('google', '//evil.example')).toBe('/api/auth/oauth/google/login?next=%2F');
  });
});

describe('loginErrorMessage', () => {
  it('is empty without a code and friendly for every known code', () => {
    expect(loginErrorMessage(null)).toBe('');
    for (const code of ['signup_disabled', 'email_not_verified', 'account_inactive', 'oauth_failed']) {
      expect(loginErrorMessage(code)).not.toBe('');
      expect(loginErrorMessage(code)).not.toBe(loginErrorMessage('something_else'));
    }
  });
});
