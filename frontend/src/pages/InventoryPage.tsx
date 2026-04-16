import { useEffect, useState } from 'react';
import { ArrowUpDown } from 'lucide-react';
import api, { getApiErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import type { InventoryAdjust, InventoryRow } from '../types/api';

type SortBy = 'name' | 'quantity' | 'date_added' | 'last_sold';
type SortOrder = 'asc' | 'desc';

export default function InventoryPage() {
  const [rows, setRows] = useState<InventoryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [search, setSearch] = useState('');
  const [sortBy, setSortBy] = useState<SortBy>('name');
  const [sortOrder, setSortOrder] = useState<SortOrder>('asc');
  // Per-row adjustment state: productId -> delta string
  const [adjusting, setAdjusting] = useState<Record<number, string>>({});
  const [submittingId, setSubmittingId] = useState<number | null>(null);

  async function loadInventory() {
    try {
      setLoading(true);
      setError('');
      const res = await api.get<InventoryRow[]>('/inventory/', {
        params: { search, sort_by: sortBy, sort_order: sortOrder },
      });
      setRows(res.data);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load inventory'));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadInventory();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, sortBy, sortOrder]);

  function toggleSort(col: SortBy) {
    if (sortBy === col) {
      setSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortBy(col);
      setSortOrder('asc');
    }
  }

  function setRowDelta(productId: number, value: string) {
    setAdjusting((prev) => ({ ...prev, [productId]: value }));
  }

  async function applyAdjustment(productId: number) {
    const delta = Number(adjusting[productId] ?? '0');
    if (delta === 0) return;

    try {
      setSubmittingId(productId);
      setError('');
      setSuccess('');
      const payload: InventoryAdjust = { product_id: productId, quantity: delta };
      await api.post('/inventory/adjust', payload);
      setAdjusting((prev) => ({ ...prev, [productId]: '' }));
      setSuccess('Inventory updated.');
      await loadInventory();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to adjust inventory'));
    } finally {
      setSubmittingId(null);
    }
  }

  function formatDate(iso: string | null) {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
  }

  function SortHeader({ col, label }: { col: SortBy; label: string }) {
    const active = sortBy === col;
    return (
      <button
        type="button"
        className={`button button--ghost inventory-sort-btn${active ? ' inventory-sort-btn--active' : ''}`}
        onClick={() => toggleSort(col)}
        title={`Sort by ${label}`}
        aria-label={`Sort by ${label}`}
      >
        {label}
        <ArrowUpDown size={12} style={{ marginLeft: 4, opacity: active ? 1 : 0.4 }} />
        {active ? <span className="sr-only">({sortOrder})</span> : null}
      </button>
    );
  }

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Inventory</p>
          <h1 className="page-title">Stock ledger</h1>
          <p className="section-copy">Search products, review on-hand quantities, and apply inline adjustments.</p>
        </div>
        <div className="status-chip">{rows.length} products</div>
      </section>

      <StatusToasts error={error} success={success} onClearError={() => setError('')} onClearSuccess={() => setSuccess('')} />

      <section className="content-grid content-grid--full">
        <article className="panel stack">
          {/* Toolbar */}
          <div className="panel__header" style={{ flexWrap: 'wrap', gap: '12px' }}>
            <div className="field" style={{ flex: '1 1 260px', margin: 0 }}>
              <input
                className="input"
                type="search"
                placeholder="Search by name or SKU…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                aria-label="Search inventory by name or SKU"
              />
            </div>
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
              <span className="muted-text" style={{ fontSize: '0.75rem' }}>Sort:</span>
              <SortHeader col="name" label="Name" />
              <SortHeader col="quantity" label="Qty" />
              <SortHeader col="date_added" label="Date added" />
              <SortHeader col="last_sold" label="Last sold" />
            </div>
          </div>

          {/* Feed table header */}
          <div className="table-list">
            {loading ? <div className="empty-state">Loading inventory…</div> : null}
            {!loading && rows.length === 0 ? (
              <div className="empty-state">No products match your search.</div>
            ) : null}
            {!loading
              ? rows.map((row) => (
                  <div key={row.product_id} className="table-row inventory-feed-row">
                    {/* Product info */}
                    <div className="table-row__meta" style={{ flex: '1 1 180px' }}>
                      <strong>{row.product_name}</strong>
                      <span className="table-subtext">{row.sku}</span>
                    </div>

                    {/* Qty pill */}
                    <span className={`pill ${row.quantity <= 5 ? 'pill--low' : 'pill--ok'}`} style={{ minWidth: 48, textAlign: 'center' }}>
                      {row.quantity}
                    </span>

                    {/* Dates */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 110 }}>
                      <span className="table-subtext" style={{ fontSize: '0.72rem' }}>
                        Added: {formatDate(row.date_added)}
                      </span>
                      <span className="table-subtext" style={{ fontSize: '0.72rem' }}>
                        Sold: {formatDate(row.last_sold_at)}
                      </span>
                    </div>

                    {/* Inline adjustment */}
                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flex: '0 0 auto' }}>
                      <input
                        className="input"
                        type="number"
                        step="1"
                        placeholder="e.g. +10"
                        value={adjusting[row.product_id] ?? ''}
                        onChange={(e) => setRowDelta(row.product_id, e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') void applyAdjustment(row.product_id); }}
                        style={{ width: 88 }}
                        aria-label={`Adjust quantity for ${row.product_name}`}
                        disabled={submittingId === row.product_id}
                      />
                      <button
                        type="button"
                        className="button button--secondary"
                        onClick={() => void applyAdjustment(row.product_id)}
                        disabled={submittingId === row.product_id || !adjusting[row.product_id]}
                        title={`Apply adjustment for ${row.product_name}`}
                        aria-label={`Apply adjustment for ${row.product_name}`}
                        style={{ whiteSpace: 'nowrap' }}
                      >
                        {submittingId === row.product_id ? 'Applying…' : 'Apply'}
                      </button>
                    </div>
                  </div>
                ))
              : null}
          </div>
        </article>
      </section>
    </div>
  );
}
