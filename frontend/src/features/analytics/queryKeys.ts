import type { AnalyticsFilters, ProductSortBy, SortDir } from './types';

export const analyticsQueryKeys = {
  all: ['analytics'] as const,
  monthlySales: (filters: AnalyticsFilters) =>
    [
      'analytics',
      'sales-by-month',
      filters.voucherType,
      filters.financialYearId ?? 'all',
      filters.fromDate ?? 'auto',
      filters.toDate ?? 'auto',
      filters.ledgerId ?? 'all',
    ] as const,
  productSales: (filters: AnalyticsFilters, sortBy: ProductSortBy, sortDir: SortDir) =>
    [
      'analytics',
      'sales-by-product',
      filters.voucherType,
      filters.financialYearId ?? 'all',
      filters.fromDate ?? 'auto',
      filters.toDate ?? 'auto',
      filters.ledgerId ?? 'all',
      filters.productId ?? 'all',
      sortBy,
      sortDir,
    ] as const,
};
