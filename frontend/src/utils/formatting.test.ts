import { expect, test } from 'vitest';
import formatCurrency, { formatDate, formatDateTime } from './formatting.ts';
import { formatInvoiceDateLabel } from './invoiceDueDate.ts';

test('formatCurrency(1000) → $1,000.00', () => {
  expect(formatCurrency(1000)).toBe('$1,000.00');
});

test('formatCurrency(1000) → ₹1,000.00', () => {
  expect(formatCurrency(1000, 'INR')).toBe('₹1,000.00');
});

test('zero value', () => {
  expect(formatCurrency(0)).toBe('$0.00');
});

test('negative value', () => {
  expect(formatCurrency(-1000)).toBe('-$1,000.00');
});

//loop through different invalid and unsupported currency code
const testValues = ['ER', '', undefined];
test.each(testValues)('invalid/unsupported currency: %s', (currency) => {
  const result = formatCurrency(1000, currency);
  expect(result).toBe('$1,000.00');
});

test('large value', () => {
  expect(formatCurrency(100000000)).toBe('$100,000,000.00');
});

test.each([
  ['2026-03-05', '05-03-2026'],
  ['2024-02-29', '29-02-2024'],
  ['2026-01-01', '01-01-2026'],
  ['0099-01-02', '02-01-0099'],
])('formats a calendar date without changing its day: %s', (value, expected) => {
  expect(formatDate(value)).toBe(expected);
  expect(formatInvoiceDateLabel(value)).toBe(expected);
});

test('formats existing invoice date labels as DD-MM-YYYY', () => {
  expect(formatInvoiceDateLabel('2026-03-05')).toBe('05-03-2026');
});

test.each([
  null, undefined, '', 'not-a-date', '2026-02-30', '2025-02-29', '2026-13-01',
  '2026-02-30T12:30:00Z', '2026-04-31T00:00:00',
])(
  'uses a dash for missing or invalid dates: %s',
  (value) => {
    expect(formatDate(value)).toBe('—');
    expect(formatDateTime(value)).toBe('—');
  },
);

test('formats local date-times with a 24-hour clock and no seconds', () => {
  expect(formatDateTime('2026-03-05T14:07:42')).toBe('05-03-2026 14:07');
  expect(formatDateTime('2026-03-05T00:03:00')).toBe('05-03-2026 00:03');
  expect(formatDateTime('2026-03-05')).toBe('05-03-2026 00:00');
});

test('renders an ISO timestamp as local time, including its offset', () => {
  const local = new Date(2026, 2, 5, 14, 7, 42);
  expect(formatDateTime(local.toISOString())).toBe('05-03-2026 14:07');
  expect(formatDate(local.toISOString())).toBe('05-03-2026');
  expect(formatDateTime('2026-03-05T14:07:00+05:30')).toBe(
    formatDateTime('2026-03-05T08:37:00Z'),
  );
});

test('accepts Date objects without mutating them and rejects invalid ones', () => {
  const date = new Date(2026, 2, 5, 14, 7, 42);
  const original = date.getTime();
  expect(formatDate(date)).toBe('05-03-2026');
  expect(formatDateTime(date)).toBe('05-03-2026 14:07');
  expect(date.getTime()).toBe(original);
  expect(formatDate(new Date(NaN))).toBe('—');
  expect(formatDateTime(new Date(NaN))).toBe('—');
});
