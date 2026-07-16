import { useQuery } from '@tanstack/react-query';
import api from '../../api/client';
import LedgerCombobox from '../../components/LedgerCombobox';
import ProductCombobox from '../../components/ProductCombobox';
import { useFY } from '../../context/FYContext';
import type { AnalyticsFilters as Filters } from '../../features/analytics/types';
import type { Ledger, Product } from '../../types/api';

type Props = {
  filters: Filters;
  onChange: (next: Filters) => void;
  /** The product picker only applies to the product report. */
  showProductFilter?: boolean;
};

export default function AnalyticsFilters({ filters, onChange, showProductFilter = false }: Props) {
  const { fyList } = useFY();

  const ledgersQuery = useQuery({
    queryKey: ['ledgers', 'lookup'],
    queryFn: async () => {
      const response = await api.get<{ items: Ledger[] }>('/ledgers/', { params: { page_size: 500 } });
      return response.data.items ?? [];
    },
  });

  const productsQuery = useQuery({
    queryKey: ['products', 'lookup'],
    queryFn: async () => {
      const response = await api.get<{ items: Product[] }>('/products/', { params: { page_size: 500 } });
      return response.data.items ?? [];
    },
    enabled: showProductFilter,
  });

  const selectFY = (value: string) => {
    if (!value) {
      onChange({ ...filters, financialYearId: undefined, fromDate: undefined, toDate: undefined });
      return;
    }
    const fy = fyList.find((entry) => String(entry.id) === value);
    if (!fy) return;
    onChange({ ...filters, financialYearId: fy.id, fromDate: fy.start_date, toDate: fy.end_date });
  };

  // Explicit dates win server-side, so clear the FY selection to match.
  const setDate = (key: 'fromDate' | 'toDate', value: string) => {
    onChange({ ...filters, [key]: value || undefined, financialYearId: undefined });
  };

  return (
    <div className="analytics-filters">
      <label className="analytics-filters__field">
        <span>Financial Year</span>
        <select
          className="input"
          value={filters.financialYearId ? String(filters.financialYearId) : ''}
          onChange={(event) => selectFY(event.target.value)}
        >
          <option value="">Custom range</option>
          {fyList.map((fy) => (
            <option key={fy.id} value={String(fy.id)}>{fy.label}</option>
          ))}
        </select>
      </label>

      <label className="analytics-filters__field">
        <span>From</span>
        <input
          className="input"
          type="date"
          value={filters.fromDate ?? ''}
          onChange={(event) => setDate('fromDate', event.target.value)}
        />
      </label>

      <label className="analytics-filters__field">
        <span>To</span>
        <input
          className="input"
          type="date"
          value={filters.toDate ?? ''}
          onChange={(event) => setDate('toDate', event.target.value)}
        />
      </label>

      <label className="analytics-filters__field">
        <span>Type</span>
        <select
          className="input"
          value={filters.voucherType}
          onChange={(event) => onChange({ ...filters, voucherType: event.target.value as Filters['voucherType'] })}
        >
          <option value="sales">Sales</option>
          <option value="purchase">Purchase</option>
        </select>
      </label>

      <div className="analytics-filters__field">
        <span>Customer</span>
        <LedgerCombobox
          id="analytics-ledger"
          ledgers={ledgersQuery.data ?? []}
          value={filters.ledgerId ? String(filters.ledgerId) : ''}
          onChange={(ledgerId) => onChange({ ...filters, ledgerId: ledgerId ? Number(ledgerId) : undefined })}
        />
      </div>

      {showProductFilter && (
        <div className="analytics-filters__field">
          <span>Product</span>
          <ProductCombobox
            id="analytics-product"
            products={productsQuery.data ?? []}
            value={filters.productId ? String(filters.productId) : ''}
            onChange={(productId) => onChange({ ...filters, productId: productId ? Number(productId) : undefined })}
          />
        </div>
      )}
    </div>
  );
}
