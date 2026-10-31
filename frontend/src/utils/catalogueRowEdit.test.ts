import { describe, expect, test } from 'vitest';
import type { RowEdit } from '../pages/catalogue/types';
import { parseRowEdit } from './catalogueRowEdit';

const valid: RowEdit = {
  name: '  Product  ', sku: ' SKU ', selling_price: '125.50',
  purchase_price: '100', reorder_level: '5', gst_rate: '18',
};

describe('parseRowEdit', () => {
  test('returns only the editable payload with trimmed identifiers and numeric values', () => {
    expect(parseRowEdit(valid)).toEqual({
      ok: true,
      value: { name: 'Product', sku: 'SKU', selling_price: 125.5, purchase_price: 100, reorder_level: 5, gst_rate: 18 },
    });
  });

  describe.each([
    ['selling_price', 'Selling price'], ['purchase_price', 'Purchase price'],
    ['reorder_level', 'Reorder level'], ['gst_rate', 'GST rate'],
  ] as const)('%s', (field, label) => {
    test.each(['', '  '])('rejects a blank field %j', (value) => {
      expect(parseRowEdit({ ...valid, [field]: value })).toEqual({ ok: false, error: `${label} is required.` });
    });
    test.each(['abc', '-1', 'Infinity', '1e309'])('rejects invalid numeric value %j', (value) => {
      expect(parseRowEdit({ ...valid, [field]: value }).ok).toBe(false);
    });
    test('accepts an explicit zero', () => {
      const result = parseRowEdit({ ...valid, [field]: '0' });
      expect(result.ok).toBe(true);
      if (result.ok) expect(result.value[field]).toBe(0);
    });
  });

  test.each(['100.01', '101'])('rejects GST above 100: %s', (gst_rate) => {
    expect(parseRowEdit({ ...valid, gst_rate })).toEqual({ ok: false, error: 'GST rate must be between 0 and 100.' });
  });
  test.each(['18', '100'])('accepts GST within its inclusive range: %s', (gst_rate) => {
    expect(parseRowEdit({ ...valid, gst_rate }).ok).toBe(true);
  });
  test.each(['', '  '])('keeps the name and SKU required: %j', (value) => {
    expect(parseRowEdit({ ...valid, name: value })).toEqual({ ok: false, error: 'Product name cannot be empty.' });
    expect(parseRowEdit({ ...valid, sku: value })).toEqual({ ok: false, error: 'SKU cannot be empty.' });
  });
});
