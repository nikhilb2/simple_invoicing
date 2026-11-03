import { describe, expect, it } from 'vitest';
import {
  addDaysToIsoDate,
  composerDocumentName,
  conversionDraftToFormItems,
  conversionLineShortfalls,
  conversionPayload,
  defaultValidUntil,
  formItemToQuotationLine,
  isQuotationVoucher,
  isSaleLikeVoucher,
  quotationToFormItems,
} from './quotationDraft';
import type { QuotationItem } from '../types/api';

const line: QuotationItem = {
  id: 9,
  product_id: 5,
  product_name: 'Widget',
  hsn_sac: '84713010',
  quantity: 3,
  unit_price: 0,
  gst_rate: 18,
  taxable_amount: 0,
  tax_amount: 0,
  cgst_amount: 0,
  sgst_amount: 0,
  igst_amount: 0,
  line_total: 0,
  description: 'Blue',
  discount_type: 'percentage',
  discount_value: 10,
};

describe('voucher helpers', () => {
  it('tells quotes from the rest', () => {
    expect(isQuotationVoucher('quotation')).toBe(true);
    expect(isQuotationVoucher('proforma')).toBe(true);
    expect(isQuotationVoucher('sales')).toBe(false);
    expect(isQuotationVoucher('purchase')).toBe(false);
  });

  it('counts quotes as selling, but not purchases or money', () => {
    expect(isSaleLikeVoucher('sales')).toBe(true);
    expect(isSaleLikeVoucher('quotation')).toBe(true);
    expect(isSaleLikeVoucher('proforma')).toBe(true);
    expect(isSaleLikeVoucher('purchase')).toBe(false);
    expect(isSaleLikeVoucher('receipt')).toBe(false);
  });

  it('names the document', () => {
    expect(composerDocumentName('quotation')).toBe('quotation');
    expect(composerDocumentName('proforma')).toBe('proforma invoice');
    expect(composerDocumentName('sales')).toBe('invoice');
  });
});

describe('validity dates', () => {
  it('defaults to thirty days on', () => {
    expect(defaultValidUntil('2026-06-01')).toBe('2026-07-01');
  });

  it('crosses months and years', () => {
    expect(addDaysToIsoDate('2026-12-20', 30)).toBe('2027-01-19');
  });

  it('gives nothing for a blank date rather than an invalid one', () => {
    expect(defaultValidUntil('')).toBe('');
  });
});

describe('conversionLineShortfalls', () => {
  const quoted = [{ product_id: 5, quantity: 5 }, { product_id: 6, quantity: 1 }];

  it('is empty when every quoted unit is on the invoice', () => {
    expect(conversionLineShortfalls(quoted, [
      { productId: 5, quantity: 5 },
      { productId: 6, quantity: 1 },
    ])).toEqual([]);
  });

  it('names a partly scanned or reduced line', () => {
    expect(conversionLineShortfalls(quoted, [
      { productId: 5, quantity: 3 },
      { productId: 6, quantity: 1 },
    ])).toEqual([{ productId: 5, quoted: 5, onInvoice: 3 }]);
  });

  it('counts a removed line as nothing on the invoice', () => {
    expect(conversionLineShortfalls(quoted, [{ productId: 5, quantity: 5 }])).toEqual([
      { productId: 6, quoted: 1, onInvoice: 0 },
    ]);
  });

  it('adds up a product split across lines, and ignores extras', () => {
    expect(conversionLineShortfalls(quoted, [
      { productId: 5, quantity: 2 },
      { productId: 5, quantity: 4 },
      { productId: 6, quantity: 1 },
      { productId: 7, quantity: 9 },
    ])).toEqual([]);
  });

  it('treats a blank quantity box as nothing rather than failing', () => {
    expect(conversionLineShortfalls([{ product_id: 5, quantity: 1 }], [{ productId: 5, quantity: Number.NaN }])).toEqual([
      { productId: 5, quoted: 1, onInvoice: 0 },
    ]);
  });
});

describe('form items', () => {
  it('fills the form from a saved quotation, keeping a price of zero', () => {
    const [item] = quotationToFormItems({ items: [line] });
    expect(item).toEqual({
      id: 1,
      productId: '5',
      quantity: '3',
      unit_price: '0',
      description: 'Blue',
      discount_type: 'percentage',
      discount_value: '10',
      serials: [],
      autoFilled: false,
    });
  });

  it('starts a conversion with no serials, whatever the draft says', () => {
    const items = conversionDraftToFormItems({
      items: [{ product_id: 5, quantity: 2, unit_price: 100, serial_numbers: ['IMEI-1', 'IMEI-2'] }],
    });
    expect(items[0].serials).toEqual([]);
  });

  it('never sends a serial or a tax rate on a quotation line', () => {
    const payload = formItemToQuotationLine({
      id: 1,
      productId: '5',
      quantity: '2',
      unit_price: '100',
      description: '',
      discount_type: '',
      discount_value: '',
      serials: ['IMEI-1'],
      autoFilled: false,
    });
    expect(payload).toEqual({
      product_id: 5,
      quantity: 2,
      unit_price: 100,
      description: undefined,
      discount_type: null,
      discount_value: null,
    });
    expect(payload).not.toHaveProperty('serial_numbers');
    expect(payload).not.toHaveProperty('gst_rate');
  });

  it('sends the version of the quotation the draft came from, digit for digit', () => {
    const edited = { voucher_type: 'sales' as const, ledger_id: 3, items: [] };
    const stamp = '2026-11-03T10:15:30.123456';
    const payload = conversionPayload(edited, {
      invoice: { voucher_type: 'sales', ledger_id: 9, items: [], quotation_updated_at: stamp },
    });
    expect(payload.quotation_updated_at).toBe(stamp);
    // Only the stamp comes from the draft. What was changed on the form stays changed.
    expect(payload.ledger_id).toBe(3);
  });
});
