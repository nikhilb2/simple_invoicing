import { create } from 'zustand';
import type { CatalogFilters, CatalogSort } from '../features/marketplace/types';

type ViewType = 'card' | 'table';

/**
 * Browse filters live here rather than in the page so they survive navigating
 * out to a listing's orders and back — the same reason the invoice feed keeps
 * its filters in a store.
 *
 * The cursor stack is what makes "Previous" work over a cursor-paginated feed:
 * the API only hands out a forward cursor, so going back means remembering
 * where each page started.
 */
type MarketplaceBrowseState = CatalogFilters & {
  viewType: ViewType;
  /** Cursor for the page currently shown; null is the first page. */
  cursor: string | null;
  /** Cursors of the pages behind the current one, oldest first. */
  cursorStack: string[];
  setViewType: (viewType: ViewType) => void;
  setQuery: (q: string) => void;
  setHsnSac: (hsnSac: string) => void;
  setMinPrice: (minPrice: string) => void;
  setMaxPrice: (maxPrice: string) => void;
  setSellerStateCode: (stateCode: string) => void;
  setInStock: (inStock: boolean) => void;
  setSort: (sort: CatalogSort) => void;
  goToNextPage: (nextCursor: string) => void;
  goToPreviousPage: () => void;
  resetFilters: () => void;
};

const initialFilters: CatalogFilters = {
  q: '',
  hsn_sac: '',
  min_price: '',
  max_price: '',
  seller_state_code: '',
  in_stock: false,
  sort: 'newest',
};

/** Any filter change invalidates the cursor — page 3 of the old query is
 *  meaningless against the new one. */
const rewound = { cursor: null, cursorStack: [] as string[] };

export const useMarketplaceBrowseStore = create<MarketplaceBrowseState>((set) => ({
  viewType: 'card',
  ...initialFilters,
  ...rewound,
  setViewType: (viewType) => set({ viewType }),
  setQuery: (q) => set({ q, ...rewound }),
  setHsnSac: (hsn_sac) => set({ hsn_sac, ...rewound }),
  setMinPrice: (min_price) => set({ min_price, ...rewound }),
  setMaxPrice: (max_price) => set({ max_price, ...rewound }),
  setSellerStateCode: (seller_state_code) => set({ seller_state_code, ...rewound }),
  setInStock: (in_stock) => set({ in_stock, ...rewound }),
  setSort: (sort) => set({ sort, ...rewound }),
  goToNextPage: (nextCursor) =>
    set((state) => ({
      cursor: nextCursor,
      cursorStack: state.cursor === null ? [] : [...state.cursorStack, state.cursor],
    })),
  goToPreviousPage: () =>
    set((state) => ({
      cursor: state.cursorStack.length > 0 ? state.cursorStack[state.cursorStack.length - 1] : null,
      cursorStack: state.cursorStack.slice(0, -1),
    })),
  resetFilters: () => set({ ...initialFilters, ...rewound }),
}));

export function countActiveFilters(filters: CatalogFilters): number {
  return [
    filters.q.trim() !== '',
    filters.hsn_sac.trim() !== '',
    filters.min_price.trim() !== '',
    filters.max_price.trim() !== '',
    filters.seller_state_code.trim() !== '',
    filters.in_stock,
    filters.sort !== 'newest',
  ].filter(Boolean).length;
}
