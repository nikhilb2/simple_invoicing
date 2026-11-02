
import { describe, expect, it } from 'vitest';
import { parseInvoiceDueSort, sortDueInvoices } from './invoiceDuesSorting';
import type { Invoice } from '../types/api';

function invoice(
  id: number,
  amount: number,
  dueDate: string | null,
  customer: string | null,
): Invoice {
  return {
    id,
    outstanding_amount: amount,
    due_date: dueDate,
    ledger_name: customer,
  } as Invoice;
}

const invoices = [
  invoice(1, 100, '2026-10-20', 'Zebra Ltd'),
  invoice(2, 300, '2026-10-10', 'acme Ltd'),
  invoice(3, 200, null, 'Beta Ltd'),
];

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

describe('sortDueInvoices', () => {
  it('preserves the original order by default', () => {
    expect(sortDueInvoices(invoices, 'default')).toEqual(invoices);
  });

  it('sorts amount due from highest to lowest', () => {
    expect(
      sortDueInvoices(invoices, 'amount-desc').map((item) => item.id),
    ).toEqual([2, 3, 1]);
  });

  it('uses invoice ID to break equal amount ties', () => {
    const items = [
      invoice(3, 100, '2026-10-20', 'C'),
      invoice(1, 100, '2026-10-20', 'A'),
      invoice(2, 200, '2026-10-20', 'B'),
    ];

    expect(
      sortDueInvoices(items, 'amount-desc').map((item) => item.id),
    ).toEqual([2, 1, 3]);
  });

  it('sorts oldest due date first and puts missing dates last', () => {
    expect(
      sortDueInvoices(invoices, 'due-date-asc').map((item) => item.id),
    ).toEqual([2, 1, 3]);
  });

  it('puts multiple missing due dates last in ID order', () => {
    const items = [
      invoice(4, 100, null, 'D'),
      invoice(2, 100, '2026-10-10', 'B'),
      invoice(1, 100, null, 'A'),
    ];

    expect(
      sortDueInvoices(items, 'due-date-asc').map((item) => item.id),
    ).toEqual([2, 1, 4]);
  });

  it('sorts customer names alphabetically without case sensitivity', () => {
    expect(
      sortDueInvoices(invoices, 'customer-asc').map((item) => item.id),
    ).toEqual([2, 3, 1]);
  });

  it('puts missing customer names last', () => {
    const items = [
      invoice(1, 100, '2026-10-20', null),
      invoice(3, 100, '2026-10-20', 'Beta Ltd'),
      invoice(2, 100, '2026-10-20', ''),
      invoice(4, 100, '2026-10-20', '   '),
    ];

    expect(
      sortDueInvoices(items, 'customer-asc').map((item) => item.id),
    ).toEqual([3, 1, 2, 4]);
  });

  it('uses invoice ID to break equal customer-name ties', () => {
    const items = [
      invoice(3, 100, '2026-10-20', 'Acme'),
      invoice(1, 100, '2026-10-20', 'acme'),
      invoice(2, 100, '2026-10-20', 'Beta'),
    ];

    expect(
      sortDueInvoices(items, 'customer-asc').map((item) => item.id),
    ).toEqual([1, 3, 2]);
  });

  it('does not mutate the input array', () => {
    const originalOrder = invoices.map((item) => item.id);

    sortDueInvoices(invoices, 'amount-desc');

    expect(invoices.map((item) => item.id)).toEqual(originalOrder);
  });
});
