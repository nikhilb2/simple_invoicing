import { useEffect, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { useEscapeClose } from '../hooks/useEscapeClose';
import { getApiErrorMessage } from '../api/client';
import type { BOMComponent, Product } from '../types/api';
import { fetchBOM, createBOMEntry, updateBOMEntry, deleteBOMEntry } from '../services/bomApi';
import ProductCombobox from './ProductCombobox';
import api from '../api/client';
import type { PaginatedProducts } from '../types/api';

type BOMConfigModalProps = {
  productId: number;
  productName: string;
  onClose: () => void;
};

export default function BOMConfigModal({ productId, productName, onClose }: BOMConfigModalProps) {
  const [components, setComponents] = useState<BOMComponent[]>([]);
  const [allProducts, setAllProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // Add row state
  const [addComponentId, setAddComponentId] = useState('');
  const [addQty, setAddQty] = useState('1');
  const [adding, setAdding] = useState(false);

  // Inline edit qty state: bomId -> draft string
  const [editQty, setEditQty] = useState<Record<number, string>>({});
  const [savingId, setSavingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  useEscapeClose(onClose);

  useEffect(() => {
    void loadData();
  }, [productId]);

  async function loadData() {
    try {
      setLoading(true);
      setError('');
      const [bomData, productsRes] = await Promise.all([
        fetchBOM(productId),
        api.get<PaginatedProducts>('/products/', { params: { page: 1, page_size: 500 } }),
      ]);
      setComponents(bomData);
      // Exclude the product itself from component options
      setAllProducts(productsRes.data.items.filter((p) => p.id !== productId));
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load BOM data'));
    } finally {
      setLoading(false);
    }
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    const componentId = Number(addComponentId);
    const qty = Number(addQty);
    if (!componentId || qty <= 0) return;

    try {
      setAdding(true);
      setError('');
      await createBOMEntry({ product_id: productId, component_product_id: componentId, quantity_required: qty });
      setAddComponentId('');
      setAddQty('1');
      setSuccess('Component added.');
      await loadData();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to add component'));
    } finally {
      setAdding(false);
    }
  }

  async function handleSaveQty(bomId: number) {
    const qty = Number(editQty[bomId]);
    if (!qty || qty <= 0) return;

    try {
      setSavingId(bomId);
      setError('');
      await updateBOMEntry(bomId, { quantity_required: qty });
      setEditQty((prev) => {
        const next = { ...prev };
        delete next[bomId];
        return next;
      });
      setSuccess('Quantity updated.');
      await loadData();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to update quantity'));
    } finally {
      setSavingId(null);
    }
  }

  async function handleDelete(bomId: number) {
    try {
      setDeletingId(bomId);
      setError('');
      await deleteBOMEntry(bomId);
      setSuccess('Component removed.');
      await loadData();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to remove component'));
    } finally {
      setDeletingId(null);
    }
  }

  const totalCost = components.reduce(
    (sum, c) => sum + c.component_price * c.quantity_required,
    0
  );

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="bom-modal-title">
      <div className="modal-panel" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '640px', width: '100%' }}>
        <div className="panel__header">
          <div>
            <p className="eyebrow">Bill of Materials</p>
            <h2 id="bom-modal-title" className="nav-panel__title">{productName}</h2>
          </div>
          <button
            type="button"
            className="button button--ghost"
            onClick={onClose}
            title="Close modal"
            aria-label="Close BOM modal"
          >
            ✕
          </button>
        </div>

        {error ? <p className="error-message" role="alert">{error}</p> : null}
        {success ? <p className="success-message" role="status">{success}</p> : null}

        {loading ? (
          <p style={{ padding: '16px 0', color: 'var(--color-text-muted)' }}>Loading components…</p>
        ) : (
          <div className="stack">
            {/* Add component form */}
            <form onSubmit={handleAdd} className="stack" style={{ gap: '8px' }}>
              <p style={{ fontWeight: 600, fontSize: '0.875rem' }}>Add component</p>
              <div className="field-grid">
                <div className="field field--full">
                  <label htmlFor="bom-component-select">Component product</label>
                  <ProductCombobox
                    id="bom-component-select"
                    products={allProducts}
                    value={addComponentId}
                    onChange={(id) => setAddComponentId(id)}
                    required
                  />
                </div>
                <div className="field">
                  <label htmlFor="bom-component-qty">Quantity required</label>
                  <input
                    id="bom-component-qty"
                    className="input"
                    type="number"
                    min="0.001"
                    step="0.001"
                    value={addQty}
                    onChange={(e) => setAddQty(e.target.value)}
                    required
                  />
                </div>
              </div>
              <div className="button-row">
                <button
                  className="button button--primary"
                  disabled={adding || !addComponentId}
                  title="Add component to BOM"
                  aria-label="Add component to BOM"
                >
                  {adding ? 'Adding…' : 'Add component'}
                </button>
              </div>
            </form>

            {/* Components list */}
            {components.length === 0 ? (
              <p style={{ color: 'var(--color-text-muted)', fontSize: '0.875rem' }}>
                No components defined yet. Add components above.
              </p>
            ) : (
              <div className="table-list">
                {components.map((c) => {
                  const isDirty = editQty[c.id] !== undefined;
                  return (
                    <div key={c.id} className="table-row">
                      <div className="table-row__meta">
                        <strong>{c.component_name}</strong>
                        <span className="table-subtext">{c.component_sku} · {c.component_unit}</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <input
                          className="input"
                          type="number"
                          min="0.001"
                          step="0.001"
                          style={{ width: '90px' }}
                          value={isDirty ? editQty[c.id] : String(c.quantity_required)}
                          onChange={(e) => setEditQty((prev) => ({ ...prev, [c.id]: e.target.value }))}
                          aria-label={`Quantity for ${c.component_name}`}
                        />
                        {isDirty ? (
                          <button
                            type="button"
                            className="button button--secondary"
                            style={{ padding: '4px 10px', fontSize: '0.8rem' }}
                            disabled={savingId === c.id}
                            onClick={() => void handleSaveQty(c.id)}
                            title="Save quantity"
                            aria-label={`Save quantity for ${c.component_name}`}
                          >
                            {savingId === c.id ? 'Saving…' : 'Save'}
                          </button>
                        ) : null}
                        <button
                          type="button"
                          className="button button--danger button--icon"
                          disabled={deletingId === c.id}
                          onClick={() => void handleDelete(c.id)}
                          title={`Remove ${c.component_name}`}
                          aria-label={`Remove ${c.component_name} from BOM`}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {components.length > 0 ? (
              <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)', textAlign: 'right' }}>
                Estimated material cost per unit: <strong>{totalCost.toFixed(2)}</strong>
              </p>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}
