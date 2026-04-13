import api from '../../api/client';
import type { CompanyProfile, Invoice, PaginatedInvoices, Product } from '../../types/api';

type InvoiceFilters = {
  page: number;
  pageSize: number;
  search: string;
  showCancelled: boolean;
  financialYearId?: number;
};

function buildInvoiceParams(filters: InvoiceFilters) {
  const params: Record<string, string | number | boolean> = {
    page: filters.page,
    page_size: filters.pageSize,
    search: filters.search,
    show_cancelled: filters.showCancelled,
  };

  if (typeof filters.financialYearId === 'number') {
    params.financial_year_id = filters.financialYearId;
  }

  return params;
}

export async function fetchInvoicePage(filters: InvoiceFilters): Promise<PaginatedInvoices> {
  const res = await api.get<PaginatedInvoices>('/invoices/', {
    params: buildInvoiceParams(filters),
  });
  return res.data;
}

export async function fetchInvoiceSummaryPages(
  baseFilters: Omit<InvoiceFilters, 'page'>,
  totalPages: number,
  currentPage: number,
  currentItems: Invoice[]
): Promise<Invoice[]> {
  if (totalPages <= 1) {
    return currentItems;
  }

  const rows: Invoice[] = [...currentItems];
  const requests: Promise<PaginatedInvoices>[] = [];

  for (let page = 1; page <= totalPages; page += 1) {
    if (page === currentPage) {
      continue;
    }
    requests.push(fetchInvoicePage({ ...baseFilters, page }));
  }

  const results = await Promise.all(requests);
  results.forEach((entry) => rows.push(...entry.items));
  return rows;
}

export async function fetchCompanyProfile(): Promise<CompanyProfile> {
  const res = await api.get<CompanyProfile>('/company/');
  return res.data;
}

export async function fetchProducts(): Promise<Product[]> {
  const res = await api.get<{ items: Product[] }>('/products/', { params: { page_size: 500 } });
  return res.data.items;
}
