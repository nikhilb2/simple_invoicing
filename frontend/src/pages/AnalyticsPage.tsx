import Tabs, { TabPanel, type TabItem } from '../components/Tabs';
import useAnalyticsFilters from '../features/analytics/useAnalyticsFilters';
import AnalyticsFilters from './analytics/AnalyticsFilters';
import MonthlySalesTab from './analytics/MonthlySalesTab';
import ProductPerformanceTab from './analytics/ProductPerformanceTab';
import ProductSalesTab from './analytics/ProductSalesTab';
import ProfitLossTab from './analytics/ProfitLossTab';

type TabId = 'month-wise' | 'product-wise' | 'profit-loss' | 'product-performance';

const TABS: TabItem<TabId>[] = [
  { id: 'month-wise', label: 'Month-wise Sales' },
  { id: 'product-wise', label: 'Product-wise Sales' },
  // Profit & Loss is built but hidden for now — re-add this entry to expose it.
  // { id: 'profit-loss', label: 'Profit & Loss' },
  { id: 'product-performance', label: 'Product performance' },
];

const TAB_IDS = TABS.map((t) => t.id);

/**
 * Tabs and filters live in the query string rather than component state, so a
 * report is linkable and bookmarkable — you can send someone the exact view.
 * (The app's two older tab bars keep this in local state and can't.)
 */
export default function AnalyticsPage() {
  const { filters, searchParams, patchParams, isFiltered, onResetFilters, onFiltersChange } =
    useAnalyticsFilters();

  const tabParam = searchParams.get('tab') as TabId | null;
  const tab: TabId = tabParam && TAB_IDS.includes(tabParam) ? tabParam : 'month-wise';

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Reports</p>
          <h1 className="page-title">Analytics</h1>
          <p className="section-copy">
            Sales, product and profit performance across any date range.
          </p>
        </div>
      </section>

      <AnalyticsFilters
        filters={filters}
        onChange={onFiltersChange}
        onReset={onResetFilters}
        canReset={isFiltered}
        showProductFilter={tab === 'product-wise' || tab === 'profit-loss' || tab === 'product-performance'}
        // Product performance reports sales and purchases side by side.
        showVoucherType={tab !== 'product-performance'}
        // …so its counterparty can be a customer or a supplier.
        ledgerLabel={tab === 'product-performance' ? 'Party' : 'Customer'}
      />

      <Tabs
        tabs={TABS}
        value={tab}
        onChange={(id) => patchParams({ tab: id })}
        label="Analytics reports"
      />

      <TabPanel id={tab}>
        {tab === 'month-wise' && <MonthlySalesTab filters={filters} />}
        {tab === 'product-wise' && <ProductSalesTab filters={filters} />}
        {tab === 'profit-loss' && <ProfitLossTab filters={filters} />}
        {tab === 'product-performance' && <ProductPerformanceTab filters={filters} />}
      </TabPanel>
    </div>
  );
}
