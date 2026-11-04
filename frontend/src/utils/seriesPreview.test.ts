import { describe, expect, test } from 'vitest';
import type { InvoiceSeries, InvoiceSeriesUpdate } from '../types/api';
import { buildSeriesPreview, gstr1SeriesFormatError } from './seriesPreview';

const format: Required<InvoiceSeriesUpdate> = {
  prefix: 'INV', suffix: '', include_year: true, year_format: 'YYYY',
  separator: '-', pad_digits: 3, next_sequence: 1,
};
const now = new Date('2026-04-15T12:00:00Z');

describe('buildSeriesPreview matches server formatting', () => {
  test.each<[Partial<InvoiceSeriesUpdate>, number, string | null, string]>([
    [{}, 1, null, 'INV-2026-001'],
    [{ year_format: 'MM-YYYY', separator: '//' }, 2, null, 'INV//04//2026//002'],
    [{ year_format: 'FY' }, 3, '2025-26', 'INV-2025-26-003'],
    [{ year_format: 'FY' }, 3, null, 'INV-FY-003'],
    [{ include_year: false }, 4, null, 'INV-004'],
    [{ include_year: false, separator: '' }, 4, null, 'INV004'],
    [{ include_year: false }, 1000, null, 'INV-1000'],
    [{ prefix: ' inv ', suffix: ' /a ' }, 1, null, 'INV-2026-001/A'],
  ])('%j, counter %i', (patch, counter, label, expected) => {
    expect(buildSeriesPreview({ ...format, ...patch }, counter, label, now)).toBe(expected);
  });

  test('uses the same UTC year/month as the server at a timezone boundary', () => {
    expect(buildSeriesPreview(
      { ...format, year_format: 'MM-YYYY' }, 1, null, new Date('2026-12-31T23:45:00Z'),
    )).toBe('INV-12-2026-001');
  });
});

const saved: InvoiceSeries = { ...format, id: 1, voucher_type: 'sales', created_at: null };
const gstin = '27AAPFU0939F1ZV';
const errorFor = (patch: Partial<InvoiceSeriesUpdate>, original = saved, gst = gstin) =>
  gstr1SeriesFormatError({ ...original, ...patch }, original, gst, null, now);

describe('GSTR-1 format validation', () => {
  test('accepts 16 characters and rejects 17, reserving four counter digits', () => {
    expect(buildSeriesPreview({ ...format, prefix: 'ABCDEF' }, 9999, null, now)).toHaveLength(16);
    expect(errorFor({ prefix: 'ABCDEF' })).toBeNull();
    expect(buildSeriesPreview({ ...format, prefix: 'ABCDEFG' }, 1, null, now)).toHaveLength(16);
    expect(errorFor({ prefix: 'ABCDEFG' })).toContain('16 characters');
  });

  test('checks a counter larger than 9999', () => {
    expect(errorFor({ prefix: 'ABCDEF', next_sequence: 10000 })).toContain('16 characters');
  });

  test.each(['IN V', 'INV_', 'INV.', 'INV\nX', 'INVé'])('rejects disallowed prefix %j', prefix => {
    expect(errorFor({ prefix, include_year: false })).toContain('only contain');
  });

  test.each(['-', '/', ''])('rejects a non-alphanumeric first character with prefix %j', prefix => {
    expect(errorFor({ prefix, include_year: false })).toContain('start with');
  });

  test('validates suffixes and separators too', () => {
    expect(errorFor({ suffix: '_', include_year: false })).toContain('only contain');
    expect(errorFor({ separator: ' ', include_year: false })).toContain('only contain');
    expect(errorFor({ suffix: '/A', separator: '/', include_year: false })).toBeNull();
  });

  test.each(['sales', 'credit_note'])('checks registered %s series', voucher_type => {
    expect(errorFor({ prefix: 'INVALID_' }, { ...saved, voucher_type })).not.toBeNull();
  });

  test.each(['purchase', 'debit_note', 'payment', 'quotation', 'proforma'])('exempts %s series', voucher_type => {
    expect(errorFor({ prefix: 'INVALID_' }, { ...saved, voucher_type })).toBeNull();
  });

  test.each(['', '   '])('exempts companies without a saved GSTIN (%j)', gst => {
    expect(errorFor({ prefix: 'INVALID_' }, saved, gst)).toBeNull();
  });

  test('permits a counter-only edit of an already invalid format', () => {
    const legacy = { ...saved, prefix: 'LEGACY_' };
    expect(errorFor({ next_sequence: 100000 }, legacy)).toBeNull();
    expect(errorFor({ prefix: ' legacy_ ', next_sequence: 42 }, legacy)).toBeNull();
  });

  test.each<Partial<InvoiceSeriesUpdate>>([
    { prefix: 'OTHER_' }, { suffix: '/A' }, { include_year: false },
    { year_format: 'FY' }, { separator: '/' }, { pad_digits: 4 },
  ])('checks every changed format field: %j', patch => {
    expect(errorFor(patch, { ...saved, prefix: 'LEGACY_' })).not.toBeNull();
  });
});
