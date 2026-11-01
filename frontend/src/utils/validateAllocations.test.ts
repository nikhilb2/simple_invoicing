import { expect, test } from 'vitest';
import { validateAllocations } from './validateAllocations';

test('returns null for valid allocations', () => {
  const result = validateAllocations(
    [{ invoice_id: 1, invoice_number: 'INV-1', allocated_amount: 50 }],
    100,
  );
  expect(result).toBeNull();
});

test('flags a zero allocation naming the invoice', () => {
  const result = validateAllocations(
    [{ invoice_id: 1, invoice_number: 'INV-12', allocated_amount: 0 }],
    100,
  );
  expect(result).toBe('Allocated amount for INV-12 must be greater than 0');
});

test('flags an empty allocation naming the invoice', () => {
  const result = validateAllocations(
    [{ invoice_id: 1, invoice_number: 'INV-12', allocated_amount: '' }],
    100,
  );
  expect(result).toBe('Allocated amount for INV-12 must be greater than 0');
});

test('flags over-allocation', () => {
  const result = validateAllocations(
    [{ invoice_id: 1, invoice_number: 'INV-1', allocated_amount: 150 }],
    100,
  );
  expect(result).toBe('Allocated amounts exceed the payment amount');
});

test('returns null for empty allocations', () => {
  const result = validateAllocations([], 100);
  expect(result).toBeNull();
});

test('accepts 50.1 + 50.2 against 100.3 (floating point)', () => {
  const result = validateAllocations(
    [
      { invoice_id: 1, invoice_number: 'INV-1', allocated_amount: 50.1 },
      { invoice_id: 2, invoice_number: 'INV-2', allocated_amount: 50.2 },
    ],
    100.3,
  );
  expect(result).toBeNull();
});

test('flags non-numeric allocation', () => {
  const result = validateAllocations(
    [{ invoice_id: 1, invoice_number: 'INV-1', allocated_amount: 'abc' }],
    100,
  );
  expect(result).toBe('Allocated amount for INV-1 must be greater than 0');
});
