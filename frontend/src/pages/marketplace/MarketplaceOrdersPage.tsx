import { useState } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { AlertTriangle, RotateCw } from 'lucide-react';
import { getApiErrorMessage } from '../../api/client';
import EmptyState from '../../components/EmptyState';
import StatusToasts from '../../components/StatusToasts';
import Tabs, { TabPanel, type TabItem } from '../../components/Tabs';
import { acceptOrder, cancelOrder, fetchOrders, rejectOrder, retryOrderPosting } from '../../features/marketplace/api';
import { marketplaceQueryKeys } from '../../features/marketplace/queryKeys';
import { useMarketplaceConnection } from '../../features/marketplace/useMarketplaceSync';
import { formatMoney, formatQuantity } from '../../features/marketplace/decimal';
import type { MarketplaceOrder, OrderSide, RejectOrderPayload } from '../../features/marketplace/types';
import MarketplaceGate from './components/MarketplaceGate';
import OrderDetailModal from './components/OrderDetailModal';
import RejectOrderModal from './components/RejectOrderModal';
import SyncStatusChip from './components/SyncStatusChip';
import UnverifiedSellerBadge from './components/UnverifiedSellerBadge';
import { formatDateTime } from './components/format';

const PAGE_SIZE = 20;

const TABS: TabItem<OrderSide>[] = [
  { id: 'sell', label: 'Selling' },
  { id: 'buy', label: 'Buying' },
];

const STATES = ['pending', 'accepted', 'posted', 'rejected', 'cancelled', 'expired'];

/** Total ordered across the lines — shown as a quantity, not summed money. */
function orderQuantity(order: MarketplaceOrder): string {
  if (order.items.length === 1) {
    return `${formatQuantity(order.items[0].quantity)} ${order.items[0].unit ?? ''}`.trim();
  }
  return `${order.items.length} lines`;
}

export default function MarketplaceOrdersPage() {
  const queryClient = useQueryClient();
  const connectionQuery = useMarketplaceConnection();
  const [searchParams, setSearchParams] = useSearchParams();

  const [detailOrder, setDetailOrder] = useState<MarketplaceOrder | null>(null);
  const [rejectTarget, setRejectTarget] = useState<MarketplaceOrder | null>(null);
  const [rejectError, setRejectError] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const sideParam = searchParams.get('side') as OrderSide | null;
  const side: OrderSide = sideParam === 'buy' || sideParam === 'sell' ? sideParam : 'sell';
  const state = searchParams.get('state') ?? '';
  const page = Number(searchParams.get('page') ?? '1') || 1;

  // Tab and filters live in the URL so an order view is linkable, matching
  // AnalyticsPage. `replace` keeps tab flips out of the history stack.
  const patchParams = (patch: Record<string, string | undefined>) => {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(patch)) {
      if (value === undefined || value === '') next.delete(key);
      else next.set(key, value);
    }
    setSearchParams(next, { replace: true });
  };

  const connected = connectionQuery.data?.status === 'connected';

  const ordersQuery = useQuery({
    queryKey: marketplaceQueryKeys.orders(side, state, page, PAGE_SIZE),
    queryFn: () => fetchOrders({ side, state, page, pageSize: PAGE_SIZE }),
    placeholderData: keepPreviousData,
    enabled: connected,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: marketplaceQueryKeys.all });

  const acceptMutation = useMutation({
    mutationFn: (order: MarketplaceOrder) => acceptOrder(order.id),
    onSuccess: () => {
      setSuccess('Order accepted. A sales invoice will be posted and your stock decremented.');
      void invalidate();
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Unable to accept this order')),
  });

  const rejectMutation = useMutation({
    mutationFn: (input: { order: MarketplaceOrder; payload: RejectOrderPayload }) =>
      rejectOrder(input.order.id, input.payload),
    onSuccess: () => {
      setSuccess('Order rejected.');
      setRejectTarget(null);
      setRejectError('');
      void invalidate();
    },
    onError: (err) => setRejectError(getApiErrorMessage(err, 'Unable to reject this order')),
  });

  const cancelMutation = useMutation({
    mutationFn: (order: MarketplaceOrder) => cancelOrder(order.id),
    onSuccess: () => {
      setSuccess('Order cancelled.');
      void invalidate();
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Unable to cancel this order')),
  });

  const retryMutation = useMutation({
    mutationFn: (order: MarketplaceOrder) => retryOrderPosting(order.id),
    onSuccess: () => {
      setSuccess('Posting queued for retry.');
      void invalidate();
    },
    onError: (err) => setError(getApiErrorMessage(err, 'Unable to retry posting')),
  });

  const orders = ordersQuery.data?.items ?? [];
  const totalPages = ordersQuery.data?.total_pages ?? 1;
  const failedCount = orders.filter((order) => order.posting_state === 'failed').length;

  return (
    <div className="marketplace-page stack">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Marketplace</p>
          <h1 className="page-title">Orders</h1>
          <p className="section-copy">
            Orders on both sides. No money moves through the marketplace — settle with the
            counterparty directly.
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
            <EmptyState message="This connection cannot trade yet. Open Marketplace settings for its current status." />
          </div>
        ) : (
          <>
            {failedCount > 0 && (
              <div className="marketplace-alert" role="alert">
                <AlertTriangle size={18} />
                <div>
                  <strong>{failedCount} order{failedCount === 1 ? '' : 's'} failed to post an invoice.</strong>
                  <p>
                    The order state is settled but the accounting entry is not. Retry each one below —
                    the underlying cause (a missing financial year, a divergent payload) has to be
                    fixed first if the retry fails again.
                  </p>
                </div>
              </div>
            )}

            <section className="panel stack">
              <div className="panel__header">
                <Tabs
                  tabs={TABS}
                  value={side}
                  label="Order side"
                  onChange={(id) => patchParams({ side: id, page: undefined })}
                />
                <label className="marketplace-field">
                  <span className="marketplace-field__label">State</span>
                  <select
                    className="input"
                    value={state}
                    onChange={(event) => patchParams({ state: event.target.value, page: undefined })}
                  >
                    <option value="">All states</option>
                    {STATES.map((value) => (
                      <option key={value} value={value}>{value}</option>
                    ))}
                  </select>
                </label>
              </div>

              <TabPanel id={side}>
                {ordersQuery.isLoading && <EmptyState message="Loading orders…" />}
                {!ordersQuery.isLoading && orders.length === 0 && (
                  <EmptyState
                    message={
                      side === 'sell'
                        ? 'No one has ordered from your listings yet.'
                        : 'You have not placed any marketplace orders yet.'
                    }
                  />
                )}

                {orders.length > 0 && (
                  <div className="marketplace-table-scroll">
                    <table className="marketplace-table">
                      <thead>
                        <tr>
                          <th>Order</th>
                          <th>{side === 'sell' ? 'Buyer' : 'Seller'}</th>
                          <th>Quantity</th>
                          <th>Total</th>
                          <th>State</th>
                          <th aria-label="Actions" />
                        </tr>
                      </thead>
                      <tbody>
                        {orders.map((order) => (
                          <tr
                            key={order.id}
                            className={order.posting_state === 'failed' ? 'marketplace-row--failed' : undefined}
                          >
                            <td>
                              <button
                                type="button"
                                className="marketplace-linklike"
                                onClick={() => setDetailOrder(order)}
                              >
                                {order.remote_order_id}
                              </button>
                              <span className="table-subtext">{formatDateTime(order.order_placed_at)}</span>
                            </td>
                            <td>
                              <span className="marketplace-card__seller">
                                {order.counterparty_name || 'Unknown'}
                                <UnverifiedSellerBadge />
                              </span>
                              <span className="table-subtext">{order.counterparty_gstin || 'No GSTIN'}</span>
                            </td>
                            <td>{orderQuantity(order)}</td>
                            <td>{formatMoney(order.remote_total_amount, order.currency_code)}</td>
                            <td>
                              <span className={`status-chip status-chip--${order.state}`}>{order.state}</span>
                              {order.posting_state === 'failed' && (
                                <span className="status-chip status-chip--failed">
                                  <AlertTriangle size={13} />
                                  Posting failed
                                </span>
                              )}
                              {order.posting_error && (
                                <span className="marketplace-note marketplace-note--error">
                                  {order.posting_error}
                                  {order.posting_attempts > 0 ? ` (${order.posting_attempts} attempts)` : ''}
                                </span>
                              )}
                              {order.total_mismatch && (
                                <span className="marketplace-note marketplace-note--warning">
                                  Invoice total differs from the order total
                                </span>
                              )}
                            </td>
                            <td>
                              <div className="button-row">
                                {order.side === 'sell' && order.state === 'pending' && (
                                  <>
                                    <button
                                      type="button"
                                      className="button button--primary button--small"
                                      onClick={() => acceptMutation.mutate(order)}
                                    >
                                      Accept
                                    </button>
                                    <button
                                      type="button"
                                      className="button button--danger button--small"
                                      onClick={() => { setRejectError(''); setRejectTarget(order); }}
                                    >
                                      Reject
                                    </button>
                                  </>
                                )}
                                {order.side === 'buy' && order.state === 'pending' && (
                                  <button
                                    type="button"
                                    className="button button--danger button--small"
                                    onClick={() => cancelMutation.mutate(order)}
                                  >
                                    Cancel
                                  </button>
                                )}
                                {order.posting_state === 'failed' && (
                                  <button
                                    type="button"
                                    className="button button--secondary button--small"
                                    onClick={() => retryMutation.mutate(order)}
                                  >
                                    <RotateCw size={14} />
                                    Retry posting
                                  </button>
                                )}
                                {order.posted_invoice_id && (
                                  <Link
                                    className="button button--ghost button--small"
                                    to={`/invoices?edit=${order.posted_invoice_id}`}
                                  >
                                    Invoice{order.posted_invoice_number ? ` ${order.posted_invoice_number}` : ''}
                                  </Link>
                                )}
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {totalPages > 1 && (
                  <div className="marketplace-pagination button-row">
                    <button
                      type="button"
                      className="button button--ghost button--small"
                      onClick={() => patchParams({ page: String(Math.max(1, page - 1)) })}
                      disabled={page <= 1}
                    >
                      Previous
                    </button>
                    <span className="marketplace-pagination__label">Page {page} of {totalPages}</span>
                    <button
                      type="button"
                      className="button button--ghost button--small"
                      onClick={() => patchParams({ page: String(Math.min(totalPages, page + 1)) })}
                      disabled={page >= totalPages}
                    >
                      Next
                    </button>
                  </div>
                )}
              </TabPanel>
            </section>
          </>
        )}
      </MarketplaceGate>

      {detailOrder && <OrderDetailModal order={detailOrder} onClose={() => setDetailOrder(null)} />}

      {rejectTarget && (
        <RejectOrderModal
          order={rejectTarget}
          submitting={rejectMutation.isPending}
          error={rejectError}
          onClose={() => { setRejectTarget(null); setRejectError(''); }}
          onConfirm={(payload) => rejectMutation.mutate({ order: rejectTarget, payload })}
        />
      )}

      <StatusToasts
        error={error || (ordersQuery.error ? getApiErrorMessage(ordersQuery.error) : '')}
        success={success}
        onClearError={() => setError('')}
        onClearSuccess={() => setSuccess('')}
      />
    </div>
  );
}
