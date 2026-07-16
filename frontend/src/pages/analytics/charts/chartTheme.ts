/**
 * Chart palette.
 *
 * The app commits to a single dark theme (`:root { color-scheme: dark }`), so
 * these are fixed rather than media-query branched. Values track the sidebar
 * and chart custom properties already in styles.css.
 */
export const chartColors = {
  sales: '#6ea8fe',
  secondary: '#f6d67b',
  revenue: '#7ee0c0',
  grid: 'rgba(148, 184, 255, 0.14)',
  axis: 'rgba(156, 173, 207, 0.75)',
};

export const tooltipStyle = {
  background: '#0d1426',
  border: '1px solid rgba(148, 184, 255, 0.24)',
  borderRadius: '8px',
  color: '#e6eefb',
  fontSize: '0.8rem',
};
