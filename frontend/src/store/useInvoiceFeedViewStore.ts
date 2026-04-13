import { create } from 'zustand';

type ViewType = 'card' | 'table';

type InvoiceFeedViewState = {
  viewType: ViewType;
  invoiceSearch: string;
  showCancelled: boolean;
  allowAllFY: boolean;
  page: number;
  setViewType: (viewType: ViewType) => void;
  setInvoiceSearch: (invoiceSearch: string) => void;
  setShowCancelled: (showCancelled: boolean) => void;
  setAllowAllFY: (allowAllFY: boolean) => void;
  setPage: (page: number) => void;
  resetPage: () => void;
};

export const useInvoiceFeedViewStore = create<InvoiceFeedViewState>((set) => ({
  viewType: 'card',
  invoiceSearch: '',
  showCancelled: false,
  allowAllFY: false,
  page: 1,
  setViewType: (viewType) => set({ viewType }),
  setInvoiceSearch: (invoiceSearch) => set({ invoiceSearch }),
  setShowCancelled: (showCancelled) => set({ showCancelled }),
  setAllowAllFY: (allowAllFY) => set({ allowAllFY }),
  setPage: (page) => set({ page }),
  resetPage: () => set({ page: 1 }),
}));
