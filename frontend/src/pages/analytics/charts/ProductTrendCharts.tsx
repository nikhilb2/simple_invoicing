import type { ReactNode } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { EMPTY_CELL, formatUnits } from '../../../features/analytics/productPerformance';
import type { ProductPerformanceMonthlyRow } from '../../../features/analytics/types';
import useMediaQuery, { NARROW_QUERY } from '../../../hooks/useMediaQuery';
import formatCurrency, { formatCompactCurrency } from '../../../utils/formatting';
import { useChartColors, useChartTooltipStyle } from './chartTheme';

/*
 * The four monthly charts on the product page. Each keeps to a single y-axis —
 * money, units, price or percent — rather than overlaying two scales, which is
 * why margin has a chart of its own instead of riding on the profit chart.
 * Months with no trades leave a gap (null), never a misleading zero price.
 */

type Rows = ProductPerformanceMonthlyRow[];

const BAR_RADIUS: [number, number, number, number] = [4, 4, 0, 0];

/** Shared frame: title, height and the x-axis every chart here uses. */
function ChartPanel({ title, caption, children }: { title: string; caption?: string; children: ReactNode }) {
  return (
    <section className="chart-frame product-detail__chart" aria-label={title}>
      <h3 className="product-detail__chart-title">{title}</h3>
      {caption && <p className="product-detail__chart-caption">{caption}</p>}
      {children}
    </section>
  );
}

function useAxisProps() {
  const chartColors = useChartColors();
  const narrow = useMediaQuery(NARROW_QUERY);
  return {
    narrow,
    height: narrow ? 220 : 260,
    margin: { top: 8, right: narrow ? 4 : 12, bottom: 4, left: narrow ? 0 : 4 },
    xAxis: {
      dataKey: 'label',
      stroke: chartColors.axis,
      tickLine: false,
      fontSize: narrow ? 10 : 12,
      interval: 'preserveStartEnd' as const,
      minTickGap: 8,
    },
    yAxis: {
      stroke: chartColors.axis,
      tickLine: false,
      fontSize: narrow ? 10 : 12,
      width: narrow ? 44 : 56,
    },
  };
}

const legendStyle = { fontSize: '0.8rem' };

/** Recharts passes null through for gaps; show those as a dash. */
const orDash = (value: unknown, format: (n: number) => string) =>
  typeof value === 'number' ? format(value) : EMPTY_CELL;

export function ProductUnitsChart({ rows }: { rows: Rows }) {
  const chartColors = useChartColors();
  const tooltipStyle = useChartTooltipStyle();
  const axis = useAxisProps();
  return (
    <ChartPanel title="Units sold vs bought" caption="Gross units each month; returns shown separately.">
      <ResponsiveContainer width="100%" height={axis.height}>
        <BarChart data={rows} margin={axis.margin} barGap={2}>
          <CartesianGrid stroke={chartColors.grid} vertical={false} />
          <XAxis {...axis.xAxis} />
          <YAxis {...axis.yAxis} allowDecimals={false} tickFormatter={(value: number) => formatUnits(value)} />
          <Tooltip
            contentStyle={tooltipStyle}
            cursor={{ fill: chartColors.cursor }}
            formatter={(value: number, name: string) => [formatUnits(value), name]}
          />
          <Legend wrapperStyle={legendStyle} />
          <Bar dataKey="units_sold" name="Sold" fill={chartColors.sales} radius={BAR_RADIUS} />
          <Bar dataKey="units_bought" name="Bought" fill={chartColors.secondary} radius={BAR_RADIUS} />
          <Bar dataKey="units_returned" name="Returned" fill={chartColors.loss} radius={BAR_RADIUS} />
        </BarChart>
      </ResponsiveContainer>
    </ChartPanel>
  );
}

export function ProductProfitChart({
  rows,
  currencyCode,
  costed,
}: {
  rows: Rows;
  currencyCode: string;
  /** False when the product has no cost: only revenue can be drawn. */
  costed: boolean;
}) {
  const chartColors = useChartColors();
  const tooltipStyle = useChartTooltipStyle();
  const axis = useAxisProps();
  const money = (value: number) => formatCurrency(value, currencyCode);
  return (
    <ChartPanel
      title={costed ? 'Revenue, cost and profit' : 'Revenue'}
      caption={
        costed
          ? 'Ex-GST, net of discounts and credit notes. Cost is net units × the period cost.'
          : 'Ex-GST, net of discounts and credit notes. No cost is known, so no profit.'
      }
    >
      <ResponsiveContainer width="100%" height={axis.height}>
        <ComposedChart data={rows} margin={axis.margin} barGap={2}>
          <CartesianGrid stroke={chartColors.grid} vertical={false} />
          <XAxis {...axis.xAxis} />
          <YAxis {...axis.yAxis} tickFormatter={(value: number) => formatCompactCurrency(value, currencyCode)} />
          <ReferenceLine y={0} stroke={chartColors.axis} />
          <Tooltip
            contentStyle={tooltipStyle}
            cursor={{ fill: chartColors.cursor }}
            formatter={(value: unknown, name: string) => [orDash(value, money), name]}
          />
          <Legend wrapperStyle={legendStyle} />
          <Bar dataKey="revenue" name="Revenue" fill={chartColors.sales} radius={BAR_RADIUS} />
          {costed && <Bar dataKey="cogs" name="Cost of goods" fill={chartColors.secondary} radius={BAR_RADIUS} />}
          {costed && (
            <Line
              type="monotone"
              dataKey="gross_profit"
              name="Gross profit"
              stroke={chartColors.profit}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </ChartPanel>
  );
}

export function ProductPriceChart({
  rows,
  currencyCode,
  periodCost,
}: {
  rows: Rows;
  currencyCode: string;
  /** The unit cost COGS uses, drawn as a reference; null when unknown. */
  periodCost: number | null;
}) {
  const chartColors = useChartColors();
  const tooltipStyle = useChartTooltipStyle();
  const axis = useAxisProps();
  const money = (value: number) => formatCurrency(value, currencyCode);
  // No purchases in any month: a legend entry with no line would read as a bug.
  const anyBuying = rows.some((row) => row.average_buying_price !== null);
  return (
    <ChartPanel
      title="Average selling vs buying price"
      caption="Per unit, ex-GST, in months the product was traded. Dashed: the cost used for profit."
    >
      <ResponsiveContainer width="100%" height={axis.height}>
        <LineChart data={rows} margin={axis.margin}>
          <CartesianGrid stroke={chartColors.grid} vertical={false} />
          <XAxis {...axis.xAxis} />
          <YAxis
            {...axis.yAxis}
            domain={['auto', 'auto']}
            tickFormatter={(value: number) => formatCompactCurrency(value, currencyCode)}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(value: unknown, name: string) => [orDash(value, money), name]}
          />
          <Legend wrapperStyle={legendStyle} />
          {periodCost !== null && (
            <ReferenceLine y={periodCost} stroke={chartColors.axis} strokeDasharray="4 4" ifOverflow="extendDomain" />
          )}
          {/* connectNulls joins traded months across a quiet one; the dots
              show which months actually had a price. Straight segments, since
              a smoothed curve would invent prices for the months between. */}
          <Line
            type="linear"
            dataKey="average_selling_price"
            name="Avg selling price"
            stroke={chartColors.sales}
            strokeWidth={2}
            dot={{ r: 3 }}
            activeDot={{ r: 5 }}
            connectNulls
          />
          {anyBuying && (
            <Line
              type="linear"
              dataKey="average_buying_price"
              name="Avg buying price"
              stroke={chartColors.secondary}
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
              connectNulls
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </ChartPanel>
  );
}

export function ProductMarginChart({ rows }: { rows: Rows }) {
  const chartColors = useChartColors();
  const tooltipStyle = useChartTooltipStyle();
  const axis = useAxisProps();
  const pct = (value: number) => `${value.toFixed(1)}%`;
  return (
    <ChartPanel title="Gross margin" caption="Gross profit as a share of revenue, month by month.">
      <ResponsiveContainer width="100%" height={axis.height}>
        <BarChart data={rows} margin={axis.margin}>
          <CartesianGrid stroke={chartColors.grid} vertical={false} />
          <XAxis {...axis.xAxis} />
          <YAxis {...axis.yAxis} tickFormatter={(value: number) => `${value.toFixed(0)}%`} />
          <ReferenceLine y={0} stroke={chartColors.axis} />
          <Tooltip
            contentStyle={tooltipStyle}
            cursor={{ fill: chartColors.cursor }}
            formatter={(value: unknown, name: string) => [orDash(value, pct), name]}
          />
          <Bar dataKey="margin_pct" name="Margin" radius={BAR_RADIUS}>
            {rows.map((row) => (
              <Cell
                key={row.month}
                fill={row.margin_pct !== null && row.margin_pct < 0 ? chartColors.loss : chartColors.profit}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartPanel>
  );
}
