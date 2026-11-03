import { describe, expect, it } from 'vitest';
import {
  EMPTY_CELL,
  ariaSort,
  formatCoverDays,
  formatMoneyOrDash,
  formatPctOrDash,
  formatUnits,
  isLoss,
  isQuietMonth,
  monthlyRate,
  nextSort,
  performanceTabHref,
  productDetailHref,
  returnRatePct,
  stockStatus,
  usesCurrentPriceCost,
  visibleMonths,
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

describe('productDetailHref / performanceTabHref', () => {
  it('carries the filters to the product page but not the tab', () => {
    const search = new URLSearchParams('tab=product-performance&fy=3&ledger=7');
    expect(productDetailHref(42, search)).toBe('/analytics/products/42?fy=3&ledger=7');
  });

  it('has no dangling ? without filters', () => {
    expect(productDetailHref(42, new URLSearchParams('tab=product-performance'))).toBe('/analytics/products/42');
  });

  it('returns to the performance tab with the same filters', () => {
    expect(performanceTabHref(new URLSearchParams('from=2026-01-01&to=2026-03-31'))).toBe(
      '/analytics?from=2026-01-01&to=2026-03-31&tab=product-performance',
    );
  });
});

describe('formatUnits', () => {
  it('groups thousands and keeps up to three decimals', () => {
    expect(formatUnits(12500)).toBe('12,500');
    expect(formatUnits(2.5)).toBe('2.5');
    expect(formatUnits(0.1234)).toBe('0.123');
  });
});

describe('returnRatePct', () => {
  it('is undefined when nothing sold', () => {
    expect(returnRatePct({ units_sold: 0, units_returned: 0 })).toBeNull();
    expect(returnRatePct({ units_sold: 10, units_returned: 4 })).toBe(40);
  });
});

describe('stockStatus', () => {
  it('distinguishes untracked, out, low and fine', () => {
    expect(stockStatus({ current_stock: null, reorder_level: 5 })).toBe('untracked');
    expect(stockStatus({ current_stock: 0, reorder_level: 0 })).toBe('out');
    expect(stockStatus({ current_stock: -2, reorder_level: 0 })).toBe('out');
    expect(stockStatus({ current_stock: 5, reorder_level: 5 })).toBe('low');
    expect(stockStatus({ current_stock: 6, reorder_level: 5 })).toBe('ok');
  });

  it('never calls stock low when no reorder level is set', () => {
    expect(stockStatus({ current_stock: 1, reorder_level: 0 })).toBe('ok');
  });
});

describe('formatCoverDays', () => {
  it('renders the edge cases as words', () => {
    expect(formatCoverDays({ stock_cover_days: null })).toBe(EMPTY_CELL);
    expect(formatCoverDays({ stock_cover_days: 0.4 })).toBe('under a day');
    expect(formatCoverDays({ stock_cover_days: 1.2 })).toBe('≈ 1 day');
    expect(formatCoverDays({ stock_cover_days: 44.6 })).toBe('≈ 45 days');
    expect(formatCoverDays({ stock_cover_days: 400 })).toBe('over a year');
  });
});

describe('monthlyRate', () => {
  it('scales the daily rate to an average month', () => {
    expect(monthlyRate({ daily_sales_rate: null })).toBeNull();
    expect(monthlyRate({ daily_sales_rate: 1 })).toBeCloseTo(30.44, 2);
  });
});

describe('visibleMonths', () => {
  const month = (key: string, unitsSold = 0) => ({
    month: key,
    units_sold: unitsSold,
    units_bought: 0,
    return_value: 0,
    purchase_return_value: 0,
  });
  const today = new Date(2026, 9, 28); // 28 Oct 2026

  it('drops empty months after the current one', () => {
    const rows = [month('2026-09', 3), month('2026-10'), month('2026-11'), month('2026-12')];
    expect(visibleMonths(rows, today).map((row) => row.month)).toEqual(['2026-09', '2026-10']);
  });

  it('keeps a future month that has entries, and the empty ones before it', () => {
    const rows = [month('2026-10'), month('2026-11'), month('2026-12', 1), month('2027-01')];
    expect(visibleMonths(rows, today).map((row) => row.month)).toEqual(['2026-10', '2026-11', '2026-12']);
  });

  it('keeps past empty months', () => {
    expect(visibleMonths([month('2026-01'), month('2026-02')], today)).toHaveLength(2);
    expect(isQuietMonth(month('2026-01'))).toBe(true);
    expect(isQuietMonth(month('2026-01', 2))).toBe(false);
  });
});
