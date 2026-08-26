/**
 * The `?next=` return path, and the one place it is validated.
 *
 * `Protected` bounces an unauthenticated visitor to /login carrying where they
 * were headed, and LoginPage / `PublicOnly` send them back there once the
 * session exists. That round trip is what makes the OAuth consent screen
 * reachable at all: a connector drops the user on /oauth/consent?request_id=…,
 * and without the return path they would sign in and land on the dashboard with
 * the pending authorization request lost.
 *
 * It is also an open redirect waiting to happen. `next` arrives from the URL
 * bar, so anything that reaches `navigate()` unchecked lets a link that *looks*
 * like this app hand the visitor — freshly signed in, at their most trusting —
 * to an attacker's page. Hence one validator, used by every call site, that
 * accepts only a same-origin path:
 *
 *   - it must begin with exactly one '/', so `https://evil.com` and the
 *     protocol-relative `//evil.com` (which browsers resolve as a *host*) are
 *     both out;
 *   - no backslashes anywhere — several browsers normalise '\' to '/', making
 *     `/\evil.com` protocol-relative after the fact;
 *   - no control characters, which are stripped rather than rejected by URL
 *     parsers and can smuggle a leading '/' past a naive prefix check.
 *
 * Everything else is a path this app can route, and an unroutable one merely
 * lands on the catch-all redirect — not a security question.
 */

/** C0, DEL, and the Unicode line separators URL parsers quietly drop. */
const FORBIDDEN_CHARS = /[\u0000-\u001f\u007f\u2028\u2029]/;

/** Long enough for any real route, short enough not to be a payload. */
const MAX_LENGTH = 2048;

export const LOGIN_PATH = '/login';
export const NEXT_PARAM = 'next';

/** Whether `value` is a relative path this app may navigate to. */
export function isSafeNextPath(value: string | null | undefined): value is string {
  if (typeof value !== 'string') return false;
  if (value.length === 0 || value.length > MAX_LENGTH) return false;
  if (FORBIDDEN_CHARS.test(value)) return false;
  if (value.includes('\\')) return false;
  if (!value.startsWith('/')) return false;
  // '//host' is protocol-relative; '/../' is not a route this app serves.
  if (value.startsWith('//')) return false;
  return true;
}

/** `value` if it is safe to navigate to, else `fallback`. */
export function sanitizeNextPath(value: string | null | undefined, fallback = '/'): string {
  return isSafeNextPath(value) ? value : fallback;
}

/**
 * The /login URL that returns to `from` afterwards.
 *
 * A `from` of '/' is dropped: it is where login already lands, and carrying it
 * would put a redundant query string on the most-visited URL in the app.
 */
export function loginPathWithNext(from: string | null | undefined): string {
  if (!isSafeNextPath(from) || from === '/') return LOGIN_PATH;
  return `${LOGIN_PATH}?${NEXT_PARAM}=${encodeURIComponent(from)}`;
}
