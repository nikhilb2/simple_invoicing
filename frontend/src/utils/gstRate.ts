/**
 * Parses the GST rate filter box. An empty box means "all rates"; a value that
 * is not a finite number is ignored instead of being sent as `NaN`.
 */
export function parseGstRate(value: string): number | undefined {
  if (!value.trim()) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}
