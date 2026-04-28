import { useState, type FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import api, { getApiErrorMessage } from '../../../api/client';
import ProductCombobox from '../../../components/ProductCombobox';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import { fetchProducts } from '../../../features/invoices/api';
import { invoiceQueryKeys } from '../../../features/invoices/queryKeys';
import { useInvoiceComposerStore } from '../../../store/useInvoiceComposerStore';
import type { StockFormState } from '../types';

function createInitialStockForm(): StockFormState {
  return { productId: '', adjustment: '' };
}

export default function StockUpdateModal() {
  const queryClient = useQueryClient();
  const showStockUpdateModal = useInvoiceComposerStore((state) => state.showStockUpdateModal);
  const closeStockUpdateModal = useInvoiceComposerStore((state) => state.closeStockUpdateModal);
  const setFeedbackError = useInvoiceComposerStore((state) => state.setFeedbackError);
  const setFeedbackSuccess = useInvoiceComposerStore((state) => state.setFeedbackSuccess);
  const [stockForm, setStockForm] = useState<StockFormState>(createInitialStockForm());
  const [stockSubmitting, setStockSubmitting] = useState(false);
  const productsQuery = useQuery({
    queryKey: invoiceQueryKeys.products,
    queryFn: fetchProducts,
    enabled: showStockUpdateModal,
  });
  const products = productsQuery.data ?? [];

  useEscapeClose(() => {
    if (showStockUpdateModal) {
      closeStockUpdateModal();
    }
  });

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    try {
      setStockSubmitting(true);
      setFeedbackError('');

      const payload = {
        product_id: Number(stockForm.productId),
        quantity: Number(stockForm.adjustment),
      };

      const selectedProduct = products.find((product) => product.id === payload.product_id);
      if (selectedProduct && !selectedProduct.maintain_inventory) {
        setFeedbackError(`Inventory is disabled for ${selectedProduct.name}. Enable Maintain inventory on the product first.`);
        return;
      }

      await api.post('/inventory/adjust', payload);
      setStockForm(createInitialStockForm());
      closeStockUpdateModal();
      setFeedbackSuccess('Stock updated successfully.');
      await queryClient.invalidateQueries({ queryKey: invoiceQueryKeys.all });
    } catch (err) {
      setFeedbackError(getApiErrorMessage(err, 'Unable to update stock'));
    } finally {
      setStockSubmitting(false);
    }
  }

  if (!showStockUpdateModal) {
    return null;
  }

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

        <form className="stack" onSubmit={handleSubmit}>
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
            <button type="button" className="button button--ghost" onClick={closeStockUpdateModal} title="Cancel stock update" aria-label="Cancel stock update">
              Cancel
            </button>
            <button
              className="button button--primary"
              disabled={
                productsQuery.isLoading ||
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
