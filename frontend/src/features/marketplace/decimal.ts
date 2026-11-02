/**
 * Exact decimal arithmetic over the contract's decimal strings.
 *
 * The marketplace transports money and quantities as strings precisely so they
 * never touch a binary float. Parsing them with `Number()` to compute an order
 * total would reintroduce the corruption the contract exists to prevent, so the
 * buy-now preview does its arithmetic on scaled BigInts instead and only ever
 * renders strings.
 */

export type Decimal = {
  /** The value with the decimal point removed. */
  units: bigint;
  /** Number of digits that sit to the right of the point. */
  scale: number;
};

const DECIMAL_PATTERN = /^[+-]?\d+(\.\d+)?$/;

export function parseDecimal(value: string | null | undefined): Decimal | null {
  if (value === null || value === undefined) return null;
  const trimmed = value.trim();
  if (!DECIMAL_PATTERN.test(trimmed)) return null;

  const negative = trimmed.startsWith('-');
  const digits = trimmed.replace(/^[+-]/, '');
  const [whole, fraction = ''] = digits.split('.');
  const units = BigInt(whole + fraction);
  return { units: negative ? -units : units, scale: fraction.length };
}

function rescale(value: Decimal, scale: number): Decimal {
  if (scale === value.scale) return value;
  // Only ever called to raise the scale, which is lossless.
  return { units: value.units * 10n ** BigInt(scale - value.scale), scale };
}

export function addDecimal(a: Decimal, b: Decimal): Decimal {
  const scale = Math.max(a.scale, b.scale);
  return { units: rescale(a, scale).units + rescale(b, scale).units, scale };
}

export function multiplyDecimal(a: Decimal, b: Decimal): Decimal {
  return { units: a.units * b.units, scale: a.scale + b.scale };
}

/** Half-up away from zero, matching how the backend rounds a rupee amount. */
export function roundDecimal(value: Decimal, scale: number): Decimal {
  if (value.scale <= scale) return rescale(value, scale);

  const divisor = 10n ** BigInt(value.scale - scale);
  const negative = value.units < 0n;
  const magnitude = negative ? -value.units : value.units;
  const quotient = magnitude / divisor;
  const remainder = magnitude % divisor;
  const rounded = remainder * 2n >= divisor ? quotient + 1n : quotient;
  return { units: negative ? -rounded : rounded, scale };
}

/** `base * rate / 100`, exact — dividing by 100 is a scale shift, not a division. */
export function percentOfDecimal(base: Decimal, rate: Decimal): Decimal {
  const product = multiplyDecimal(base, rate);
  return { units: product.units, scale: product.scale + 2 };
}

/**
 * `a / b`, rounded half-up to `scale` decimals.
 *
 * Unlike every other operation here this one cannot be exact — a rate like 18%
 * makes the tax-exclusive price a repeating decimal — so the rounding is
 * explicit and the caller chooses the scale it will actually store.
 */
export function divideDecimal(a: Decimal, b: Decimal, scale: number): Decimal | null {
  if (b.units === 0n) return null;

  // result = round(a / b * 10^scale), with the two operands' own scales folded
  // into the exponent so the whole thing stays integer arithmetic.
  const shift = scale + b.scale - a.scale;
  const numerator = shift >= 0 ? a.units * 10n ** BigInt(shift) : a.units;
  const denominator = shift >= 0 ? b.units : b.units * 10n ** BigInt(-shift);

  const negative = (numerator < 0n) !== (denominator < 0n);
  const absNumerator = numerator < 0n ? -numerator : numerator;
  const absDenominator = denominator < 0n ? -denominator : denominator;

  const quotient = absNumerator / absDenominator;
  const remainder = absNumerator % absDenominator;
  const rounded = remainder * 2n >= absDenominator ? quotient + 1n : quotient;
  return { units: negative ? -rounded : rounded, scale };
}

export function formatDecimal(value: Decimal, minFractionDigits = 2): string {
  const scale = Math.max(value.scale, minFractionDigits);
  const scaled = rescale(value, scale);
  const negative = scaled.units < 0n;
  const digits = (negative ? -scaled.units : scaled.units).toString().padStart(scale + 1, '0');
  const whole = digits.slice(0, digits.length - scale) || '0';
  const fraction = scale > 0 ? `.${digits.slice(digits.length - scale)}` : '';
  return `${negative ? '-' : ''}${whole}${fraction}`;
}

/**
 * Render a decimal string for display without ever parsing it as a number.
 * An unparseable value is passed through verbatim rather than silently
 * becoming "NaN" — whatever the server sent is more useful than that.
 */
export function formatMoney(value: string | null | undefined, currencyCode?: string | null): string {
  if (!value) return '—';
  const parsed = parseDecimal(value);
  const text = parsed ? formatDecimal(parsed, 2) : value;
  return currencyCode ? `${currencyCode} ${text}` : text;
}

/** Quantities carry up to 3 decimals but are usually whole; drop trailing zeros. */
export function formatQuantity(value: string | null | undefined): string {
  if (!value) return '—';
  const parsed = parseDecimal(value);
  if (!parsed) return value;
  const text = formatDecimal(parsed, 0);
  return text.includes('.') ? text.replace(/0+$/, '').replace(/\.$/, '') : text;
}

/** GST line preview: taxable, tax and total for one order, all as strings. */
export function computeOrderTotals(unitPrice: string, quantity: string, gstRate: string) {
  const price = parseDecimal(unitPrice);
  const qty = parseDecimal(quantity);
  const rate = parseDecimal(gstRate);
  if (!price || !qty || !rate) return null;

  const taxable = roundDecimal(multiplyDecimal(price, qty), 2);
  const tax = roundDecimal(percentOfDecimal(taxable, rate), 2);
  // The CGST half is rounded and the SGST half is the remainder, so an odd
  // paisa lands on one side instead of making the two halves overshoot `tax`.
  const cgst = roundDecimal({ units: tax.units * 5n, scale: tax.scale + 1 }, 2);
  const sgst = addDecimal(tax, { units: -cgst.units, scale: cgst.scale });

  return {
    taxable: formatDecimal(taxable, 2),
    tax: formatDecimal(tax, 2),
    cgst: formatDecimal(cgst, 2),
    sgst: formatDecimal(sgst, 2),
    total: formatDecimal(addDecimal(taxable, tax), 2),
  };
}

/**
 * Tax-exclusive <-> tax-inclusive conversion for a listing's unit price.
 *
 * The contract stores `asking_price` tax-exclusive and nothing about that
 * changes — these exist so the seller may *type* whichever number they actually
 * have on their price list, and see the other one before they publish.
 *
 * Both round to two decimals because that is the precision the price is stored
 * at (`Numeric(12,2)`, quantized again by the backend serializer). Rounding here
 * rather than later means the number the seller confirms is the number that
 * ships — a gross price entered at a rate that does not divide evenly comes back
 * a paisa off, and it is better to show that than to hide it.
 */
const HUNDRED: Decimal = { units: 100n, scale: 0 };

export function inclusiveFromExclusive(exclusive: string, gstRate: string): string | null {
  const price = parseDecimal(exclusive);
  const rate = parseDecimal(gstRate);
  if (!price || !rate) return null;
  return formatDecimal(roundDecimal(addDecimal(price, percentOfDecimal(price, rate)), 2), 2);
}

export function exclusiveFromInclusive(inclusive: string, gstRate: string): string | null {
  const price = parseDecimal(inclusive);
  const rate = parseDecimal(gstRate);
  if (!price || !rate) return null;
  // net = gross * 100 / (100 + rate) — a division, so it is the one step here
  // that cannot be exact.
  const net = divideDecimal(multiplyDecimal(price, HUNDRED), addDecimal(HUNDRED, rate), 2);
  return net ? formatDecimal(net, 2) : null;
}

/**
 * The tax-exclusive price to publish, given what the seller typed and which of
 * the two prices they meant.
 *
 * This is the rule the whole toggle rests on: `asking_price` on the wire is
 * always tax-exclusive, so an inclusive entry has to be divided down before it
 * leaves. A rate of `null` means no product is chosen yet and there is nothing
 * to divide by — the text is kept as typed and reinterpreted once one is, so a
 * price entered before the product is not silently taken as net.
 */
export function canonicalAskingPrice(
  typed: string,
  includesTax: boolean,
  gstRate: string | null,
): string {
  if (!includesTax || gstRate === null) return typed;
  return exclusiveFromInclusive(typed, gstRate) ?? '';
}

/** Per-unit net/tax/gross for the publish form's price preview. Mirrors
 *  `computeOrderTotals` at quantity 1, which is what a buyer will see. */
export function computeUnitPrice(exclusive: string, gstRate: string) {
  const price = parseDecimal(exclusive);
  const rate = parseDecimal(gstRate);
  if (!price || !rate) return null;

  const net = roundDecimal(price, 2);
  const tax = roundDecimal(percentOfDecimal(net, rate), 2);
  return {
    net: formatDecimal(net, 2),
    tax: formatDecimal(tax, 2),
    gross: formatDecimal(addDecimal(net, tax), 2),
  };
}

/** The first two digits of a GSTIN are the state code. */
export function stateCodeFromGstin(gstin: string | null | undefined): string | null {
  if (!gstin || gstin.length < 2) return null;
  const code = gstin.slice(0, 2);
  return /^\d{2}$/.test(code) ? code : null;
}

export type GstTreatment = { kind: 'igst' | 'cgst_sgst' | 'unknown'; label: string };

/**
 * IGST when the two state codes differ, CGST/SGST when they match. An unknown
 * counterparty state is reported as unknown rather than silently assumed
 * intrastate — that assumption is exactly the bug the contract calls out.
 */
export function gstTreatment(ourStateCode: string | null, theirStateCode: string | null): GstTreatment {
  if (!ourStateCode || !theirStateCode) {
    return { kind: 'unknown', label: 'GST treatment cannot be determined — a state code is missing' };
  }
  return ourStateCode === theirStateCode
    ? { kind: 'cgst_sgst', label: 'Intra-state supply — CGST + SGST' }
    : { kind: 'igst', label: 'Inter-state supply — IGST' };
}
