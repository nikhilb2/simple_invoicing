import { create } from 'zustand';

type InvoiceCancelState = {
  pendingCancelId: number | null;
  pendingCancelNumber: string | null;
  requestCancel: (invoiceId: number, invoiceNumber?: string | null) => void;
  dismissCancel: () => void;
};

export const useInvoiceCancelStore = create<InvoiceCancelState>((set) => ({
  pendingCancelId: null,
  pendingCancelNumber: null,
  requestCancel: (invoiceId, invoiceNumber) =>
    set({ pendingCancelId: invoiceId, pendingCancelNumber: invoiceNumber ?? null }),
  dismissCancel: () => set({ pendingCancelId: null, pendingCancelNumber: null }),
}));
