import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api, { getApiErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import EmptyState from '../components/EmptyState';
import { MonthlyTrendChart, PaymentStatusDonut, TopProductsBars } from '../components/DashboardCharts';
import type { DashboardMetrics, InventoryRow, Invoice, PaginatedInventoryOut } from '../types/api';
import formatCurrency, { formatCompactCurrency } from '../utils/formatting';

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

const LOW_STOCK_THRESHOLD = 5;

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [lowStock, setLowStock] = useState<InventoryRow[]>([]);
  const [recentInvoices, setRecentInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const currencyCode = metrics?.currency_code || 'USD';

  useEffect(() => {
    let active = true;

    async function loadDashboard() {
      try {
        setLoading(true);
        setError('');
        const [metricsRes, inventoryRes, invoicesRes] = await Promise.all([
          api.get<DashboardMetrics>('/dashboard/metrics'),
          api.get<PaginatedInventoryOut>('/inventory/', {
            params: { sort_by: 'quantity', sort_order: 'asc', page_size: 5 },
          }),
          api.get<{ items: Invoice[] }>('/invoices/', { params: { page_size: 6 } }),
        ]);

        if (!active) {
          return;
        }

        setMetrics(metricsRes.data);
        setLowStock(normalizeInventoryRows(inventoryRes.data));
        setRecentInvoices(invoicesRes.data.items);
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

  const skeleton = (width: string) => (
    <span className="skeleton" style={{ width, height: '38px', display: 'inline-block' }} />
  );

  const money = (value: number) => ({
    value: formatCompactCurrency(value, currencyCode),
    title: formatCurrency(value, currencyCode),
  });

  const statCards: Array<{
    eyebrow: string;
    value: string | null;
    title?: string;
    width: string;
    copy: string;
    tone?: 'danger' | 'warning';
  }> = [
    {
      eyebrow: 'Net sales',
      ...(metrics ? money(metrics.sales.total_sales) : { value: null }),
      width: '120px',
      copy: `${metrics?.sales.sales_invoice_count ?? 0} active sales invoices.`,
    },
    {
      eyebrow: 'Outstanding',
      ...(metrics ? money(metrics.receivables.outstanding_amount) : { value: null }),
      width: '120px',
      copy: `${(metrics?.receivables.unpaid_count ?? 0) + (metrics?.receivables.partial_count ?? 0)} invoices awaiting payment.`,
    },
    {
      eyebrow: 'Overdue',
      ...(metrics ? money(metrics.receivables.overdue_amount) : { value: null }),
      width: '110px',
      copy: `${metrics?.receivables.overdue_count ?? 0} invoices past their due date.`,
      tone: (metrics?.receivables.overdue_amount ?? 0) > 0 ? 'danger' : undefined,
    },
    {
      eyebrow: 'This month',
      ...(metrics ? money(metrics.sales.this_month_sales) : { value: null }),
      width: '120px',
      copy: `${formatCompactCurrency(metrics?.payments.this_month_received ?? 0, currencyCode)} received this month.`,
    },
    {
      eyebrow: 'Catalog',
      value: metrics ? String(metrics.catalog.total_products) : null,
      width: '60px',
      copy: 'Products available for quoting and invoicing.',
    },
    {
      eyebrow: 'Stock value',
      ...(metrics ? money(metrics.inventory.stock_value) : { value: null }),
      width: '120px',
      copy: `${metrics?.inventory.total_units ?? 0} units across ${metrics?.inventory.tracked_products ?? 0} tracked products.`,
    },
    {
      eyebrow: 'Low stock',
      value: metrics ? String(metrics.inventory.low_stock_count) : null,
      width: '50px',
      copy: `${metrics?.inventory.out_of_stock_count ?? 0} products are out of stock.`,
      tone: (metrics?.inventory.low_stock_count ?? 0) > 0 ? 'warning' : undefined,
    },
    {
      eyebrow: 'Avg invoice',
      ...(metrics ? money(metrics.sales.average_invoice_value) : { value: null }),
      width: '110px',
      copy: `${formatCompactCurrency(metrics?.payments.received_total ?? 0, currencyCode)} received all-time.`,
    },
  ];

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Overview</p>
          <h1 className="page-title">Operations dashboard</h1>
          <p className="section-copy">A live snapshot of revenue, receivables, and stock position.</p>
        </div>
        <div className="status-chip">Backend synced</div>
      </section>

      <StatusToasts error={error} onClearError={() => setError('')} onClearSuccess={() => {}} />

      <section className="stats-grid stats-grid--dense">
        {statCards.map((card) => (
          <article key={card.eyebrow} className="stat-card">
            <p className="eyebrow">{card.eyebrow}</p>
            <p
              className={`stat-card__value${card.tone ? ` stat-card__value--${card.tone}` : ''}`}
              title={!loading && metrics ? card.title : undefined}
            >
              {loading || !metrics ? skeleton(card.width) : card.value}
            </p>
            <p className="muted-text">{card.copy}</p>
          </article>
        ))}
      </section>

      <section className="content-grid">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Trend</p>
              <h2 className="nav-panel__title">Sales, purchases & receipts</h2>
            </div>
            <div className="status-chip">Last 12 months</div>
          </div>
          {loading || !metrics ? (
            <div className="skeleton" role="status" aria-label="Loading chart" style={{ height: '240px', borderRadius: '18px' }} />
          ) : (
            <MonthlyTrendChart data={metrics.charts.monthly} currencyCode={currencyCode} />
          )}
        </article>

        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Receivables</p>
              <h2 className="nav-panel__title">Payment status</h2>
            </div>
          </div>
          {loading || !metrics ? (
            <div className="skeleton" role="status" aria-label="Loading chart" style={{ height: '200px', borderRadius: '18px' }} />
          ) : (
            <PaymentStatusDonut
              paid={metrics.receivables.paid_count}
              partial={metrics.receivables.partial_count}
              unpaid={metrics.receivables.unpaid_count}
            />
          )}
        </article>
      </section>

      <section className="content-grid">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Stock watch</p>
              <h2 className="nav-panel__title">Inventory pressure points</h2>
            </div>
            {metrics ? <div className="status-chip">{metrics.inventory.tracked_products} tracked</div> : null}
          </div>

          <div className="table-list">
            {loading ? (
              <>
                <div className="table-row skeleton" role="status" aria-label="Loading" style={{ height: '76px', borderColor: 'transparent' }}></div>
                <div className="table-row skeleton" role="status" aria-label="Loading" style={{ height: '76px', borderColor: 'transparent' }}></div>
                <div className="table-row skeleton" role="status" aria-label="Loading" style={{ height: '76px', borderColor: 'transparent' }}></div>
              </>
            ) : null}
            {!loading && lowStock.length === 0 ? (
              <EmptyState
                message="No inventory rows yet. Add products to track their stock."
                action={<Link to="/products" className="button button--secondary button--small">Go to Products</Link>}
              />
            ) : null}
            {!loading
              ? lowStock.map((row) => (
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
              <p className="eyebrow">Best sellers</p>
              <h2 className="nav-panel__title">Top products by revenue</h2>
            </div>
          </div>
          {loading || !metrics ? (
            <div className="skeleton" role="status" aria-label="Loading" style={{ height: '160px', borderRadius: '18px' }} />
          ) : (
            <TopProductsBars data={metrics.charts.top_products} currencyCode={currencyCode} />
          )}
        </article>
      </section>

      <section className="content-grid content-grid--single">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Recent invoices</p>
              <h2 className="nav-panel__title">Latest activity</h2>
            </div>
            <Link to="/invoices" className="button button--secondary button--small">View all</Link>
          </div>

          <div className="invoice-list">
            {loading ? (
              <>
                <div className="invoice-row skeleton" role="status" aria-label="Loading" style={{ height: '88px', borderColor: 'transparent' }}></div>
                <div className="invoice-row skeleton" role="status" aria-label="Loading" style={{ height: '88px', borderColor: 'transparent' }}></div>
                <div className="invoice-row skeleton" role="status" aria-label="Loading" style={{ height: '88px', borderColor: 'transparent' }}></div>
              </>
            ) : null}
            {!loading && recentInvoices.length === 0 ? (
              <EmptyState
                message="No invoices yet. Create your first invoice to get started."
                action={<Link to="/invoices" className="button button--primary button--small">Create Invoice</Link>}
              />
            ) : null}
            {!loading
              ? recentInvoices.map((invoice) => (
                  <div key={invoice.id} className="invoice-row">
                    <div className="invoice-row__meta">
                      <strong>{invoice.ledger?.name || invoice.ledger_name || 'Unknown ledger'}</strong>
                      <span className="table-subtext">Invoice #{invoice.id}</span>
                    </div>
                    <span className="invoice-row__price">{formatCurrency(invoice.total_amount, currencyCode)}</span>
                  </div>
                ))
              : null}
          </div>
        </article>
      </section>
    </div>
  );
}
