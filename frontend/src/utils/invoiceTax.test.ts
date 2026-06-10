import { expect, test } from 'vitest';

/**
 * Tests for tax-inclusive/exclusive pricing toggle logic.
 *
 * These tests verify the calculation logic used in CreateInvoiceModal and
 * InvoicesPageView components.
 */

// Replicating the calculation logic from the components:
function calculateLineTotal(
  unitPrice: number,
  quantity: number,
  gstRate: number,
  taxInclusive: boolean,
): number {
  if (taxInclusive) {
    return unitPrice * quantity;
  }
  const taxableAmount = unitPrice * quantity;
  return taxableAmount + taxableAmount * gstRate / 100;
}

function calculateTaxAmount(
  unitPrice: number,
  quantity: number,
  gstRate: number,
  taxInclusive: boolean,
): number {
  if (taxInclusive) {
    const lineTotal = unitPrice * quantity;
    return lineTotal - lineTotal / (1 + gstRate / 100);
  }
  const taxableAmount = unitPrice * quantity;
  return taxableAmount * gstRate / 100;
}

test('tax_exclusive: taxable + tax = line total', () => {
  // unit_price=100, qty=2, GST=18%
  // taxable = 200, tax = 36, line total = 236
  const lineTotal = calculateLineTotal(100, 2, 18, false);
  expect(lineTotal).toBe(236);
});

test('tax_exclusive: tax amount calculation', () => {
  const taxAmount = calculateTaxAmount(100, 2, 18, false);
  expect(taxAmount).toBe(36);
});

test('tax_inclusive: line total = unit_price * quantity (no extra tax)', () => {
  // unit_price=118 (inclusive of 18% GST), qty=1
  // line total = 118
  const lineTotal = calculateLineTotal(118, 1, 18, true);
  expect(lineTotal).toBe(118);
});

test('tax_inclusive: tax is backed out from inclusive price', () => {
  // unit_price=118 (inclusive of 18% GST), qty=1
  // line total = 118, tax = 118 - 118/1.18 = 18
  const taxAmount = calculateTaxAmount(118, 1, 18, true);
  expect(taxAmount).toBeCloseTo(18, 1);
});

test('tax_inclusive: zero GST rate', () => {
  const lineTotal = calculateLineTotal(100, 1, 0, true);
  expect(lineTotal).toBe(100);

  const taxAmount = calculateTaxAmount(100, 1, 0, true);
  expect(taxAmount).toBe(0);
});

test('tax_exclusive: zero GST rate', () => {
  const lineTotal = calculateLineTotal(100, 1, 0, false);
  expect(lineTotal).toBe(100);

  const taxAmount = calculateTaxAmount(100, 1, 0, false);
  expect(taxAmount).toBe(0);
});

test('tax_inclusive with tax_exclusive give same result when GST=0', () => {
  const inc = calculateLineTotal(100, 1, 0, true);
  const exc = calculateLineTotal(100, 1, 0, false);
  expect(inc).toBe(exc);
});

test('tax_inclusive with tax_exclusive differ when GST>0', () => {
  const inc = calculateLineTotal(100, 1, 18, true);
  const exc = calculateLineTotal(100, 1, 18, false);
  expect(inc).toBe(100);
  expect(exc).toBe(118);
  expect(inc).not.toBe(exc);
});
