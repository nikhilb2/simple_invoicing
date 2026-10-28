import { useState, type ReactNode } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react';
import { fetchProductPerformance } from '../../features/analytics/api';
import {
  EMPTY_CELL,
  ariaSort,
  formatMoneyOrDash,
  formatPctOrDash,
  isLoss,
  nextSort,
  usesCurrentPriceCost,
} from '../../features/analytics/productPerformance';
import { analyticsQueryKeys } from '../../features/analytics/queryKeys';
import type {
  AnalyticsFilters,
  PerformanceSortBy,
  ProductPerformanceRow,
  SortDir,
} from '../../features/analytics/types';
import formatCurrency, { formatCompactCurrency } from '../../utils/formatting';

type Column = {
  key: PerformanceSortBy;
  label: string;
  numeric?: boolean;
  render: (row: ProductPerformanceRow, currency: string) => ReactNode;
};

const lossClass = (value: number | null) => (isLoss(value) ? ' analytics-loss-text' : '');

const COLUMNS: Column[] = [
  {
    key: 'name',
    label: 'Product',
    render: (row) => (
      <>
        {row.name}
        {row.sku && <span className="product-performance__sku">{row.sku}</span>}
      </>
    ),
  },
  { key: 'units_sold', label: 'Units Sold', numeric: true, render: (row) => row.units_sold },
  {
    key: 'units_returned',
    label: 'Returns',
    numeric: true,
    render: (row, currency) =>
      row.units_returned || row.return_value ? (
        <span title={`${formatCurrency(row.return_value, currency)} credited`}>
          {row.units_returned}
          <span className="product-performance__sub">{formatCurrency(row.return_value, currency)}</span>
        </span>
      ) : (
        0
      ),
  },
  { key: 'net_units_sold', label: 'Net Units', numeric: true, render: (row) => row.net_units_sold },
  {
    key: 'units_bought',
    label: 'Units Bought',
    numeric: true,
    render: (row) =>
      row.units_purchase_returned ? (
        <span title={`${row.units_purchase_returned} returned to supplier`}>
          {row.units_bought}
          <span className="product-performance__sub">−{row.units_purchase_returned} returned</span>
        </span>
      ) : (
        row.units_bought
      ),
  },
  {
    key: 'average_selling_price',
    label: 'Avg Sell Price',
    numeric: true,
    render: (row, currency) => formatMoneyOrDash(row.average_selling_price, currency),
  },
  {
    key: 'average_buying_price',
    label: 'Avg Buy Price',
    numeric: true,
    render: (row, currency) => (
      <>
        {formatMoneyOrDash(row.average_buying_price, currency)}
        {usesCurrentPriceCost(row) && (
          <span
            className="product-performance__basis"
            title="No purchases in this period: costed at the product's current purchase price"
          >
            current price
          </span>
        )}
      </>
    ),
  },
  { key: 'revenue', label: 'Revenue', numeric: true, render: (row, currency) => formatCurrency(row.revenue, currency) },
  {
    key: 'purchase_spend',
    label: 'Purchase Spend',
    numeric: true,
    render: (row, currency) => formatCurrency(row.purchase_spend, currency),
  },
  { key: 'cogs', label: 'COGS', numeric: true, render: (row, currency) => formatMoneyOrDash(row.cogs, currency) },
  {
    key: 'gross_profit',
    label: 'Gross Profit',
    numeric: true,
    render: (row, currency) => formatMoneyOrDash(row.gross_profit, currency),
  },
  { key: 'margin_pct', label: 'Margin', numeric: true, render: (row) => formatPctOrDash(row.margin_pct) },
  {
    key: 'profit_per_unit',
    label: 'Profit / Unit',
    numeric: true,
    render: (row, currency) => formatMoneyOrDash(row.profit_per_unit, currency),
  },
  {
    key: 'current_stock',
    label: 'Stock',
    numeric: true,
    // Not tracked reads as "—" rather than a misleading 0.
    render: (row) => row.current_stock ?? EMPTY_CELL,
  },
];

/** Columns whose cell text turns red on a loss. */
const LOSS_COLUMNS = new Set<PerformanceSortBy>(['gross_profit', 'margin_pct', 'profit_per_unit']);

export default function ProductPerformanceTab({ filters }: { filters: AnalyticsFilters }) {
  const [sort, setSort] = useState<{ sortBy: PerformanceSortBy; sortDir: SortDir }>({
    sortBy: 'revenue',
    sortDir: 'desc',
  });

  const query = useQuery({
    queryKey: analyticsQueryKeys.productPerformance(filters, sort.sortBy, sort.sortDir),
    queryFn: () => fetchProductPerformance(filters, sort.sortBy, sort.sortDir),
    placeholderData: keepPreviousData,
  });

  if (query.isLoading) {
    return <div className="empty-state">Loading product performance…</div>;
  }

  if (query.error || !query.data) {
    return <div className="empty-state">Unable to load product performance.</div>;
  }

  const { rows, totals, currency_code: currency } = query.data;

  if (totals.product_count === 0) {
    return (
      <div className="analytics-tab">
        <div className="empty-state">No sales or purchases in this period.</div>
      </div>
    );
  }

  const profitTone = isLoss(totals.gross_profit) ? ' stat-card__value--danger' : '';

  return (
    <div className="analytics-tab">
      <section className="stats-grid stats-grid--dense">
        <article className="stat-card">
          <p className="eyebrow">Revenue (ex-GST)</p>
          <p className="stat-card__value" title={formatCurrency(totals.revenue, currency)}>
            {formatCompactCurrency(totals.revenue, currency)}
          </p>
          <p className="muted-text">
            After discounts and {formatCurrency(totals.return_value, currency)} of credit notes.
          </p>
        </article>
        <article className="stat-card">
          <p className="eyebrow">Gross profit</p>
          <p className={`stat-card__value${profitTone}`} title={formatCurrency(totals.gross_profit, currency)}>
            {formatCompactCurrency(totals.gross_profit, currency)}
          </p>
          <p className="muted-text">
            {totals.uncosted_product_count > 0
              ? `Excludes ${totals.uncosted_product_count} product${totals.uncosted_product_count === 1 ? '' : 's'} with no cost.`
              : 'Revenue − cost of goods sold.'}
          </p>
        </article>
        <article className="stat-card">
          <p className="eyebrow">Gross margin</p>
          <p className={`stat-card__value${profitTone}`}>{formatPctOrDash(totals.margin_pct)}</p>
          <p className="muted-text">Over revenue of products with a known cost.</p>
        </article>
        <article className="stat-card">
          <p className="eyebrow">Units sold</p>
          <p className="stat-card__value">{totals.net_units_sold}</p>
          <p className="muted-text">
            {totals.units_returned > 0 ? `Net of ${totals.units_returned} returned.` : 'No returns.'}
          </p>
        </article>
        <article className="stat-card">
          <p className="eyebrow">Units bought</p>
          <p className="stat-card__value">{totals.net_units_bought}</p>
          <p className="muted-text" title={formatCurrency(totals.purchase_spend, currency)}>
            {formatCompactCurrency(totals.purchase_spend, currency)} spent (ex-GST).
          </p>
        </article>
      </section>

      <p className="muted-text">
        Cost is each product's average purchase price in this period. Products with no purchases
        in the period use their current purchase price
        {totals.current_price_product_count > 0 ? ` (${totals.current_price_product_count} here, marked "current price")` : ''};
        products with neither show "—".
      </p>

      <div className="analytics-table-scroll">
        <table className="invoice-feed-table">
          <thead>
            <tr>
              {COLUMNS.map((column) => {
                const active = sort.sortBy === column.key;
                return (
                  <th
                    key={column.key}
                    scope="col"
                    className={column.numeric ? 'text-right' : undefined}
                    aria-sort={ariaSort(sort, column.key)}
                  >
                    <button
                      type="button"
                      className={`catalogue-sort${active ? ' catalogue-sort--active' : ''}`}
                      onClick={() => setSort((current) => nextSort(current, column.key))}
                    >
                      {column.label}
                      {active ? (
                        sort.sortDir === 'asc' ? (
                          <ArrowUp size={13} aria-hidden="true" />
                        ) : (
                          <ArrowDown size={13} aria-hidden="true" />
                        )
                      ) : (
                        <ArrowUpDown size={13} aria-hidden="true" />
                      )}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.product_id}>
                {COLUMNS.map((column) => (
                  <td
                    key={column.key}
                    className={`${column.numeric ? 'text-right' : ''}${
                      LOSS_COLUMNS.has(column.key) ? lossClass(row.gross_profit) : ''
                    }`}
                  >
                    {column.render(row, currency)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">{totals.product_count} products</th>
              <th className="text-right">{totals.units_sold}</th>
              <th className="text-right">{totals.units_returned}</th>
              <th className="text-right">{totals.net_units_sold}</th>
              <th className="text-right">{totals.units_bought}</th>
              <th className="text-right">{EMPTY_CELL}</th>
              <th className="text-right">{EMPTY_CELL}</th>
              <th className="text-right">{formatCurrency(totals.revenue, currency)}</th>
              <th className="text-right">{formatCurrency(totals.purchase_spend, currency)}</th>
              <th className="text-right">{formatCurrency(totals.cogs, currency)}</th>
              <th className={`text-right${lossClass(totals.gross_profit)}`}>
                {formatCurrency(totals.gross_profit, currency)}
              </th>
              <th className="text-right">{formatPctOrDash(totals.margin_pct)}</th>
              <th className="text-right">{EMPTY_CELL}</th>
              <th className="text-right">{EMPTY_CELL}</th>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
