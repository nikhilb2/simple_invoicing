import { execFileSync } from 'node:child_process';
import { describe, expect, it } from 'vitest';

describe('local input dates in non-UTC processes', () => {
  it.each([
    ['Asia/Kolkata', '2026-11-03T19:30:00Z', '2026-11-05', '2027-11-04', '2026-11-04T01:00'],
    ['America/Los_Angeles', '2026-11-04T07:30:00Z', '2026-11-04', '2027-11-03', '2026-11-03T23:30'],
  ])('keeps the expiry bounds and receipt clock valid in %s', (zone, now, min, max, localClock) => {
    // Launch Node with TZ before startup: this remains effective when the parent CI runs in UTC.
    // Node 24 is the version configured by Frontend CI; its native TS loader runs the production helper.
    const code = `
      const { localDateInputToIso, toLocalDateTimeInput } = await import(${JSON.stringify(new URL('./dateRanges.ts', import.meta.url).href)});
      const now = new Date(${JSON.stringify(now)});
      console.log(JSON.stringify({
        min: localDateInputToIso(${JSON.stringify(min)}),
        max: localDateInputToIso(${JSON.stringify(max)}),
        clock: toLocalDateTimeInput(now),
      }));
    `;
    const result = JSON.parse(execFileSync(process.execPath, [
      '--experimental-strip-types', '--input-type=module', '--eval', code,
    ], { env: { ...process.env, TZ: zone }, encoding: 'utf8' }));
    const earliest = new Date(result.min).getTime();
    const latest = new Date(result.max).getTime();
    const current = new Date(now).getTime();
    expect(earliest).toBeGreaterThan(current);
    expect(latest).toBeGreaterThan(current);
    expect(latest).toBeLessThanOrEqual(current + 365 * 24 * 60 * 60 * 1000);
    expect(result.clock).toBe(localClock);
  });
});
