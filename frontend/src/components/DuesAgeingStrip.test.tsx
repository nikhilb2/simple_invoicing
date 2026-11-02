import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';
import { DuesAgeingTiles } from './DuesAgeingStrip';
import type { DuesAgeing } from '../types/api';

const ageing: DuesAgeing = {
  as_of_date: '2026-10-29',
  buckets: [
    { key: 'not_yet_due', label: 'Not yet due', invoice_count: 2, total_remaining: 150 },
    { key: '1_30', label: '1 to 30 days overdue', invoice_count: 1, total_remaining: 200 },
    { key: '31_60', label: '31 to 60 days overdue', invoice_count: 1, total_remaining: 200 },
    { key: '61_90', label: '61 to 90 days overdue', invoice_count: 1, total_remaining: 150 },
    { key: 'over_90', label: 'Over 90 days overdue', invoice_count: 1, total_remaining: 400 },
  ],
  total_invoice_count: 6,
  total_remaining: 1100,
};

describe('DuesAgeingTiles', () => {
  test('shows every bucket with its amount and invoice count, plus the total', () => {
    const html = renderToStaticMarkup(<DuesAgeingTiles ageing={ageing} currencyCode="INR" />);

    expect(html).toContain('Not yet due');
    expect(html).toContain('1 to 30 days overdue');
    expect(html).toContain('31 to 60 days overdue');
    expect(html).toContain('61 to 90 days overdue');
    expect(html).toContain('Over 90 days overdue');
    expect(html).toContain('Total outstanding');
    expect(html).toContain('(2)');
    expect(html).toContain('(6)');
    expect(html).toContain('1,100');
  });

  test('shows zero buckets as zero, not as missing tiles', () => {
    const empty: DuesAgeing = {
      as_of_date: '2026-10-29',
      buckets: ageing.buckets.map((bucket) => ({ ...bucket, invoice_count: 0, total_remaining: 0 })),
      total_invoice_count: 0,
      total_remaining: 0,
    };
    const html = renderToStaticMarkup(<DuesAgeingTiles ageing={empty} currencyCode="INR" />);

    expect(html).toContain('Not yet due');
    expect(html).toContain('Over 90 days overdue');
    expect(html).toContain('(0)');
  });
});
