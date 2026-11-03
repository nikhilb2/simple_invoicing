/**
 * Day Book filters in the URL, so a filtered view survives a refresh and can
 * be shared as a link. Mirrors the Catalogue page, which carries its search
 * in `q`: the Day Book search is `q` and the voucher-type filter is `type`.
 *
 * The defaults stay out of the URL so links stay clean: an empty search and
 * `all` voucher types mean no `q` and no `type` param at all. The date range
 * is deliberately not part of this: it already has its own handling on the
 * page and the issue leaves it alone.
 */

/** The Day Book filters as read from a query string. */
export interface DayBookFilters {
  search: string;
  voucherType: string;
}

/** Read the filters out of a query string, defaulting to an empty search and `all` types. */
export function parseDayBookFilters(params: URLSearchParams): DayBookFilters {
  return {
    search: params.get('q') ?? '',
    voucherType: params.get('type') ?? 'all',
  };
}

/**
 * The voucher type the page actually filters on.
 *
 * A `type` in the URL that is not among the loaded entries (a stale link, a
 * typo) falls back to `all` instead of showing an empty register with no way
 * to see why. While nothing has loaded yet the available list is empty and
 * the requested value is passed through untouched, so the decision is made
 * once the entries are known rather than on an empty list.
 */
export function resolveVoucherType(requested: string, available: string[]): string {
  if (requested === '' || requested === 'all') return 'all';
  if (available.length === 0) return requested;
  return available.includes(requested) ? requested : 'all';
}

/**
 * Build the query string for a filter state, starting from `base` so unrelated
 * params on the URL are preserved. Defaults are omitted: a blank search drops
 * `q` and `all` drops `type`.
 */
export function buildDayBookParams(
  filters: DayBookFilters,
  base: URLSearchParams = new URLSearchParams(),
): URLSearchParams {
  const next = new URLSearchParams(base);
  if (filters.search.trim() === '') next.delete('q');
  else next.set('q', filters.search);
  if (filters.voucherType === '' || filters.voucherType === 'all') next.delete('type');
  else next.set('type', filters.voucherType);
  return next;
}
