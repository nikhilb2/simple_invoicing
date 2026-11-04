export type DateRange = { fromDate: string; toDate: string };

/**
 * Local calendar date as YYYY-MM-DD.
 *
 * UTC conversion can turn an early-morning local date into the previous day.
 */
export function toIsoDate(date: Date): string {
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}

/** Local date and time as YYYY-MM-DDTHH:mm for a datetime-local input. */
export function toLocalDateTimeInput(date: Date): string {
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${toIsoDate(date)}T${hours}:${minutes}`;
}

function startOfWeek(today: Date): Date {
  // Monday-first: the accounting week everywhere this app is used.
  const offset = (today.getDay() + 6) % 7;
  return new Date(today.getFullYear(), today.getMonth(), today.getDate() - offset);
}

/**
 * The return most likely being prepared: last month's, due this month. A closed
 * financial year has no "last month", so that year's final month stands in.
 */
export function defaultFilingPeriod(
  fy?: { start_date: string; end_date: string } | null,
  today: Date = new Date(),
): DateRange {
  const iso = toIsoDate(today);
  const reference = fy?.end_date && fy.end_date < iso
    ? new Date(Number(fy.end_date.slice(0, 4)), Number(fy.end_date.slice(5, 7)), 1)
    : today;
  const year = reference.getFullYear();
  const month = reference.getMonth();
  return { fromDate: toIsoDate(new Date(year, month - 1, 1)), toDate: toIsoDate(new Date(year, month, 0)) };
}

export type RangePreset = { key: string; label: string } & DateRange;

/**
 * The ranges a report is actually asked for, in the order they are reached for.
 * A financial year is included whenever one is active, so the chip row covers
 * the default the page already opens on.
 */
export function buildRangePresets(fy?: { start_date: string; end_date: string } | null): RangePreset[] {
  const today = new Date();
  const iso = toIsoDate(today);
  const at = (y: number, m: number, d: number) => toIsoDate(new Date(y, m, d));
  const year = today.getFullYear();
  const month = today.getMonth();
  const quarter = Math.floor(month / 3) * 3;

  const presets: RangePreset[] = [
    { key: 'today', label: 'Today', fromDate: iso, toDate: iso },
    { key: 'week', label: 'This week', fromDate: toIsoDate(startOfWeek(today)), toDate: iso },
    { key: 'month', label: 'This month', fromDate: at(year, month, 1), toDate: iso },
    { key: 'last-month', label: 'Last month', fromDate: at(year, month - 1, 1), toDate: at(year, month, 0) },
    { key: 'quarter', label: 'This quarter', fromDate: at(year, quarter, 1), toDate: iso },
    { key: 'last-quarter', label: 'Last quarter', fromDate: at(year, quarter - 3, 1), toDate: at(year, quarter, 0) },
  ];

  if (fy?.start_date && fy?.end_date) {
    presets.push({ key: 'fy', label: 'Financial year', fromDate: fy.start_date, toDate: fy.end_date });
  }

  return presets;
}

/** The preset the current range happens to match, if any — so the chips read
 *  as state rather than as six buttons that forget they were pressed. */
export function matchPreset(presets: RangePreset[], range: DateRange): string | null {
  return presets.find((p) => p.fromDate === range.fromDate && p.toDate === range.toDate)?.key ?? null;
}
