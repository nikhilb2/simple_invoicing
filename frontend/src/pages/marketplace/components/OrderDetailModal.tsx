import { Link } from 'react-router-dom';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import { formatMoney, formatQuantity } from '../../../features/marketplace/decimal';
import type { MarketplaceOrder } from '../../../features/marketplace/types';
import { formatDate, formatDateTime } from './format';
import UnverifiedSellerBadge from './UnverifiedSellerBadge';

/** Order detail is a modal rather than a route: it is a read-only expansion of
 *  a row, and a route would need its own guard stack and title entry for it. */
export default function OrderDetailModal({
  order,
  onClose,
}: {
  order: MarketplaceOrder;
  onClose: () => void;
}) {
  useEscapeClose(onClose);

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="marketplace-order-title"
      onClick={onClose}
    >
      <div className="modal-panel modal-panel--marketplace-order" onClick={(event) => event.stopPropagation()}>
        <div className="panel__header">
          <div>
            <p className="eyebrow">{order.side === 'sell' ? 'Selling' : 'Buying'}</p>
            <h2 id="marketplace-order-title" className="nav-panel__title">{order.remote_order_id}</h2>
          </div>
          <span className={`status-chip status-chip--${order.state}`}>{order.state}</span>
        </div>

        <div className="marketplace-buy__seller">
          <span>
            {order.side === 'sell' ? 'Buyer' : 'Seller'}: <strong>{order.counterparty_name || 'Unknown'}</strong>
            {order.counterparty_gstin ? ` · ${order.counterparty_gstin}` : ''}
          </span>
          <UnverifiedSellerBadge />
        </div>

        <dl className="marketplace-summary">
          <div>
            <dt>Placed</dt>
            <dd>{formatDateTime(order.order_placed_at)}</dd>
          </div>
          <div>
            <dt>Expires</dt>
            <dd>{formatDateTime(order.expires_at)}</dd>
          </div>
          <div>
            <dt>Accepted</dt>
            <dd>{formatDateTime(order.accepted_at)}</dd>
          </div>
          <div>
            <dt>Contact</dt>
            <dd>{order.counterparty_email || order.counterparty_phone || '—'}</dd>
          </div>
          <div className="marketplace-summary__total">
            <dt>Order total</dt>
            <dd>{formatMoney(order.remote_total_amount, order.currency_code)}</dd>
          </div>
        </dl>

        {order.counterparty_address && (
          <p className="marketplace-note">Address: {order.counterparty_address}</p>
        )}

        <div className="marketplace-table-scroll">
          <table className="marketplace-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Item</th>
                <th>Quantity</th>
                <th>Unit price</th>
                <th>GST</th>
              </tr>
            </thead>
            <tbody>
              {order.items.map((item) => (
                <tr key={item.id}>
                  <td>{item.line_no}</td>
                  <td>
                    <strong>{item.title || item.remote_listing_id || '—'}</strong>
                    {item.hsn_sac && <span className="table-subtext">HSN {item.hsn_sac}</span>}
                  </td>
                  <td>{formatQuantity(item.quantity)} {item.unit ?? ''}</td>
                  <td>{formatMoney(item.unit_price, order.currency_code)}</td>
                  <td>{item.gst_rate}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {order.reject_reason && (
          <p className="marketplace-note marketplace-note--warning">
            Rejected: {order.reject_reason}{order.reject_note ? ` — ${order.reject_note}` : ''}
          </p>
        )}

        {order.seller_invoice_number && (
          <p className="marketplace-note">
            Seller's invoice {order.seller_invoice_number} dated {formatDate(order.seller_invoice_date)}.
          </p>
        )}

        {order.total_mismatch && (
          <p className="marketplace-note marketplace-note--warning">
            The invoice total posted here does not match the order total held by the marketplace. The
            local invoice is authoritative — reconcile with the counterparty before settling.
          </p>
        )}

        {order.posting_warnings && (
          <p className="marketplace-note marketplace-note--warning">{order.posting_warnings}</p>
        )}

        <div className="button-row" style={{ justifyContent: 'flex-end' }}>
          {order.posted_invoice_id && (
            <Link className="button button--secondary" to={`/invoices?edit=${order.posted_invoice_id}`}>
              Open invoice{order.posted_invoice_number ? ` ${order.posted_invoice_number}` : ''}
            </Link>
          )}
          <button type="button" className="button button--ghost" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
