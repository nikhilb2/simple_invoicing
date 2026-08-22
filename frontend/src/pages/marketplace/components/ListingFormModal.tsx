import { useEffect, useRef, useState } from 'react';
import ProductCombobox from '../../../components/ProductCombobox';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import type { MarketplaceListing } from '../../../features/marketplace/types';
import type { Product } from '../../../types/api';

export type ListingFormValues = {
  productId: string;
  askingPrice: string;
  availableQuantity: string;
  title: string;
  description: string;
  minOrderQuantity: string;
  maxOrderQuantity: string;
};

type ListingFormModalProps = {
  /** Omitted when publishing a new product. */
  listing?: MarketplaceListing;
  products: Product[];
  submitting: boolean;
  error: string;
  onClose: () => void;
  onSubmit: (values: ListingFormValues) => void;
};

/**
 * Publish and edit share one form: the only structural difference is that the
 * product is chosen once and then fixed — a listing is unique per product, and
 * repointing one at a different product would silently change what a live
 * remote listing sells.
 */
export default function ListingFormModal({
  listing,
  products,
  submitting,
  error,
  onClose,
  onSubmit,
}: ListingFormModalProps) {
  const [values, setValues] = useState<ListingFormValues>({
    productId: listing ? String(listing.product_id) : '',
    askingPrice: listing?.asking_price ?? '',
    availableQuantity: listing?.available_quantity_published ?? '',
    title: listing?.title ?? '',
    description: listing?.description ?? '',
    minOrderQuantity: listing?.min_order_quantity ?? '',
    maxOrderQuantity: listing?.max_order_quantity ?? '',
  });
  const priceRef = useRef<HTMLInputElement>(null);

  useEscapeClose(onClose);
  useEffect(() => { priceRef.current?.focus(); }, []);

  const patch = (next: Partial<ListingFormValues>) => setValues((prev) => ({ ...prev, ...next }));

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="marketplace-listing-title"
      onClick={onClose}
    >
      <div className="modal-panel" onClick={(event) => event.stopPropagation()}>
        <div className="panel__header">
          <div>
            <p className="eyebrow">{listing ? 'Edit listing' : 'Publish a product'}</p>
            <h2 id="marketplace-listing-title" className="nav-panel__title">
              {listing ? listing.title : 'New marketplace listing'}
            </h2>
          </div>
        </div>

        <form
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit(values);
          }}
        >
          {!listing && (
            <div className="field">
              <label htmlFor="marketplace-listing-product">Product</label>
              <ProductCombobox
                id="marketplace-listing-product"
                products={products}
                value={values.productId}
                onChange={(productId, product) =>
                  patch({
                    productId,
                    // Seed the copy from the product so publishing is one click
                    // away for the common case.
                    title: values.title || product.name,
                    description: values.description || product.description || '',
                    askingPrice: values.askingPrice || String(product.price),
                  })
                }
                required
              />
              <p className="marketplace-note">
                GST rate, HSN/SAC and unit are taken from the product — the marketplace shows the
                seller's declared rate and both invoices are posted from it.
              </p>
            </div>
          )}

          <div className="field-grid">
            <div className="field">
              <label htmlFor="marketplace-listing-price">Asking price per unit (tax-exclusive)</label>
              <input
                id="marketplace-listing-price"
                ref={priceRef}
                className="input"
                type="text"
                inputMode="decimal"
                value={values.askingPrice}
                onChange={(event) => patch({ askingPrice: event.target.value })}
                required
              />
            </div>
            <div className="field">
              <label htmlFor="marketplace-listing-quantity">Quantity to advertise</label>
              <input
                id="marketplace-listing-quantity"
                className="input"
                type="text"
                inputMode="decimal"
                value={values.availableQuantity}
                onChange={(event) => patch({ availableQuantity: event.target.value })}
                required
              />
            </div>
            <div className="field">
              <label htmlFor="marketplace-listing-min">Minimum order quantity</label>
              <input
                id="marketplace-listing-min"
                className="input"
                type="text"
                inputMode="decimal"
                value={values.minOrderQuantity}
                onChange={(event) => patch({ minOrderQuantity: event.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor="marketplace-listing-max">Maximum order quantity</label>
              <input
                id="marketplace-listing-max"
                className="input"
                type="text"
                inputMode="decimal"
                value={values.maxOrderQuantity}
                onChange={(event) => patch({ maxOrderQuantity: event.target.value })}
              />
            </div>
          </div>

          <div className="field">
            <label htmlFor="marketplace-listing-name">Listing title</label>
            <input
              id="marketplace-listing-name"
              className="input"
              type="text"
              value={values.title}
              onChange={(event) => patch({ title: event.target.value })}
              maxLength={255}
              required
            />
          </div>

          <div className="field">
            <label htmlFor="marketplace-listing-description">Description</label>
            <textarea
              id="marketplace-listing-description"
              className="input textarea"
              rows={3}
              value={values.description}
              onChange={(event) => patch({ description: event.target.value })}
            />
          </div>

          <p className="marketplace-note">
            The quantity you advertise is an advisory snapshot. Your own stock stays authoritative —
            an order is checked against real inventory before it is accepted.
          </p>

          {error && <p className="marketplace-note marketplace-note--error">{error}</p>}

          <div className="button-row" style={{ justifyContent: 'flex-end' }}>
            <button type="button" className="button button--ghost" onClick={onClose} disabled={submitting}>
              Cancel
            </button>
            <button
              type="submit"
              className="button button--primary"
              disabled={submitting || (!listing && !values.productId)}
            >
              {submitting ? 'Saving…' : listing ? 'Save changes' : 'Publish listing'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
