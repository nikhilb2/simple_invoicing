import { expect, test } from 'vitest';
import {
  canonicalAskingPrice,
  computeUnitPrice,
  divideDecimal,
  exclusiveFromInclusive,
  formatDecimal,
  inclusiveFromExclusive,
  parseDecimal,
} from './decimal';

/**
 * The publish form lets a seller type the price either way round, but the
 * marketplace only ever stores the tax-exclusive one. These cover the
 * conversion in both directions, including the cases where it cannot be exact.
 */

function div(a: string, b: string, scale: number): string {
  const result = divideDecimal(parseDecimal(a)!, parseDecimal(b)!, scale);
  return result ? formatDecimal(result, scale) : 'null';
}

test('divideDecimal rounds half-up at the requested scale', () => {
  expect(div('10', '4', 2)).toBe('2.50');
  expect(div('1', '3', 2)).toBe('0.33');
  expect(div('2', '3', 2)).toBe('0.67');
  // Exactly half rounds away from zero, matching roundDecimal.
  expect(div('1', '8', 2)).toBe('0.13');
  expect(div('-1', '8', 2)).toBe('-0.13');
});

test('divideDecimal refuses to divide by zero rather than returning Infinity', () => {
  expect(divideDecimal(parseDecimal('5')!, parseDecimal('0')!, 2)).toBeNull();
});

test('inclusiveFromExclusive grosses a net price up by the GST rate', () => {
  expect(inclusiveFromExclusive('100', '18')).toBe('118.00');
  expect(inclusiveFromExclusive('125.00', '18.00')).toBe('147.50');
  expect(inclusiveFromExclusive('99.99', '5')).toBe('104.99');
});

test('exclusiveFromInclusive backs the tax out of a gross price', () => {
  expect(exclusiveFromInclusive('118', '18')).toBe('100.00');
  expect(exclusiveFromInclusive('147.50', '18.00')).toBe('125.00');
});

test('a zero GST rate leaves the price untouched in both directions', () => {
  expect(inclusiveFromExclusive('250', '0')).toBe('250.00');
  expect(exclusiveFromInclusive('250', '0')).toBe('250.00');
});

test('a gross price that does not divide evenly round-trips within a paisa', () => {
  // 1000 / 1.18 = 847.4576..., and 847.46 grosses back to 1000.0028.
  const net = exclusiveFromInclusive('1000', '18');
  expect(net).toBe('847.46');
  expect(inclusiveFromExclusive(net!, '18')).toBe('1000.00');
});

test('conversion never parses its inputs as floats', () => {
  // 0.1 + 0.2 territory: a float round-trip of this rate would drift.
  expect(inclusiveFromExclusive('0.07', '12.5')).toBe('0.08');
  expect(exclusiveFromInclusive('1234567.89', '18')).toBe('1046243.97');
});

test('malformed input yields null instead of NaN', () => {
  expect(inclusiveFromExclusive('', '18')).toBeNull();
  expect(inclusiveFromExclusive('abc', '18')).toBeNull();
  expect(exclusiveFromInclusive('100', '')).toBeNull();
});

test('computeUnitPrice splits a net price into net, tax and gross', () => {
  expect(computeUnitPrice('125', '18')).toEqual({ net: '125.00', tax: '22.50', gross: '147.50' });
  expect(computeUnitPrice('100', '0')).toEqual({ net: '100.00', tax: '0.00', gross: '100.00' });
  expect(computeUnitPrice('nope', '18')).toBeNull();
});

test('computeUnitPrice agrees with the gross the seller typed', () => {
  const net = exclusiveFromInclusive('590', '18')!;
  expect(computeUnitPrice(net, '18')!.gross).toBe('590.00');
});

/**
 * `canonicalAskingPrice` is the rule that keeps a tax-inclusive entry from ever
 * reaching the wire, where `asking_price` is defined tax-exclusive.
 */
test('an exclusive entry is published exactly as typed', () => {
  expect(canonicalAskingPrice('125', false, '18')).toBe('125');
  expect(canonicalAskingPrice('125', false, null)).toBe('125');
});

test('an inclusive entry is divided down before it is published', () => {
  expect(canonicalAskingPrice('147.50', true, '18')).toBe('125.00');
  expect(canonicalAskingPrice('118', true, '18')).toBe('100.00');
});

test('an inclusive entry made before a product is chosen is kept, not taken as net', () => {
  // No rate yet, so nothing to divide by — the text survives...
  expect(canonicalAskingPrice('118', true, null)).toBe('118');
  // ...and is reinterpreted as the gross the moment a rate arrives.
  expect(canonicalAskingPrice('118', true, '18')).toBe('100.00');
});

test('an unusable entry yields an empty price rather than a wrong one', () => {
  expect(canonicalAskingPrice('12.', true, '18')).toBe('');
  expect(canonicalAskingPrice('', true, '18')).toBe('');
});
