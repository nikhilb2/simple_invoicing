import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useFY } from '../../context/FYContext';
import type { AnalyticsFilters, VoucherType } from './types';

/** Every filter the URL carries. `tab` is deliberately not one — resetting the
 *  filters shouldn't throw you back to a different report. */
export const FILTER_PARAMS = ['type', 'fy', 'from', 'to', 'ledger', 'product'] as const;

/**
 * Analytics filters live in the query string rather than component state, so a
 * report is linkable and bookmarkable — you can send someone the exact view.
 * Shared by the Analytics page and the per-product page so a link between the
 * two carries the same period and party across.
 */
export default function useAnalyticsFilters() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { activeFY } = useFY();

  const filters: AnalyticsFilters = useMemo(() => {
    const fyParam = searchParams.get('fy');
    const from = searchParams.get('from') ?? undefined;
    const to = searchParams.get('to') ?? undefined;
    const ledgerId = searchParams.get('ledger') ? Number(searchParams.get('ledger')) : undefined;
    const productId = searchParams.get('product') ? Number(searchParams.get('product')) : undefined;
    const voucherType = (searchParams.get('type') as VoucherType) ?? 'sales';

    // With nothing in the URL, default to the active FY. Its dates are sent
    // explicitly so the view doesn't silently change when the FY is switched.
    if (!fyParam && !from && !to && activeFY) {
      return {
        voucherType,
        financialYearId: activeFY.id,
        fromDate: activeFY.start_date,
        toDate: activeFY.end_date,
        ledgerId,
        productId,
      };
    }

    return {
      voucherType,
      financialYearId: fyParam ? Number(fyParam) : undefined,
      fromDate: from,
      toDate: to,
      ledgerId,
      productId,
    };
  }, [searchParams, activeFY]);

  const patchParams = (patch: Record<string, string | undefined>) => {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(patch)) {
      if (value === undefined || value === '') next.delete(key);
      else next.set(key, value);
    }
    // replace: switching tabs or nudging a filter shouldn't stack history entries.
    setSearchParams(next, { replace: true });
  };

  // Filters live entirely in the URL, so resetting is just dropping them —
  // `filters` then falls back to the active FY defaults above.
  const isFiltered = FILTER_PARAMS.some((param) => searchParams.has(param));

  const onResetFilters = () => {
    const next = new URLSearchParams(searchParams);
    FILTER_PARAMS.forEach((param) => next.delete(param));
    setSearchParams(next, { replace: true });
  };

  const onFiltersChange = (next: AnalyticsFilters) => {
    patchParams({
      type: next.voucherType,
      fy: next.financialYearId ? String(next.financialYearId) : undefined,
      from: next.fromDate,
      to: next.toDate,
      ledger: next.ledgerId ? String(next.ledgerId) : undefined,
      product: next.productId ? String(next.productId) : undefined,
    });
  };

  return { filters, searchParams, patchParams, isFiltered, onResetFilters, onFiltersChange };
}
