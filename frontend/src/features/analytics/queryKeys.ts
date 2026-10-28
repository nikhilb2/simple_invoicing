import type { AnalyticsFilters, PerformanceSortBy, ProductSortBy, SortDir } from './types';

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
  // No voucherType: the report covers sales and purchases together.
  productPerformance: (filters: AnalyticsFilters, sortBy: PerformanceSortBy, sortDir: SortDir) =>
    [
      'analytics',
      'product-performance',
      filters.financialYearId ?? 'all',
      filters.fromDate ?? 'auto',
      filters.toDate ?? 'auto',
      filters.ledgerId ?? 'all',
      filters.productId ?? 'all',
      sortBy,
      sortDir,
    ] as const,
  profitLoss: (filters: AnalyticsFilters) =>
    [
      'analytics',
      'profit-loss',
      filters.financialYearId ?? 'all',
      filters.fromDate ?? 'auto',
      filters.toDate ?? 'auto',
      filters.ledgerId ?? 'all',
      filters.productId ?? 'all',
    ] as const,
};
