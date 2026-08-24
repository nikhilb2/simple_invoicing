import { useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { AlertTriangle, Download } from 'lucide-react';
import { getBlobErrorMessage } from '../../api/client';
import StatusToasts from '../../components/StatusToasts';
import { downloadProfitLossCsv, fetchProfitLoss } from '../../features/analytics/api';
import { analyticsQueryKeys } from '../../features/analytics/queryKeys';
import type { AnalyticsFilters, ProfitLossProductRow } from '../../features/analytics/types';
import formatCurrency, { formatCompactCurrency } from '../../utils/formatting';
import MonthlyProfitChart from './charts/MonthlyProfitChart';
import ProfitByProductChart from './charts/ProfitByProductChart';

const CHART_ROWS = 10;

const formatPct = (value: number) => `${value.toFixed(1)}%`;

/** A product is flagged when it lost money, or its cost meets/exceeds its
 *  average selling price — a pricing problem worth surfacing. */
function isLossMaking(row: ProfitLossProductRow) {
  return row.gross_profit < 0 || (row.quantity_sold > 0 && row.purchase_price >= row.average_selling_price);
}

export default function ProfitLossTab({ filters }: { filters: AnalyticsFilters }) {
  const [breakdown, setBreakdown] = useState<'product' | 'customer'>('product');
  const [ranking, setRanking] = useState<'top' | 'bottom'>('top');
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState('');

  const query = useQuery({
    queryKey: analyticsQueryKeys.profitLoss(filters),
    queryFn: () => fetchProfitLoss(filters),
    placeholderData: keepPreviousData,
  });

  async function handleDownload() {
    if (!query.data) return;
    try {
      setDownloading(true);
      setError('');
      await downloadProfitLossCsv(filters, {
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
    return <div className="empty-state">Loading profit & loss…</div>;
  }

  if (query.error || !query.data) {
    return <div className="empty-state">Unable to load profit & loss.</div>;
  }

  const {
    product_rows: productRows,
    monthly_rows: monthlyRows,
    customer_rows: customerRows,
    totals,
    currency_code: currency,
  } = query.data;

  // When a single product is filtered, the monthly series is that product's —
  // relabel the section so it reads as the per-product purchase-vs-sales view.
  const selectedProduct = filters.productId && productRows.length === 1 ? productRows[0] : null;

  // Rank for the chart by absolute profit, independent of the table order.
  const ranked = [...productRows].sort((a, b) => b.gross_profit - a.gross_profit);
  const chartRows = ranking === 'top' ? ranked.slice(0, CHART_ROWS) : ranked.slice(-CHART_ROWS).reverse();

  const profitTone = totals.gross_profit < 0 ? ' stat-card__value--danger' : '';

  return (
    <div className="analytics-tab">
      <StatusToasts error={error} onClearError={() => setError('')} onClearSuccess={() => {}} />

      <div className="analytics-tab__actions">
        <button className="button button--ghost" onClick={handleDownload} disabled={downloading}>
          <Download size={16} aria-hidden="true" />
          {downloading ? 'Preparing…' : 'Export CSV'}
        </button>
      </div>

      {totals.product_count === 0 ? (
        <div className="empty-state">No sales in this period.</div>
      ) : (
        <>
          <section className="stats-grid stats-grid--dense">
            <article className="stat-card">
              <p className="eyebrow">Revenue (ex-GST)</p>
              <p className="stat-card__value" title={formatCurrency(totals.revenue, currency)}>
                {formatCompactCurrency(totals.revenue, currency)}
              </p>
              <p className="muted-text">Taxable value of sales.</p>
            </article>
            <article className="stat-card">
              <p className="eyebrow">Cost of goods sold</p>
              <p className="stat-card__value" title={formatCurrency(totals.cogs, currency)}>
                {formatCompactCurrency(totals.cogs, currency)}
              </p>
              <p className="muted-text">Quantity sold × purchase price.</p>
            </article>
            <article className="stat-card">
              <p className="eyebrow">Gross profit</p>
              <p className={`stat-card__value${profitTone}`} title={formatCurrency(totals.gross_profit, currency)}>
                {formatCompactCurrency(totals.gross_profit, currency)}
              </p>
              <p className="muted-text">Revenue − cost of goods sold.</p>
            </article>
            <article className="stat-card">
              <p className="eyebrow">Gross margin</p>
              <p className={`stat-card__value${profitTone}`}>{formatPct(totals.margin_pct)}</p>
              <p className="muted-text">Gross profit as a share of revenue.</p>
            </article>
          </section>

          <p className="muted-text">
            Profit uses each product's current purchase price as cost, so historical periods reflect
            today's costs.
          </p>

          <div className="analytics-chart-controls">
            <h3 className="nav-panel__title">
              {selectedProduct ? `${selectedProduct.name}: monthly profit` : 'Monthly profit'}
            </h3>
          </div>
          <MonthlyProfitChart rows={monthlyRows} currencyCode={currency} />

          <div className="analytics-table-scroll">
            <table className="invoice-feed-table">
              <thead>
                <tr>
                  <th>Month</th>
                  <th className="text-right">Qty Sold</th>
                  <th className="text-right">Revenue</th>
                  <th className="text-right">COGS</th>
                  <th className="text-right">Gross Profit</th>
                  <th className="text-right">Margin</th>
                </tr>
              </thead>
              <tbody>
                {monthlyRows.map((row) => (
                  <tr key={row.month}>
                    <td>{row.label}</td>
                    <td className="text-right">{row.quantity}</td>
                    <td className="text-right">{formatCurrency(row.revenue, currency)}</td>
                    <td className="text-right">{formatCurrency(row.cogs, currency)}</td>
                    <td className={`text-right${row.gross_profit < 0 ? ' analytics-loss-text' : ''}`}>
                      {formatCurrency(row.gross_profit, currency)}
                    </td>
                    <td className="text-right">{formatPct(row.margin_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Breakdown switcher — product vs customer profitability. */}
          <div className="analytics-chart-controls">
            <div className="tab-bar">
              <button
                className={`button ${breakdown === 'product' ? 'button--primary' : 'button--ghost'}`}
                onClick={() => setBreakdown('product')}
              >
                By Product
              </button>
              <button
                className={`button ${breakdown === 'customer' ? 'button--primary' : 'button--ghost'}`}
                onClick={() => setBreakdown('customer')}
              >
                By Customer
              </button>
            </div>
            {breakdown === 'product' && (
              <div className="tab-bar">
                <button
                  className={`button ${ranking === 'top' ? 'button--primary' : 'button--ghost'}`}
                  onClick={() => setRanking('top')}
                >
                  Most Profitable
                </button>
                <button
                  className={`button ${ranking === 'bottom' ? 'button--primary' : 'button--ghost'}`}
                  onClick={() => setRanking('bottom')}
                >
                  Least Profitable
                </button>
              </div>
            )}
          </div>

          {breakdown === 'product' ? (
            <>
              <ProfitByProductChart rows={chartRows} currencyCode={currency} />

              <div className="analytics-table-scroll">
                <table className="invoice-feed-table">
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th className="text-right">Qty Sold</th>
                      <th className="text-right">Avg Selling Price</th>
                      <th className="text-right">Purchase Price</th>
                      <th className="text-right">Revenue</th>
                      <th className="text-right">COGS</th>
                      <th className="text-right">Gross Profit</th>
                      <th className="text-right">Margin</th>
                    </tr>
                  </thead>
                  <tbody>
                    {productRows.map((row) => (
                      <tr key={row.product_id}>
                        <td>
                          {row.name}
                          {isLossMaking(row) && (
                            <span className="analytics-loss-badge" title="Sold at or below cost">
                              <AlertTriangle size={12} aria-hidden="true" /> Loss
                            </span>
                          )}
                        </td>
                        <td className="text-right">{row.quantity_sold}</td>
                        <td className="text-right">{formatCurrency(row.average_selling_price, currency)}</td>
                        <td className="text-right">{formatCurrency(row.purchase_price, currency)}</td>
                        <td className="text-right">{formatCurrency(row.sales_amount, currency)}</td>
                        <td className="text-right">{formatCurrency(row.cogs, currency)}</td>
                        <td className={`text-right${row.gross_profit < 0 ? ' analytics-loss-text' : ''}`}>
                          {formatCurrency(row.gross_profit, currency)}
                        </td>
                        <td className="text-right">{formatPct(row.margin_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <th>{totals.product_count} products</th>
                      <th className="text-right">{totals.quantity_sold}</th>
                      <th className="text-right">—</th>
                      <th className="text-right">—</th>
                      <th className="text-right">{formatCurrency(totals.revenue, currency)}</th>
                      <th className="text-right">{formatCurrency(totals.cogs, currency)}</th>
                      <th className="text-right">{formatCurrency(totals.gross_profit, currency)}</th>
                      <th className="text-right">{formatPct(totals.margin_pct)}</th>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </>
          ) : (
            <div className="analytics-table-scroll">
              <table className="invoice-feed-table">
                <thead>
                  <tr>
                    <th>Customer</th>
                    <th className="text-right">Invoices</th>
                    <th className="text-right">Revenue</th>
                    <th className="text-right">COGS</th>
                    <th className="text-right">Gross Profit</th>
                    <th className="text-right">Margin</th>
                  </tr>
                </thead>
                <tbody>
                  {customerRows.map((row) => (
                    <tr key={row.ledger_id ?? row.name}>
                      <td>{row.name}</td>
                      <td className="text-right">{row.invoice_count}</td>
                      <td className="text-right">{formatCurrency(row.revenue, currency)}</td>
                      <td className="text-right">{formatCurrency(row.cogs, currency)}</td>
                      <td className={`text-right${row.gross_profit < 0 ? ' analytics-loss-text' : ''}`}>
                        {formatCurrency(row.gross_profit, currency)}
                      </td>
                      <td className="text-right">{formatPct(row.margin_pct)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <th>Totals</th>
                    <th className="text-right">—</th>
                    <th className="text-right">{formatCurrency(totals.revenue, currency)}</th>
                    <th className="text-right">{formatCurrency(totals.cogs, currency)}</th>
                    <th className="text-right">{formatCurrency(totals.gross_profit, currency)}</th>
                    <th className="text-right">{formatPct(totals.margin_pct)}</th>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
