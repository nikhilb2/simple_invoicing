import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { buildRangePresets, defaultFilingPeriod, matchPreset, toIsoDate, toLocalDateTimeInput } from './dateRanges.ts';

describe('toLocalDateTimeInput', () => {
  test('an early-morning time keeps its local date and clock', () => {
    expect(toLocalDateTimeInput(new Date(2026, 4, 9, 0, 30))).toBe('2026-05-09T00:30');
  });

  test('single-digit hours and minutes are zero-padded', () => {
    expect(toLocalDateTimeInput(new Date(2026, 4, 9, 7, 5))).toBe('2026-05-09T07:05');
  });

  test('midnight has no seconds or timezone suffix', () => {
    expect(toLocalDateTimeInput(new Date(2026, 4, 9))).toBe('2026-05-09T00:00');
  });

  test('month boundaries follow the local calendar', () => {
    expect(toLocalDateTimeInput(new Date(2026, 5, 1, 0, 1))).toBe('2026-06-01T00:01');
  });

  test('year boundaries follow the local calendar', () => {
    expect(toLocalDateTimeInput(new Date(2027, 0, 1, 0, 1))).toBe('2027-01-01T00:01');
    expect(toLocalDateTimeInput(new Date(2026, 11, 31, 23, 59))).toBe('2026-12-31T23:59');
  });
});

describe('toIsoDate — local calendar date, zero-padded', () => {
  test('single-digit month and day are zero-padded', () => {
    expect(toIsoDate(new Date(2026, 0, 5))).toBe('2026-01-05');
  });

  test('double-digit month and day pass through', () => {
    expect(toIsoDate(new Date(2026, 11, 25))).toBe('2026-12-25');
  });

  test('an early-morning local time stays on the local date, not the UTC date', () => {
    // East of Greenwich, 00:30 local is still the previous day in UTC — a
    // toISOString-based implementation would return '2026-05-08' here.
    expect(toIsoDate(new Date(2026, 4, 9, 0, 30))).toBe('2026-05-09');
  });
});

describe('buildRangePresets — pinned "today"', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test('today preset is the pinned day on both ends', () => {
    vi.setSystemTime(new Date(2026, 9, 26));
    const presets = buildRangePresets();
    expect(presets.find((p) => p.key === 'today')).toEqual({
      key: 'today',
      label: 'Today',
      fromDate: '2026-10-26',
      toDate: '2026-10-26',
    });
  });

  test('week starts on Monday: a Sunday looks back to the previous Monday', () => {
    vi.setSystemTime(new Date(2026, 9, 25)); // a Sunday
    const week = buildRangePresets().find((p) => p.key === 'week');
    expect(week?.fromDate).toBe('2026-10-19');
    expect(week?.toDate).toBe('2026-10-25');
  });

  test('week starts on Monday: a Monday starts the week on itself', () => {
    vi.setSystemTime(new Date(2026, 9, 26)); // a Monday
    const week = buildRangePresets().find((p) => p.key === 'week');
    expect(week?.fromDate).toBe('2026-10-26');
    expect(week?.toDate).toBe('2026-10-26');
  });

  test('this month starts on the 1st', () => {
    vi.setSystemTime(new Date(2026, 9, 26));
    const month = buildRangePresets().find((p) => p.key === 'month');
    expect(month?.fromDate).toBe('2026-10-01');
    expect(month?.toDate).toBe('2026-10-26');
  });

  test('last month in January rolls back to December of the previous year', () => {
    vi.setSystemTime(new Date(2026, 0, 15));
    const lastMonth = buildRangePresets().find((p) => p.key === 'last-month');
    expect(lastMonth?.fromDate).toBe('2025-12-01');
    expect(lastMonth?.toDate).toBe('2025-12-31');
  });

  test('this quarter starts on the first month of the quarter', () => {
    vi.setSystemTime(new Date(2026, 9, 26)); // October -> Q4
    const quarter = buildRangePresets().find((p) => p.key === 'quarter');
    expect(quarter?.fromDate).toBe('2026-10-01');
    vi.setSystemTime(new Date(2026, 1, 10)); // February -> Q1
    const q1 = buildRangePresets().find((p) => p.key === 'quarter');
    expect(q1?.fromDate).toBe('2026-01-01');
  });

  test('financial year preset appears only when a financial year is passed', () => {
    vi.setSystemTime(new Date(2026, 9, 26));
    const withFy = buildRangePresets({ start_date: '2026-04-01', end_date: '2027-03-31' });
    expect(withFy.find((p) => p.key === 'fy')).toEqual({
      key: 'fy',
      label: 'Financial year',
      fromDate: '2026-04-01',
      toDate: '2027-03-31',
    });
    expect(buildRangePresets().some((p) => p.key === 'fy')).toBe(false);
    expect(buildRangePresets(null).some((p) => p.key === 'fy')).toBe(false);
    expect(
      buildRangePresets({ start_date: '2026-04-01', end_date: '' }).some((p) => p.key === 'fy'),
    ).toBe(false);
  });
});

describe('matchPreset — exact range match or null', () => {
  const presets = buildRangePresets();

  test('returns the key of the preset whose range matches exactly', () => {
    const today = presets.find((p) => p.key === 'today')!;
    expect(matchPreset(presets, { fromDate: today.fromDate, toDate: today.toDate })).toBe('today');
  });

  test('returns null when only one end matches', () => {
    const today = presets.find((p) => p.key === 'today')!;
    expect(matchPreset(presets, { fromDate: today.fromDate, toDate: '2099-01-01' })).toBe(null);
  });

  test('returns null when nothing matches, or there are no presets', () => {
    expect(matchPreset(presets, { fromDate: '2020-01-01', toDate: '2020-01-31' })).toBe(null);
    expect(matchPreset([], { fromDate: '2026-10-26', toDate: '2026-10-26' })).toBe(null);
  });
});

describe('defaultFilingPeriod', () => {
  test('is last month, not the whole financial year', () => {
    const fy = { start_date: '2026-04-01', end_date: '2027-03-31' };
    expect(defaultFilingPeriod(fy, new Date(2026, 10, 3))).toEqual({ fromDate: '2026-10-01', toDate: '2026-10-31' });
  });

  test('January reaches back across the calendar year', () => {
    expect(defaultFilingPeriod(null, new Date(2027, 0, 15))).toEqual({ fromDate: '2026-12-01', toDate: '2026-12-31' });
  });

  test('a financial year that has closed offers its last month', () => {
    const fy = { start_date: '2024-04-01', end_date: '2025-03-31' };
    expect(defaultFilingPeriod(fy, new Date(2026, 10, 3))).toEqual({ fromDate: '2025-03-01', toDate: '2025-03-31' });
  });

  test('February ends on its real last day', () => {
    expect(defaultFilingPeriod(null, new Date(2024, 2, 10))).toEqual({ fromDate: '2024-02-01', toDate: '2024-02-29' });
  });
});
