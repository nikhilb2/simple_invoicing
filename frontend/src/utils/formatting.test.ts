import { expect, test } from 'vitest';
import formatCurrency from './formatting.ts';

test('formatCurrency(1000) → $1,000.00', () => {
  expect(formatCurrency(1000)).toBe('$1,000.00');
});

test('formatCurrency(1000,) → ₹1,000.00', () => {
  expect(formatCurrency(1000, 'INR')).toBe('₹1,000.00');
});

test('zero value', () => {
  expect(formatCurrency(0)).toBe('$0.00');
});

test('negative value', () => {
  expect(formatCurrency(-1000)).toBe('-$1,000.00');
});

//loop through different invalid and unssupported currency code
const testValues = ['ER', '', undefined];
test.each(testValues)('invalid/unsupported currency: %s', (currency) => {
  const result = formatCurrency(1000, currency);
  expect(result).toBe('$1,000.00');
});
