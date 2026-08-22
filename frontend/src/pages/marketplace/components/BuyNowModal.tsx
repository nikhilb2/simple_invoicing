import { useEffect, useMemo, useRef, useState } from 'react';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import {
  computeOrderTotals,
  formatMoney,
  formatQuantity,
  gstTreatment,
  stateCodeFromGstin,
} from '../../../features/marketplace/decimal';
import type { CatalogListing } from '../../../features/marketplace/types';
import { formatRelativeTime } from './format';
import UnverifiedSellerBadge, { UNVERIFIED_SELLER_COPY } from './UnverifiedSellerBadge';

type BuyNowModalProps = {
  listing: CatalogListing;
  /** Our own GSTIN — its first two digits decide IGST vs CGST/SGST. */
  ourGstin: string | null;
  submitting: boolean;
  error: string;
  onClose: () => void;
  onConfirm: (quantity: string) => void;
};

export default function BuyNowModal({
  listing,
  ourGstin,
  submitting,
  error,
  onClose,
  onConfirm,
}: BuyNowModalProps) {
  const [quantity, setQuantity] = useState(listing.min_order_quantity ?? '1');
  const quantityRef = useRef<HTMLInputElement>(null);

  useEscapeClose(onClose);
  useEffect(() => { quantityRef.current?.focus(); }, []);

  const totals = useMemo(
    () => computeOrderTotals(listing.asking_price, quantity, listing.gst_rate),
    [listing.asking_price, listing.gst_rate, quantity],
  );

  const treatment = gstTreatment(stateCodeFromGstin(ourGstin), listing.seller.state_code);

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="marketplace-buy-title"
      onClick={onClose}
    >
      <div className="modal-panel" onClick={(event) => event.stopPropagation()}>
        <div className="panel__header">
          <div>
            <p className="eyebrow">Buy now</p>
            <h2 id="marketplace-buy-title" className="nav-panel__title">{listing.title}</h2>
          </div>
        </div>

        <div className="marketplace-buy__seller">
          <span>
            Sold by <strong>{listing.seller.legal_name}</strong>
            {listing.seller.gstin ? ` · ${listing.seller.gstin}` : ''}
          </span>
          <UnverifiedSellerBadge />
        </div>
        <p className="marketplace-note marketplace-note--warning">{UNVERIFIED_SELLER_COPY}</p>

        <form
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            onConfirm(quantity.trim());
          }}
        >
          <div className="field">
            <label htmlFor="marketplace-buy-quantity">Quantity ({listing.unit})</label>
            <input
              id="marketplace-buy-quantity"
              ref={quantityRef}
              className="input"
              type="text"
              inputMode="decimal"
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              required
            />
            <p className="marketplace-note">
              {listing.min_order_quantity ? `Minimum ${formatQuantity(listing.min_order_quantity)}. ` : ''}
              {listing.max_order_quantity ? `Maximum ${formatQuantity(listing.max_order_quantity)}. ` : ''}
              {listing.allow_decimal ? 'Fractional quantities allowed.' : 'Whole units only.'}
            </p>
          </div>

          <dl className="marketplace-summary">
            <div>
              <dt>Unit price (tax-exclusive)</dt>
              <dd>{formatMoney(listing.asking_price, listing.currency_code)}</dd>
            </div>
            <div>
              <dt>Quantity</dt>
              <dd>{formatQuantity(quantity)} {listing.unit}</dd>
            </div>
            <div>
              <dt>Taxable value</dt>
              <dd>{totals ? formatMoney(totals.taxable, listing.currency_code) : '—'}</dd>
            </div>
            <div>
              <dt>GST @ {listing.gst_rate}%</dt>
              <dd>
                {totals ? formatMoney(totals.tax, listing.currency_code) : '—'}
                {totals && treatment.kind === 'cgst_sgst' && (
                  <span className="marketplace-summary__hint">
                    CGST {totals.cgst} + SGST {totals.sgst}
                  </span>
                )}
              </dd>
            </div>
            <div className="marketplace-summary__total">
              <dt>Total payable</dt>
              <dd>{totals ? formatMoney(totals.total, listing.currency_code) : '—'}</dd>
            </div>
          </dl>

          <p
            className={`marketplace-note${treatment.kind === 'unknown' ? ' marketplace-note--warning' : ''}`}
          >
            {treatment.label}
            {treatment.kind !== 'unknown' && listing.seller.state_code
              ? ` (seller state ${listing.seller.state_code}, your state ${stateCodeFromGstin(ourGstin)})`
              : ''}
          </p>

          <p className="marketplace-note marketplace-note--emphasis">
            Placing this order will create a <strong>purchase invoice</strong> in your books and
            <strong> increase your stock</strong> once the seller accepts and posts. Prices are
            tax-exclusive; no money moves through the marketplace — settle with the seller directly.
          </p>

          {error && <p className="marketplace-note marketplace-note--error">{error}</p>}

          <div className="button-row" style={{ justifyContent: 'flex-end' }}>
            <button type="button" className="button button--ghost" onClick={onClose} disabled={submitting}>
              Cancel
            </button>
            <button type="submit" className="button button--primary" disabled={submitting || !totals}>
              {submitting ? 'Placing order…' : 'Place order'}
            </button>
          </div>
        </form>

        <p className="marketplace-note">
          Seller reports {formatQuantity(listing.available_quantity)} {listing.unit} available
          {listing.available_quantity_as_of
            ? ` (as of ${formatRelativeTime(listing.available_quantity_as_of)})`
            : ''}
          . That figure is a snapshot the seller republishes, not a live reading — the order can
          still be rejected for stock.
        </p>
      </div>
    </div>
  );
}
