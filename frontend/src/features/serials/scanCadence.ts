/**
 * Tells a barcode scanner apart from a person typing.
 *
 * The scan box auto-submits after a short silence, so a scanner configured
 * without an Enter suffix still works. That fallback is safe only for input
 * that arrived at machine speed: a scanner empties its buffer into the field
 * in a few milliseconds, so a pause genuinely means "the code ended". A
 * shopkeeper reading an IMEI off the back of a handset pauses far longer than
 * that between digits, and firing the fallback on them looks up a half-typed
 * serial and reports it missing.
 *
 * So the box measures the gaps between characters and only arms the fallback
 * while they stay machine-fast. Typed input submits on Enter instead.
 */

/**
 * A scanner emits characters as fast as the keyboard buffer accepts them, tens
 * of a millisecond apart. The quickest human touch-typist is an order of
 * magnitude slower, which leaves this threshold plenty of room on both sides.
 */
export const SCANNER_MAX_GAP_MS = 35;

export type ScanCadence = {
  /** Whether everything now in the box arrived too fast to have been typed. */
  machineSpeed: boolean;
  /** When the last character landed, to time the next one against. */
  lastInputAt: number;
};

/** A code starts out assumed machine-fast; the first slow gap settles it. */
export function freshCadence(now: number): ScanCadence {
  return { machineSpeed: true, lastInputAt: now };
}

/**
 * Folds one character into the running judgement.
 *
 * `previousLength` and `nextLength` are the box's contents either side of the
 * change. Anything that does not grow the field — a clear, a backspace, typing
 * over a selected code — begins a new code, and the cadence of the old one
 * says nothing about it.
 */
export function noteScanInput(
  cadence: ScanCadence,
  previousLength: number,
  nextLength: number,
  now: number,
): ScanCadence {
  if (previousLength === 0 || nextLength <= previousLength) {
    return freshCadence(now);
  }

  const gap = now - cadence.lastInputAt;
  return {
    machineSpeed: cadence.machineSpeed && gap <= SCANNER_MAX_GAP_MS,
    lastInputAt: now,
  };
}
