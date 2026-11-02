/**
 * GSTIN checks for the ledger form, run as the user types.
 *
 * The backend (`backend/src/core/validation.py`, `normalize_gstin`) is the
 * authority: it rejects a submitted GSTIN on its format, its state code and its
 * check digit. These helpers repeat the same three checks, in the same order and
 * with the same messages, so the form can say what is wrong before the request
 * is sent. If the backend rules change, change them here too — a GSTIN the form
 * accepts but the API refuses only moves the error back to submit time.
 */

const GSTIN_PATTERN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$/;
const GSTIN_ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';

export const GSTIN_LENGTH = 15;

/** What the user typed, upper-cased with whitespace removed, as the API stores it. */
export function normalizeGstinInput(raw: string): string {
  return raw.replace(/\s+/g, '').toUpperCase();
}

/** Whether the 15th character is the Luhn mod-36 digit of the first 14. */
export function isValidGstinChecksum(gstin: string): boolean {
  if (gstin.length !== GSTIN_LENGTH || [...gstin].some((char) => !GSTIN_ALPHABET.includes(char))) {
    return false;
  }

  let total = 0;
  [...gstin.slice(0, -1)].reverse().forEach((char, index) => {
    const product = GSTIN_ALPHABET.indexOf(char) * (index % 2 === 0 ? 2 : 1);
    total += Math.floor(product / 36) + (product % 36);
  });

  return gstin[GSTIN_LENGTH - 1] === GSTIN_ALPHABET[(36 - (total % 36)) % 36];
}

/**
 * Why `value` would be rejected, or `null` when it is acceptable.
 *
 * An empty value is acceptable: GST is optional on a ledger.
 */
export function gstinError(value: string): string | null {
  const gstin = normalizeGstinInput(value);
  if (!gstin) {
    return null;
  }

  if (!GSTIN_PATTERN.test(gstin)) {
    return 'Invalid GSTIN format. Expected 15-character GSTIN, e.g. 27ABCDE1234F1Z0';
  }

  const stateCode = Number(gstin.slice(0, 2));
  if (!((stateCode >= 1 && stateCode <= 38) || stateCode === 97 || stateCode === 99)) {
    return 'Invalid GSTIN state code. Expected 01-38, 97 or 99';
  }

  if (!isValidGstinChecksum(gstin)) {
    return 'Invalid GSTIN checksum. Check the 15th character';
  }

  return null;
}

/** The PAN and state code inside a valid GSTIN, or `null` for anything else. */
export function describeGstin(value: string): { pan: string; stateCode: string } | null {
  const gstin = normalizeGstinInput(value);
  if (!gstin || gstinError(gstin)) {
    return null;
  }

  return { pan: gstin.slice(2, 12), stateCode: gstin.slice(0, 2) };
}
