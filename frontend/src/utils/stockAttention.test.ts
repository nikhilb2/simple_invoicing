import { describe, expect, it } from 'vitest';
import { needsStockAttention } from './stockAttention';

describe('needsStockAttention', () => {
  const cases: [number, number, boolean][] = [
    [-1, 0, true],
    [0, 0, true],
    [1, 0, false],
    [5, 0, false],
    [20, 50, true],
    [50, 50, true],
    [51, 50, false],
    [3, 2, false],
    [0.5, 1, true],
    [0.5, 0, false],
  ];
  it.each(cases)('quantity %s with reorder level %s needs attention: %s', (quantity, reorder, expected) => {
    expect(needsStockAttention(quantity, reorder)).toBe(expected);
  });

  it('treats a missing reorder level as zero', () => {
    expect(needsStockAttention(1)).toBe(false);
    expect(needsStockAttention(0)).toBe(true);
  });
});
