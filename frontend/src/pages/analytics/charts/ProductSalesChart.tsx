import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ProductSalesRow } from '../../../features/analytics/types';
import formatCurrency, { formatCompactCurrency } from '../../../utils/formatting';
import { chartColors, tooltipStyle } from './chartTheme';

export type ProductMetric = 'revenue' | 'quantity';

/**
 * Horizontal ranked bars — product names are long, and vertical bars would
 * either truncate them or turn the axis into diagonal text.
 */
export default function ProductSalesChart({
  rows,
  metric,
  currencyCode,
}: {
  rows: ProductSalesRow[];
  metric: ProductMetric;
  currencyCode: string;
}) {
  const dataKey = metric === 'revenue' ? 'total_revenue' : 'quantity_sold';
  const name = metric === 'revenue' ? 'Revenue' : 'Quantity Sold';
  const fill = metric === 'revenue' ? chartColors.revenue : chartColors.sales;

  const format = (value: number) =>
    metric === 'revenue' ? formatCurrency(value, currencyCode) : String(value);
  const formatAxis = (value: number) =>
    metric === 'revenue' ? formatCompactCurrency(value, currencyCode) : String(value);

  // Grow with the row count so bars stay legible whether there are 3 or 10.
  const height = Math.max(220, rows.length * 34 + 60);

  return (
    <div className="chart-frame">
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={rows} layout="vertical" margin={{ top: 8, right: 24, bottom: 8, left: 8 }}>
          <CartesianGrid stroke={chartColors.grid} horizontal={false} />
          <XAxis
            type="number"
            stroke={chartColors.axis}
            tickLine={false}
            fontSize={12}
            tickFormatter={formatAxis}
          />
          <YAxis
            type="category"
            dataKey="name"
            stroke={chartColors.axis}
            tickLine={false}
            fontSize={12}
            width={140}
          />
          <Tooltip contentStyle={tooltipStyle} formatter={(value: number) => [format(value), name]} />
          <Bar dataKey={dataKey} name={name} fill={fill} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
