import { describe, expect, it } from 'vitest';
import { computeInvoiceTotals, computeLineTotal, roundMoney } from './invoiceTotals';

const line = { unitPrice: 10.1, quantity: 1, gstRate: 5 };

describe('rounded invoice previews', () => {
  it('sums rounded line taxes: three 10.10 lines at 5% IGST total 31.83', () => {
    expect(computeInvoiceTotals([line, line, line], {
      taxInclusive: false, interstateSupply: true,
    })).toEqual({
      taxableAmount: 30.3, taxAmount: 1.53, totalAmount: 31.83,
      invoiceDiscountAmount: 0, afterDiscountTotal: 31.83, roundOffAmount: 0, total: 31.83,
    });
  });

  it('rounds each half-rate independently for CGST/SGST, as the saved invoice does', () => {
    const result = computeInvoiceTotals([line, line, line], {
      taxInclusive: false, interstateSupply: false,
    });
    // Each head is round(10.10 * 2.5%) = 0.25, not half of a rounded 0.51.
    expect(result.taxAmount).toBe(1.5);
    expect(result.total).toBe(31.8);
  });

  it('rounds inclusive taxable value before computing tax', () => {
    expect(computeLineTotal({ unitPrice: 1.01, quantity: 1, gstRate: 18, taxInclusive: true }))
      .toEqual({ taxableAmount: 0.86, taxAmount: 0.15, lineTotal: 1.01 });
    expect(computeLineTotal({
      unitPrice: 1.01, quantity: 1, gstRate: 18, taxInclusive: true, interstateSupply: false,
    })).toEqual({ taxableAmount: 0.86, taxAmount: 0.16, lineTotal: 1.02 });
  });

  it('rounds fractional quantities and a percentage line discount before recomputing tax', () => {
    expect(computeLineTotal({
      ...line, quantity: 0.125, taxInclusive: false, discountType: 'percentage', discountValue: 10,
    })).toEqual({ taxableAmount: 1.13, taxAmount: 0.06, lineTotal: 1.19 });
  });

  it('rounds a net line discount before rebuilding an inclusive line', () => {
    expect(computeLineTotal({
      ...line, gstRate: 18, taxInclusive: true, discountType: 'net', discountValue: 1.005,
    })).toEqual({ taxableAmount: 7.55, taxAmount: 1.36, lineTotal: 8.91 });
  });

  it('caps a rounded net line discount at the taxable value', () => {
    expect(computeLineTotal({
      ...line, taxInclusive: false, discountType: 'net', discountValue: 100,
    })).toEqual({ taxableAmount: 0, taxAmount: 0, lineTotal: 0 });
  });

  it('rounds an invoice percentage discount before subtracting it', () => {
    const result = computeInvoiceTotals([line, line, line], {
      taxInclusive: false, invoiceDiscount: { type: 'percentage', value: 5 },
    });
    expect(result.invoiceDiscountAmount).toBe(1.59);
    expect(result.afterDiscountTotal).toBe(30.24);
  });

  it('rounds and caps an invoice net discount', () => {
    const result = computeInvoiceTotals([line], {
      taxInclusive: false, invoiceDiscount: { type: 'net', value: 0.005 },
    });
    expect(result.invoiceDiscountAmount).toBe(0.01);
    expect(result.total).toBe(10.6);
    expect(computeInvoiceTotals([line], {
      taxInclusive: false, invoiceDiscount: { type: 'net', value: 100 },
    }).total).toBe(0);
  });

  it('rounds the already rounded total to a rupee at the .50 boundary', () => {
    const result = computeInvoiceTotals([
      { unitPrice: 1, quantity: 1, gstRate: 0 },
      { unitPrice: 0.995, quantity: 1, gstRate: 0 },
      { unitPrice: 0.495, quantity: 1, gstRate: 0 },
    ], { taxInclusive: false, applyRoundOff: true });
    expect(result.afterDiscountTotal).toBe(2.5);
    expect(result.total).toBe(3);
    expect(result.roundOffAmount).toBe(0.5);
  });

  it('keeps ordinary whole-value invoices unchanged', () => {
    expect(computeInvoiceTotals([{ unitPrice: 100, quantity: 2, gstRate: 18 }], {
      taxInclusive: false,
    }).total).toBe(236);
  });

  it('shows zero for empty or incomplete form lines', () => {
    expect(computeInvoiceTotals([], { taxInclusive: false }).total).toBe(0);
    expect(computeLineTotal({ ...line, unitPrice: NaN, taxInclusive: false }).lineTotal).toBe(0);
  });
});

describe('half-up money rounding', () => {
  it.each([[1.005, 1.01], [10.075, 10.08], [-1.005, -1.01], [0, 0]])('%s rounds to %s', (value, expected) => {
    expect(roundMoney(value)).toBe(expected);
  });
});
