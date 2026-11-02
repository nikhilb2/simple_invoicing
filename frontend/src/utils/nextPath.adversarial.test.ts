import { describe, it, expect } from 'vitest';
import { isSafeNextPath, sanitizeNextPath, loginPathWithNext } from './nextPath';

// Open-redirect cases written independently of nextPath.test.ts, which tests the
// implementation's own reasoning. `next` is the one value in this app that comes
// straight from the URL bar and ends up in navigate(), and it is read at the exact
// moment a user has just signed in — so it gets a second, adversarial suite.
const MUST_REJECT = [
  '//evil.com', '///evil.com', '/\\evil.com', '\\\\evil.com', '/\\/evil.com',
  'https://evil.com', 'http://evil.com', '//evil.com/path', 'javascript:alert(1)',
  '/\tevil', '/\nevil', '/\r\n//evil.com', '\t//evil.com',
  '', ' /ok', 'ok', '../etc', 'javascript:/**/alert(1)', '/'.repeat(3000),
];
const MUST_ACCEPT = [
  '/', '/oauth/consent?request_id=abc', '/settings/connected-apps',
  '/invoices-view?invoice_id=12', '/ledgers/5', '/a?b=%2F%2Fevil.com',
  '/ /spaced', '/localhost:3000', '/#hash',
];

describe('nextPath adversarial', () => {
  for (const v of MUST_REJECT) {
    it('rejects ' + JSON.stringify(v).slice(0, 40), () => {
      expect(isSafeNextPath(v)).toBe(false);
      expect(sanitizeNextPath(v)).toBe('/');
    });
  }
  for (const v of MUST_ACCEPT) {
    it('accepts ' + JSON.stringify(v), () => expect(isSafeNextPath(v)).toBe(true));
  }
  it('round-trips through URLSearchParams without becoming unsafe', () => {
    for (const v of MUST_ACCEPT) {
      const url = loginPathWithNext(v);
      if (v === '/') { expect(url).toBe('/login'); continue; }
      const got = new URLSearchParams(url.split('?')[1] ?? '').get('next');
      expect(got).toBe(v);
      expect(isSafeNextPath(got)).toBe(true);
    }
  });
  it('sanitize never yields a non-relative string', () => {
    for (const v of [...MUST_REJECT, ...MUST_ACCEPT]) {
      const out = sanitizeNextPath(v);
      expect(out.startsWith('/')).toBe(true);
      expect(out.startsWith('//')).toBe(false);
    }
  });
});
