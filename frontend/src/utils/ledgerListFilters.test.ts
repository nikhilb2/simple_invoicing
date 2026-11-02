import { describe, expect, it } from 'vitest';
import { buildLedgerListParams, parseLedgerListFilters } from './ledgerListFilters';

const params = (query: string) => new URLSearchParams(query);

describe('parseLedgerListFilters', () => {
  it('reads q, sort and page from the URL', () => {
    expect(parseLedgerListFilters(params('q=sharma&sort=balance_desc&page=2'))).toEqual({
      search: 'sharma',
      sort: 'balance_desc',
      page: 2,
    });
  });

  it('defaults to an empty search, name sort and page 1', () => {
    expect(parseLedgerListFilters(params(''))).toEqual({ search: '', sort: 'name', page: 1 });
  });

  it('keeps a decoded search term intact', () => {
    expect(parseLedgerListFilters(params('q=Acme%20Traders')).search).toBe('Acme Traders');
  });

  it('accepts every value the sort select offers', () => {
    for (const sort of ['name', '-name', 'newest', 'balance_desc']) {
      expect(parseLedgerListFilters(params(`sort=${sort}`)).sort).toBe(sort);
    }
  });

  it('falls back to name sort for an unknown sort instead of breaking', () => {
    expect(parseLedgerListFilters(params('sort=bogus')).sort).toBe('name');
  });

  it('falls back to page 1 for a non numeric, zero or negative page', () => {
    expect(parseLedgerListFilters(params('page=bogus')).page).toBe(1);
    expect(parseLedgerListFilters(params('page=0')).page).toBe(1);
    expect(parseLedgerListFilters(params('page=-3')).page).toBe(1);
  });
});

describe('buildLedgerListParams', () => {
  it('writes q, sort and page', () => {
    const next = buildLedgerListParams({ search: 'sharma', sort: 'balance_desc', page: 2 });
    expect(next.get('q')).toBe('sharma');
    expect(next.get('sort')).toBe('balance_desc');
    expect(next.get('page')).toBe('2');
  });

  it('leaves the defaults out of the URL so links stay clean', () => {
    const next = buildLedgerListParams({ search: '', sort: 'name', page: 1 });
    expect(next.has('q')).toBe(false);
    expect(next.has('sort')).toBe(false);
    expect(next.has('page')).toBe(false);
  });

  it('drops a blank search and reset sort and page from an existing URL', () => {
    const next = buildLedgerListParams(
      { search: '   ', sort: 'name', page: 1 },
      params('q=sharma&sort=balance_desc&page=2'),
    );
    expect(next.toString()).toBe('');
  });

  it('preserves unrelated params already on the URL', () => {
    const next = buildLedgerListParams(
      { search: 'sharma', sort: 'name', page: 1 },
      params('tab=all'),
    );
    expect(next.get('tab')).toBe('all');
    expect(next.get('q')).toBe('sharma');
    expect(next.has('sort')).toBe(false);
    expect(next.has('page')).toBe(false);
  });
});
