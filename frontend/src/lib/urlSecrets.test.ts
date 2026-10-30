import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readUrlSecret, resetUrlSecrets, scrubUrlSecrets } from './urlSecrets';

let url: string;
const replaceState = vi.fn((_state: unknown, _title: string, next: string) => { url = next; });

function setUrl(value: string) {
  url = value;
}

beforeEach(() => {
  resetUrlSecrets();
  replaceState.mockClear();
  vi.stubGlobal('window', {
    get location() {
      const u = new URL(url, 'http://app.test');
      return { pathname: u.pathname, search: u.search, hash: u.hash };
    },
    history: { state: null, replaceState },
  });
});

afterEach(() => vi.unstubAllGlobals());

describe('urlSecrets', () => {
  it('removes the token from the URL and hands it to the page', () => {
    setUrl('/verify-email?token=abc123&x=1#h');
    scrubUrlSecrets();
    expect(url).toBe('/verify-email?x=1#h');
    expect(readUrlSecret('token')).toBe('abc123');
  });

  it('is idempotent, so StrictMode double reads agree', () => {
    setUrl('/auth/callback?code=c0de&next=%2Finvoices');
    expect(readUrlSecret('code')).toBe('c0de');
    expect(readUrlSecret('code')).toBe('c0de');
    expect(url).toBe('/auth/callback?next=%2Finvoices');
    expect(replaceState).toHaveBeenCalledTimes(1);
  });

  it('leaves other pages alone', () => {
    setUrl('/login?token=keep');
    scrubUrlSecrets();
    expect(replaceState).not.toHaveBeenCalled();
    expect(readUrlSecret('token')).toBeNull();
  });
});
