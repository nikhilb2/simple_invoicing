import api from '../../api/client';
import type {
  AnalyticsFilters,
  MonthlySalesReport,
  ProductSalesReport,
  ProductSortBy,
  SortDir,
} from './types';

/**
 * Reports can scan a multi-year book, which comfortably exceeds the client's
 * 10s default. Downloads run even longer.
 */
const REPORT_TIMEOUT_MS = 60_000;

function toParams(filters: AnalyticsFilters) {
  return {
    voucher_type: filters.voucherType,
    financial_year_id: filters.financialYearId,
    from_date: filters.fromDate,
    to_date: filters.toDate,
    ledger_id: filters.ledgerId,
  };
}

export async function fetchMonthlySales(filters: AnalyticsFilters): Promise<MonthlySalesReport> {
  const response = await api.get<MonthlySalesReport>('/analytics/sales-by-month', {
    params: toParams(filters),
    timeout: REPORT_TIMEOUT_MS,
  });
  return response.data;
}

export async function fetchProductSales(
  filters: AnalyticsFilters,
  sortBy: ProductSortBy,
  sortDir: SortDir,
): Promise<ProductSalesReport> {
  const response = await api.get<ProductSalesReport>('/analytics/sales-by-product', {
    params: { ...toParams(filters), product_id: filters.productId, sort_by: sortBy, sort_dir: sortDir },
    timeout: REPORT_TIMEOUT_MS,
  });
  return response.data;
}

async function downloadCsv(path: string, params: Record<string, unknown>, filename: string) {
  const response = await api.get(path, {
    params,
    responseType: 'blob',
    timeout: REPORT_TIMEOUT_MS,
  });

  const url = window.URL.createObjectURL(response.data as Blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  window.URL.revokeObjectURL(url);
}

export function downloadMonthlySalesCsv(filters: AnalyticsFilters, period: { from: string; to: string }) {
  return downloadCsv(
    '/analytics/sales-by-month/csv',
    toParams(filters),
    `sales_by_month_${period.from}_${period.to}.csv`,
  );
}

export function downloadProductSalesCsv(
  filters: AnalyticsFilters,
  sortBy: ProductSortBy,
  sortDir: SortDir,
  period: { from: string; to: string },
) {
  return downloadCsv(
    '/analytics/sales-by-product/csv',
    { ...toParams(filters), product_id: filters.productId, sort_by: sortBy, sort_dir: sortDir },
    `sales_by_product_${period.from}_${period.to}.csv`,
  );
}
