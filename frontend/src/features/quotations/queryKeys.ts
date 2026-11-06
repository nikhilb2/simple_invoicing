import type { QuotationListFilters } from './api';

export const quotationQueryKeys = {
  all: ['quotations'] as const,
  list: (filters: QuotationListFilters) => ['quotations', 'list', filters] as const,
};
