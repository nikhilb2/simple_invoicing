import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ProfitLossProductRow } from '../../../features/analytics/types';
import useMediaQuery, { NARROW_QUERY } from '../../../hooks/useMediaQuery';
import formatCurrency, { formatCompactCurrency } from '../../../utils/formatting';
import { chartColors, tooltipStyle } from './chartTheme';

/**
 * Horizontal ranked bars of gross profit by product. Loss-makers turn red so a
 * Bottom-N view reads as losses, not just "smaller profits".
 */
export default function ProfitByProductChart({
  rows,
  currencyCode,
}: {
  rows: ProfitLossProductRow[];
  currencyCode: string;
}) {
  const narrow = useMediaQuery(NARROW_QUERY);
  const height = Math.max(220, rows.length * 34 + 60);

  return (
    <div className="chart-frame">
      <ResponsiveContainer width="100%" height={height}>
        <BarChart
          data={rows}
          layout="vertical"
          margin={{ top: 8, right: narrow ? 8 : 24, bottom: 8, left: 8 }}
        >
          <CartesianGrid stroke={chartColors.grid} horizontal={false} />
          <XAxis
            type="number"
            stroke={chartColors.axis}
            tickLine={false}
            fontSize={narrow ? 10 : 12}
            tickFormatter={(value: number) => formatCompactCurrency(value, currencyCode)}
          />
          <YAxis
            type="category"
            dataKey="name"
            stroke={chartColors.axis}
            tickLine={false}
            fontSize={narrow ? 10 : 12}
            width={narrow ? 84 : 140}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(value: number) => [formatCurrency(value, currencyCode), 'Gross Profit']}
          />
          <Bar dataKey="gross_profit" name="Gross Profit" radius={[0, 4, 4, 0]}>
            {rows.map((row) => (
              <Cell
                key={row.product_id}
                fill={row.gross_profit < 0 ? chartColors.loss : chartColors.profit}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
