import { describe, expect, it } from 'vitest';
import { parseInvoiceDueSort } from './invoiceDuesSorting';

describe('parseInvoiceDueSort', () => {
  it('accepts supported sorting options', () => {
    expect(parseInvoiceDueSort('amount-desc')).toBe('amount-desc');
    expect(parseInvoiceDueSort('due-date-asc')).toBe('due-date-asc');
    expect(parseInvoiceDueSort('customer-asc')).toBe('customer-asc');
  });

  it('uses default for missing or invalid values', () => {
    expect(parseInvoiceDueSort(null)).toBe('default');
    expect(parseInvoiceDueSort('invalid')).toBe('default');
    expect(parseInvoiceDueSort('')).toBe('default');
  });
});
