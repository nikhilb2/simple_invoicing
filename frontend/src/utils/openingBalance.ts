export type OpeningBalanceSide = 'debit' | 'credit';

export function openingBalanceSideFromValue(value: number | null | undefined): OpeningBalanceSide {
  return value != null && value < 0 ? 'credit' : 'debit';
}

export function openingBalanceMagnitude(value: number | null | undefined): number | null {
  if (value == null) return null;
  return Math.abs(value);
}

export function applyOpeningBalanceSide(
  value: number | null | undefined,
  side: OpeningBalanceSide,
): number | null {
  if (value == null || value === 0) return null;
  const normalized = Math.abs(value);
  return side === 'credit' ? -normalized : normalized;
}

export function parseOpeningBalanceInput(
  value: string,
  side: OpeningBalanceSide,
): number | null {
  if (value === '') return null;
  const parsed = Number.parseFloat(value);
  if (Number.isNaN(parsed) || parsed === 0) return null;
  const normalized = Math.abs(parsed);
  return side === 'credit' ? -normalized : normalized;
}