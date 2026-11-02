/**
 * Chart palette.
 *
 * Recharts writes colours into SVG presentation attributes (fill, stroke),
 * where `var(--x)` does not work, so the charts need concrete colour strings.
 * They are read at runtime from the `--chart-*` tokens in styles.css, which
 * differ per theme, and re-read whenever the resolved theme changes. The
 * literals below are the dark values and only act as a fallback for an empty
 * variable (for example outside a browser).
 */
import { useMemo, useState } from 'react';
import { useThemeStore } from '../../../store/useThemeStore';

export type ChartColors = {
  sales: string;
  secondary: string;
  revenue: string;
  profit: string;
  loss: string;
  purchases: string;
  grid: string;
  axis: string;
  cursor: string;
  tooltipBg: string;
  tooltipText: string;
  tooltipBorder: string;
};

const VARIABLES: Record<keyof ChartColors, { name: string; fallback: string }> = {
  sales: { name: '--chart-sales', fallback: '#6ea8fe' },
  secondary: { name: '--chart-secondary', fallback: '#f6d67b' },
  revenue: { name: '--chart-revenue', fallback: '#7ee0c0' },
  profit: { name: '--chart-profit', fallback: '#7ee0c0' },
  loss: { name: '--chart-loss', fallback: '#ff8b8b' },
  purchases: { name: '--chart-purchases', fallback: '#6f8bd8' },
  grid: { name: '--chart-grid', fallback: 'rgba(148, 184, 255, 0.14)' },
  axis: { name: '--chart-axis', fallback: 'rgba(156, 173, 207, 0.75)' },
  cursor: { name: '--chart-cursor', fallback: 'rgba(148, 184, 255, 0.08)' },
  tooltipBg: { name: '--chart-tooltip-bg', fallback: '#0d1426' },
  tooltipText: { name: '--chart-tooltip-text', fallback: '#e6eefb' },
  tooltipBorder: { name: '--chart-tooltip-border', fallback: 'rgba(148, 184, 255, 0.24)' },
};

/** Pure: build the palette from a CSS-variable reader, falling back per empty variable. */
export function readChartColors(read: (name: string) => string): ChartColors {
  const out = {} as ChartColors;
  for (const key of Object.keys(VARIABLES) as (keyof ChartColors)[]) {
    const { name, fallback } = VARIABLES[key];
    out[key] = read(name).trim() || fallback;
  }
  return out;
}

/** Pure: the Recharts tooltip `contentStyle` for a palette. */
export function buildTooltipStyle(colors: ChartColors) {
  return {
    background: colors.tooltipBg,
    border: `1px solid ${colors.tooltipBorder}`,
    borderRadius: '8px',
    color: colors.tooltipText,
    fontSize: '0.8rem',
  };
}

function readFromDocument(): ChartColors {
  if (typeof document === 'undefined' || typeof getComputedStyle !== 'function') {
    return readChartColors(() => '');
  }
  const style = getComputedStyle(document.documentElement);
  return readChartColors((name) => style.getPropertyValue(name));
}

/**
 * Concrete chart colours for the active theme. The theme store sets
 * `data-theme` before it updates `resolved`, so reading when `resolved`
 * changes sees the new tokens. The first read is synchronous, never empty.
 */
export function useChartColors(): ChartColors {
  const resolved = useThemeStore((state) => state.resolved);
  const [state, setState] = useState(() => ({ resolved, colors: readFromDocument() }));
  if (state.resolved !== resolved) {
    // Adjust state during render (React-supported) so no frame uses stale colours.
    setState({ resolved, colors: readFromDocument() });
  }
  return state.colors;
}

export function useChartTooltipStyle() {
  const colors = useChartColors();
  return useMemo(() => buildTooltipStyle(colors), [colors]);
}
