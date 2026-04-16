import api from '../../api/client';
import type { CompanyProfile, Invoice, Ledger, PaginatedInvoices, Product } from '../../types/api';

type InvoiceFilters = {
  page: number;
  pageSize: number;
  search: string;
  showCancelled: boolean;
  financialYearId?: number;
  productId?: number;
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

  if (typeof filters.productId === 'number') {
    params.product_id = filters.productId;
  }

  return params;
}

export async function fetchInvoiceById(invoiceId: number): Promise<Invoice> {
  const res = await api.get<Invoice>(`/invoices/${invoiceId}`);
  return res.data;
}

export async function fetchInvoicePage(filters: InvoiceFilters): Promise<PaginatedInvoices> {
  const res = await api.get<PaginatedInvoices>('/invoices/', {
    params: buildInvoiceParams(filters),
  });
  return res.data;
}

export async function fetchInvoiceSummaryPages(
  baseFilters: Omit<InvoiceFilters, 'page'>,
  totalItems: number,
  currentItems: Invoice[]
): Promise<Invoice[]> {
  if (totalItems <= currentItems.length) {
    return currentItems;
  }

  const response = await fetchInvoicePage({
    ...baseFilters,
    page: 1,
    pageSize: totalItems,
  });

  return response.items;
}

export async function fetchCompanyProfile(): Promise<CompanyProfile> {
  const res = await api.get<CompanyProfile>('/company/');
  return res.data;
}

export async function fetchProducts(): Promise<Product[]> {
  const res = await api.get<{ items: Product[] }>('/products/', { params: { page_size: 500 } });
  return res.data.items;
}

export async function fetchLedgers(): Promise<Ledger[]> {
  const res = await api.get<{ items: Ledger[] }>('/ledgers/', { params: { page_size: 500 } });
  return res.data.items;
}

export async function fetchInvoiceComposerData(input: {
  page: number;
  pageSize: number;
  search: string;
  showCancelled: boolean;
  financialYearId?: number;
}) {
  const [productsRes, ledgersRes, invoicesRes, companyRes] = await Promise.all([
    api.get<{ items: Product[] }>('/products/', { params: { page_size: 500 } }),
    api.get<{ items: Ledger[] }>('/ledgers/', { params: { page_size: 500 } }),
    fetchInvoicePage({
      page: input.page,
      pageSize: input.pageSize,
      search: input.search,
      showCancelled: input.showCancelled,
      financialYearId: input.financialYearId,
    }),
    fetchCompanyProfile(),
  ]);

  return {
    products: productsRes.data.items,
    ledgers: ledgersRes.data.items,
    invoices: invoicesRes.items,
    invoiceTotal: invoicesRes.total,
    invoiceTotalPages: invoicesRes.total_pages,
    company: companyRes,
  };
}
