import api, { withParams } from './client';
import type { CreditNote, CreditNoteCreate, PaginatedCreditNotes } from '../types/api';

type CreditNoteListParams = {
  page?: number;
  page_size?: number;
  ledger_id?: number;
  invoice_id?: number;
  status?: string;
  search?: string;
  date_from?: string;
  date_to?: string;
};

export function listCreditNotes(params: CreditNoteListParams) {
  return api.get<PaginatedCreditNotes>('/credit-notes/', withParams({}, params));
}

export function getCreditNote(creditNoteId: number) {
  return api.get<CreditNote>(`/credit-notes/${creditNoteId}`);
}

export function createCreditNote(payload: CreditNoteCreate) {
  return api.post<CreditNote>('/credit-notes/', payload);
}

export function cancelCreditNote(creditNoteId: number) {
  return api.post<CreditNote>(`/credit-notes/${creditNoteId}/cancel`);
}