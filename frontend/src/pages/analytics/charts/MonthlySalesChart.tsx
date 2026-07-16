import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { MonthlySalesRow } from '../../../features/analytics/types';
import useMediaQuery, { NARROW_QUERY } from '../../../hooks/useMediaQuery';
import formatCurrency, { formatCompactCurrency } from '../../../utils/formatting';
import { chartColors, tooltipStyle } from './chartTheme';

/**
 * Sales bars with the average invoice value overlaid as a line.
 *
 * One chart rather than the separate bar and line charts the issue listed:
 * the two series share an x-axis, and overlaying them shows whether a strong
 * month came from more invoices or bigger ones — which two charts side by side
 * make the reader work out for themselves.
 */
export default function MonthlySalesChart({
  rows,
  currencyCode,
}: {
  rows: MonthlySalesRow[];
  currencyCode: string;
}) {
  const narrow = useMediaQuery(NARROW_QUERY);

  return (
    <div className="chart-frame">
      <ResponsiveContainer width="100%" height={narrow ? 260 : 320}>
        <ComposedChart
          data={rows}
          margin={{ top: 8, right: narrow ? 4 : 16, bottom: 8, left: narrow ? 0 : 8 }}
        >
          <CartesianGrid stroke={chartColors.grid} vertical={false} />
          {/* Angled labels on a phone: twelve "Apr 26"s won't fit flat, and
              letting Recharts drop every other tick hides months. */}
          <XAxis
            dataKey="label"
            stroke={chartColors.axis}
            tickLine={false}
            fontSize={narrow ? 10 : 12}
            interval={narrow ? 0 : 'preserveEnd'}
            angle={narrow ? -45 : 0}
            textAnchor={narrow ? 'end' : 'middle'}
            height={narrow ? 52 : 30}
          />
          <YAxis
            yAxisId="left"
            stroke={chartColors.axis}
            tickLine={false}
            fontSize={narrow ? 10 : 12}
            width={narrow ? 44 : 60}
            tickFormatter={(value: number) => formatCompactCurrency(value, currencyCode)}
          />
          {/* Hidden, not removed — the line still needs this scale to plot
              against. Its values stay readable in the tooltip. */}
          <YAxis
            yAxisId="right"
            orientation="right"
            stroke={chartColors.axis}
            tickLine={false}
            fontSize={12}
            hide={narrow}
            tickFormatter={(value: number) => formatCompactCurrency(value, currencyCode)}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(value: number, name: string) => [formatCurrency(value, currencyCode), name]}
          />
          <Legend wrapperStyle={{ fontSize: '0.8rem' }} />
          <Bar yAxisId="left" dataKey="total_sales" name="Total Sales" fill={chartColors.sales} radius={[4, 4, 0, 0]} />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="average_invoice_value"
            name="Avg Invoice Value"
            stroke={chartColors.secondary}
            strokeWidth={2}
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
