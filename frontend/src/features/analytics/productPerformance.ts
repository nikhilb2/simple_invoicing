import formatCurrency from '../../utils/formatting';
import type {
  PerformanceSortBy,
  ProductPerformanceMonthlyRow,
  ProductPerformanceProduct,
  ProductPerformanceRow,
  ProductSalesVelocity,
  SortDir,
} from './types';

/** Shown wherever a figure is undefined (no cost known, nothing sold). */
export const EMPTY_CELL = '—';

/** Currency, or "—" for null. A null margin must never render as ₹0.00. */
export function formatMoneyOrDash(value: number | null, currencyCode: string): string {
  return value === null ? EMPTY_CELL : formatCurrency(value, currencyCode);
}

export function formatPctOrDash(value: number | null): string {
  return value === null ? EMPTY_CELL : `${value.toFixed(1)}%`;
}

/**
 * The fallback marker: true when the row's cost is the product's current
 * purchase price because it had no purchases in the period, so its margin is
 * an estimate rather than what the goods actually cost.
 */
export function usesCurrentPriceCost(row: Pick<ProductPerformanceRow, 'cost_basis'>): boolean {
  return row.cost_basis === 'current_price';
}

/** Profit colouring: only a known, negative profit is a loss. */
export function isLoss(value: number | null): boolean {
  return value !== null && value < 0;
}

/**
 * Clicking the active column flips its direction; clicking a new column starts
 * at the direction a reader expects first — A→Z for names, biggest first for
 * numbers.
 */
export function nextSort(
  current: { sortBy: PerformanceSortBy; sortDir: SortDir },
  clicked: PerformanceSortBy,
): { sortBy: PerformanceSortBy; sortDir: SortDir } {
  if (current.sortBy === clicked) {
    return { sortBy: clicked, sortDir: current.sortDir === 'asc' ? 'desc' : 'asc' };
  }
  return { sortBy: clicked, sortDir: clicked === 'name' ? 'asc' : 'desc' };
}

/** aria-sort value for a column header. */
export function ariaSort(
  current: { sortBy: PerformanceSortBy; sortDir: SortDir },
  column: PerformanceSortBy,
): 'ascending' | 'descending' | 'none' {
  if (current.sortBy !== column) return 'none';
  return current.sortDir === 'asc' ? 'ascending' : 'descending';
}

// --- Per-product page --------------------------------------------------------

/** The tab a "Back" link from the product page returns to. */
export const PERFORMANCE_TAB = 'product-performance';

/**
 * Links between the tab and the product page carry the query string across —
 * period, party and any product filter — so drilling in and coming back shows
 * the same view. `tab` is the one param that belongs to the Analytics page.
 */
export function productDetailHref(productId: number, search: URLSearchParams): string {
  const next = new URLSearchParams(search);
  next.delete('tab');
  const query = next.toString();
  return `/analytics/products/${productId}${query ? `?${query}` : ''}`;
}

export function performanceTabHref(search: URLSearchParams): string {
  const next = new URLSearchParams(search);
  next.set('tab', PERFORMANCE_TAB);
  return `/analytics?${next.toString()}`;
}

/** Units can be fractional (kg, metres); show up to three places, grouped. */
export function formatUnits(value: number): string {
  return value.toLocaleString('en-US', { maximumFractionDigits: 3 });
}

/** Share of units sold that came back, or null when nothing sold. */
export function returnRatePct(row: Pick<ProductPerformanceRow, 'units_sold' | 'units_returned'>): number | null {
  return row.units_sold > 0 ? (row.units_returned / row.units_sold) * 100 : null;
}

export type StockStatus = 'untracked' | 'out' | 'low' | 'ok';

/**
 * "low" is at or under the reorder level, when one is set. A product with no
 * reorder level is never low on that count: 0 means "not configured" there.
 */
export function stockStatus(product: Pick<ProductPerformanceProduct, 'current_stock' | 'reorder_level'>): StockStatus {
  if (product.current_stock === null) return 'untracked';
  if (product.current_stock <= 0) return 'out';
  if (product.reorder_level > 0 && product.current_stock <= product.reorder_level) return 'low';
  return 'ok';
}

/**
 * "≈ 12 days", "under a day", "over a year", or "—" when no rate is known.
 * Past a year the exact figure is noise: the period's pace won't hold that long.
 */
export function formatCoverDays(velocity: Pick<ProductSalesVelocity, 'stock_cover_days'>): string {
  const days = velocity.stock_cover_days;
  if (days === null) return EMPTY_CELL;
  if (days < 1) return 'under a day';
  if (days > 365) return 'over a year';
  const whole = Math.round(days);
  return `≈ ${whole} day${whole === 1 ? '' : 's'}`;
}

/** Units sold per month at the period's daily rate (an average month). */
export function monthlyRate(velocity: Pick<ProductSalesVelocity, 'daily_sales_rate'>): number | null {
  return velocity.daily_sales_rate === null ? null : velocity.daily_sales_rate * (365.25 / 12);
}

type MonthActivity = Pick<
  ProductPerformanceMonthlyRow,
  'month' | 'units_sold' | 'units_bought' | 'return_value' | 'purchase_return_value'
>;

/** Nothing sold, bought or credited in the month. */
export function isQuietMonth(row: MonthActivity): boolean {
  return row.units_sold === 0 && row.units_bought === 0 && row.return_value === 0 && row.purchase_return_value === 0;
}

/**
 * The months worth drawing: a financial year runs to March, but months that
 * haven't happened yet would only flatten every chart to zero on the right.
 * Trailing future months are dropped only while they are empty, so a
 * post-dated invoice still shows. Totals are unaffected — those months are 0.
 */
export function visibleMonths<T extends MonthActivity>(rows: T[], today: Date = new Date()): T[] {
  const current = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`;
  let end = rows.length;
  while (end > 0 && rows[end - 1].month > current && isQuietMonth(rows[end - 1])) end -= 1;
  return rows.slice(0, end);
}
