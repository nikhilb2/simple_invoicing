import { create } from 'zustand';
import type { Invoice } from '../types/api';

type InvoiceModalState = {
  previewInvoice: Invoice | null;
  openPreview: (invoice: Invoice) => void;
  closePreview: () => void;
};

export const useInvoiceModalStore = create<InvoiceModalState>((set) => ({
  previewInvoice: null,
  openPreview: (invoice) => set({ previewInvoice: invoice }),
  closePreview: () => set({ previewInvoice: null }),
}));
