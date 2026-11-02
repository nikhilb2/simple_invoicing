import { useEffect, useMemo, useRef, useState } from 'react';
import ProductCombobox from '../../../components/ProductCombobox';
import ModalCloseButton from '../../../components/ModalCloseButton';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import {
  canonicalAskingPrice,
  computeUnitPrice,
  inclusiveFromExclusive,
  parseDecimal,
} from '../../../features/marketplace/decimal';
import type { MarketplaceListing } from '../../../features/marketplace/types';
import type { Product } from '../../../types/api';

export type ListingFormValues = {
  productId: string;
  /** Always tax-exclusive, whichever way the seller typed it. */
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
  /**
   * Publish a product the caller already chose — from a Products or Inventory
   * row. The picker is replaced by a fixed summary so the row you clicked is
   * the row you publish.
   */
  lockedProduct?: Product;
  /** Advisory stock to seed the published quantity with, when the caller knows it. */
  initialQuantity?: string;
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
 *
 * The price is entered either tax-exclusive or tax-inclusive but always *sent*
 * tax-exclusive: that is what the contract stores, and both sides post their
 * invoice with `tax_inclusive=false` from it. The toggle only decides which of
 * the two numbers the seller types; the other one is shown underneath either
 * way, so the price a buyer will actually pay is never hidden behind a mode.
 */
export default function ListingFormModal({
  listing,
  products,
  lockedProduct,
  initialQuantity,
  submitting,
  error,
  onClose,
  onSubmit,
}: ListingFormModalProps) {
  const [fields, setFields] = useState<Omit<ListingFormValues, 'askingPrice'>>(() => ({
    productId: listing ? String(listing.product_id) : lockedProduct ? String(lockedProduct.id) : '',
    availableQuantity: listing?.available_quantity_published ?? initialQuantity ?? '',
    title: listing?.title ?? lockedProduct?.name ?? '',
    description: listing?.description ?? lockedProduct?.description ?? '',
    minOrderQuantity: listing?.min_order_quantity ?? '',
    maxOrderQuantity: listing?.max_order_quantity ?? '',
  }));
  /**
   * The price is held exactly as typed, and which of the two prices that text
   * means is a separate flag. The tax-exclusive value the contract wants is
   * *derived* from the pair rather than stored alongside it — keeping a second
   * copy in state is what lets the two drift apart when the rate arrives late
   * (a price typed before a product is picked) or when a partial entry like
   * "12." converts to nothing.
   */
  const [priceInput, setPriceInput] = useState(
    () => listing?.asking_price ?? (lockedProduct ? String(lockedProduct.price) : ''),
  );
  const [priceIncludesTax, setPriceIncludesTax] = useState(false);
  /**
   * The product the combobox handed us. It is kept rather than re-looked-up in
   * `products`, which is capped at 500 rows — the combobox runs its own server
   * search and can hand back a product that is not in that list at all. Deriving
   * the rate from the prop would then leave it null and publish a GST-inclusive
   * entry as if it were tax-exclusive.
   */
  const [pickedProduct, setPickedProduct] = useState<Product | null>(null);
  /** Which product's list price the box was auto-seeded from, if it was. */
  const [seededFrom, setSeededFrom] = useState<number | null>(
    lockedProduct && !listing ? lockedProduct.id : null,
  );
  const priceRef = useRef<HTMLInputElement>(null);

  useEscapeClose(onClose);
  useEffect(() => { priceRef.current?.focus(); }, []);

  const patch = (next: Partial<typeof fields>) => setFields((prev) => ({ ...prev, ...next }));

  // The rate is the product's, not the seller's to override here — it is what
  // the buyer books, so the preview has to use the same number the wire will.
  const selectedProduct =
    lockedProduct ?? pickedProduct ?? products.find((p) => String(p.id) === fields.productId);
  const gstRate = listing ? listing.gst_rate : selectedProduct ? String(selectedProduct.gst_rate) : null;

  const askingPrice = useMemo(
    () => canonicalAskingPrice(priceInput, priceIncludesTax, gstRate),
    [priceInput, priceIncludesTax, gstRate],
  );

  const togglePriceMode = (includesTax: boolean) => {
    // Without a rate the box cannot be restated, and flipping the flag alone
    // would silently reinterpret the same digits as the other price once a
    // product arrives. The control is disabled in that state; this is the guard.
    if (gstRate === null || includesTax === priceIncludesTax) return;
    setPriceIncludesTax(includesTax);
    // Restate the same price in the new mode rather than reinterpreting the
    // digits already in the box as a different one.
    const converted = includesTax ? inclusiveFromExclusive(askingPrice, gstRate) : askingPrice;
    // An unparseable entry has no counterpart to restate to — leave what the
    // seller typed alone rather than blanking the field under them.
    if (converted && parseDecimal(converted)) setPriceInput(converted);
  };

  const selectProduct = (productId: string, product: Product) => {
    setPickedProduct(product);
    patch({
      productId,
      // Seed the copy from the product so publishing is one click away for the
      // common case.
      title: fields.title || product.name,
      description: fields.description || product.description || '',
    });
    // Re-seed when the box is empty or still holds the *previous* product's
    // list price — otherwise switching product would publish it at the old one.
    if (priceInput && seededFrom === null) return;
    if (seededFrom === product.id) return;
    // `product.price` is a net price, so seeding an inclusive box with it
    // verbatim would understate the listing by the GST.
    const rate = String(product.gst_rate);
    const seed = String(product.price);
    setPriceInput(priceIncludesTax ? inclusiveFromExclusive(seed, rate) ?? seed : seed);
    setSeededFrom(product.id);
  };

  const typePrice = (text: string) => {
    setPriceInput(text);
    // Once the seller edits it, it is theirs — a later product change must not
    // overwrite it.
    setSeededFrom(null);
  };

  // A half-typed price ("12.") derives to nothing, and in inclusive mode that
  // leaves the submitted value empty behind a box that still looks filled in —
  // so the guard is on the derived value, not on the text. Zero and negative
  // prices parse fine and the backend has no constraint against them, so they
  // are stopped here.
  const parsedPrice = parseDecimal(askingPrice);
  const priceIsValid = parsedPrice !== null && parsedPrice.units > 0n;

  const currencyCode = listing?.currency_code ?? 'INR';

  const preview = useMemo(
    () => (gstRate === null ? null : computeUnitPrice(askingPrice, gstRate)),
    [askingPrice, gstRate],
  );

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
              {listing ? listing.title : lockedProduct?.name ?? 'New marketplace listing'}
            </h2>
          </div>
          <ModalCloseButton onClick={onClose} label="Close listing form" />
        </div>

        <form
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit({ ...fields, askingPrice });
          }}
        >
          {!listing && !lockedProduct && (
            <div className="field">
              <label htmlFor="marketplace-listing-product">Product</label>
              <ProductCombobox
                id="marketplace-listing-product"
                products={products}
                value={fields.productId}
                onChange={selectProduct}
                required
              />
              <p className="marketplace-note">
                GST rate, HSN/SAC and unit are taken from the product — the marketplace shows the
                seller's declared rate and both invoices are posted from it.
              </p>
            </div>
          )}

          {!listing && lockedProduct && (
            <div className="marketplace-note marketplace-note--emphasis">
              Publishing <strong>{lockedProduct.name}</strong> ({lockedProduct.sku}) — GST{' '}
              {lockedProduct.gst_rate}%
              {lockedProduct.hsn_sac ? ` · HSN/SAC ${lockedProduct.hsn_sac}` : ''} · per{' '}
              {lockedProduct.unit}. The rate, HSN/SAC and unit come from the product master and are
              what a buyer will book.
            </div>
          )}

          <fieldset className="marketplace-price-mode" disabled={gstRate === null}>
            <legend>Price entry</legend>
            <label>
              <input
                type="radio"
                name="marketplace-listing-price-mode"
                checked={!priceIncludesTax}
                onChange={() => togglePriceMode(false)}
              />
              Excluding GST
            </label>
            <label>
              <input
                type="radio"
                name="marketplace-listing-price-mode"
                checked={priceIncludesTax}
                onChange={() => togglePriceMode(true)}
              />
              Including GST
            </label>
            {gstRate === null && (
              <span className="marketplace-note">
                Choose a product first — its GST rate is what converts between the two.
              </span>
            )}
          </fieldset>

          <div className="field-grid field-grid--align-controls">
            <div className="field">
              <label htmlFor="marketplace-listing-price">
                {priceIncludesTax ? 'Asking price / unit (incl. GST)' : 'Asking price / unit (excl. GST)'}
              </label>
              <input
                id="marketplace-listing-price"
                ref={priceRef}
                className="input"
                type="text"
                inputMode="decimal"
                value={priceInput}
                onChange={(event) => typePrice(event.target.value)}
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
                value={fields.availableQuantity}
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
                value={fields.minOrderQuantity}
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
                value={fields.maxOrderQuantity}
                onChange={(event) => patch({ maxOrderQuantity: event.target.value })}
              />
            </div>
          </div>

          {gstRate !== null && (
            <>
              <dl className="marketplace-summary">
                <div>
                  <dt>Price published</dt>
                  <dd>{preview ? `${currencyCode} ${preview.net}` : '—'}</dd>
                </div>
                <div>
                  <dt>GST @ {gstRate}%</dt>
                  <dd>{preview ? `${currencyCode} ${preview.tax}` : '—'}</dd>
                </div>
                <div className="marketplace-summary__total">
                  <dt>Buyer pays per unit</dt>
                  <dd>{preview ? `${currencyCode} ${preview.gross}` : '—'}</dd>
                </div>
              </dl>
              <p className="marketplace-note">
                {priceIncludesTax
                  ? 'The marketplace stores the tax-exclusive price, so the amount you typed is divided by the GST rate before publishing. Check the figures above — a rate that does not divide evenly can land a paisa away from the gross you entered.'
                  : 'The marketplace publishes the tax-exclusive price. Buyers see the GST added on top, as above.'}
              </p>
            </>
          )}

          <div className="field">
            <label htmlFor="marketplace-listing-name">Listing title</label>
            <input
              id="marketplace-listing-name"
              className="input"
              type="text"
              value={fields.title}
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
              value={fields.description}
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
              disabled={submitting || !priceIsValid || (!listing && !fields.productId)}
            >
              {submitting ? 'Saving…' : listing ? 'Save changes' : 'Publish listing'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
