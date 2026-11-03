import axios from 'axios';
import { Link, useParams } from 'react-router-dom';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { ArrowLeft, RotateCw } from 'lucide-react';
import { fetchProductPerformanceDetail } from '../../features/analytics/api';
import {
  EMPTY_CELL,
  formatCoverDays,
  formatMoneyOrDash,
  formatPctOrDash,
  formatUnits,
  isLoss,
  isQuietMonth,
  monthlyRate,
  performanceTabHref,
  returnRatePct,
  stockStatus,
  usesCurrentPriceCost,
  visibleMonths,
} from '../../features/analytics/productPerformance';
import { analyticsQueryKeys } from '../../features/analytics/queryKeys';
import type {
  ProductPerformanceDetail,
  ProductPerformanceRow,
} from '../../features/analytics/types';
import useAnalyticsFilters from '../../features/analytics/useAnalyticsFilters';
import formatCurrency, { formatCompactCurrency, formatDate } from '../../utils/formatting';
import AnalyticsFilters from './AnalyticsFilters';
import {
  ProductMarginChart,
  ProductPriceChart,
  ProductProfitChart,
  ProductUnitsChart,
} from './charts/ProductTrendCharts';

const isNotFound = (error: unknown) => axios.isAxiosError(error) && error.response?.status === 404;

const lossClass = (value: number | null) => (isLoss(value) ? ' analytics-loss-text' : '');

/**
 * One product's performance: the row it was opened from on the Product
 * performance tab, broken out month by month. Period and party come from the
 * same URL params as the Analytics page, so the two link back and forth
 * without losing the view.
 */
export default function ProductPerformancePage() {
  const { productId: productParam } = useParams();
  const productId = Number(productParam);
  const validId = Number.isInteger(productId) && productId > 0;
  const { filters, searchParams, isFiltered, onResetFilters, onFiltersChange } = useAnalyticsFilters();
  const backHref = performanceTabHref(searchParams);

  const query = useQuery({
    queryKey: analyticsQueryKeys.productPerformanceDetail(productId, filters),
    queryFn: () => fetchProductPerformanceDetail(productId, filters),
    placeholderData: keepPreviousData,
    enabled: validId,
    // A missing product won't appear on a retry.
    retry: (failureCount, error) => !isNotFound(error) && failureCount < 1,
  });

  const data = query.data;
  const notFound = !validId || isNotFound(query.error);

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Product performance</p>
          <h1 className="page-title">{notFound ? 'Product not found' : data?.product.name ?? 'Loading…'}</h1>
          {data && !notFound && <p className="section-copy">{describe(data)}</p>}
        </div>
        <div className="page-hero__actions">
          <Link className="button button--ghost product-detail__back" to={backHref}>
            <ArrowLeft size={16} aria-hidden="true" />
            All products
          </Link>
        </div>
      </section>

      {!notFound && (
        <AnalyticsFilters
          filters={filters}
          onChange={onFiltersChange}
          onReset={onResetFilters}
          canReset={isFiltered}
          showVoucherType={false}
          ledgerLabel="Party"
        />
      )}

      {notFound ? (
        <div className="empty-state">
          This product doesn't exist in the current company. <Link to={backHref}>Back to all products</Link>
        </div>
      ) : query.isLoading ? (
        <div className="empty-state">Loading product performance…</div>
      ) : query.error || !data ? (
        <div className="empty-state">
          Unable to load product performance.{' '}
          <button type="button" className="button button--ghost" onClick={() => query.refetch()}>
            <RotateCw size={16} aria-hidden="true" />
            Retry
          </button>
        </div>
      ) : (
        <ProductPerformanceBody data={data} partyFiltered={filters.ledgerId !== undefined} />
      )}
    </div>
  );
}

/** "SKU · Pieces · 1 Apr 2026 – 31 Mar 2027 (FY 2026-27)". */
function describe({ product, period }: ProductPerformanceDetail): string {
  const range = `${formatDate(period.from_date)} – ${formatDate(period.to_date)}`;
  return [product.sku, product.unit, period.fy_label ? `${range} (FY ${period.fy_label})` : range]
    .filter(Boolean)
    .join(' · ');
}

function ProductPerformanceBody({ data, partyFiltered }: { data: ProductPerformanceDetail; partyFiltered: boolean }) {
  const { product, summary, currency_code: currency } = data;
  const monthlyRows = visibleMonths(data.monthly_rows);

  if (!summary) {
    return (
      <div className="analytics-tab">
        <div className="empty-state">
          No sales or purchases of this product {partyFiltered ? 'with this party ' : ''}in this period.
          {product.current_stock !== null && ` ${formatUnits(product.current_stock)} in stock.`}
        </div>
      </div>
    );
  }

  const costed = summary.cogs !== null;

  return (
    <div className="analytics-tab">
      <SummaryCards data={data} summary={summary} />

      <CostNote summary={summary} partyFiltered={partyFiltered} />

      <div className="product-detail__charts">
        <ProductUnitsChart rows={monthlyRows} />
        <ProductProfitChart rows={monthlyRows} currencyCode={currency} costed={costed} />
        <ProductPriceChart rows={monthlyRows} currencyCode={currency} periodCost={summary.average_buying_price} />
        {costed && <ProductMarginChart rows={monthlyRows} />}
      </div>

      <h2 className="nav-panel__title">Month by month</h2>
      <div className="analytics-table-scroll">
        <table className="invoice-feed-table product-detail__table">
          <caption className="sr-only">Month by month</caption>
          <thead>
            <tr>
              <th scope="col">Month</th>
              <th scope="col" className="text-right">Sold</th>
              <th scope="col" className="text-right">Returned</th>
              <th scope="col" className="text-right">Bought</th>
              <th scope="col" className="text-right">Avg Sell</th>
              <th scope="col" className="text-right">Avg Buy</th>
              <th scope="col" className="text-right">Revenue</th>
              <th scope="col" className="text-right">COGS</th>
              <th scope="col" className="text-right">Gross Profit</th>
              <th scope="col" className="text-right">Margin</th>
            </tr>
          </thead>
          <tbody>
            {monthlyRows.map((row) => {
              return (
                <tr key={row.month} className={isQuietMonth(row) ? 'product-detail__quiet' : undefined}>
                  <th scope="row">{row.label}</th>
                  <td className="text-right">{formatUnits(row.units_sold)}</td>
                  <td className="text-right">{formatUnits(row.units_returned)}</td>
                  <td className="text-right">{formatUnits(row.units_bought)}</td>
                  <td className="text-right">{formatMoneyOrDash(row.average_selling_price, currency)}</td>
                  <td className="text-right">{formatMoneyOrDash(row.average_buying_price, currency)}</td>
                  <td className="text-right">{formatCurrency(row.revenue, currency)}</td>
                  <td className="text-right">{formatMoneyOrDash(row.cogs, currency)}</td>
                  <td className={`text-right${lossClass(row.gross_profit)}`}>
                    {formatMoneyOrDash(row.gross_profit, currency)}
                  </td>
                  <td className={`text-right${lossClass(row.margin_pct)}`}>{formatPctOrDash(row.margin_pct)}</td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">Period</th>
              <th className="text-right">{formatUnits(summary.units_sold)}</th>
              <th className="text-right">{formatUnits(summary.units_returned)}</th>
              <th className="text-right">{formatUnits(summary.units_bought)}</th>
              <th className="text-right">{formatMoneyOrDash(summary.average_selling_price, currency)}</th>
              <th className="text-right" title="The unit cost used for COGS">
                {formatMoneyOrDash(summary.average_buying_price, currency)}
              </th>
              <th className="text-right">{formatCurrency(summary.revenue, currency)}</th>
              <th className="text-right">{formatMoneyOrDash(summary.cogs, currency)}</th>
              <th className={`text-right${lossClass(summary.gross_profit)}`}>
                {formatMoneyOrDash(summary.gross_profit, currency)}
              </th>
              <th className={`text-right${lossClass(summary.margin_pct)}`}>{formatPctOrDash(summary.margin_pct)}</th>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

function SummaryCards({ data, summary }: { data: ProductPerformanceDetail; summary: ProductPerformanceRow }) {
  const { product, velocity, currency_code: currency } = data;
  const profitTone = isLoss(summary.gross_profit) ? ' stat-card__value--danger' : '';
  const returnRate = returnRatePct(summary);
  const status = stockStatus(product);
  const stockTone =
    status === 'out' ? ' stat-card__value--danger' : status === 'low' ? ' stat-card__value--warning' : '';
  const perMonth = monthlyRate(velocity);

  return (
    <section className="stats-grid stats-grid--dense" aria-label="Period summary">
      <article className="stat-card">
        <p className="eyebrow">Revenue (ex-GST)</p>
        <p className="stat-card__value" title={formatCurrency(summary.revenue, currency)}>
          {formatCompactCurrency(summary.revenue, currency)}
        </p>
        <p className="muted-text">After discounts and credit notes.</p>
      </article>
      <article className="stat-card">
        <p className="eyebrow">Gross profit</p>
        <p
          className={`stat-card__value${profitTone}`}
          title={summary.gross_profit === null ? undefined : formatCurrency(summary.gross_profit, currency)}
        >
          {summary.gross_profit === null ? EMPTY_CELL : formatCompactCurrency(summary.gross_profit, currency)}
        </p>
        <p className="muted-text">
          {summary.margin_pct === null ? 'No cost known.' : `${formatPctOrDash(summary.margin_pct)} margin.`}
        </p>
      </article>
      <article className="stat-card">
        <p className="eyebrow">Profit / unit</p>
        <p className={`stat-card__value${profitTone}`}>{formatMoneyOrDash(summary.profit_per_unit, currency)}</p>
        <p className="muted-text">Per net unit sold.</p>
      </article>
      <article className="stat-card">
        <p className="eyebrow">Stock</p>
        <p className={`stat-card__value${stockTone}`}>
          {product.current_stock === null ? EMPTY_CELL : formatUnits(product.current_stock)}
        </p>
        <p className="muted-text">
          {status === 'untracked'
            ? 'Not stock-tracked.'
            : status === 'out'
              ? 'Out of stock.'
              : `${status === 'low' ? 'At or below reorder level. ' : ''}` +
                (velocity.stock_cover_days === null
                  ? 'No sales pace to estimate cover.'
                  : `Cover ${formatCoverDays(velocity)} at this period's pace.`)}
        </p>
      </article>
      <article className="stat-card">
        <p className="eyebrow">Units sold</p>
        <p className="stat-card__value">{formatUnits(summary.net_units_sold)}</p>
        <p className="muted-text">
          {summary.units_returned > 0
            ? `Net of ${formatUnits(summary.units_returned)} returned (${formatPctOrDash(returnRate)}).`
            : 'No returns.'}
          {perMonth !== null && ` ≈ ${formatUnits(Math.round(perMonth * 10) / 10)} a month.`}
        </p>
      </article>
      <article className="stat-card">
        <p className="eyebrow">Units bought</p>
        <p className="stat-card__value">{formatUnits(summary.net_units_bought)}</p>
        <p className="muted-text" title={formatCurrency(summary.purchase_spend, currency)}>
          {formatCompactCurrency(summary.purchase_spend, currency)} spent (ex-GST)
          {summary.units_purchase_returned > 0 ? `, ${formatUnits(summary.units_purchase_returned)} sent back.` : '.'}
        </p>
      </article>
      <article className="stat-card">
        <p className="eyebrow">Avg selling price</p>
        <p className="stat-card__value">{formatMoneyOrDash(summary.average_selling_price, currency)}</p>
        <p className="muted-text">Catalogue price {formatCurrency(product.price, currency)}.</p>
      </article>
      <article className="stat-card">
        <p className="eyebrow">Avg buying price</p>
        <p className="stat-card__value">{formatMoneyOrDash(summary.average_buying_price, currency)}</p>
        <p className="muted-text">
          {summary.cost_basis === 'purchases'
            ? "This period's purchases; the cost used for profit."
            : usesCurrentPriceCost(summary)
              ? 'No purchases this period: current purchase price.'
              : 'No purchases and no purchase price.'}
        </p>
      </article>
    </section>
  );
}

function CostNote({ summary, partyFiltered }: { summary: ProductPerformanceRow; partyFiltered: boolean }) {
  const notes: string[] = [];
  if (usesCurrentPriceCost(summary)) {
    notes.push(
      "There were no purchases in this period, so profit uses the product's current purchase price — an estimate.",
    );
  } else if (summary.cost_basis === null) {
    notes.push('This product has no purchases in the period and no purchase price, so profit is not shown.');
  }
  if (partyFiltered) {
    notes.push(
      'Filtered to one party: units and money cover only that party, but cost is still what the product cost from every supplier.',
    );
  }
  if (notes.length === 0) return null;
  return <p className="muted-text">{notes.join(' ')}</p>;
}
