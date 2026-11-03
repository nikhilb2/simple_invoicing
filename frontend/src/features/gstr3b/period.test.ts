import { describe, expect, it } from 'vitest';
import { checkPeriod, defaultPeriod, worksheetPresets } from './period';
import { gstr3bQueryKeys } from './queryKeys';

describe('checkPeriod', () => {
  it.each([
    ['2026-06-01', '2026-06-30', 'month'],
    ['2024-02-01', '2024-02-29', 'month'],
    ['2026-02-01', '2026-02-28', 'month'],
    ['2026-04-01', '2026-06-30', 'quarter'],
    ['2026-07-01', '2026-09-30', 'quarter'],
    ['2026-10-01', '2026-12-31', 'quarter'],
    ['2027-01-01', '2027-03-31', 'quarter'],
  ])('accepts %s to %s as a %s', (fromDate, toDate, kind) => {
    expect(checkPeriod({ fromDate, toDate })).toEqual({ ok: true, kind });
  });

  it.each([
    ['2026-06-01', '2026-06-29'],
    ['2026-06-02', '2026-06-30'],
    ['2026-05-01', '2026-07-31'],
    ['2026-04-01', '2026-05-31'],
    ['2026-04-01', '2027-03-31'],
    ['2026-12-01', '2027-02-28'],
    ['2026-06-30', '2026-06-01'],
    ['', '2026-06-30'],
    ['2026-06-01', ''],
  ])('refuses %s to %s', (fromDate, toDate) => {
    expect(checkPeriod({ fromDate, toDate }).ok).toBe(false);
  });
});

describe('worksheetPresets', () => {
  it('offers whole periods only, which is why the shared chips are not used', () => {
    for (const preset of worksheetPresets(new Date(2026, 10, 2))) {
      expect(checkPeriod(preset).ok).toBe(true);
    }
  });

  it('works out the months and quarters around today', () => {
    const presets = Object.fromEntries(worksheetPresets(new Date(2026, 10, 2)).map((p) => [p.key, p]));
    expect(presets['last-month']).toMatchObject({ fromDate: '2026-10-01', toDate: '2026-10-31' });
    expect(presets.month).toMatchObject({ fromDate: '2026-11-01', toDate: '2026-11-30' });
    expect(presets['last-quarter']).toMatchObject({ fromDate: '2026-07-01', toDate: '2026-09-30' });
    expect(presets.quarter).toMatchObject({ fromDate: '2026-10-01', toDate: '2026-12-31' });
  });

  it('crosses the year boundary going back', () => {
    const presets = Object.fromEntries(worksheetPresets(new Date(2027, 0, 15)).map((p) => [p.key, p]));
    expect(presets['last-month']).toMatchObject({ fromDate: '2026-12-01', toDate: '2026-12-31' });
    expect(presets['last-quarter']).toMatchObject({ fromDate: '2026-10-01', toDate: '2026-12-31' });
  });
});

describe('defaultPeriod', () => {
  it('opens on the month just finished', () => {
    expect(defaultPeriod(new Date(2026, 10, 2))).toEqual({ fromDate: '2026-10-01', toDate: '2026-10-31' });
  });
});

describe('gstr3bQueryKeys', () => {
  it('keys on the period, so one period cannot be served for another', () => {
    expect(gstr3bQueryKeys.worksheet('2026-06-01', '2026-06-30')).not.toEqual(
      gstr3bQueryKeys.worksheet('2026-04-01', '2026-06-30'),
    );
    expect(gstr3bQueryKeys.worksheet('2026-06-01', '2026-06-30')).toContain('2026-06-01');
    expect(gstr3bQueryKeys.worksheet('2026-06-01', '2026-06-30')).toContain('2026-06-30');
  });
});
