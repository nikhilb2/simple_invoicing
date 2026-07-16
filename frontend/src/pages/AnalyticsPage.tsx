import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import Tabs, { TabPanel, type TabItem } from '../components/Tabs';
import { useFY } from '../context/FYContext';
import type { AnalyticsFilters as Filters, VoucherType } from '../features/analytics/types';
import AnalyticsFilters from './analytics/AnalyticsFilters';
import MonthlySalesTab from './analytics/MonthlySalesTab';
import ProductSalesTab from './analytics/ProductSalesTab';

type TabId = 'month-wise' | 'product-wise';

const TABS: TabItem<TabId>[] = [
  { id: 'month-wise', label: 'Month-wise Sales' },
  { id: 'product-wise', label: 'Product-wise Sales' },
];

/**
 * Tabs and filters live in the query string rather than component state, so a
 * report is linkable and bookmarkable — you can send someone the exact view.
 * (The app's two older tab bars keep this in local state and can't.)
 */
export default function AnalyticsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { activeFY } = useFY();

  const tab: TabId = searchParams.get('tab') === 'product-wise' ? 'product-wise' : 'month-wise';

  const filters: Filters = useMemo(() => {
    const fyParam = searchParams.get('fy');
    const from = searchParams.get('from') ?? undefined;
    const to = searchParams.get('to') ?? undefined;

    // With nothing in the URL, default to the active FY. Its dates are sent
    // explicitly so the view doesn't silently change when the FY is switched.
    if (!fyParam && !from && !to && activeFY) {
      return {
        voucherType: (searchParams.get('type') as VoucherType) ?? 'sales',
        financialYearId: activeFY.id,
        fromDate: activeFY.start_date,
        toDate: activeFY.end_date,
        ledgerId: searchParams.get('ledger') ? Number(searchParams.get('ledger')) : undefined,
        productId: searchParams.get('product') ? Number(searchParams.get('product')) : undefined,
      };
    }

    return {
      voucherType: (searchParams.get('type') as VoucherType) ?? 'sales',
      financialYearId: fyParam ? Number(fyParam) : undefined,
      fromDate: from,
      toDate: to,
      ledgerId: searchParams.get('ledger') ? Number(searchParams.get('ledger')) : undefined,
      productId: searchParams.get('product') ? Number(searchParams.get('product')) : undefined,
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

  const onFiltersChange = (next: Filters) => {
    patchParams({
      type: next.voucherType,
      fy: next.financialYearId ? String(next.financialYearId) : undefined,
      from: next.fromDate,
      to: next.toDate,
      ledger: next.ledgerId ? String(next.ledgerId) : undefined,
      product: next.productId ? String(next.productId) : undefined,
    });
  };

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Reports</p>
          <h1 className="page-title">Analytics</h1>
          <p className="section-copy">
            Sales performance by month and by product, across any date range.
          </p>
        </div>
      </section>

      <AnalyticsFilters
        filters={filters}
        onChange={onFiltersChange}
        showProductFilter={tab === 'product-wise'}
      />

      <Tabs
        tabs={TABS}
        value={tab}
        onChange={(id) => patchParams({ tab: id })}
        label="Analytics reports"
      />

      <TabPanel id={tab}>
        {tab === 'month-wise' ? (
          <MonthlySalesTab filters={filters} />
        ) : (
          <ProductSalesTab filters={filters} />
        )}
      </TabPanel>
    </div>
  );
}
