/**
 * Shapes returned by `/api/marketplace/*`.
 *
 * Money, quantities and GST rates arrive as **decimal strings**, never JSON
 * numbers — float round-tripping silently corrupts tax arithmetic, so the
 * contract transports them as text and this app never parses them into a
 * `number`. Use the helpers in `./decimal.ts` for any arithmetic.
 */

export type MarketplaceConnectionStatus =
  | 'unregistered'
  | 'pending_approval'
  | 'connected'
  | 'unauthorized'
  | 'suspended'
  | 'disconnected';

export type MarketplaceConnection = {
  status: MarketplaceConnectionStatus;
  base_url: string | null;
  seller_id: string | null;
  credential_prefix: string | null;
  gstin: string | null;
  legal_name: string | null;
  last_sync_at: string | null;
  last_sync_error: string | null;
  auto_accept: boolean;
  auto_accept_max_amount: string | null;
  auto_post: boolean;
};

/** The remote `/v1/meta`, proxied — what a pasted base URL is validated against. */
export type MarketplaceMeta = {
  marketplace_name: string;
  min_client_version: string | null;
  terms_url: string | null;
  registration_open: boolean;
  requires_approval: boolean;
  order_ttl_hours: number | null;
  event_retention_days?: number | null;
};

export type MarketplaceRegisterPayload = {
  base_url: string;
  legal_name?: string;
  contact_email: string;
  contact_phone?: string;
};

export type MarketplaceConnectionSettings = {
  auto_accept: boolean;
  auto_accept_max_amount: string | null;
  auto_post: boolean;
};

export type MarketplaceSeller = {
  seller_id: string;
  legal_name: string;
  gstin: string | null;
  state_code: string | null;
  /** Always false in v1 — GSTIN ownership is not verified. See MARKETPLACE.md §8. */
  verified: boolean;
};

export type CatalogListing = {
  listing_id: string;
  title: string;
  description: string | null;
  asking_price: string;
  currency_code: string;
  gst_rate: string;
  hsn_sac: string | null;
  unit: string;
  allow_decimal: boolean;
  min_order_quantity: string | null;
  max_order_quantity: string | null;
  available_quantity: string | null;
  /** Timestamp the seller last republished the quantity. It is never live. */
  available_quantity_as_of: string | null;
  seller: MarketplaceSeller;
};

export type CatalogPage = {
  items: CatalogListing[];
  next_cursor: string | null;
  total_estimate: number | null;
};

export type CatalogSort = 'newest' | 'price_asc' | 'price_desc';

export type CatalogFilters = {
  q: string;
  hsn_sac: string;
  min_price: string;
  max_price: string;
  seller_state_code: string;
  in_stock: boolean;
  sort: CatalogSort;
};

export type ListingStatus = 'draft' | 'active' | 'paused' | 'withdrawn' | 'rejected';

/** A listing we published — the local mirror, not the browse view. */
export type MarketplaceListing = {
  id: number;
  product_id: number;
  remote_listing_id: string | null;
  title: string;
  description: string | null;
  asking_price: string;
  currency_code: string;
  gst_rate: string;
  hsn_sac: string | null;
  unit: string;
  allow_decimal: boolean;
  min_order_quantity: string | null;
  max_order_quantity: string | null;
  available_quantity_published: string | null;
  status: ListingStatus;
  listing_type: string;
  last_published_at: string | null;
  last_error: string | null;
};

export type ListingCreatePayload = {
  product_id: number;
  asking_price: string;
  available_quantity: string;
  title?: string;
  description?: string;
  min_order_quantity?: string | null;
  max_order_quantity?: string | null;
};

export type ListingUpdatePayload = {
  asking_price?: string;
  available_quantity?: string;
  status?: ListingStatus;
  title?: string;
  description?: string;
  min_order_quantity?: string | null;
  max_order_quantity?: string | null;
};

export type OrderSide = 'buy' | 'sell';

export type OrderState = 'pending' | 'accepted' | 'rejected' | 'cancelled' | 'expired' | 'posted';

export type PostingState = 'not_required' | 'pending' | 'posting' | 'posted' | 'failed' | 'skipped';

export type MarketplaceOrderItem = {
  id: number;
  line_no: number;
  remote_listing_id: string | null;
  title: string | null;
  product_id: number | null;
  quantity: string;
  unit: string | null;
  unit_price: string;
  gst_rate: string;
  hsn_sac: string | null;
};

export type MarketplaceOrder = {
  id: number;
  side: OrderSide;
  remote_order_id: string;
  order_type: string;
  state: OrderState;
  remote_listing_id: string | null;
  counterparty_remote_id: string | null;
  counterparty_name: string | null;
  counterparty_gstin: string | null;
  counterparty_address: string | null;
  counterparty_phone: string | null;
  counterparty_email: string | null;
  currency_code: string;
  remote_total_amount: string | null;
  order_placed_at: string | null;
  expires_at: string | null;
  accepted_at: string | null;
  closed_at: string | null;
  reject_reason: string | null;
  reject_note: string | null;
  seller_invoice_number: string | null;
  seller_invoice_date: string | null;
  posting_state: PostingState;
  posted_invoice_id: number | null;
  posted_invoice_number: string | null;
  posted_at: string | null;
  posting_error: string | null;
  posting_attempts: number;
  posting_warnings: string | null;
  total_mismatch: boolean;
  items: MarketplaceOrderItem[];
};

export type PaginatedOrders = {
  items: MarketplaceOrder[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
};

export type BuyNowPayload = {
  listing_id: string;
  quantity: string;
  buyer_note?: string;
  delivery_address?: string;
};

export type RejectOrderPayload = {
  reason: 'insufficient_stock' | 'price_changed' | 'cannot_ship' | 'unknown_buyer' | 'other';
  note?: string;
};

export type SyncResult = {
  applied: number;
  failed: number;
  cursor: number;
};
