import formatCurrency from '../../utils/formatting';
import type { PerformanceSortBy, ProductPerformanceRow, SortDir } from './types';

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
