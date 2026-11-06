import { execFileSync } from 'node:child_process';
import { describe, expect, it } from 'vitest';

describe('API key expiry picker limit', () => {
  it.each([
    ['UTC', '2027-03-01T12:00:00Z', '2028-02-29'],
    ['Asia/Kolkata', '2027-02-28T19:30:00Z', '2028-02-29'],
    ['UTC', '2028-02-29T12:00:00Z', '2029-02-28'],
    ['Asia/Kolkata', '2026-11-03T19:30:00Z', '2027-11-04'],
    ['America/Los_Angeles', '2027-03-01T07:30:00Z', '2028-02-28'],
    ['Europe/London', '2026-10-25T23:30:00Z', '2027-10-26'],
  ])('offers the last accepted local date in %s at %s', (zone, now, expected) => {
    // Use a real timezone at process startup, including when the CI parent uses UTC.
    const code = `
      const { maxApiKeyExpiryDate, localDateInputToIso } = await import(${JSON.stringify(new URL('./dateRanges.ts', import.meta.url).href)});
      const max = maxApiKeyExpiryDate(new Date(${JSON.stringify(now)}));
      const [year, month, day] = max.split('-').map(Number);
      console.log(JSON.stringify({
        max, expiry: localDateInputToIso(max),
        next: new Date(year, month - 1, day + 1).toISOString(),
      }));
    `;
    const result = JSON.parse(execFileSync(process.execPath, [
      '--experimental-strip-types', '--input-type=module', '--eval', code,
    ], { env: { ...process.env, TZ: zone }, encoding: 'utf8' }));
    const current = new Date(now).getTime();
    // ApiKeyCreate.validate_expiry allows at most timedelta(days=365), not a calendar year.
    const deadline = current + 365 * 24 * 60 * 60 * 1000;
    expect(result.max).toBe(expected);
    expect(new Date(result.expiry).getTime()).toBeGreaterThan(current);
    expect(new Date(result.expiry).getTime()).toBeLessThanOrEqual(deadline);
    expect(new Date(result.next).getTime()).toBeGreaterThan(deadline);
  });
});
