import { describe, expect, test } from 'vitest';
import { invoiceDraftSnapshot, type InvoiceDraft, type InvoiceDraftItem } from './invoiceDraft';

function item(overrides: Partial<InvoiceDraftItem> = {}): InvoiceDraftItem {
  return {
    id: 1,
    productId: '7',
    quantity: '1',
    unit_price: '250',
    description: '',
    discount_type: '',
    discount_value: '',
    serials: [],
    ...overrides,
  };
}

function draft(overrides: Partial<InvoiceDraft> = {}): InvoiceDraft {
  return {
    ledgerId: '3',
    voucherType: 'sales',
    taxInclusive: false,
    invoiceDate: '2026-04-10',
    dueDateMode: 'none',
    dueDate: '',
    dueDateDays: '',
    referenceNotes: '',
    items: [item()],
    ...overrides,
  };
}

describe('invoiceDraftSnapshot', () => {
  test('is the same for an untouched form', () => {
    expect(invoiceDraftSnapshot(draft())).toBe(invoiceDraftSnapshot(draft()));
  });

  test.each<[string, Partial<InvoiceDraft>]>([
    ['ledger', { ledgerId: '4' }],
    ['voucher type', { voucherType: 'purchase' }],
    ['tax-inclusive toggle', { taxInclusive: true }],
    ['invoice date', { invoiceDate: '2026-04-11' }],
    ['due date mode', { dueDateMode: 'days' }],
    ['exact due date', { dueDate: '2026-05-10' }],
    ['due in days', { dueDateDays: '30' }],
    ['reference notes', { referenceNotes: 'PO 4471' }],
    ['an added line', { items: [item(), item({ id: 2 })] }],
  ])('changes when the %s changes', (_field, change) => {
    expect(invoiceDraftSnapshot(draft(change))).not.toBe(invoiceDraftSnapshot(draft()));
  });

  test.each<[string, Partial<InvoiceDraftItem>]>([
    ['product', { productId: '8' }],
    ['quantity', { quantity: '2' }],
    ['unit price', { unit_price: '300' }],
    ['description', { description: 'Gift wrapped' }],
    ['discount type', { discount_type: 'percentage' }],
    ['discount value', { discount_value: '5' }],
    ['serials', { serials: ['SN-001'] }],
  ])('changes when a line %s changes', (_field, change) => {
    expect(invoiceDraftSnapshot(draft({ items: [item(change)] }))).not.toBe(invoiceDraftSnapshot(draft()));
  });

  test('ignores line ids, so adding a line and removing the original loses nothing', () => {
    expect(invoiceDraftSnapshot(draft({ items: [item({ id: 2 })] }))).toBe(invoiceDraftSnapshot(draft()));
  });

  test('keeps line order', () => {
    const a = item({ productId: '7' });
    const b = item({ id: 2, productId: '8' });
    expect(invoiceDraftSnapshot(draft({ items: [a, b] }))).not.toBe(invoiceDraftSnapshot(draft({ items: [b, a] })));
  });
});
