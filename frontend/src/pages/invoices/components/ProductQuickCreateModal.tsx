import type { Dispatch, FormEvent, SetStateAction } from 'react';
import type { ProductFormState } from '../types';

type ProductQuickCreateModalProps = {
  productForm: ProductFormState;
  setProductForm: Dispatch<SetStateAction<ProductFormState>>;
  productSubmitting: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onClose: () => void;
};

export default function ProductQuickCreateModal({
  productForm,
  setProductForm,
  productSubmitting,
  onSubmit,
  onClose,
}: ProductQuickCreateModalProps) {
  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="product-modal-title">
      <div className="modal-panel">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Quick add</p>
            <h2 id="product-modal-title" className="nav-panel__title">Create product</h2>
          </div>
        </div>

        <form className="stack" onSubmit={onSubmit}>
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
            <input
              id="modal-product-gst-rate"
              className="input"
              type="number"
              min="0"
              max="100"
              step="0.01"
              value={productForm.gst_rate}
              onChange={(event) => setProductForm((current) => ({ ...current, gst_rate: event.target.value }))}
              placeholder="18"
              required
            />
          </div>
          <div className="field field--full" style={{ marginBottom: 0 }}>
            <label htmlFor="modal-product-maintain-inventory" style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: 0 }}>
              <input
                id="modal-product-maintain-inventory"
                type="checkbox"
                checked={productForm.maintain_inventory}
                onChange={(event) => setProductForm((current) => ({ ...current, maintain_inventory: event.target.checked }))}
              />
              Maintain inventory for this product
            </label>
            <small className="field-hint">Disable this for service charges and other non-stock items.</small>
          </div>

          <div className="button-row">
            <button type="button" className="button button--ghost" onClick={onClose} title="Cancel product creation" aria-label="Cancel product creation">
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
