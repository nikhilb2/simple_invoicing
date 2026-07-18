import { create } from 'zustand';

type ViewType = 'card' | 'table';

export type VoucherTypeFilter = 'all' | 'sales' | 'purchase';

type InvoiceFeedViewState = {
  viewType: ViewType;
  invoiceSearch: string;
  searchDescription: boolean;
  showCancelled: boolean;
  allowAllFY: boolean;
  page: number;
  productId: number | null;
  voucherType: VoucherTypeFilter;
  dateFrom: string;
  dateTo: string;
  setViewType: (viewType: ViewType) => void;
  setInvoiceSearch: (invoiceSearch: string) => void;
  setSearchDescription: (searchDescription: boolean) => void;
  setShowCancelled: (showCancelled: boolean) => void;
  setAllowAllFY: (allowAllFY: boolean) => void;
  setPage: (page: number) => void;
  resetPage: () => void;
  setProductId: (productId: number | null) => void;
  setVoucherType: (voucherType: VoucherTypeFilter) => void;
  setDateFrom: (dateFrom: string) => void;
  setDateTo: (dateTo: string) => void;
  setDateRange: (dateFrom: string, dateTo: string) => void;
  resetFilters: () => void;
};

const initialFilters = {
  invoiceSearch: '',
  searchDescription: false,
  showCancelled: false,
  page: 1,
  productId: null as number | null,
  voucherType: 'all' as VoucherTypeFilter,
  dateFrom: '',
  dateTo: '',
};

export const useInvoiceFeedViewStore = create<InvoiceFeedViewState>((set) => ({
  viewType: 'card',
  allowAllFY: false,
  ...initialFilters,
  setViewType: (viewType) => set({ viewType }),
  setInvoiceSearch: (invoiceSearch) => set({ invoiceSearch }),
  setSearchDescription: (searchDescription) => set({ searchDescription }),
  setShowCancelled: (showCancelled) => set({ showCancelled }),
  setAllowAllFY: (allowAllFY) => set({ allowAllFY }),
  setPage: (page) => set({ page }),
  resetPage: () => set({ page: 1 }),
  setProductId: (productId) => set({ productId }),
  setVoucherType: (voucherType) => set({ voucherType }),
  setDateFrom: (dateFrom) => set({ dateFrom }),
  setDateTo: (dateTo) => set({ dateTo }),
  setDateRange: (dateFrom, dateTo) => set({ dateFrom, dateTo }),
  resetFilters: () => set({ ...initialFilters }),
}));
