
import type { Invoice } from '../types/api';

export type InvoiceDueSort =
  | 'default'
  | 'amount-desc'
  | 'due-date-asc'
  | 'customer-asc';

const validSortOptions: InvoiceDueSort[] = [
  'default',
  'amount-desc',
  'due-date-asc',
  'customer-asc',
];

export function parseInvoiceDueSort(
  value: string | null,
): InvoiceDueSort {
  return validSortOptions.includes(value as InvoiceDueSort)
    ? (value as InvoiceDueSort)
    : 'default';
}

export function sortDueInvoices(
  invoices: Invoice[],
  sort: InvoiceDueSort,
): Invoice[] {
  // Sorting is page-local: only the invoices loaded for the current page are sorted.
  if (sort === 'default') {
    return invoices;
  }

  return [...invoices].sort((a, b) => {
    let result = 0;

    switch (sort) {
      case 'amount-desc':
        result = b.outstanding_amount - a.outstanding_amount;
        break;

      case 'due-date-asc': {
        // Missing due dates always sort last.
        if (!a.due_date && b.due_date) return 1;
        if (a.due_date && !b.due_date) return -1;
        if (a.due_date && b.due_date) {
          result = a.due_date.localeCompare(b.due_date);
        }
        break;
      }

      case 'customer-asc': {
        // Missing customer names always sort last.
        const nameA = a.ledger_name?.trim() ?? '';
        const nameB = b.ledger_name?.trim() ?? '';

        if (!nameA && nameB) return 1;
        if (nameA && !nameB) return -1;

        result = nameA.localeCompare(nameB, undefined, {
          sensitivity: 'base',
        });
        break;
      }
    }

    // Use invoice ID as a deterministic tie-breaker.
    return result || a.id - b.id;
  });
}
