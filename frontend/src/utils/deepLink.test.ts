import { describe, expect, it } from 'vitest';
import { deepLinkClass, numericParam } from './deepLink';

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
