import { create } from 'zustand';

type ViewType = 'card' | 'table';

type InvoiceFeedViewState = {
  viewType: ViewType;
  invoiceSearch: string;
  searchDescription: boolean;
  showCancelled: boolean;
  allowAllFY: boolean;
  page: number;
  productId: number | null;
  setViewType: (viewType: ViewType) => void;
  setInvoiceSearch: (invoiceSearch: string) => void;
  setSearchDescription: (searchDescription: boolean) => void;
  setShowCancelled: (showCancelled: boolean) => void;
  setAllowAllFY: (allowAllFY: boolean) => void;
  setPage: (page: number) => void;
  resetPage: () => void;
  setProductId: (productId: number | null) => void;
};

export const useInvoiceFeedViewStore = create<InvoiceFeedViewState>((set) => ({
  viewType: 'card',
  invoiceSearch: '',
  searchDescription: false,
  showCancelled: false,
  allowAllFY: false,
  page: 1,
  productId: null,
  setViewType: (viewType) => set({ viewType }),
  setInvoiceSearch: (invoiceSearch) => set({ invoiceSearch }),
  setSearchDescription: (searchDescription) => set({ searchDescription }),
  setShowCancelled: (showCancelled) => set({ showCancelled }),
  setAllowAllFY: (allowAllFY) => set({ allowAllFY }),
  setPage: (page) => set({ page }),
  resetPage: () => set({ page: 1 }),
  setProductId: (productId) => set({ productId }),
}));
