/**
 * Ledger list filters in the URL, so a filtered view survives a refresh, a
 * back navigation or a shared link. Follows the Day Book pattern
 * (dayBookFilters.ts): the Ledgers search is `q`, the sort choice is
 * `sort` and the page number is `page`.
 *
 * The defaults stay out of the URL so links stay clean: an empty search,
 * `name` sorting and page 1 mean no `q`, `sort` or `page` param at all.
 * Page size is deliberately not part of this: it is already remembered in
 * localStorage by the page itself, so it is left alone.
 */

/** The sort values the Ledgers page select offers. */
export const LEDGER_SORTS = ['name', '-name', 'newest', 'balance_desc'] as const;

/** The Ledger list filters as read from a query string. */
export interface LedgerListFilters {
  search: string;
  sort: string;
  page: number;
}

/**
 * Read the filters out of a query string, validating what comes from the
 * URL. An unknown sort falls back to `name` and a page that is not a
 * positive integer falls back to 1, so a stale or hand edited link never
 * breaks the page.
 */
export function parseLedgerListFilters(params: URLSearchParams): LedgerListFilters {
  const requestedSort = params.get('sort') ?? 'name';
  const sort = (LEDGER_SORTS as readonly string[]).includes(requestedSort) ? requestedSort : 'name';
  const rawPage = params.get('page');
  const page = rawPage !== null && /^\d+$/.test(rawPage) && Number(rawPage) >= 1 ? Number(rawPage) : 1;
  return {
    search: params.get('q') ?? '',
    sort,
    page,
  };
}

/**
 * Build the query string for a filter state, starting from `base` so
 * unrelated params on the URL are preserved. Defaults are omitted: a blank
 * search drops `q`, `name` drops `sort` and page 1 drops `page`.
 */
export function buildLedgerListParams(
  filters: LedgerListFilters,
  base: URLSearchParams = new URLSearchParams(),
): URLSearchParams {
  const next = new URLSearchParams(base);
  if (filters.search.trim() === '') next.delete('q');
  else next.set('q', filters.search);
  if (filters.sort === 'name') next.delete('sort');
  else next.set('sort', filters.sort);
  if (filters.page <= 1) next.delete('page');
  else next.set('page', String(filters.page));
  return next;
}
