import { useEffect, useState } from 'react';
import api, { getApiErrorMessage } from '../api/client';
import type { BOMComponent, PaginatedProducts, Product, ProductionTransaction } from '../types/api';
import StatusToasts from '../components/StatusToasts';
import EmptyState from '../components/EmptyState';
import { fetchBOM, fetchProductionHistory, produceBatch } from '../services/bomApi';

export default function ProduceItemsPage() {
  // Producable products list
  const [products, setProducts] = useState<Product[]>([]);
  const [loadingProducts, setLoadingProducts] = useState(true);

  // Selected product & BOM
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [bom, setBom] = useState<BOMComponent[]>([]);
  const [loadingBom, setLoadingBom] = useState(false);

  // Produce form
  const [quantity, setQuantity] = useState('1');
  const [notes, setNotes] = useState('');
  const [producing, setProducing] = useState(false);

  // History
  const [history, setHistory] = useState<ProductionTransaction[]>([]);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyTotalPages, setHistoryTotalPages] = useState(1);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const historyPageSize = 20;

  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // Product name lookup for history
  const [productNameMap, setProductNameMap] = useState<Record<number, string>>({});

  useEffect(() => {
    void loadProducableProducts();
    void loadHistory(1);
  }, []);

  useEffect(() => {
    void loadHistory(historyPage);
  }, [historyPage]);

  async function loadProducableProducts() {
    try {
      setLoadingProducts(true);
      const res = await api.get<PaginatedProducts>('/products/', {
        params: { page: 1, page_size: 500, is_producable: true },
      });
      const items = res.data.items;
      setProducts(items);
      const nameMap: Record<number, string> = {};
      items.forEach((p) => { nameMap[p.id] = p.name; });
      setProductNameMap(nameMap);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load producable products'));
    } finally {
      setLoadingProducts(false);
    }
  }

  async function handleSelectProduct(product: Product) {
    setSelectedProduct(product);
    setQuantity('1');
    setNotes('');
    setBom([]);
    try {
      setLoadingBom(true);
      const components = await fetchBOM(product.id);
      setBom(components);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load BOM for this product'));
    } finally {
      setLoadingBom(false);
    }
  }

  async function handleProduce(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedProduct) return;
    const qty = Number(quantity);
    if (!qty || qty <= 0) return;

    try {
      setProducing(true);
      setError('');
      setSuccess('');
      await produceBatch({ product_id: selectedProduct.id, quantity: qty });
      setSuccess(`Produced ${qty} × ${selectedProduct.name} successfully.`);
      // Refresh BOM requirements display (available qty may have changed)
      const components = await fetchBOM(selectedProduct.id);
      setBom(components);
      await loadHistory(1);
      setHistoryPage(1);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Production failed'));
    } finally {
      setProducing(false);
    }
  }

  async function loadHistory(page: number) {
    try {
      setLoadingHistory(true);
      const res = await fetchProductionHistory(page, historyPageSize);
      setHistory(res.items);
      setHistoryTotal(res.total);
      setHistoryTotalPages(res.total_pages);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load production history'));
    } finally {
      setLoadingHistory(false);
    }
  }

  function formatDate(iso: string | null) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString(undefined, {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  const qty = Number(quantity) || 0;

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Production</p>
          <h1 className="page-title">Produce items</h1>
          <p className="section-copy">
            Select a producable product, verify component availability, and run a production batch. Components are deducted from
            inventory automatically.
          </p>
        </div>
        <div className="status-chip">{historyTotal} runs logged</div>
      </section>

      <StatusToasts
        error={error}
        success={success}
        onClearError={() => setError('')}
        onClearSuccess={() => setSuccess('')}
      />

      <section className="content-grid">
        {/* Left panel — product select + produce form */}
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Run production</p>
              <h2 className="nav-panel__title">Select product &amp; quantity</h2>
            </div>
          </div>

          {loadingProducts ? (
            <EmptyState message="Loading producable products…" />
          ) : products.length === 0 ? (
            <EmptyState
              message="No producable products found. Mark a product as Producable on the Products page, then configure its Bill of Materials."
            />
          ) : (
            <>
              <div className="field">
                <label htmlFor="produce-product-select">Product to produce</label>
                <select
                  id="produce-product-select"
                  className="input"
                  value={selectedProduct?.id ?? ''}
                  onChange={(e) => {
                    const product = products.find((p) => p.id === Number(e.target.value));
                    if (product) void handleSelectProduct(product);
                  }}
                >
                  <option value="">— select a product —</option>
                  {products.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.sku})
                    </option>
                  ))}
                </select>
              </div>

              {selectedProduct ? (
                <>
                  {/* BOM requirements table */}
                  <div>
                    <p style={{ fontWeight: 600, fontSize: '0.875rem', marginBottom: '8px' }}>
                      Required components {qty > 0 ? `for ${qty} unit${qty !== 1 ? 's' : ''}` : ''}
                    </p>
                    {loadingBom ? (
                      <p style={{ color: 'var(--color-text-muted)', fontSize: '0.875rem' }}>Loading BOM…</p>
                    ) : bom.length === 0 ? (
                      <p style={{ color: 'var(--color-text-muted)', fontSize: '0.875rem' }}>
                        No BOM configured for this product. Add components via Products → Configure BOM.
                      </p>
                    ) : (
                      <div className="table-list">
                        {bom.map((c) => (
                          <div key={c.id} className="table-row">
                            <div className="table-row__meta">
                              <strong>{c.component_name}</strong>
                              <span className="table-subtext">{c.component_sku} · {c.component_unit}</span>
                            </div>
                            <span style={{ fontSize: '0.875rem', color: 'var(--color-text-muted)' }}>
                              {qty > 0
                                ? `${(c.quantity_required * qty).toFixed(3).replace(/\.?0+$/, '')} ${c.component_unit} needed`
                                : `${c.quantity_required} ${c.component_unit} per unit`}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {bom.length > 0 ? (
                    <form onSubmit={(e) => void handleProduce(e)} className="stack">
                      <div className="field-grid">
                        <div className="field">
                          <label htmlFor="produce-qty">Quantity to produce</label>
                          <input
                            id="produce-qty"
                            className="input"
                            type="number"
                            min={selectedProduct.allow_decimal ? '0.001' : '1'}
                            step={selectedProduct.allow_decimal ? '0.001' : '1'}
                            value={quantity}
                            onChange={(e) => setQuantity(e.target.value)}
                            required
                          />
                        </div>
                        <div className="field field--full">
                          <label htmlFor="produce-notes">Notes (optional)</label>
                          <input
                            id="produce-notes"
                            className="input"
                            value={notes}
                            onChange={(e) => setNotes(e.target.value)}
                            placeholder="e.g. Batch #42, assembly run"
                          />
                        </div>
                      </div>
                      <div className="button-row">
                        <button
                          className="button button--primary"
                          disabled={producing || bom.length === 0}
                          title="Start production run"
                          aria-label="Start production run"
                        >
                          {producing ? 'Producing…' : `Produce ${quantity || '?'} × ${selectedProduct.name}`}
                        </button>
                      </div>
                    </form>
                  ) : null}
                </>
              ) : null}
            </>
          )}
        </article>

        {/* Right panel — production history */}
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Audit log</p>
              <h2 className="nav-panel__title">Production history</h2>
            </div>
          </div>

          {loadingHistory ? (
            <EmptyState message="Loading history…" />
          ) : history.length === 0 ? (
            <EmptyState message="No production runs recorded yet." />
          ) : (
            <div className="table-list">
              {history.map((tx) => (
                <div key={tx.id} className="table-row">
                  <div className="table-row__meta">
                    <strong>{productNameMap[tx.product_id] ?? `Product #${tx.product_id}`}</strong>
                    <span className="table-subtext">
                      {formatDate(tx.created_at)}
                      {tx.notes ? ` · ${tx.notes}` : ''}
                    </span>
                  </div>
                  <span style={{ fontSize: '0.875rem', color: 'var(--color-text)' }}>
                    ×{tx.quantity_produced}
                  </span>
                </div>
              ))}
            </div>
          )}

          {historyTotalPages > 1 ? (
            <div className="button-row" style={{ justifyContent: 'center', paddingTop: '8px' }}>
              <button
                type="button"
                className="button button--ghost"
                disabled={historyPage <= 1}
                onClick={() => setHistoryPage((p) => p - 1)}
                title="Previous page"
                aria-label="Previous page"
              >
                Previous
              </button>
              <span className="muted-text" style={{ alignSelf: 'center' }}>
                Page {historyPage} of {historyTotalPages}
              </span>
              <button
                type="button"
                className="button button--ghost"
                disabled={historyPage >= historyTotalPages}
                onClick={() => setHistoryPage((p) => p + 1)}
                title="Next page"
                aria-label="Next page"
              >
                Next
              </button>
            </div>
          ) : null}
        </article>
      </section>
    </div>
  );
}
