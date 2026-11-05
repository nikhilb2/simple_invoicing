import { useState, type FormEvent } from 'react';
import ModalCloseButton from '../../../components/ModalCloseButton';
import { useQueryClient } from '@tanstack/react-query';
import api, { getApiErrorMessage } from '../../../api/client';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import { invoiceQueryKeys } from '../../../features/invoices/queryKeys';
import { useInvoiceComposerStore } from '../../../store/useInvoiceComposerStore';
import type { Product } from '../../../types/api';
import type { ProductFormState } from '../types';
import GstRateSelect from '../../catalogue/GstRateSelect';
import {
  NO_STOCK_SAVED_NOTE,
  NO_STOCK_WARNING,
  hsnProblem,
  plainProductError,
  startsWithNoStock,
} from '../../catalogue/productFormRules';

const UNIT_OPTIONS = ['Pieces', 'Kg', 'g', 'm', 'l', 'Ounce'];
const CUSTOM_UNIT_VALUE = '__custom__';

/* Serial tracking is asked for here and nowhere else in the composer, so it
   rides along locally rather than widening the shared form state. */

function createInitialProductForm(): ProductFormState {
  return { name: '', sku: '', hsn_sac: '', price: '', gst_rate: '', unit: 'Pieces', allow_decimal: false, maintain_inventory: true, track_serials: false, initial_quantity: '0' };
}

export default function ProductQuickCreateModal() {
  const queryClient = useQueryClient();
  const showProductCreateModal = useInvoiceComposerStore((state) => state.showProductCreateModal);
  const closeProductCreateModal = useInvoiceComposerStore((state) => state.closeProductCreateModal);
  const setFeedbackError = useInvoiceComposerStore((state) => state.setFeedbackError);
  const setFeedbackSuccess = useInvoiceComposerStore((state) => state.setFeedbackSuccess);
  const [productForm, setProductForm] = useState<ProductFormState>(createInitialProductForm());
  const [productSubmitting, setProductSubmitting] = useState(false);

  /* Stock is only counted here for a plain tracked product: serials are received
     on a purchase entry, and an untracked product has no stock to open with. */
  const asksOpeningStock = productForm.maintain_inventory && !productForm.track_serials;
  const openingQuantity = asksOpeningStock ? Number(productForm.initial_quantity || 0) : 0;
  const noOpeningStock = !productForm.track_serials && startsWithNoStock(productForm.maintain_inventory, openingQuantity);

  useEscapeClose(() => {
    if (showProductCreateModal) {
      closeProductCreateModal();
    }
  });

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const hsnError = hsnProblem(productForm.hsn_sac);
    if (hsnError) {
      setFeedbackError(hsnError);
      return;
    }
    if (asksOpeningStock && (Number.isNaN(openingQuantity) || openingQuantity < 0)) {
      setFeedbackError('Opening stock cannot be negative.');
      return;
    }

    try {
      setProductSubmitting(true);
      setFeedbackError('');

      const payload = {
        name: productForm.name.trim(),
        sku: productForm.sku.trim().toUpperCase(),
        hsn_sac: productForm.hsn_sac.trim(),
        price: Number(productForm.price),
        gst_rate: Number(productForm.gst_rate),
        unit: productForm.unit.trim() || 'Pieces',
        allow_decimal: productForm.allow_decimal,
        maintain_inventory: productForm.maintain_inventory,
        track_serials: productForm.track_serials,
        initial_quantity: openingQuantity,
      };

      const created = await api.post<Product>('/products/', payload);
      setProductForm(createInitialProductForm());
      closeProductCreateModal();
      const notes = [created.data.hsn_warning, noOpeningStock ? NO_STOCK_SAVED_NOTE : null].filter(Boolean);
      setFeedbackSuccess(`Product created successfully.${notes.length ? ` ${notes.join(' ')}` : ''}`);
      await queryClient.invalidateQueries({ queryKey: invoiceQueryKeys.all });
      await queryClient.invalidateQueries({ queryKey: invoiceQueryKeys.products });
    } catch (err) {
      setFeedbackError(plainProductError(getApiErrorMessage(err, 'Unable to create product')));
    } finally {
      setProductSubmitting(false);
    }
  }

  if (!showProductCreateModal) {
    return null;
  }

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="product-modal-title">
      <div className="modal-panel">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Quick add</p>
            <h2 id="product-modal-title" className="nav-panel__title">Create product</h2>
          </div>
          <ModalCloseButton onClick={closeProductCreateModal} label="Close create product" />
        </div>

        <form className="stack" onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="modal-product-name">Product name</label>
            <input
              id="modal-product-name"
              className="input"
              value={productForm.name}
              onChange={(event) => setProductForm((current) => ({ ...current, name: event.target.value }))}
              placeholder="e.g., Widget Pro"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="modal-product-sku">SKU</label>
            <input
              id="modal-product-sku"
              className="input"
              value={productForm.sku}
              onChange={(event) => setProductForm((current) => ({ ...current, sku: event.target.value }))}
              placeholder="e.g., WP-001"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="modal-product-hsn-sac">HSN/SAC</label>
            <input
              id="modal-product-hsn-sac"
              className="input"
              value={productForm.hsn_sac}
              onChange={(event) => setProductForm((current) => ({ ...current, hsn_sac: event.target.value }))}
              placeholder="8471 or 9983"
            />
          </div>
          <div className="field">
            <label htmlFor="modal-product-price">Unit price</label>
            <input
              id="modal-product-price"
              className="input"
              type="number"
              step="0.01"
              min="0"
              value={productForm.price}
              onChange={(event) => setProductForm((current) => ({ ...current, price: event.target.value }))}
              placeholder="0.00"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="modal-product-gst-rate">GST %</label>
            <GstRateSelect id="modal-product-gst-rate" value={productForm.gst_rate} onChange={(rate) => setProductForm((current) => ({ ...current, gst_rate: rate }))} />
          </div>
          <div className="field">
            <label htmlFor="modal-product-unit">Unit</label>
            <select
              id="modal-product-unit"
              className="input"
              value={UNIT_OPTIONS.includes(productForm.unit) ? productForm.unit : CUSTOM_UNIT_VALUE}
              onChange={(event) => {
                const value = event.target.value;
                setProductForm((current) => ({
                  ...current,
                  unit: value === CUSTOM_UNIT_VALUE ? '' : value,
                }));
              }}
            >
              {UNIT_OPTIONS.map((unitOption) => (
                <option key={unitOption} value={unitOption}>{unitOption}</option>
              ))}
              <option value={CUSTOM_UNIT_VALUE}>Other (custom)</option>
            </select>
          </div>
          {UNIT_OPTIONS.includes(productForm.unit) ? null : (
            <div className="field">
              <label htmlFor="modal-product-custom-unit">Custom unit</label>
              <input
                id="modal-product-custom-unit"
                className="input"
                value={productForm.unit}
                onChange={(event) => setProductForm((current) => ({ ...current, unit: event.target.value }))}
                placeholder="e.g. cm, ml, pack"
                required
              />
            </div>
          )}
          <div className="field field--full" style={{ marginBottom: 0 }}>
            <label htmlFor="modal-product-maintain-inventory" style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: 0 }}>
              <input
                id="modal-product-maintain-inventory"
                type="checkbox"
                checked={productForm.maintain_inventory}
                disabled={productForm.track_serials}
                onChange={(event) => setProductForm((current) => ({ ...current, maintain_inventory: event.target.checked }))}
              />
              Maintain inventory for this product
            </label>
            <small className="field-hint">
              {productForm.track_serials
                ? 'Always on while serial numbers are tracked — every serial is a unit of stock.'
                : 'Disable this for service charges and other non-stock items.'}
            </small>
          </div>
          {asksOpeningStock ? (
            <div className="field">
              <label htmlFor="modal-product-opening-stock">Opening stock</label>
              <input
                id="modal-product-opening-stock"
                className="input"
                type="number"
                min="0"
                step={productForm.allow_decimal ? '0.001' : '1'}
                value={productForm.initial_quantity}
                onChange={(event) => setProductForm((current) => ({ ...current, initial_quantity: event.target.value }))}
              />
              {noOpeningStock ? <small className="field-warning" role="status">{NO_STOCK_WARNING}</small> : null}
            </div>
          ) : null}
          <div className="field field--full" style={{ marginBottom: 0 }}>
            <label htmlFor="modal-product-allow-decimal" style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: 0 }}>
              <input
                id="modal-product-allow-decimal"
                type="checkbox"
                checked={productForm.allow_decimal}
                disabled={productForm.track_serials}
                onChange={(event) => setProductForm((current) => ({ ...current, allow_decimal: event.target.checked }))}
              />
              Allow decimal quantity
            </label>
            <small className="field-hint">
              {productForm.track_serials
                ? 'Not available while serial numbers are tracked — half a serial number does not exist.'
                : 'Enable this for fractional stock units like Kg or l.'}
            </small>
          </div>
          <div className="field field--full" style={{ marginBottom: 0 }}>
            <label htmlFor="modal-product-track-serials" style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: 0 }}>
              <input
                id="modal-product-track-serials"
                type="checkbox"
                checked={productForm.track_serials}
                onChange={(event) => setProductForm((current) => ({
                  ...current,
                  track_serials: event.target.checked,
                  allow_decimal: event.target.checked ? false : current.allow_decimal,
                  maintain_inventory: event.target.checked ? true : current.maintain_inventory,
                }))}
              />
              Track serial numbers / IMEI
            </label>
            <small className="field-hint">
              Each unit gets its own IMEI or serial number — for phones, appliances, anything with a warranty.
              Receive the units on a purchase entry once the product is saved.
            </small>
          </div>

          <div className="button-row">
            <button type="button" className="button button--ghost" onClick={closeProductCreateModal} title="Cancel product creation" aria-label="Cancel product creation">
              Cancel
            </button>
            <button className="button button--primary" disabled={productSubmitting} title="Save product" aria-label="Save product">
              {productSubmitting ? 'Saving product...' : 'Save product'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
