import { useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import { getBlobErrorMessage } from '../../api/client';
import StatusToasts from '../../components/StatusToasts';
import { downloadProductSalesCsv, fetchProductSales } from '../../features/analytics/api';
import { analyticsQueryKeys } from '../../features/analytics/queryKeys';
import type { AnalyticsFilters, ProductSortBy, SortDir } from '../../features/analytics/types';
import formatCurrency from '../../utils/formatting';
import ProductSalesChart, { type ProductMetric } from './charts/ProductSalesChart';

const CHART_ROWS = 10;

export default function ProductSalesTab({ filters }: { filters: AnalyticsFilters }) {
  const [sortBy, setSortBy] = useState<ProductSortBy>('revenue');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [metric, setMetric] = useState<ProductMetric>('revenue');
  const [ranking, setRanking] = useState<'top' | 'bottom'>('top');
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState('');

  const query = useQuery({
    queryKey: analyticsQueryKeys.productSales(filters, sortBy, sortDir),
    queryFn: () => fetchProductSales(filters, sortBy, sortDir),
    placeholderData: keepPreviousData,
  });

  async function handleDownload() {
    if (!query.data) return;
    try {
      setDownloading(true);
      setError('');
      await downloadProductSalesCsv(filters, sortBy, sortDir, {
        from: query.data.period.from_date,
        to: query.data.period.to_date,
      });
    } catch (err) {
      setError(await getBlobErrorMessage(err, 'Unable to download the CSV'));
    } finally {
      setDownloading(false);
    }
  }

  if (query.isLoading) {
    return <div className="empty-state">Loading product-wise sales…</div>;
  }

  if (query.error || !query.data) {
    return <div className="empty-state">Unable to load product-wise sales.</div>;
  }

  const { rows, totals, currency_code: currency } = query.data;

  // Rank for the chart independently of the table's sort, so changing the table
  // sort doesn't silently redefine what "Top 10" means.
  const ranked = [...rows].sort((a, b) =>
    metric === 'revenue' ? b.total_revenue - a.total_revenue : b.quantity_sold - a.quantity_sold,
  );
  const chartRows = ranking === 'top' ? ranked.slice(0, CHART_ROWS) : ranked.slice(-CHART_ROWS).reverse();

  return (
    <div className="analytics-tab">
      <StatusToasts error={error} onClearError={() => setError('')} onClearSuccess={() => {}} />

      <div className="analytics-tab__actions">
        <label className="analytics-filters__field">
          <span>Sort by</span>
          <select className="input" value={sortBy} onChange={(e) => setSortBy(e.target.value as ProductSortBy)}>
            <option value="revenue">Revenue</option>
            <option value="quantity">Quantity Sold</option>
            <option value="name">Product Name</option>
            <option value="stock">Current Stock</option>
          </select>
        </label>
        <label className="analytics-filters__field">
          <span>Order</span>
          <select className="input" value={sortDir} onChange={(e) => setSortDir(e.target.value as SortDir)}>
            <option value="desc">Descending</option>
            <option value="asc">Ascending</option>
          </select>
        </label>
        <button className="button button--ghost" onClick={handleDownload} disabled={downloading}>
          <Download size={16} aria-hidden="true" />
          {downloading ? 'Preparing…' : 'Export CSV'}
        </button>
      </div>

      {rows.length === 0 ? (
        <div className="empty-state">No products sold in this period.</div>
      ) : (
        <>
          <div className="analytics-chart-controls">
            <div className="tab-bar">
              <button
                className={`button ${ranking === 'top' ? 'button--primary' : 'button--ghost'}`}
                onClick={() => setRanking('top')}
              >
                Top {CHART_ROWS}
              </button>
              <button
                className={`button ${ranking === 'bottom' ? 'button--primary' : 'button--ghost'}`}
                onClick={() => setRanking('bottom')}
              >
                Bottom {CHART_ROWS}
              </button>
            </div>
            <div className="tab-bar">
              <button
                className={`button ${metric === 'revenue' ? 'button--primary' : 'button--ghost'}`}
                onClick={() => setMetric('revenue')}
              >
                By Revenue
              </button>
              <button
                className={`button ${metric === 'quantity' ? 'button--primary' : 'button--ghost'}`}
                onClick={() => setMetric('quantity')}
              >
                By Quantity
              </button>
            </div>
          </div>

          <ProductSalesChart rows={chartRows} metric={metric} currencyCode={currency} />

          <div className="analytics-table-scroll">
            <table className="invoice-feed-table">
              <thead>
                <tr>
                  <th>Product</th>
                  <th>Item Code</th>
                  <th className="text-right">Qty Sold</th>
                  <th className="text-right">Sales Amount</th>
                  <th className="text-right">Avg Selling Price</th>
                  <th className="text-right">Total Revenue</th>
                  <th className="text-right">Total GST</th>
                  <th className="text-right">Invoices</th>
                  <th className="text-right">Current Stock</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.product_id}>
                    <td>{row.name}</td>
                    <td>{row.sku ?? '—'}</td>
                    <td className="text-right">{row.quantity_sold}</td>
                    <td className="text-right">{formatCurrency(row.sales_amount, currency)}</td>
                    <td className="text-right">{formatCurrency(row.average_selling_price, currency)}</td>
                    <td className="text-right">{formatCurrency(row.total_revenue, currency)}</td>
                    <td className="text-right">{formatCurrency(row.total_gst, currency)}</td>
                    <td className="text-right">{row.invoice_count}</td>
                    {/* Not tracked reads as "—" rather than a misleading 0. */}
                    <td className="text-right">{row.current_stock ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th>Totals</th>
                  <th>{totals.product_count} products</th>
                  <th className="text-right">{totals.quantity_sold}</th>
                  <th className="text-right">{formatCurrency(totals.sales_amount, currency)}</th>
                  <th className="text-right">—</th>
                  <th className="text-right">{formatCurrency(totals.total_revenue, currency)}</th>
                  <th className="text-right">{formatCurrency(totals.total_gst, currency)}</th>
                  <th className="text-right">{totals.invoice_count}</th>
                  <th className="text-right">—</th>
                </tr>
              </tfoot>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
