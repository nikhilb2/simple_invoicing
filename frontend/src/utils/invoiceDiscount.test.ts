/**
 * Tests for invoice discount calculations.
 *
 * These test the client-side discount computation logic that is used in
 * the invoice composer to preview totals before submission.
 */

import { describe, it, expect } from 'vitest';

/**
 * Compute line total with optional item-level discount (mirrors invoice composer logic).
 */
function computeLineTotal(params: {
  unitPrice: number;
  quantity: number;
  gstRate: number;
  taxInclusive: boolean;
  discountType?: string;
  discountValue?: number;
}): { lineTotal: number; taxableAmount: number; taxAmount: number } {
  const { unitPrice, quantity, gstRate, taxInclusive, discountType, discountValue } = params;

  let taxableAmount: number;
  let taxAmount: number;
  let lineTotal: number;

  if (taxInclusive) {
    lineTotal = unitPrice * quantity;
    taxableAmount = lineTotal / (1 + gstRate / 100);
  } else {
    taxableAmount = unitPrice * quantity;
    lineTotal = taxableAmount + taxableAmount * gstRate / 100;
  }

  // Apply item-level discount
  if (discountType && discountValue != null && discountValue > 0) {
    let discAmount = 0;
    if (discountType === 'percentage') {
      discAmount = taxableAmount * discountValue / 100;
    } else {
      discAmount = Math.min(discountValue, taxableAmount);
    }
    const discountedTaxable = taxableAmount - discAmount;
    if (taxInclusive) {
      lineTotal = discountedTaxable * (1 + gstRate / 100);
    } else {
      lineTotal = discountedTaxable + discountedTaxable * gstRate / 100;
    }
    taxableAmount = discountedTaxable;
  }

  taxAmount = taxInclusive ? lineTotal - taxableAmount : taxableAmount * gstRate / 100;

  return { lineTotal: Math.round((lineTotal + Number.EPSILON) * 100) / 100, taxableAmount: Math.round((taxableAmount + Number.EPSILON) * 100) / 100, taxAmount: Math.round((taxAmount + Number.EPSILON) * 100) / 100 };
}

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
  function applyInvoiceDiscount(
    total: number,
    discountType: string,
    discountValue: number,
  ): { discountAmount: number; afterDiscount: number } {
    if (!discountType || !discountValue || discountValue <= 0) {
      return { discountAmount: 0, afterDiscount: total };
    }
    let discountAmount: number;
    if (discountType === 'percentage') {
      discountAmount = total * discountValue / 100;
    } else {
      discountAmount = Math.min(discountValue, total);
    }
    return {
      discountAmount: Math.round((discountAmount + Number.EPSILON) * 100) / 100,
      afterDiscount: Math.round((total - discountAmount + Number.EPSILON) * 100) / 100,
    };
  }

  it('percentage discount on invoice total', () => {
    const result = applyInvoiceDiscount(1000, 'percentage', 5);
    expect(result.discountAmount).toBe(50);
    expect(result.afterDiscount).toBe(950);
  });

  it('flat discount on invoice total', () => {
    const result = applyInvoiceDiscount(1000, 'net', 75);
    expect(result.discountAmount).toBe(75);
    expect(result.afterDiscount).toBe(925);
  });

  it('flat discount capped at total', () => {
    const result = applyInvoiceDiscount(50, 'net', 100);
    expect(result.discountAmount).toBe(50);
    expect(result.afterDiscount).toBe(0);
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

    function applyInvoiceDiscount(
      total: number,
      discountType: string,
      discountValue: number,
    ): number {
      let disc = 0;
      if (discountType === 'percentage') {
        disc = total * discountValue / 100;
      } else {
        disc = Math.min(discountValue, total);
      }
      return Math.round((total - disc + Number.EPSILON) * 100) / 100;
    }

    const final = applyInvoiceDiscount(total, 'net', 20);
    expect(final).toBe(487.4);
  });
});
