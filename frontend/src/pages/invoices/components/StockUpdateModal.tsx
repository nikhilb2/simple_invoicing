import type { Dispatch, FormEvent, SetStateAction } from 'react';
import ProductCombobox from '../../../components/ProductCombobox';
import type { Product } from '../../../types/api';
import type { StockFormState } from '../types';

type StockUpdateModalProps = {
  products: Product[];
  stockForm: StockFormState;
  setStockForm: Dispatch<SetStateAction<StockFormState>>;
  stockSubmitting: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onClose: () => void;
};

export default function StockUpdateModal({
  products,
  stockForm,
  setStockForm,
  stockSubmitting,
  onSubmit,
  onClose,
}: StockUpdateModalProps) {
  const selectedProduct = stockForm.productId
    ? products.find((product) => product.id === Number(stockForm.productId))
    : null;

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="stock-modal-title">
      <div className="modal-panel">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Inventory</p>
            <h2 id="stock-modal-title" className="nav-panel__title">Update stock</h2>
          </div>
        </div>

        <form className="stack" onSubmit={onSubmit}>
          {stockForm.productId ? (
            <div className="field-hint">
              {selectedProduct?.maintain_inventory
                ? 'Inventory tracking is enabled for this product.'
                : 'Inventory is disabled for this product. Enable Maintain inventory on the product before adjusting stock.'}
            </div>
          ) : null}
          <div className="field">
            <label htmlFor="modal-stock-product">Product</label>
            <ProductCombobox
              id="modal-stock-product"
              products={products}
              value={stockForm.productId}
              onChange={(productId) => setStockForm((current) => ({ ...current, productId }))}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="modal-stock-adjustment">Quantity adjustment</label>
            <input
              id="modal-stock-adjustment"
              className="input"
              type="number"
              step="1"
              value={stockForm.adjustment}
              onChange={(event) => setStockForm((current) => ({ ...current, adjustment: event.target.value }))}
              placeholder="e.g., +10 to add, -5 to remove"
              required
            />
          </div>
          <div className="field-hint">
            Use positive numbers to increase stock, negative numbers (like -5) to decrease stock.
          </div>

          <div className="button-row">
            <button type="button" className="button button--ghost" onClick={onClose} title="Cancel stock update" aria-label="Cancel stock update">
              Cancel
            </button>
            <button
              className="button button--primary"
              disabled={
                stockSubmitting ||
                (stockForm.productId
                  ? !products.find((product) => product.id === Number(stockForm.productId))?.maintain_inventory
                  : false)
              }
              title="Update stock"
              aria-label="Update stock"
            >
              {stockSubmitting ? 'Updating stock...' : 'Update stock'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
