import api, { cleanParams } from '../../api/client';
import type {
  PaginatedQuotations,
  Quotation,
  QuotationConversionDraft,
  QuotationCreate,
  QuotationDocumentType,
  QuotationDisplayStatus,
  QuotationSettableStatus,
  QuotationUpdate,
} from '../../types/api';

export type QuotationListFilters = {
  page: number;
  pageSize: number;
  search: string;
  status?: QuotationDisplayStatus;
  documentType?: QuotationDocumentType;
};

export async function fetchQuotations(filters: QuotationListFilters): Promise<PaginatedQuotations> {
  const res = await api.get<PaginatedQuotations>('/quotations/', {
    params: cleanParams({
      page: filters.page,
      page_size: filters.pageSize,
      search: filters.search,
      status: filters.status,
      document_type: filters.documentType,
    }),
  });
  return res.data;
}

export async function fetchQuotationById(id: number): Promise<Quotation> {
  const res = await api.get<Quotation>(`/quotations/${id}`);
  return res.data;
}

export async function fetchConversionDraft(id: number): Promise<QuotationConversionDraft> {
  const res = await api.get<QuotationConversionDraft>(`/quotations/${id}/conversion-draft`);
  return res.data;
}

export async function createQuotation(payload: QuotationCreate): Promise<Quotation> {
  const res = await api.post<Quotation>('/quotations/', payload);
  return res.data;
}

export async function updateQuotation(id: number, payload: QuotationUpdate): Promise<Quotation> {
  const res = await api.put<Quotation>(`/quotations/${id}`, payload);
  return res.data;
}

export async function setQuotationStatus(
  id: number,
  status: QuotationSettableStatus,
  note?: string,
): Promise<Quotation> {
  const res = await api.post<Quotation>(`/quotations/${id}/status`, { status, note: note || null });
  return res.data;
}

export async function cancelQuotation(id: number): Promise<Quotation> {
  const res = await api.post<Quotation>(`/quotations/${id}/cancel`);
  return res.data;
}

export async function duplicateQuotation(id: number): Promise<Quotation> {
  const res = await api.post<Quotation>(`/quotations/${id}/duplicate`);
  return res.data;
}
