export const invoiceQueryKeys = {
  all: ['invoices'] as const,
  composer: (
    page: number,
    pageSize: number,
    search: string,
    showCancelled: boolean,
    financialYearId?: number
  ) => ['invoices', 'composer', page, pageSize, search, showCancelled, financialYearId ?? 'all'] as const,
  list: (
    page: number,
    pageSize: number,
    search: string,
    showCancelled: boolean,
    financialYearId?: number,
    productId?: number
  ) => ['invoices', 'list', page, pageSize, search, showCancelled, financialYearId ?? 'all', productId ?? 'all'] as const,
  dues: (
    page: number,
    pageSize: number,
    search: string,
    ledgerId?: number,
    dueDateFrom?: string,
    dueDateTo?: string,
  ) => ['invoices', 'dues', page, pageSize, search, ledgerId ?? 'all', dueDateFrom ?? 'none', dueDateTo ?? 'none'] as const,
  outstanding: (
    ledgerId: number,
    voucherType: 'receipt' | 'payment',
    amount?: number,
    paymentId?: number,
  ) => ['invoices', 'outstanding', ledgerId, voucherType, amount ?? 'none', paymentId ?? 'none'] as const,
  company: ['company', 'profile'] as const,
  products: ['products', 'lookup'] as const,
};
