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
  return (
    <div className="chart-frame">
      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
          <CartesianGrid stroke={chartColors.grid} vertical={false} />
          <XAxis dataKey="label" stroke={chartColors.axis} tickLine={false} fontSize={12} />
          <YAxis
            yAxisId="left"
            stroke={chartColors.axis}
            tickLine={false}
            fontSize={12}
            tickFormatter={(value: number) => formatCompactCurrency(value, currencyCode)}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            stroke={chartColors.axis}
            tickLine={false}
            fontSize={12}
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
