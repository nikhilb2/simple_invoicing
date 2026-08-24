import api, { cleanParams } from '../../api/client';
import type {
  BuyNowPayload,
  CatalogFilters,
  CatalogListing,
  CatalogPage,
  ListingCreatePayload,
  ListingUpdatePayload,
  MarketplaceConnection,
  MarketplaceConnectionSettings,
  MarketplaceListing,
  MarketplaceMeta,
  MarketplaceOrder,
  MarketplaceRegisterPayload,
  OrderSide,
  PaginatedOrders,
  RejectOrderPayload,
  SyncResult,
} from './types';

// ---------------------------------------------------------------------------
// Connection
// ---------------------------------------------------------------------------

export async function fetchConnection(): Promise<MarketplaceConnection> {
  const res = await api.get<MarketplaceConnection>('/marketplace/connection');
  return res.data;
}

/** Probes the pasted base URL through the backend proxy — the browser must never
 *  reach the central server itself: it would leak the credential and break CORS
 *  on every self-hosted deployment. */
export async function fetchMarketplaceMeta(baseUrl: string): Promise<MarketplaceMeta> {
  const res = await api.get<MarketplaceMeta>('/marketplace/connection/meta', {
    params: { base_url: baseUrl },
  });
  return res.data;
}

export async function registerConnection(payload: MarketplaceRegisterPayload): Promise<MarketplaceConnection> {
  const res = await api.post<MarketplaceConnection>('/marketplace/connection', payload);
  return res.data;
}

export async function updateConnection(
  payload: Partial<MarketplaceConnectionSettings>,
): Promise<MarketplaceConnection> {
  const res = await api.patch<MarketplaceConnection>('/marketplace/connection', payload);
  return res.data;
}

export async function disconnectMarketplace(): Promise<void> {
  await api.delete('/marketplace/connection');
}

export async function rotateCredential(): Promise<MarketplaceConnection> {
  const res = await api.post<MarketplaceConnection>('/marketplace/connection/rotate-key');
  return res.data;
}

// ---------------------------------------------------------------------------
// Catalog (browse)
// ---------------------------------------------------------------------------

export async function fetchCatalog(
  filters: CatalogFilters,
  cursor: string | null,
  pageSize: number,
): Promise<CatalogPage> {
  const res = await api.get<CatalogPage>('/marketplace/catalog', {
    params: cleanParams({
      q: filters.q,
      hsn_sac: filters.hsn_sac,
      min_price: filters.min_price,
      max_price: filters.max_price,
      seller_state_code: filters.seller_state_code,
      in_stock: filters.in_stock ? true : undefined,
      sort: filters.sort,
      cursor,
      page_size: pageSize,
    }),
  });
  return res.data;
}

export async function fetchCatalogListing(listingId: string): Promise<CatalogListing> {
  const res = await api.get<CatalogListing>(`/marketplace/catalog/${listingId}`);
  return res.data;
}

// ---------------------------------------------------------------------------
// My listings
// ---------------------------------------------------------------------------

export async function fetchMyListings(): Promise<MarketplaceListing[]> {
  const res = await api.get<MarketplaceListing[] | { items: MarketplaceListing[] }>('/marketplace/listings');
  // Tolerates either a bare array or an envelope: the listing cap is 500 per
  // seller, so this list is never paginated in practice and the backend may
  // legitimately return either shape.
  return Array.isArray(res.data) ? res.data : res.data.items;
}

export async function createListing(payload: ListingCreatePayload): Promise<MarketplaceListing> {
  const res = await api.post<MarketplaceListing>('/marketplace/listings', payload);
  return res.data;
}

export async function updateListing(
  listingId: number,
  payload: ListingUpdatePayload,
): Promise<MarketplaceListing> {
  const res = await api.patch<MarketplaceListing>(`/marketplace/listings/${listingId}`, payload);
  return res.data;
}

export async function withdrawListing(listingId: number): Promise<void> {
  await api.delete(`/marketplace/listings/${listingId}`);
}

// ---------------------------------------------------------------------------
// Orders
// ---------------------------------------------------------------------------

export async function fetchOrders(input: {
  side: OrderSide;
  state: string;
  page: number;
  pageSize: number;
}): Promise<PaginatedOrders> {
  const res = await api.get<PaginatedOrders>('/marketplace/orders', {
    params: cleanParams({
      side: input.side,
      state: input.state,
      page: input.page,
      page_size: input.pageSize,
    }),
  });
  return res.data;
}

export async function fetchOrder(orderId: number): Promise<MarketplaceOrder> {
  const res = await api.get<MarketplaceOrder>(`/marketplace/orders/${orderId}`);
  return res.data;
}

export async function placeOrder(payload: BuyNowPayload): Promise<MarketplaceOrder> {
  const res = await api.post<MarketplaceOrder>('/marketplace/orders', payload);
  return res.data;
}

export async function acceptOrder(orderId: number): Promise<MarketplaceOrder> {
  const res = await api.post<MarketplaceOrder>(`/marketplace/orders/${orderId}/accept`);
  return res.data;
}

export async function rejectOrder(orderId: number, payload: RejectOrderPayload): Promise<MarketplaceOrder> {
  const res = await api.post<MarketplaceOrder>(`/marketplace/orders/${orderId}/reject`, payload);
  return res.data;
}

export async function cancelOrder(orderId: number): Promise<MarketplaceOrder> {
  const res = await api.post<MarketplaceOrder>(`/marketplace/orders/${orderId}/cancel`);
  return res.data;
}

export async function retryOrderPosting(orderId: number): Promise<MarketplaceOrder> {
  const res = await api.post<MarketplaceOrder>(`/marketplace/orders/${orderId}/retry-posting`);
  return res.data;
}

export async function linkOrderProduct(orderId: number, productId: number): Promise<MarketplaceOrder> {
  const res = await api.post<MarketplaceOrder>(`/marketplace/orders/${orderId}/link-product`, {
    product_id: productId,
  });
  return res.data;
}

// ---------------------------------------------------------------------------
// Sync
// ---------------------------------------------------------------------------

/**
 * Drains the event feed. The 30 s override is required: the shared axios
 * instance has a 10 s global timeout and a drain legitimately runs longer —
 * it walks up to ten pages of events and then posts invoices for them.
 */
export async function runSync(): Promise<SyncResult> {
  const res = await api.post<SyncResult>('/marketplace/sync', undefined, { timeout: 30_000 });
  return res.data;
}
