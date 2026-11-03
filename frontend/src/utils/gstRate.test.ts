import { expect, test } from 'vitest';
import { parseGstRate } from './gstRate.ts';

test('treats an empty or blank rate as all rates', () => {
  expect(parseGstRate('')).toBeUndefined();
  expect(parseGstRate('   ')).toBeUndefined();
});

test('parses a numeric rate', () => {
  expect(parseGstRate('18')).toBe(18);
  expect(parseGstRate('0.5')).toBe(0.5);
});

test('ignores a value that is not a finite number', () => {
  expect(parseGstRate('abc')).toBeUndefined();
  expect(parseGstRate('Infinity')).toBeUndefined();
});
