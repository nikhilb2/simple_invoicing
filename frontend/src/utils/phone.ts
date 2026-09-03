/**
 * Turning a stored phone number into something wa.me will accept.
 *
 * Nothing in this app normalises phone numbers: `Ledger.phone_number` and
 * `Invoice.ledger_phone` are free text, filled in by hand over years — with or
 * without a `+`, with spaces, dashes, brackets, an STD `0`, or nothing at all.
 * wa.me wants bare digits including a country code, so the gap has to be closed
 * here, and it can only be closed by guessing.
 *
 * The guess is therefore deliberately narrow, and every uncertain case answers
 * `null` rather than inventing a country code. A wrong guess does not fail
 * loudly — it silently addresses a customer's invoice to a stranger who happens
 * to own that number in another country. `null` costs the user two taps in
 * WhatsApp's own contact picker, which is the cheaper mistake by a wide margin.
 */

/**
 * Best-effort E.164-ish digits for wa.me, or `null` when the input is not
 * confidently a phone number.
 *
 * - every non-digit is stripped (`+`, spaces, dashes, brackets)
 * - a leading `00` (the international access prefix, as in `0091…`) is dropped
 * - otherwise one leading `0` is dropped (the Indian STD prefix, and the same
 *   habit elsewhere)
 * - exactly 10 digits is read as a national number and gets `defaultCountryCode`
 * - 11 to 13 digits is read as already carrying a country code and is used as-is
 * - anything else — empty, too short, too long, or text — is `null`
 */
export function toWhatsAppNumber(
  raw: string | null | undefined,
  defaultCountryCode = '91',
): string | null {
  if (!raw) {
    return null;
  }

  const digits = raw.replace(/\D/g, '');
  // `00` is the international access prefix, so `0091 98765 43210` is the same
  // number as `+91 98765 43210` and both zeroes go. Dropping only one would
  // leave `0919876543210`, and wa.me rejects a leading zero outright.
  // A single leading `0` is instead a national trunk prefix, so only it goes.
  let trimmed = digits;
  if (trimmed.startsWith('00')) {
    trimmed = trimmed.slice(2);
  } else if (trimmed.startsWith('0')) {
    trimmed = trimmed.slice(1);
  }

  if (trimmed.length === 10) {
    return `${defaultCountryCode}${trimmed}`;
  }

  if (trimmed.length >= 11 && trimmed.length <= 13) {
    return trimmed;
  }

  return null;
}

/**
 * A wa.me deep link for `message`, addressed to `number` when there is one.
 *
 * With no number WhatsApp opens its own contact picker holding the message —
 * the intended path for every number `toWhatsAppNumber` would not vouch for,
 * not a degraded one.
 */
export function buildWhatsAppUrl(number: string | null, message: string): string {
  const text = encodeURIComponent(message);
  return number ? `https://wa.me/${number}?text=${text}` : `https://wa.me/?text=${text}`;
}
