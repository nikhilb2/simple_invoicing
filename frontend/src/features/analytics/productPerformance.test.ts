import { describe, expect, it } from 'vitest';
import {
  EMPTY_CELL,
  ariaSort,
  formatMoneyOrDash,
  formatPctOrDash,
  isLoss,
  nextSort,
  usesCurrentPriceCost,
} from './productPerformance';

describe('formatMoneyOrDash', () => {
  it('renders null as a dash, not zero', () => {
    expect(formatMoneyOrDash(null, 'INR')).toBe(EMPTY_CELL);
  });

  it('formats a real value, including zero', () => {
    expect(formatMoneyOrDash(0, 'USD')).toBe('$0.00');
    expect(formatMoneyOrDash(1234.5, 'USD')).toBe('$1,234.50');
  });
});

describe('formatPctOrDash', () => {
  it('renders null as a dash', () => {
    expect(formatPctOrDash(null)).toBe(EMPTY_CELL);
  });

  it('rounds to one decimal place', () => {
    expect(formatPctOrDash(35)).toBe('35.0%');
    expect(formatPctOrDash(-12.345)).toBe('-12.3%');
  });
});

describe('usesCurrentPriceCost', () => {
  it('flags only the current-price fallback', () => {
    expect(usesCurrentPriceCost({ cost_basis: 'current_price' })).toBe(true);
    expect(usesCurrentPriceCost({ cost_basis: 'purchases' })).toBe(false);
    expect(usesCurrentPriceCost({ cost_basis: null })).toBe(false);
  });
});

describe('isLoss', () => {
  it('treats an unknown profit as neither profit nor loss', () => {
    expect(isLoss(null)).toBe(false);
    expect(isLoss(0)).toBe(false);
    expect(isLoss(-0.01)).toBe(true);
  });
});

describe('nextSort', () => {
  it('flips direction on the active column', () => {
    expect(nextSort({ sortBy: 'revenue', sortDir: 'desc' }, 'revenue')).toEqual({ sortBy: 'revenue', sortDir: 'asc' });
    expect(nextSort({ sortBy: 'revenue', sortDir: 'asc' }, 'revenue')).toEqual({ sortBy: 'revenue', sortDir: 'desc' });
  });

  it('starts numbers biggest-first and names A to Z', () => {
    expect(nextSort({ sortBy: 'name', sortDir: 'asc' }, 'gross_profit')).toEqual({
      sortBy: 'gross_profit',
      sortDir: 'desc',
    });
    expect(nextSort({ sortBy: 'revenue', sortDir: 'desc' }, 'name')).toEqual({ sortBy: 'name', sortDir: 'asc' });
  });
});

describe('ariaSort', () => {
  it('marks only the active column', () => {
    const current = { sortBy: 'margin_pct' as const, sortDir: 'asc' as const };
    expect(ariaSort(current, 'margin_pct')).toBe('ascending');
    expect(ariaSort(current, 'revenue')).toBe('none');
  });
});
