import { expect, test } from 'vitest';
import { zeroRateSalesNote } from './gstr1Notes';

test('no 0% sales, no note', () => {
  expect(zeroRateSalesNote(0, '₹0.00')).toBeNull();
});

test('the note gives the count and value and says where the JSON files them', () => {
  const note = zeroRateSalesNote(2, '₹3,500.50');

  expect(note).toContain('2 invoices have ₹3,500.50');
  expect(note).toContain('rate 0');
  expect(note).toContain('not in Table 8');
});

test('one invoice reads as one', () => {
  expect(zeroRateSalesNote(1, '₹10.00')).toContain('1 invoice has');
});
