import { describe, expect, test } from 'vitest';
import { describeGstin, gstinError, isValidGstinChecksum, normalizeGstinInput } from './gstin.ts';

// The fixtures are the ones `backend/tests/core/test_validation.py` uses, so the
// two sides are checked against the same answers.

describe('normalizeGstinInput', () => {
  test('upper-cases and drops whitespace, as the API stores it', () => {
    expect(normalizeGstinInput('  27abcde1234f1z0  ')).toBe('27ABCDE1234F1Z0');
    expect(normalizeGstinInput('27 abcde 1234 f1z0')).toBe('27ABCDE1234F1Z0');
  });
});

describe('gstinError — accepted values', () => {
  test('empty is allowed because GST is optional', () => {
    expect(gstinError('')).toBeNull();
    expect(gstinError('   ')).toBeNull();
  });

  test.each([
    '27ABCDE1234F1Z0',
    '27AAPFU0939F1ZV',
    '29ABCDE1234F1ZW',
    '01ABCDE1234F1ZE',
    '38ABCDE1234F1ZX',
    '97ABCDE1234F1ZT',
    '99ABCDE1234F1ZP',
  ])('%s', (gstin) => {
    expect(gstinError(gstin)).toBeNull();
  });

  test('lower case is checked after normalising, not rejected', () => {
    expect(gstinError('27abcde1234f1z0')).toBeNull();
  });
});

describe('gstinError — rejected values, with the backend message', () => {
  test.each(['27ABCDE1234F1Z', '27ABCDE1234F1A5', '2XABCDE1234F1Z0', '27ABCD01234F1Z0'])(
    'format: %s',
    (gstin) => {
      expect(gstinError(gstin)).toBe(
        'Invalid GSTIN format. Expected 15-character GSTIN, e.g. 27ABCDE1234F1Z0',
      );
    },
  );

  test.each(['00ABCDE1234F1ZG', '39ABCDE1234F1ZV', '96ABCDE1234F1ZV', '98ABCDE1234F1ZR'])(
    'state code: %s',
    (gstin) => {
      expect(gstinError(gstin)).toBe('Invalid GSTIN state code. Expected 01-38, 97 or 99');
    },
  );

  test.each(['27ABCDE1234F1Z5', '27AAPFU0939F1ZO', '27AAPFU0938F1ZV', '27AAQFU0939F1ZV'])(
    'checksum: %s',
    (gstin) => {
      expect(gstinError(gstin)).toBe('Invalid GSTIN checksum. Check the 15th character');
    },
  );
});

describe('isValidGstinChecksum', () => {
  test('only one check digit is accepted', () => {
    const accepted = [...'0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'].filter((digit) =>
      isValidGstinChecksum(`27AAPFU0939F1Z${digit}`),
    );
    expect(accepted).toEqual(['V']);
  });

  test('malformed input is not a checksum match', () => {
    expect(isValidGstinChecksum('27AAPFU0939F1Z')).toBe(false);
    expect(isValidGstinChecksum('27aapfu0939f1zv')).toBe(false);
  });
});

describe('describeGstin', () => {
  test('a valid GSTIN gives its PAN and state code', () => {
    expect(describeGstin('27aapfu0939f1zv')).toEqual({ pan: 'AAPFU0939F', stateCode: '27' });
  });

  test('nothing is described for an empty or invalid GSTIN', () => {
    expect(describeGstin('')).toBeNull();
    expect(describeGstin('27AAPFU0939F1ZO')).toBeNull();
  });
});
