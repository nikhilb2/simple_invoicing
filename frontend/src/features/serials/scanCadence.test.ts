import { describe, expect, it } from 'vitest';
import { freshCadence, noteScanInput, SCANNER_MAX_GAP_MS, type ScanCadence } from './scanCadence';

const IMEI = '356938035643809';

/** Feeds a code in one character at a time, `gapMs` apart, from an empty box. */
function typeCode(code: string, gapMs: number, start = 1_000): ScanCadence {
  let cadence = freshCadence(start);
  let now = start;
  for (let index = 0; index < code.length; index += 1) {
    now += gapMs;
    cadence = noteScanInput(cadence, index, index + 1, now);
  }
  return cadence;
}

describe('noteScanInput', () => {
  it('keeps the silence fallback armed for a scanner burst', () => {
    expect(typeCode(IMEI, 4).machineSpeed).toBe(true);
  });

  it('disarms it for a code typed by hand', () => {
    expect(typeCode(IMEI, 180).machineSpeed).toBe(false);
  });

  // The reported bug: the box submitted after six characters because a typist's
  // pause was read as the end of the code, so the lookup ran on a prefix.
  it('has already disarmed by the length that used to auto-submit', () => {
    expect(typeCode(IMEI.slice(0, 6), 180).machineSpeed).toBe(false);
  });

  it('disarms on the first human-length gap, even mid-burst', () => {
    let cadence = freshCadence(0);
    cadence = noteScanInput(cadence, 1, 2, 5);
    cadence = noteScanInput(cadence, 2, 3, 400);
    expect(cadence.machineSpeed).toBe(false);

    // Typing quickly after the pause does not make it a scanner again.
    cadence = noteScanInput(cadence, 3, 4, 404);
    expect(cadence.machineSpeed).toBe(false);
  });

  it('treats a gap at the threshold as machine speed and one beyond it as typing', () => {
    expect(noteScanInput(freshCadence(0), 1, 2, SCANNER_MAX_GAP_MS).machineSpeed).toBe(true);
    expect(noteScanInput(freshCadence(0), 1, 2, SCANNER_MAX_GAP_MS + 1).machineSpeed).toBe(false);
  });

  it('arms for a whole code landing in one event, as a paste or a buffering scanner does', () => {
    expect(noteScanInput(freshCadence(0), 0, IMEI.length, 5_000).machineSpeed).toBe(true);
  });

  it('starts over when a failed code is typed over, so the old cadence does not linger', () => {
    const typed = typeCode(IMEI, 180);
    expect(typed.machineSpeed).toBe(false);

    // The failed code is put back and selected; the next character replaces it.
    const restarted = noteScanInput(typed, IMEI.length, 1, 60_000);
    expect(restarted.machineSpeed).toBe(true);
  });

  it('starts over on a backspace', () => {
    const scanned = typeCode(IMEI, 4);
    const afterDelete = noteScanInput(scanned, IMEI.length, IMEI.length - 1, 9_000);
    expect(afterDelete).toEqual(freshCadence(9_000));
  });
});
