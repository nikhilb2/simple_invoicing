/**
 * True when saving would replace a saved currency with a different one. A
 * company with no saved currency has nothing to keep, so it never counts.
 */
export function isCurrencyChange(saved: string, next: string): boolean {
  const from = saved.trim().toUpperCase();
  const to = next.trim().toUpperCase();
  return from !== '' && to !== '' && from !== to;
}
