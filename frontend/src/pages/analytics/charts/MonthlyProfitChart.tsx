import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ProfitLossMonthlyRow } from '../../../features/analytics/types';
import useMediaQuery, { NARROW_QUERY } from '../../../hooks/useMediaQuery';
import formatCurrency, { formatCompactCurrency } from '../../../utils/formatting';
import { chartColors, tooltipStyle } from './chartTheme';

/**
 * Monthly gross profit as bars with the margin % overlaid as a line. A losing
 * month's bar turns red so it reads at a glance rather than needing the axis.
 * Doubles as the selected-product profit/loss chart — when a product filter is
 * active the same monthly series is scoped to that product.
 */
export default function MonthlyProfitChart({
  rows,
  currencyCode,
}: {
  rows: ProfitLossMonthlyRow[];
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
          <YAxis
            yAxisId="right"
            orientation="right"
            stroke={chartColors.axis}
            tickLine={false}
            fontSize={12}
            hide={narrow}
            tickFormatter={(value: number) => `${value.toFixed(0)}%`}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(value: number, name: string) =>
              name === 'Margin %'
                ? [`${value.toFixed(1)}%`, name]
                : [formatCurrency(value, currencyCode), name]
            }
          />
          <Legend wrapperStyle={{ fontSize: '0.8rem' }} />
          <Bar yAxisId="left" dataKey="gross_profit" name="Gross Profit" radius={[4, 4, 0, 0]}>
            {rows.map((row) => (
              <Cell key={row.month} fill={row.gross_profit < 0 ? chartColors.loss : chartColors.profit} />
            ))}
          </Bar>
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="margin_pct"
            name="Margin %"
            stroke={chartColors.secondary}
            strokeWidth={2}
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
