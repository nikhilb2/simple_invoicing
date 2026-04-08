import { useEffect, useState } from 'react';
import api, { getApiErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import ProductCombobox from '../components/ProductCombobox';
import type { InventoryAdjust, InventoryRow, Product } from '../types/api';

export default function InventoryPage() {
  const [rows, setRows] = useState<InventoryRow[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [form, setForm] = useState({ productId: '', quantity: '1' });

  async function loadInventoryData() {
    try {
      setLoading(true);
      setError('');
      const [inventoryRes, productsRes] = await Promise.all([
        api.get<InventoryRow[]>('/inventory/'),
        api.get<{ items: Product[] }>('/products/', { params: { page_size: 500 } }),
      ]);

      setRows(inventoryRes.data);
      setProducts(productsRes.data.items);

      if (!form.productId && productsRes.data.items[0]) {
        setForm((current) => ({ ...current, productId: String(productsRes.data.items[0].id) }));
      }
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load inventory'));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadInventoryData();
  }, []);

  async function handleAdjustInventory(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    try {
      setSubmitting(true);
      setError('');
      setSuccess('');

      const payload: InventoryAdjust = {
        product_id: Number(form.productId),
        quantity: Number(form.quantity),
      };

      await api.post('/inventory/adjust', payload);
      setSuccess('Inventory updated successfully.');
      setForm((current) => ({ ...current, quantity: '1' }));
      await loadInventoryData();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to adjust inventory'));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Inventory</p>
          <h1 className="page-title">Stock adjustments</h1>
          <p className="section-copy">Apply inbound or outbound quantity changes and review current stock levels.</p>
        </div>
        <div className="status-chip">{rows.length} rows tracked</div>
      </section>

      <StatusToasts error={error} success={success} onClearError={() => setError('')} onClearSuccess={() => setSuccess('')} />

      <section className="content-grid">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Adjust stock</p>
              <h2 className="nav-panel__title">Inventory movement</h2>
            </div>
          </div>

          <form className="stack" onSubmit={handleAdjustInventory}>
            <div className="field-grid">
              <div className="field field--full">
                <label htmlFor="inventory-product">Product</label>
                <ProductCombobox
                  id="inventory-product"
                  products={products}
                  value={form.productId}
                  onChange={(productId) => setForm((current) => ({ ...current, productId }))}
                  required
                />
              </div>
              <div className="field field--full">
                <label htmlFor="inventory-quantity">Quantity delta</label>
                <input
                  id="inventory-quantity"
                  className="input"
                  type="number"
                  step="1"
                  value={form.quantity}
                  onChange={(event) => setForm((current) => ({ ...current, quantity: event.target.value }))}
                  required
                />
                <span className="field-hint">Use negative values to deduct stock. The API blocks negative ending balances.</span>
              </div>
            </div>

            <div className="button-row">
              <button className="button button--secondary" disabled={submitting || products.length === 0} title="Apply inventory adjustment" aria-label="Apply inventory adjustment">
                {submitting ? 'Applying change...' : 'Apply adjustment'}
              </button>
            </div>
          </form>
        </article>

        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">On-hand quantities</p>
              <h2 className="nav-panel__title">Stock ledger</h2>
            </div>
          </div>

          <div className="table-list">
            {loading ? <div className="empty-state">Loading inventory...</div> : null}
            {!loading && rows.length === 0 ? <div className="empty-state">No inventory entries yet.</div> : null}
            {!loading
              ? rows
                  .slice()
                  .sort((a, b) => a.product_name.localeCompare(b.product_name))
                  .map((row) => (
                    <div key={row.product_id} className="table-row">
                      <div className="table-row__meta">
                        <strong>{row.product_name}</strong>
                        <span className="table-subtext">Product #{row.product_id}</span>
                      </div>
                      <span className={`pill ${row.quantity <= 5 ? 'pill--low' : 'pill--ok'}`}>{row.quantity}</span>
                      <span className="table-subtext text-right">{row.quantity <= 5 ? 'Low stock' : 'Healthy stock'}</span>
                    </div>
                  ))
              : null}
          </div>
        </article>
      </section>
    </div>
  );
}
