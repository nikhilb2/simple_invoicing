import { describe, expect, test } from 'vitest';
import { GST_SLABS, HSN_ERROR, hsnProblem, isGstSlab, plainProductError, startsWithNoStock } from './productFormRules';

describe('GST slabs', () => {
  test('offers the standard rates and recognises them however they are written', () => {
    expect(GST_SLABS).toEqual([0, 5, 12, 18, 28, 40]);
    expect(isGstSlab('18')).toBe(true);
    expect(isGstSlab('5.00')).toBe(true);
    expect(isGstSlab('0')).toBe(true);
  });

  test('treats an unusual rate, or no choice yet, as not a slab', () => {
    expect(isGstSlab('')).toBe(false);
    expect(isGstSlab('0.25')).toBe(false);
    expect(isGstSlab('3')).toBe(false);
  });
});

describe('HSN/SAC', () => {
  test('accepts blank and 4, 6 or 8 digits', () => {
    for (const code of ['', ' ', '6109', '610910', '61091000']) expect(hsnProblem(code)).toBe('');
  });

  test('says what is wrong in words, not a column name', () => {
    for (const code of ['610', '61091', 'abcd']) expect(hsnProblem(code)).toBe(HSN_ERROR);
    expect(HSN_ERROR).not.toMatch(/hsn sac:/i);
  });

  test('rewrites the server message that names the column, and leaves others alone', () => {
    expect(plainProductError('Hsn sac: HSN/SAC must be 4, 6 or 8 digits')).toBe(HSN_ERROR);
    expect(plainProductError('SKU already exists')).toBe('SKU already exists');
  });
});

describe('opening stock', () => {
  test('flags a tracked product that starts at zero, and only that', () => {
    expect(startsWithNoStock(true, 0)).toBe(true);
    expect(startsWithNoStock(true, 4)).toBe(false);
    expect(startsWithNoStock(false, 0)).toBe(false);
  });
});
