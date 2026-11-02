import { describe, expect, it } from 'vitest';
import { isSerialFilter } from './types';

describe('isSerialFilter', () => {
  it('accepts the two filtered states', () => {
    expect(isSerialFilter('tracked')).toBe(true);
    expect(isSerialFilter('untracked')).toBe(true);
  });

  it('treats anything else as no filter', () => {
    // These arrive straight from the URL bar, so every one has to fall back to
    // the unfiltered list rather than to an empty one.
    for (const raw of [null, '', 'all', 'true', 'TRACKED', 'serialised', '1']) {
      expect(isSerialFilter(raw)).toBe(false);
    }
  });
});
