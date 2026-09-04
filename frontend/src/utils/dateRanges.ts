export type DateRange = { fromDate: string; toDate: string };

/**
 * Local calendar date as YYYY-MM-DD.
 *
 * Not `toISOString().slice(0, 10)`: that converts to UTC first, so anywhere
 * east of Greenwich "today" becomes yesterday for the whole evening — an
 * off-by-one-day report on every Indian install after 05:30 IST.
 */
export function toIsoDate(date: Date): string {
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}

function startOfWeek(today: Date): Date {
  // Monday-first: the accounting week everywhere this app is used.
  const offset = (today.getDay() + 6) % 7;
  return new Date(today.getFullYear(), today.getMonth(), today.getDate() - offset);
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
