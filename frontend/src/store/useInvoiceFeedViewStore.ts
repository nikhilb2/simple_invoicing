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
  applySearchDeepLink: (search: string) => void;
  resetFilters: () => void;
};

const initialFilters = {
  invoiceSearch: '',
  searchDescription: false,
  showCancelled: false,
  // Reset has to clear this too, because the header counts it in the Filters
  // badge and because the deep links now switch it on by themselves: leaving it
  // set means Reset lands on "Filters (1)" and a scope the user never chose.
  // A company with no active FY can still get back to all-FY from the empty
  // state's "Search all FY" button, so nothing becomes unreachable.
  allowAllFY: false,
  page: 1,
  productId: null as number | null,
  voucherType: 'all' as VoucherTypeFilter,
  dateFrom: '',
  dateTo: '',
};

export const useInvoiceFeedViewStore = create<InvoiceFeedViewState>((set) => ({
  viewType: 'card',
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
  // Arriving on /invoices-view?search=… names a document, so the URL has to
  // beat whatever this store is still holding from the last visit. This store
  // is a module singleton with no persist middleware, so a reload clears it but
  // an in-app navigation does not: the "Open invoice" link is followed from
  // another page in the same session, which is exactly when the stale value is
  // there to override. One `set` so the query key changes once, not four times.
  applySearchDeepLink: (search) => set({
    invoiceSearch: search,
    // Widened for the same reason the ?invoice_id= deep link widens: the caller
    // has named a specific document and expects to land on it, and the document
    // it names is typically the *older* invoice a serial arrived on — a
    // different financial year, and possibly since cancelled. A deep link that
    // resolves to "No invoices match your search" is the reported bug. Both
    // toggles are visible in the Filters badge and undone by Reset, so the
    // widening is discoverable rather than a silent change of scope.
    allowAllFY: true,
    showCancelled: true,
    page: 1,
  }),
  resetFilters: () => set({ ...initialFilters }),
}));
