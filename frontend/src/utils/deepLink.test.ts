import { describe, expect, it } from 'vitest';
import { deepLinkClass, numericParam, textParam } from './deepLink';

const params = (query: string) => new URLSearchParams(query);

describe('numericParam', () => {
  it('reads a record id', () => {
    expect(numericParam(params('invoice_id=123'), 'invoice_id')).toBe(123);
  });

  it('returns null when the parameter is absent', () => {
    expect(numericParam(params('cn_id=4'), 'invoice_id')).toBeNull();
  });

  it('rejects anything that is not a positive integer id', () => {
    // These arrive straight from the URL bar, so every one of them has to fall
    // back to "no deep link" rather than reaching a `/payments/${id}` URL.
    for (const raw of ['', 'abc', '0', '007', '-3', '1.5', '1e3', '0x1f', 'NaN', ' 12 ', '../../secrets']) {
      expect(numericParam(params(`payment_id=${encodeURIComponent(raw)}`), 'payment_id')).toBeNull();
    }
  });

  it('rejects a numeric string with a path appended', () => {
    expect(numericParam(params('product_id=12%2F..%2F..'), 'product_id')).toBeNull();
  });
});

describe('textParam', () => {
  it('reads the decoded value of an encodeURIComponent-ed label', () => {
    // This is exactly the link InvoicesPageView builds behind "Open invoice".
    const label = 'INV-2026-27-160';
    expect(textParam(params(`search=${encodeURIComponent(label)}`), 'search')).toBe(label);
  });

  it('decodes once, not twice', () => {
    // A ledger name with a slash or a space must survive intact; decoding the
    // already-decoded value again would corrupt or crash on it.
    expect(textParam(params('search=INV%2F2026%2F160'), 'search')).toBe('INV/2026/160');
    expect(textParam(params('search=Acme%20Traders%20%26%20Co'), 'search')).toBe('Acme Traders & Co');
    expect(textParam(params('search=100%25%20cotton'), 'search')).toBe('100% cotton');
  });

  it('treats absent, empty and whitespace-only params as no deep link', () => {
    // `?search=` must leave the feed alone rather than filter on '' or ' '.
    expect(textParam(params('product_id=4'), 'search')).toBeNull();
    expect(textParam(params('search='), 'search')).toBeNull();
    expect(textParam(params('search=%20%20'), 'search')).toBeNull();
  });

  it('trims padding around a real term', () => {
    expect(textParam(params('search=%20INV-1%20'), 'search')).toBe('INV-1');
  });
});

describe('deepLinkClass', () => {
  it('flags only the targeted row', () => {
    expect(deepLinkClass(true, 'invoice-row')).toBe('invoice-row deep-link-target');
    expect(deepLinkClass(false, 'invoice-row')).toBe('invoice-row');
  });

  it('works with no base class', () => {
    expect(deepLinkClass(true)).toBe('deep-link-target');
    expect(deepLinkClass(false)).toBe('');
  });
});
