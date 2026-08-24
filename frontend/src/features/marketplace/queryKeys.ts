import type { CatalogFilters, OrderSide } from './types';

/**
 * Every marketplace key hangs off `all`, so a mutation anywhere in the feature
 * can invalidate the whole surface with one call — connection status, listings
 * and orders all move together when a drain applies events.
 */
export const marketplaceQueryKeys = {
  all: ['marketplace'] as const,
  connection: () => ['marketplace', 'connection'] as const,
  meta: (baseUrl: string) => ['marketplace', 'connection', 'meta', baseUrl] as const,
  catalog: (filters: CatalogFilters, cursor: string | null, pageSize: number) =>
    ['marketplace', 'catalog', 'list', filters, cursor ?? 'first', pageSize] as const,
  catalogItem: (listingId: string) => ['marketplace', 'catalog', 'item', listingId] as const,
  listings: () => ['marketplace', 'listings'] as const,
  orders: (side: OrderSide, state: string, page: number, pageSize: number) =>
    ['marketplace', 'orders', 'list', side, state || 'all', page, pageSize] as const,
  order: (orderId: number) => ['marketplace', 'orders', 'detail', orderId] as const,
};
