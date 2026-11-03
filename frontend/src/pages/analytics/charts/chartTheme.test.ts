import { describe, expect, it } from 'vitest';
import { buildTooltipStyle, readChartColors } from './chartTheme';

const dark: Record<string, string> = {
  '--chart-sales': '#6ea8fe',
  '--chart-secondary': '#f6d67b',
  '--chart-revenue': '#7ee0c0',
  '--chart-profit': '#7ee0c0',
  '--chart-loss': '#ff8b8b',
  '--chart-purchases': '#6f8bd8',
  '--chart-grid': 'rgba(148, 184, 255, 0.14)',
  '--chart-axis': 'rgba(156, 173, 207, 0.75)',
  '--chart-cursor': 'rgba(148, 184, 255, 0.08)',
  '--chart-tooltip-bg': '#0d1426',
  '--chart-tooltip-text': '#e6eefb',
  '--chart-tooltip-border': 'rgba(148, 184, 255, 0.24)',
};

const light: Record<string, string> = {
  ...dark,
  '--chart-sales': '#1d4ed8',
  '--chart-axis': ' rgb(71, 85, 105) ',
  '--chart-tooltip-bg': '#ffffff',
};

describe('readChartColors', () => {
  it('reads the dark tokens, equal to the former literals', () => {
    const colors = readChartColors((n) => dark[n] ?? '');
    expect(colors.sales).toBe('#6ea8fe');
    expect(colors.secondary).toBe('#f6d67b');
    expect(colors.loss).toBe('#ff8b8b');
    expect(colors.grid).toBe('rgba(148, 184, 255, 0.14)');
    expect(colors.axis).toBe('rgba(156, 173, 207, 0.75)');
    expect(buildTooltipStyle(colors)).toEqual({
      background: '#0d1426',
      border: '1px solid rgba(148, 184, 255, 0.24)',
      borderRadius: '8px',
      color: '#e6eefb',
      fontSize: '0.8rem',
    });
  });

  it('reads light values and trims whitespace', () => {
    const colors = readChartColors((n) => light[n] ?? '');
    expect(colors.sales).toBe('#1d4ed8');
    expect(colors.axis).toBe('rgb(71, 85, 105)');
    expect(buildTooltipStyle(colors).background).toBe('#ffffff');
  });

  it('falls back to the dark literals when variables are empty', () => {
    const colors = readChartColors(() => '');
    expect(colors).toEqual(readChartColors((n) => dark[n] ?? ''));
    expect(Object.values(colors).every((v) => v.length > 0)).toBe(true);
  });

  it('falls back per variable, not all-or-nothing', () => {
    const colors = readChartColors((n) => (n === '--chart-sales' ? '#123456' : '   '));
    expect(colors.sales).toBe('#123456');
    expect(colors.secondary).toBe('#f6d67b');
  });
});
