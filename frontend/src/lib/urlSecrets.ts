/**
 * One-time secrets that arrive in the URL (`?token=` on /verify-email and
 * /reset-password, `?code=` on /auth/callback) must not stay there: session
 * replay records the address bar and the page's network calls, and a live
 * token in a recording is a credential in a third party's storage.
 *
 * `scrubUrlSecrets` runs in main.tsx before analytics start. It lifts the value
 * into a module variable and rewrites the URL with history.replaceState. Pages
 * read it back through `readUrlSecret`, which is idempotent (StrictMode runs
 * initialisers twice) and also scrubs on its own, for an in-app navigation that
 * never passed through startup. Nothing is persisted: the values are single-use.
 */

const SECRET_PARAMS: Record<string, string> = {
  '/verify-email': 'token',
  '/reset-password': 'token',
  '/auth/callback': 'code',
};

const held = new Map<string, string>();

function keyFor(pathname: string, param: string) {
  return `${pathname}?${param}`;
}

/** Moves the secret for the current page out of the URL; returns the paths' param if one was found. */
export function scrubUrlSecrets(): void {
  const { pathname, search, hash } = window.location;
  const param = SECRET_PARAMS[pathname];
  if (!param) return;

  const params = new URLSearchParams(search);
  const value = params.get(param);
  if (value === null) return;

  held.set(keyFor(pathname, param), value);
  params.delete(param);
  const rest = params.toString();
  window.history.replaceState(window.history.state, '', `${pathname}${rest ? `?${rest}` : ''}${hash}`);
}

/** The secret for `param` on the current page, scrubbed from the URL; null if there is none. */
export function readUrlSecret(param: string): string | null {
  scrubUrlSecrets();
  return held.get(keyFor(window.location.pathname, param)) ?? null;
}

/** For tests. */
export function resetUrlSecrets(): void {
  held.clear();
}
