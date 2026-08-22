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
