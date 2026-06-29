import type { DashboardMonthlyPoint, DashboardTopProduct } from '../types/api';
import formatCurrency, { formatCompactCurrency } from '../utils/formatting';

type MonthlyTrendChartProps = {
  data: DashboardMonthlyPoint[];
  currencyCode: string;
};

/**
 * Grouped bar chart of sales vs. purchases per month with a receipts overlay line.
 * Hand-rolled SVG so the dashboard stays dependency-free.
 */
export function MonthlyTrendChart({ data, currencyCode }: MonthlyTrendChartProps) {
  const width = 720;
  const height = 240;
  const padding = { top: 16, right: 16, bottom: 28, left: 16 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  const maxValue = Math.max(
    1,
    ...data.map((point) => Math.max(point.sales, point.purchases, point.receipts)),
  );

  const groupWidth = plotWidth / data.length;
  const barGap = 4;
  const barWidth = Math.max(4, (groupWidth - barGap * 3) / 2);
  const yFor = (value: number) => padding.top + plotHeight - (value / maxValue) * plotHeight;

  const linePoints = data
    .map((point, index) => {
      const x = padding.left + groupWidth * index + groupWidth / 2;
      return `${x},${yFor(point.receipts)}`;
    })
    .join(' ');

  const hasData = data.some((point) => point.sales || point.purchases || point.receipts);

  return (
    <div className="chart">
      <div className="chart__legend">
        <span className="chart__legend-item"><i className="chart__swatch chart__swatch--sales" /> Sales</span>
        <span className="chart__legend-item"><i className="chart__swatch chart__swatch--purchases" /> Purchases</span>
        <span className="chart__legend-item"><i className="chart__swatch chart__swatch--receipts" /> Receipts</span>
      </div>
      {!hasData ? (
        <p className="muted-text chart__empty">No invoice or payment activity in the last 12 months.</p>
      ) : (
        <svg viewBox={`0 0 ${width} ${height}`} className="chart__svg" role="img" aria-label="Monthly sales, purchases and receipts">
          {[0.25, 0.5, 0.75, 1].map((fraction) => (
            <line
              key={fraction}
              x1={padding.left}
              x2={width - padding.right}
              y1={padding.top + plotHeight * (1 - fraction)}
              y2={padding.top + plotHeight * (1 - fraction)}
              className="chart__gridline"
            />
          ))}
          {data.map((point, index) => {
            const groupX = padding.left + groupWidth * index;
            const salesX = groupX + barGap;
            const purchasesX = salesX + barWidth + barGap;
            return (
              <g key={point.month}>
                <rect
                  x={salesX}
                  y={yFor(point.sales)}
                  width={barWidth}
                  height={padding.top + plotHeight - yFor(point.sales)}
                  rx={3}
                  className="chart__bar chart__bar--sales"
                >
                  <title>{`${point.label} · Sales ${formatCurrency(point.sales, currencyCode)}`}</title>
                </rect>
                <rect
                  x={purchasesX}
                  y={yFor(point.purchases)}
                  width={barWidth}
                  height={padding.top + plotHeight - yFor(point.purchases)}
                  rx={3}
                  className="chart__bar chart__bar--purchases"
                >
                  <title>{`${point.label} · Purchases ${formatCurrency(point.purchases, currencyCode)}`}</title>
                </rect>
                <text x={groupX + groupWidth / 2} y={height - 8} textAnchor="middle" className="chart__xlabel">
                  {point.label}
                </text>
              </g>
            );
          })}
          <polyline points={linePoints} className="chart__line" fill="none" />
          {data.map((point, index) => {
            const x = padding.left + groupWidth * index + groupWidth / 2;
            return (
              <circle key={`dot-${point.month}`} cx={x} cy={yFor(point.receipts)} r={3} className="chart__dot">
                <title>{`${point.label} · Receipts ${formatCurrency(point.receipts, currencyCode)}`}</title>
              </circle>
            );
          })}
        </svg>
      )}
    </div>
  );
}

type PaymentStatusDonutProps = {
  paid: number;
  partial: number;
  unpaid: number;
};

const DONUT_SEGMENTS = [
  { key: 'paid', label: 'Paid', className: 'donut__legend-swatch--paid' },
  { key: 'partial', label: 'Partial', className: 'donut__legend-swatch--partial' },
  { key: 'unpaid', label: 'Unpaid', className: 'donut__legend-swatch--unpaid' },
] as const;

export function PaymentStatusDonut({ paid, partial, unpaid }: PaymentStatusDonutProps) {
  const counts = { paid, partial, unpaid };
  const total = paid + partial + unpaid;
  const radius = 52;
  const stroke = 18;
  const circumference = 2 * Math.PI * radius;

  let offset = 0;
  const arcs = DONUT_SEGMENTS.map((segment) => {
    const value = counts[segment.key];
    const fraction = total > 0 ? value / total : 0;
    const dash = fraction * circumference;
    const arc = {
      key: segment.key,
      dashArray: `${dash} ${circumference - dash}`,
      dashOffset: -offset,
      className: `donut__arc donut__arc--${segment.key}`,
    };
    offset += dash;
    return arc;
  });

  return (
    <div className="donut">
      <svg viewBox="0 0 140 140" className="donut__svg" role="img" aria-label="Invoice payment status breakdown">
        <circle cx="70" cy="70" r={radius} className="donut__track" strokeWidth={stroke} fill="none" />
        {total > 0
          ? arcs.map((arc) => (
              <circle
                key={arc.key}
                cx="70"
                cy="70"
                r={radius}
                className={arc.className}
                strokeWidth={stroke}
                fill="none"
                strokeDasharray={arc.dashArray}
                strokeDashoffset={arc.dashOffset}
                transform="rotate(-90 70 70)"
                strokeLinecap="butt"
              />
            ))
          : null}
        <text x="70" y="66" textAnchor="middle" className="donut__total">{total}</text>
        <text x="70" y="84" textAnchor="middle" className="donut__caption">invoices</text>
      </svg>
      <ul className="donut__legend">
        {DONUT_SEGMENTS.map((segment) => (
          <li key={segment.key} className="donut__legend-item">
            <span className={`donut__legend-swatch ${segment.className}`} />
            <span>{segment.label}</span>
            <strong>{counts[segment.key]}</strong>
          </li>
        ))}
      </ul>
    </div>
  );
}

type TopProductsBarsProps = {
  data: DashboardTopProduct[];
  currencyCode: string;
};

export function TopProductsBars({ data, currencyCode }: TopProductsBarsProps) {
  if (data.length === 0) {
    return <p className="muted-text">No sales recorded yet.</p>;
  }
  const maxRevenue = Math.max(1, ...data.map((product) => product.revenue));
  return (
    <ul className="top-products">
      {data.map((product) => (
        <li key={product.product_id} className="top-products__row">
          <div className="top-products__meta">
            <span className="top-products__name">{product.name}</span>
            <span className="top-products__value">{formatCompactCurrency(product.revenue, currencyCode)}</span>
          </div>
          <div className="top-products__track">
            <div
              className="top-products__fill"
              style={{ width: `${Math.max(4, (product.revenue / maxRevenue) * 100)}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}
