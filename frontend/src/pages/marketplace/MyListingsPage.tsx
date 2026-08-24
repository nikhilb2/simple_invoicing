import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Pause, Play, Plus, Trash2 } from 'lucide-react';
import { getApiErrorMessage } from '../../api/client';
import ConfirmDialog from '../../components/ConfirmDialog';
import EmptyState from '../../components/EmptyState';
import StatusToasts from '../../components/StatusToasts';
import { createListing, fetchMyListings, updateListing, withdrawListing } from '../../features/marketplace/api';
import { marketplaceQueryKeys } from '../../features/marketplace/queryKeys';
import { useMarketplaceConnection } from '../../features/marketplace/useMarketplaceSync';
import { formatMoney, formatQuantity, inclusiveFromExclusive } from '../../features/marketplace/decimal';
import type { ListingStatus, MarketplaceListing } from '../../features/marketplace/types';
import { fetchProducts } from '../../features/invoices/api';
import { invoiceQueryKeys } from '../../features/invoices/queryKeys';
import ListingFormModal, { type ListingFormValues } from './components/ListingFormModal';
import MarketplaceGate from './components/MarketplaceGate';
import SyncStatusChip from './components/SyncStatusChip';
import { formatRelativeTime } from './components/format';

const STATUS_LABELS: Record<ListingStatus, string> = {
  draft: 'Draft',
  active: 'Active',
  paused: 'Paused',
  withdrawn: 'Withdrawn',
  rejected: 'Rejected by operator',
};

/** Blank optional fields are omitted rather than sent as "" — the contract's
 *  quantities are decimal strings and an empty one is not one. */
function optionalDecimal(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed === '' ? undefined : trimmed;
}

export default function MyListingsPage() {
  const queryClient = useQueryClient();
  const connectionQuery = useMarketplaceConnection();

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<MarketplaceListing | null>(null);
  const [withdrawTarget, setWithdrawTarget] = useState<MarketplaceListing | null>(null);
  const [formError, setFormError] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const connected = connectionQuery.data?.status === 'connected';

  const listingsQuery = useQuery({
    queryKey: marketplaceQueryKeys.listings(),
    queryFn: fetchMyListings,
    enabled: connected,
  });

  const productsQuery = useQuery({
    queryKey: invoiceQueryKeys.products,
    queryFn: fetchProducts,
    enabled: connected,
  });

  const closeForm = () => {
    setFormOpen(false);
    setEditing(null);
    setFormError('');
  };

  const saveMutation = useMutation({
    mutationFn: (values: ListingFormValues) => {
      const shared = {
        asking_price: values.askingPrice.trim(),
        available_quantity: values.availableQuantity.trim(),
        title: values.title.trim(),
        description: values.description.trim(),
        min_order_quantity: optionalDecimal(values.minOrderQuantity) ?? null,
        max_order_quantity: optionalDecimal(values.maxOrderQuantity) ?? null,
      };
      return editing
        ? updateListing(editing.id, shared)
        : createListing({ product_id: Number(values.productId), ...shared });
    },
    onSuccess: () => {
      setSuccess(editing ? 'Listing updated.' : 'Product published to the marketplace.');
      closeForm();
      void queryClient.invalidateQueries({ queryKey: marketplaceQueryKeys.all });
    },
    onError: (err) => setFormError(getApiErrorMessage(err, 'Unable to save this listing')),
  });

  const statusMutation = useMutation({
    mutationFn: (input: { listing: MarketplaceListing; status: ListingStatus }) =>
      updateListing(input.listing.id, { status: input.status }),
    onSuccess: (_data, input) => {
      setSuccess(input.status === 'paused' ? 'Listing paused.' : 'Listing is live again.');
      void queryClient.invalidateQueries({ queryKey: marketplaceQueryKeys.all });
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Unable to change the listing status')),
  });

  const withdrawMutation = useMutation({
    mutationFn: (listing: MarketplaceListing) => withdrawListing(listing.id),
    onSuccess: () => {
      setSuccess('Listing withdrawn from the marketplace.');
      setWithdrawTarget(null);
      void queryClient.invalidateQueries({ queryKey: marketplaceQueryKeys.all });
    },
    onError: (err) => {
      setError(getApiErrorMessage(err, 'Unable to withdraw this listing'));
      setWithdrawTarget(null);
    },
  });

  const listings = listingsQuery.data ?? [];

  return (
    <div className="marketplace-page stack">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Marketplace</p>
          <h1 className="page-title">My listings</h1>
          <p className="section-copy">
            Products you have published for other businesses to buy. Prices are per unit; the
            marketplace publishes the tax-exclusive figure, with what a buyer pays shown beneath
            it.
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
                  ? 'Your registration is awaiting operator approval. You can publish listings as soon as it is approved — no re-registration needed.'
                  : 'This connection cannot publish listings right now. Open Marketplace settings for details.'
              }
            />
          </div>
        ) : (
          <section className="panel stack">
            <div className="panel__header">
              <div>
                <p className="eyebrow">Published</p>
                <h2 className="nav-panel__title">{listings.length} listings</h2>
              </div>
              <button
                type="button"
                className="button button--primary button--small"
                onClick={() => { setEditing(null); setFormError(''); setFormOpen(true); }}
              >
                <Plus size={16} />
                Publish a product
              </button>
            </div>

            {listingsQuery.isLoading && <EmptyState message="Loading listings…" />}
            {!listingsQuery.isLoading && listings.length === 0 && (
              <EmptyState message="You have not published anything yet. Publish a product to make it visible to every other instance on this marketplace." />
            )}

            {listings.length > 0 && (
              <div className="marketplace-table-scroll">
                <table className="marketplace-table">
                  <thead>
                    <tr>
                      <th>Listing</th>
                      <th>Price / unit</th>
                      <th>Advertised quantity</th>
                      <th>Status</th>
                      <th aria-label="Actions" />
                    </tr>
                  </thead>
                  <tbody>
                    {listings.map((listing) => (
                      <tr key={listing.id}>
                        <td>
                          <strong>{listing.title}</strong>
                          <span className="table-subtext">
                            {listing.hsn_sac ? `HSN ${listing.hsn_sac} · ` : ''}GST {listing.gst_rate}% · {listing.unit}
                          </span>
                          {listing.last_error && (
                            <span className="marketplace-note marketplace-note--error">{listing.last_error}</span>
                          )}
                        </td>
                        <td>
                          {formatMoney(listing.asking_price, listing.currency_code)}
                          {inclusiveFromExclusive(listing.asking_price, listing.gst_rate) && (
                            <span className="table-subtext">
                              {inclusiveFromExclusive(listing.asking_price, listing.gst_rate)} incl.
                              GST
                            </span>
                          )}
                        </td>
                        <td>
                          {formatQuantity(listing.available_quantity_published)}
                          <span className="table-subtext">
                            published {formatRelativeTime(listing.last_published_at)}
                          </span>
                        </td>
                        <td>
                          <span className={`status-chip status-chip--${listing.status}`}>
                            {STATUS_LABELS[listing.status] ?? listing.status}
                          </span>
                        </td>
                        <td>
                          <div className="button-row">
                            <button
                              type="button"
                              className="button button--ghost button--small"
                              onClick={() => { setEditing(listing); setFormError(''); setFormOpen(true); }}
                            >
                              Edit
                            </button>
                            {listing.status === 'active' && (
                              <button
                                type="button"
                                className="button button--ghost button--small"
                                onClick={() => statusMutation.mutate({ listing, status: 'paused' })}
                              >
                                <Pause size={14} />
                                Pause
                              </button>
                            )}
                            {listing.status === 'paused' && (
                              <button
                                type="button"
                                className="button button--ghost button--small"
                                onClick={() => statusMutation.mutate({ listing, status: 'active' })}
                              >
                                <Play size={14} />
                                Resume
                              </button>
                            )}
                            {listing.status !== 'withdrawn' && (
                              <button
                                type="button"
                                className="button button--danger button--small"
                                onClick={() => setWithdrawTarget(listing)}
                              >
                                <Trash2 size={14} />
                                Withdraw
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}
      </MarketplaceGate>

      {formOpen && (
        <ListingFormModal
          listing={editing ?? undefined}
          products={productsQuery.data ?? []}
          submitting={saveMutation.isPending}
          error={formError}
          onClose={closeForm}
          onSubmit={(values) => saveMutation.mutate(values)}
        />
      )}

      {withdrawTarget && (
        <ConfirmDialog
          title="Withdraw listing"
          message={`Withdraw "${withdrawTarget.title}" from the marketplace? It stops appearing in every other instance's browse immediately. Orders already placed against it are unaffected.`}
          confirmText="Withdraw"
          danger
          onConfirm={() => withdrawMutation.mutate(withdrawTarget)}
          onCancel={() => setWithdrawTarget(null)}
        />
      )}

      <StatusToasts
        error={error || (listingsQuery.error ? getApiErrorMessage(listingsQuery.error) : '')}
        success={success}
        onClearError={() => setError('')}
        onClearSuccess={() => setSuccess('')}
      />
    </div>
  );
}
