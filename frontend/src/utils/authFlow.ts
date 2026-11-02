import axios from 'axios';
import { apiBaseURL, getApiErrorMessage } from '../api/client';
import { sanitizeNextPath } from './nextPath';

/**
 * Where the browser goes to start a provider sign-in.
 *
 * A full-page navigation, never an XHR: the backend answers with a 302 to the
 * provider, and the provider's consent screen has to own the tab. `next` goes
 * through the same validator as every other return path.
 */
export function oauthLoginUrl(providerId: string, next: string | null | undefined): string {
  const base = apiBaseURL.replace(/\/+$/, '');
  return `${base}/auth/oauth/${encodeURIComponent(providerId)}/login?next=${encodeURIComponent(sanitizeNextPath(next))}`;
}

/** Messages for the `?error=` codes the OAuth callback redirects to /login with. */
const LOGIN_ERROR_MESSAGES: Record<string, string> = {
  signup_disabled: 'Sign-up is not open for this account. Ask an administrator for access.',
  email_not_verified: 'Please verify your email address before signing in.',
  account_inactive: 'This account has been deactivated.',
  oauth_failed: 'Sign-in with the provider did not complete. Please try again.',
};

export function loginErrorMessage(code: string | null | undefined): string {
  if (!code) return '';
  return LOGIN_ERROR_MESSAGES[code] ?? 'Unable to sign in. Please try again.';
}

/** Message for a failed auth request, with the 429 case spelled out. */
export function authErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error) && error.response?.status === 429) {
    return 'Too many attempts. Please wait a few minutes and try again.';
  }
  return getApiErrorMessage(error, fallback);
}

/** Where /auth/callback sends the visitor once the one-time code is exchanged. */
export function callbackNextPath(params: URLSearchParams): string {
  return sanitizeNextPath(params.get('next'));
}

export const OAUTH_FAILED_PATH = '/login?error=oauth_failed';
