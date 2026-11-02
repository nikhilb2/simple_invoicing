import { describe, expect, it } from 'vitest';
import { buildDayBookParams, parseDayBookFilters, resolveVoucherType } from './dayBookFilters';

const params = (query: string) => new URLSearchParams(query);

describe('parseDayBookFilters', () => {
  it('reads q and type from the URL', () => {
    expect(parseDayBookFilters(params('q=INV-1&type=sales'))).toEqual({
      search: 'INV-1',
      voucherType: 'sales',
    });
  });

  it('defaults to an empty search and all types', () => {
    expect(parseDayBookFilters(params(''))).toEqual({ search: '', voucherType: 'all' });
  });

  it('keeps a decoded search term intact', () => {
    expect(parseDayBookFilters(params('q=Acme%20Traders')).search).toBe('Acme Traders');
  });
});

describe('buildDayBookParams', () => {
  it('writes q and type', () => {
    const next = buildDayBookParams({ search: 'INV-1', voucherType: 'sales' });
    expect(next.get('q')).toBe('INV-1');
    expect(next.get('type')).toBe('sales');
  });

  it('leaves the defaults out of the URL so links stay clean', () => {
    const next = buildDayBookParams({ search: '', voucherType: 'all' });
    expect(next.has('q')).toBe(false);
    expect(next.has('type')).toBe(false);
  });

  it('drops a blank search and a reset type from an existing URL', () => {
    const next = buildDayBookParams(
      { search: '   ', voucherType: 'all' },
      params('q=INV-1&type=sales'),
    );
    expect(next.toString()).toBe('');
  });

  it('preserves unrelated params already on the URL', () => {
    const next = buildDayBookParams(
      { search: 'INV-1', voucherType: 'all' },
      params('from=2026-10-01'),
    );
    expect(next.get('from')).toBe('2026-10-01');
    expect(next.get('q')).toBe('INV-1');
    expect(next.has('type')).toBe(false);
  });
});

describe('resolveVoucherType', () => {
  it('keeps a type that is present in the loaded entries', () => {
    expect(resolveVoucherType('sales', ['sales', 'payment'])).toBe('sales');
  });

  it('falls back to all for an unknown type instead of an empty register', () => {
    expect(resolveVoucherType('bogus', ['sales', 'payment'])).toBe('all');
  });

  it('treats an absent or all type as all', () => {
    expect(resolveVoucherType('', ['sales'])).toBe('all');
    expect(resolveVoucherType('all', ['sales'])).toBe('all');
  });

  it('defers the decision while nothing has loaded yet', () => {
    // An empty available list means "not loaded", not "no such type": deciding
    // now would clear every deep link before the entries arrive.
    expect(resolveVoucherType('sales', [])).toBe('sales');
  });
});
