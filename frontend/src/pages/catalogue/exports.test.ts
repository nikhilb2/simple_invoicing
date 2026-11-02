import { describe, expect, it } from 'vitest';
import { toQueryParams } from './exports';
import type { ExportFilters } from './exports';

const filters = (overrides: Partial<ExportFilters> = {}): ExportFilters => ({
  search: '',
  status: '',
  lowStock: false,
  serials: '',
  sortBy: 'name',
  sortOrder: 'asc',
  ...overrides,
});

describe('toQueryParams', () => {
  it('sends the serial filter under the name the API uses', () => {
    // The export is the grid saved to a file: if this drops a filter the grid
    // applied, the download quietly contains rows that were not on screen.
    expect(toQueryParams(filters({ serials: 'tracked' }), false)).toEqual({ serials: 'tracked' });
    expect(toQueryParams(filters({ serials: 'untracked' }), false)).toEqual({ serials: 'untracked' });
  });

  it('omits the serial filter when it is off', () => {
    expect(toQueryParams(filters(), false)).toEqual({});
  });

  it('carries the serial filter alongside the others', () => {
    expect(
      toQueryParams(filters({ search: '  IMEI-1  ', status: 'active', lowStock: true, serials: 'tracked' }), true),
    ).toEqual({
      search: 'IMEI-1',
      status: 'active',
      low_stock: true,
      serials: 'tracked',
      sort_by: 'name',
      sort_order: 'asc',
    });
  });
});
