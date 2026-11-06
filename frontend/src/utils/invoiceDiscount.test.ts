/**
 * Tests for invoice discount calculations.
 *
 * These test the client-side discount computation logic that is used in
 * the invoice composer to preview totals before submission.
 */

import { describe, it, expect } from 'vitest';
import { computeInvoiceTotals, computeLineTotal } from './invoiceTotals';

describe('Item-level percentage discount', () => {
  it('reduces line total for 10% off 100 at 18% GST (non-inclusive)', () => {
    const result = computeLineTotal({
      unitPrice: 100,
      quantity: 1,
      gstRate: 18,
      taxInclusive: false,
      discountType: 'percentage',
      discountValue: 10,
    });
    // taxable = 90, tax = 16.20, line = 106.20
    expect(result.taxableAmount).toBe(90);
    expect(result.taxAmount).toBe(16.2);
    expect(result.lineTotal).toBe(106.2);
  });

  it('no discount when value is 0', () => {
    const result = computeLineTotal({
      unitPrice: 100,
      quantity: 1,
      gstRate: 18,
      taxInclusive: false,
      discountType: 'percentage',
      discountValue: 0,
    });
    expect(result.lineTotal).toBe(118);
  });

  it('no discount when type is empty', () => {
    const result = computeLineTotal({
      unitPrice: 100,
      quantity: 1,
      gstRate: 18,
      taxInclusive: false,
      discountType: '',
      discountValue: 10,
    });
    expect(result.lineTotal).toBe(118);
  });
});

describe('Item-level net discount', () => {
  it('reduces line total by flat 25 on 100 at 18% GST (non-inclusive)', () => {
    const result = computeLineTotal({
      unitPrice: 100,
      quantity: 1,
      gstRate: 18,
      taxInclusive: false,
      discountType: 'net',
      discountValue: 25,
    });
    // taxable = 75, tax = 13.50, line = 88.50
    expect(result.taxableAmount).toBe(75);
    expect(result.taxAmount).toBe(13.5);
    expect(result.lineTotal).toBe(88.5);
  });

  it('caps net discount at taxable amount', () => {
    const result = computeLineTotal({
      unitPrice: 50,
      quantity: 1,
      gstRate: 18,
      taxInclusive: false,
      discountType: 'net',
      discountValue: 100, // larger than taxable
    });
    // taxable becomes 0
    expect(result.taxableAmount).toBe(0);
    expect(result.lineTotal).toBe(0);
  });
});

describe('Invoice-level discount', () => {
  it('percentage discount on invoice total', () => {
    const result = computeInvoiceTotals([{ unitPrice: 1000, quantity: 1, gstRate: 0 }], {
      taxInclusive: false, invoiceDiscount: { type: 'percentage', value: 5 },
    });
    expect(result.invoiceDiscountAmount).toBe(50);
    expect(result.afterDiscountTotal).toBe(950);
  });

  it('flat discount on invoice total', () => {
    const result = computeInvoiceTotals([{ unitPrice: 1000, quantity: 1, gstRate: 0 }], {
      taxInclusive: false, invoiceDiscount: { type: 'net', value: 75 },
    });
    expect(result.invoiceDiscountAmount).toBe(75);
    expect(result.afterDiscountTotal).toBe(925);
  });

  it('flat discount capped at total', () => {
    const result = computeInvoiceTotals([{ unitPrice: 50, quantity: 1, gstRate: 0 }], {
      taxInclusive: false, invoiceDiscount: { type: 'net', value: 100 },
    });
    expect(result.invoiceDiscountAmount).toBe(50);
    expect(result.afterDiscountTotal).toBe(0);
  });
});

describe('Combined item and invoice discounts', () => {
  it('item discount + invoice discount stack', () => {
    // Item 1: 200 at 18%, 10% off → taxable=180, line=212.40
    // Item 2: 300 at 18%, flat 50 off → taxable=250, line=295.00
    // Total: 507.40
    // Invoice 20 flat → 487.40
    const item1 = computeLineTotal({ unitPrice: 200, quantity: 1, gstRate: 18, taxInclusive: false, discountType: 'percentage', discountValue: 10 });
    const item2 = computeLineTotal({ unitPrice: 300, quantity: 1, gstRate: 18, taxInclusive: false, discountType: 'net', discountValue: 50 });

    expect(item1.lineTotal).toBe(212.4);
    expect(item2.lineTotal).toBe(295);

    const total = item1.lineTotal + item2.lineTotal;
    expect(total).toBe(507.4);

    const { total: final } = computeInvoiceTotals([
      { unitPrice: 200, quantity: 1, gstRate: 18, discountType: 'percentage', discountValue: 10 },
      { unitPrice: 300, quantity: 1, gstRate: 18, discountType: 'net', discountValue: 50 },
    ], { taxInclusive: false, invoiceDiscount: { type: 'net', value: 20 } });
    expect(final).toBe(487.4);
  });
});
