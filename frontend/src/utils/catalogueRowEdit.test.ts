import { expect, test } from 'vitest';
import { parseRowEdit } from './catalogueRowEdit';

const base = {
  name: 'Widget',
  sku: 'W-1',
  selling_price: '10',
  purchase_price: '5',
  reorder_level: '2',
  gst_rate: '18',
};

test('parses normal values', () => {
  const r = parseRowEdit(base);
  expect(r.ok).toBe(true);
  if (r.ok) {
    expect(r.value.selling_price).toBe(10);
    expect(r.value.gst_rate).toBe(18);
  }
});

test('rejects empty string', () => {
  const r = parseRowEdit({ ...base, selling_price: '' });
  expect(r.ok).toBe(false);
  if (!r.ok) expect(r.error).toBe('Selling price must be a number of 0 or more.');
});

test('rejects whitespace', () => {
  const r = parseRowEdit({ ...base, selling_price: '  ' });
  expect(r.ok).toBe(false);
});

test('rejects non-numeric', () => {
  const r = parseRowEdit({ ...base, selling_price: 'abc' });
  expect(r.ok).toBe(false);
});

test('rejects negative', () => {
  const r = parseRowEdit({ ...base, selling_price: '-1' });
  expect(r.ok).toBe(false);
});

test('accepts zero', () => {
  const r = parseRowEdit({ ...base, selling_price: '0' });
  expect(r.ok).toBe(true);
});

test('rejects gst over 100', () => {
  const r = parseRowEdit({ ...base, gst_rate: '100.01' });
  expect(r.ok).toBe(false);
});

test('accepts gst 18', () => {
  const r = parseRowEdit({ ...base, gst_rate: '18' });
  expect(r.ok).toBe(true);
});
