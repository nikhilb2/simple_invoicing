import { useEffect, useState } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { ChevronDown, LayoutGrid, SlidersHorizontal, Table as TableIcon } from 'lucide-react';
import { getApiErrorMessage } from '../../api/client';
import EmptyState from '../../components/EmptyState';
import StatusToasts from '../../components/StatusToasts';
import { fetchCatalog, placeOrder } from '../../features/marketplace/api';
import { marketplaceQueryKeys } from '../../features/marketplace/queryKeys';
import { useMarketplaceConnection } from '../../features/marketplace/useMarketplaceSync';
import { formatMoney, formatQuantity } from '../../features/marketplace/decimal';
import type { CatalogFilters, CatalogListing, CatalogSort } from '../../features/marketplace/types';
import { fetchCompanyProfile } from '../../features/invoices/api';
import { invoiceQueryKeys } from '../../features/invoices/queryKeys';
import { countActiveFilters, useMarketplaceBrowseStore } from '../../store/useMarketplaceBrowseStore';
import BuyNowModal from './components/BuyNowModal';
import MarketplaceGate from './components/MarketplaceGate';
import SyncStatusChip from './components/SyncStatusChip';
import UnverifiedSellerBadge from './components/UnverifiedSellerBadge';
import { formatRelativeTime } from './components/format';

const PAGE_SIZE = 24;

/** The seller's quantity is a republished snapshot, never a live reading, so it
 *  is only ever rendered together with its age. */
function availabilityLabel(listing: CatalogListing): string {
  const quantity = formatQuantity(listing.available_quantity);
  if (quantity === '—') return 'Seller has not published a quantity';
  const asOf = listing.available_quantity_as_of
    ? ` (as of ${formatRelativeTime(listing.available_quantity_as_of)})`
    : '';
  return `Seller reports ${quantity} ${listing.unit}${asOf}`;
}

export default function MarketplaceBrowsePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const connectionQuery = useMarketplaceConnection();

  const [filtersOpen, setFiltersOpen] = useState(false);
  const [buyTarget, setBuyTarget] = useState<CatalogListing | null>(null);
  const [buyError, setBuyError] = useState('');
  const [success, setSuccess] = useState('');
  const [listError, setListError] = useState('');

  const {
    viewType,
    cursor,
    cursorStack,
    setViewType,
    setQuery,
    setHsnSac,
    setMinPrice,
    setMaxPrice,
    setSellerStateCode,
    setInStock,
    setSort,
    goToNextPage,
    goToPreviousPage,
    resetFilters,
    ...rest
  } = useMarketplaceBrowseStore();

  const filters: CatalogFilters = {
    q: rest.q,
    hsn_sac: rest.hsn_sac,
    min_price: rest.min_price,
    max_price: rest.max_price,
    seller_state_code: rest.seller_state_code,
    in_stock: rest.in_stock,
    sort: rest.sort,
  };

  const connected = connectionQuery.data?.status === 'connected';

  const catalogQuery = useQuery({
    queryKey: marketplaceQueryKeys.catalog(filters, cursor, PAGE_SIZE),
    queryFn: () => fetchCatalog(filters, cursor, PAGE_SIZE),
    placeholderData: keepPreviousData,
    enabled: connected,
  });

  const companyQuery = useQuery({
    queryKey: invoiceQueryKeys.company,
    queryFn: fetchCompanyProfile,
  });

  const buyMutation = useMutation({
    mutationFn: (input: { listingId: string; quantity: string }) =>
      placeOrder({ listing_id: input.listingId, quantity: input.quantity }),
    onSuccess: () => {
      setBuyTarget(null);
      setBuyError('');
      setSuccess('Order placed. It stays pending until the seller accepts — track it under Orders.');
      void queryClient.invalidateQueries({ queryKey: marketplaceQueryKeys.all });
    },
    onError: (err) => setBuyError(getApiErrorMessage(err, 'Unable to place this order')),
  });

  // Browse failures are ordinary (the marketplace may be down); they surface as
  // a toast rather than replacing the page.
  useEffect(() => {
    if (catalogQuery.error) setListError(getApiErrorMessage(catalogQuery.error, 'Unable to load listings'));
  }, [catalogQuery.error]);

  const activeFilterCount = countActiveFilters(filters);
  const listings = catalogQuery.data?.items ?? [];
  const ourGstin = connectionQuery.data?.gstin ?? companyQuery.data?.gst ?? null;

  return (
    <div className="marketplace-page stack">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Marketplace</p>
          <h1 className="page-title">Browse listings</h1>
          <p className="section-copy">
            Surplus stock published by other businesses running this app. Prices are per unit and
            tax-exclusive.
          </p>
        </div>
        {connectionQuery.data && <SyncStatusChip connection={connectionQuery.data} />}
      </section>

      <MarketplaceGate
        connection={connectionQuery.data}
        isLoading={connectionQuery.isLoading}
        failed={Boolean(connectionQuery.error)}
      >
        {!connected ? (
          <div className="panel stack">
            <EmptyState
              message={
                connectionQuery.data?.status === 'pending_approval'
                  ? 'Your marketplace registration is awaiting operator approval. Browsing opens as soon as it is approved — no action needed.'
                  : 'This connection cannot trade right now. Open Marketplace settings for details.'
              }
              action={{ label: 'Open marketplace settings', onClick: () => navigate('/marketplace/settings') }}
            />
          </div>
        ) : (
          <>
            <section className="panel stack">
              <div className="panel__header">
                <div>
                  <p className="eyebrow">Catalogue</p>
                  <h2 className="nav-panel__title">
                    {catalogQuery.data?.total_estimate != null
                      ? `About ${catalogQuery.data.total_estimate} listings`
                      : 'Listings'}
                  </h2>
                </div>

                <div className="marketplace-view-tabs" role="tablist" aria-label="Listing view">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={viewType === 'card'}
                    className={`button button--small ${viewType === 'card' ? 'button--primary' : 'button--ghost'}`}
                    onClick={() => setViewType('card')}
                  >
                    <LayoutGrid size={16} />
                    Card
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={viewType === 'table'}
                    className={`button button--small ${viewType === 'table' ? 'button--primary' : 'button--ghost'}`}
                    onClick={() => setViewType('table')}
                  >
                    <TableIcon size={16} />
                    Table
                  </button>
                </div>
              </div>

              <div className="marketplace-toolbar">
                <input
                  className="input marketplace-toolbar__search"
                  type="search"
                  placeholder="Search titles and descriptions…"
                  value={filters.q}
                  onChange={(event) => setQuery(event.target.value)}
                />
                <div className="marketplace-toolbar__actions">
                  <button
                    type="button"
                    className={`button button--small ${filtersOpen || activeFilterCount > 0 ? 'button--primary' : 'button--ghost'}`}
                    onClick={() => setFiltersOpen((open) => !open)}
                    aria-expanded={filtersOpen}
                  >
                    <SlidersHorizontal size={16} />
                    Filters
                    {activeFilterCount > 0 && (
                      <span className="marketplace-filter-badge">{activeFilterCount}</span>
                    )}
                    <ChevronDown
                      size={16}
                      className="marketplace-chevron"
                      style={{ transform: filtersOpen ? 'rotate(180deg)' : 'none' }}
                    />
                  </button>
                  <button type="button" className="button button--ghost button--small" onClick={resetFilters}>
                    Reset
                  </button>
                </div>
              </div>

              {filtersOpen && (
                <div className="marketplace-drawer">
                  <div className="marketplace-drawer__fields">
                    <label className="marketplace-field">
                      <span className="marketplace-field__label">HSN / SAC</span>
                      <input
                        className="input"
                        type="text"
                        value={filters.hsn_sac}
                        onChange={(event) => setHsnSac(event.target.value)}
                        placeholder="e.g. 8482"
                      />
                    </label>
                    <label className="marketplace-field">
                      <span className="marketplace-field__label">Min price</span>
                      <input
                        className="input"
                        type="text"
                        inputMode="decimal"
                        value={filters.min_price}
                        onChange={(event) => setMinPrice(event.target.value)}
                      />
                    </label>
                    <label className="marketplace-field">
                      <span className="marketplace-field__label">Max price</span>
                      <input
                        className="input"
                        type="text"
                        inputMode="decimal"
                        value={filters.max_price}
                        onChange={(event) => setMaxPrice(event.target.value)}
                      />
                    </label>
                    <label className="marketplace-field">
                      <span className="marketplace-field__label">Seller state code</span>
                      <input
                        className="input"
                        type="text"
                        maxLength={2}
                        value={filters.seller_state_code}
                        onChange={(event) => setSellerStateCode(event.target.value)}
                        placeholder="e.g. 27"
                      />
                    </label>
                    <label className="marketplace-field">
                      <span className="marketplace-field__label">Sort</span>
                      <select
                        className="input"
                        value={filters.sort}
                        onChange={(event) => setSort(event.target.value as CatalogSort)}
                      >
                        <option value="newest">Newest</option>
                        <option value="price_asc">Price: low to high</option>
                        <option value="price_desc">Price: high to low</option>
                      </select>
                    </label>
                  </div>
                  <label className="marketplace-checkbox">
                    <input
                      type="checkbox"
                      checked={filters.in_stock}
                      onChange={(event) => setInStock(event.target.checked)}
                    />
                    <span>Only listings the seller reports as in stock</span>
                  </label>
                </div>
              )}
            </section>

            <section className="panel marketplace-results">
              {catalogQuery.isLoading && <EmptyState message="Loading listings…" />}
              {!catalogQuery.isLoading && listings.length === 0 && (
                <EmptyState message="No listings match these filters." />
              )}

              {!catalogQuery.isLoading && listings.length > 0 && viewType === 'card' && (
                <div className="marketplace-card-grid">
                  {listings.map((listing) => (
                    <article key={listing.listing_id} className="marketplace-card">
                      <header className="marketplace-card__header">
                        <h3 className="marketplace-card__title">{listing.title}</h3>
                        <span className="marketplace-card__price">
                          {formatMoney(listing.asking_price, listing.currency_code)}
                          <small> / {listing.unit}</small>
                        </span>
                      </header>

                      {listing.description && (
                        <p className="marketplace-card__description">{listing.description}</p>
                      )}

                      <div className="marketplace-card__seller">
                        <span>{listing.seller.legal_name}</span>
                        <UnverifiedSellerBadge />
                      </div>

                      <dl className="marketplace-card__meta">
                        <div>
                          <dt>GST</dt>
                          <dd>{listing.gst_rate}%</dd>
                        </div>
                        <div>
                          <dt>HSN/SAC</dt>
                          <dd>{listing.hsn_sac || '—'}</dd>
                        </div>
                        <div>
                          <dt>State</dt>
                          <dd>{listing.seller.state_code || '—'}</dd>
                        </div>
                      </dl>

                      <p className="marketplace-note">{availabilityLabel(listing)}</p>

                      <div className="button-row">
                        <button
                          type="button"
                          className="button button--primary button--small"
                          onClick={() => { setBuyError(''); setBuyTarget(listing); }}
                        >
                          Buy now
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              )}

              {!catalogQuery.isLoading && listings.length > 0 && viewType === 'table' && (
                <div className="marketplace-table-scroll">
                  <table className="marketplace-table">
                    <thead>
                      <tr>
                        <th>Listing</th>
                        <th>Seller</th>
                        <th>Price / unit</th>
                        <th>GST</th>
                        <th>Availability</th>
                        <th aria-label="Actions" />
                      </tr>
                    </thead>
                    <tbody>
                      {listings.map((listing) => (
                        <tr key={listing.listing_id}>
                          <td>
                            <strong>{listing.title}</strong>
                            <span className="table-subtext">
                              {listing.hsn_sac ? `HSN ${listing.hsn_sac} · ` : ''}{listing.unit}
                            </span>
                          </td>
                          <td>
                            <span className="marketplace-card__seller">
                              {listing.seller.legal_name}
                              <UnverifiedSellerBadge />
                            </span>
                            <span className="table-subtext">State {listing.seller.state_code || '—'}</span>
                          </td>
                          <td>{formatMoney(listing.asking_price, listing.currency_code)}</td>
                          <td>{listing.gst_rate}%</td>
                          <td><span className="table-subtext">{availabilityLabel(listing)}</span></td>
                          <td>
                            <div className="button-row">
                              <button
                                type="button"
                                className="button button--primary button--small"
                                onClick={() => { setBuyError(''); setBuyTarget(listing); }}
                              >
                                Buy now
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <div className="marketplace-pagination button-row">
                <button
                  type="button"
                  className="button button--ghost button--small"
                  onClick={goToPreviousPage}
                  disabled={cursor === null && cursorStack.length === 0}
                >
                  Previous
                </button>
                <span className="marketplace-pagination__label">Page {cursorStack.length + 1}</span>
                <button
                  type="button"
                  className="button button--ghost button--small"
                  onClick={() => {
                    const next = catalogQuery.data?.next_cursor;
                    if (next) goToNextPage(next);
                  }}
                  disabled={!catalogQuery.data?.next_cursor}
                >
                  Next
                </button>
              </div>
            </section>
          </>
        )}
      </MarketplaceGate>

      {buyTarget && (
        <BuyNowModal
          listing={buyTarget}
          ourGstin={ourGstin}
          submitting={buyMutation.isPending}
          error={buyError}
          onClose={() => { setBuyTarget(null); setBuyError(''); }}
          onConfirm={(quantity) => buyMutation.mutate({ listingId: buyTarget.listing_id, quantity })}
        />
      )}

      <StatusToasts
        error={listError}
        success={success}
        onClearError={() => setListError('')}
        onClearSuccess={() => setSuccess('')}
      />
    </div>
  );
}
