export const invoiceQueryKeys = {
  all: ['invoices'] as const,
  list: (
    page: number,
    pageSize: number,
    search: string,
    showCancelled: boolean,
    financialYearId?: number
  ) => ['invoices', 'list', page, pageSize, search, showCancelled, financialYearId ?? 'all'] as const,
  company: ['company', 'profile'] as const,
  products: ['products', 'lookup'] as const,
  summary: (
    page: number,
    pageSize: number,
    search: string,
    showCancelled: boolean,
    financialYearId?: number,
    totalPages?: number
  ) => ['invoices', 'summary', page, pageSize, search, showCancelled, financialYearId ?? 'all', totalPages ?? 1] as const,
};
