import { toIsoDate, type DateRange, type RangePreset } from '../../utils/dateRanges';

export type PeriodCheck =
  | { ok: true; kind: 'month' | 'quarter' }
  | { ok: false; message: string };

export const PERIOD_RULE =
  'GSTR-3B covers one calendar month or one quarter (Apr-Jun, Jul-Sep, Oct-Dec, Jan-Mar). Choose the first and last day of that period.';

const QUARTER_START_MONTHS = [0, 3, 6, 9];

function parseIso(value: string): { year: number; month: number; day: number } | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  return { year: Number(match[1]), month: Number(match[2]) - 1, day: Number(match[3]) };
}

function lastDayOfMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate();
}

/** The same rule the backend enforces, so a half-typed range makes no request. */
export function checkPeriod({ fromDate, toDate }: DateRange): PeriodCheck {
  const from = parseIso(fromDate);
  const to = parseIso(toDate);
  if (!from || !to || from.day !== 1 || from.year !== to.year) {
    return { ok: false, message: PERIOD_RULE };
  }
  if (to.month === from.month && to.day === lastDayOfMonth(from.year, from.month)) {
    return { ok: true, kind: 'month' };
  }
  if (
    QUARTER_START_MONTHS.includes(from.month)
    && to.month === from.month + 2
    && to.day === lastDayOfMonth(from.year, to.month)
  ) {
    return { ok: true, kind: 'quarter' };
  }
  return { ok: false, message: PERIOD_RULE };
}

function monthRange(year: number, month: number): DateRange {
  return {
    fromDate: toIsoDate(new Date(year, month, 1)),
    toDate: toIsoDate(new Date(year, month + 1, 0)),
  };
}

function quarterRange(year: number, startMonth: number): DateRange {
  return {
    fromDate: toIsoDate(new Date(year, startMonth, 1)),
    toDate: toIsoDate(new Date(year, startMonth + 3, 0)),
  };
}

/**
 * Whole periods only. The chips the other reports share run "this month" up to
 * today, which is a range this report refuses, so it has its own.
 */
export function worksheetPresets(today: Date = new Date()): RangePreset[] {
  const year = today.getFullYear();
  const month = today.getMonth();
  const quarter = Math.floor(month / 3) * 3;
  return [
    { key: 'last-month', label: 'Last month', ...monthRange(year, month - 1) },
    { key: 'month', label: 'This month', ...monthRange(year, month) },
    { key: 'last-quarter', label: 'Last quarter', ...quarterRange(year, quarter - 3) },
    { key: 'quarter', label: 'This quarter', ...quarterRange(year, quarter) },
  ];
}

/** The month that is usually being filed for: the one just finished. */
export function defaultPeriod(today: Date = new Date()): DateRange {
  return monthRange(today.getFullYear(), today.getMonth() - 1);
}
