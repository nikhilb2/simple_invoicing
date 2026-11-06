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
