import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api, { getApiErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import EmptyState from '../components/EmptyState';
import type { CompanyProfile, InventoryRow, Invoice, PaginatedInventoryOut, Product } from '../types/api';
import formatCurrency from '../utils/formatting';

type DashboardState = {
  products: Product[];
  inventory: InventoryRow[];
  invoices: Invoice[];
};

function normalizeInventoryRows(payload: PaginatedInventoryOut | InventoryRow[] | unknown): InventoryRow[] {
  if (Array.isArray(payload)) {
    return payload;
  }
  if (payload && typeof payload === 'object' && 'items' in payload) {
    const items = (payload as PaginatedInventoryOut).items;
    return Array.isArray(items) ? items : [];
  }
  return [];
}

export default function DashboardPage() {
  const [state, setState] = useState<DashboardState>({ products: [], inventory: [], invoices: [] });
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const activeCurrencyCode = company?.currency_code || 'USD';
  const LOW_STOCK_THRESHOLD = 5;

  useEffect(() => {
    let active = true;

    async function loadDashboard() {
      try {
        setLoading(true);
        setError('');
        const [productsRes, inventoryRes, invoicesRes, companyRes] = await Promise.all([
          api.get<{ items: Product[] }>('/products/', { params: { page_size: 100 } }),
          api.get<PaginatedInventoryOut>('/inventory/', { params: { page_size: 100 } }),
          api.get<{ items: Invoice[] }>('/invoices/', { params: { page_size: 100 } }),
          api.get<CompanyProfile>('/company/'),
        ]);

        if (!active) {
          return;
        }

        setState({
          products: productsRes.data.items,
          inventory: normalizeInventoryRows(inventoryRes.data),
          invoices: invoicesRes.data.items,
        });
        setCompany(companyRes.data);
      } catch (err) {
        if (active) {
          setError(getApiErrorMessage(err, 'Unable to load dashboard data'));
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadDashboard();

    return () => {
      active = false;
    };
  }, []);

  const totalInventoryUnits = state.inventory.reduce((sum, row) => sum + row.quantity, 0);
  const lowStockCount = state.inventory.filter((row) => row.quantity <= LOW_STOCK_THRESHOLD).length;
  const invoiceRevenue = state.invoices.reduce((sum, invoice) => sum + invoice.total_amount, 0);

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Overview</p>
          <h1 className="page-title">Operations dashboard</h1>
          <p className="section-copy">A live snapshot of catalog size, stock position, and invoice throughput.</p>
        </div>
        <div className="status-chip">Backend synced</div>
      </section>

      <StatusToasts error={error} onClearError={() => setError('')} onClearSuccess={() => {}} />

      <section className="stats-grid">
        <article className="stat-card">
          <p className="eyebrow">Catalog</p>
          <p className="stat-card__value">{loading ? <span className="skeleton" style={{ width: '60px', height: '38px', display: 'inline-block' }} /> : state.products.length}</p>
          <p className="muted-text">Products available for quoting and invoicing.</p>
        </article>
        <article className="stat-card">
          <p className="eyebrow">Stock units</p>
          <p className="stat-card__value">{loading ? <span className="skeleton" style={{ width: '80px', height: '38px', display: 'inline-block' }} /> : totalInventoryUnits}</p>
          <p className="muted-text">Total quantity currently registered across inventory rows.</p>
        </article>
        <article className="stat-card">
          <p className="eyebrow">Low stock</p>
          <p className="stat-card__value">{loading ? <span className="skeleton" style={{ width: '40px', height: '38px', display: 'inline-block' }} /> : lowStockCount}</p>
          <p className="muted-text">Rows at 5 units or less that likely need replenishment.</p>
        </article>
        <article className="stat-card">
          <p className="eyebrow">Invoice value</p>
          <p className="stat-card__value">{loading ? <span className="skeleton" style={{ width: '120px', height: '38px', display: 'inline-block' }} /> : formatCurrency(invoiceRevenue, activeCurrencyCode)}</p>
          <p className="muted-text">Combined gross amount from currently listed invoices.</p>
        </article>
      </section>

      <section className="content-grid">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Stock watch</p>
              <h2 className="nav-panel__title">Inventory pressure points</h2>
            </div>
            <div className="status-chip">{state.inventory.length} tracked rows</div>
          </div>

          <div className="table-list">
            {loading ? (
              <>
                <div className="table-row skeleton" role="status" aria-label="Loading" style={{ height: '76px', borderColor: 'transparent' }}></div>
                <div className="table-row skeleton" role="status" aria-label="Loading" style={{ height: '76px', borderColor: 'transparent' }}></div>
                <div className="table-row skeleton" role="status" aria-label="Loading" style={{ height: '76px', borderColor: 'transparent' }}></div>
              </>
            ) : null}
            {!loading && state.inventory.length === 0 ? (
              <EmptyState 
                message="No inventory rows yet. Add products to track their stock." 
                action={<Link to="/products" className="button button--secondary button--small">Go to Products</Link>}
              />
            ) : null}
            {!loading
              ? state.inventory
                  .slice()
                  .sort((a, b) => a.quantity - b.quantity)
                  .slice(0, 5)
                  .map((row) => (
                    <div key={row.product_id} className="table-row">
                      <div className="table-row__meta">
                        <strong>{row.product_name}</strong>
                        <span className="table-subtext">Product ID #{row.product_id}</span>
                      </div>
                      <span className={`pill ${row.quantity <= LOW_STOCK_THRESHOLD ? 'pill--low' : 'pill--ok'}`}>{row.quantity} units</span>
                      <span className="table-subtext text-right">{row.quantity <= LOW_STOCK_THRESHOLD ? 'Needs attention' : 'Stable'}</span>
                    </div>
                  ))
              : null}
          </div>
        </article>

        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Recent invoices</p>
              <h2 className="nav-panel__title">Latest activity</h2>
            </div>
          </div>

          <div className="invoice-list">
            {loading ? (
              <>
                <div className="invoice-row skeleton" role="status" aria-label="Loading" style={{ height: '88px', borderColor: 'transparent' }}></div>
                <div className="invoice-row skeleton" role="status" aria-label="Loading" style={{ height: '88px', borderColor: 'transparent' }}></div>
                <div className="invoice-row skeleton" role="status" aria-label="Loading" style={{ height: '88px', borderColor: 'transparent' }}></div>
              </>
            ) : null}
            {!loading && state.invoices.length === 0 ? (
              <EmptyState 
                message="No invoices yet. Create your first invoice to get started." 
                action={<Link to="/invoices" className="button button--primary button--small">Create Invoice</Link>}
              />
            ) : null}
            {!loading
              ? state.invoices.slice(0, 6).map((invoice) => (
                  <div key={invoice.id} className="invoice-row">
                    <div className="invoice-row__meta">
                      <strong>{invoice.ledger?.name || invoice.ledger_name || 'Unknown ledger'}</strong>
                      <span className="table-subtext">Invoice #{invoice.id}</span>
                    </div>
                    <span className="invoice-row__price">{formatCurrency(invoice.total_amount, activeCurrencyCode)}</span>
                  </div>
                ))
              : null}
          </div>
        </article>
      </section>
    </div>
  );
}
