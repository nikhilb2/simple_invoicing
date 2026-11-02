import { describe, expect, test } from 'vitest';
import {
  applyOpeningBalanceSide,
  openingBalanceMagnitude,
  openingBalanceSideFromValue,
  parseOpeningBalanceInput,
} from './openingBalance.ts';

describe('openingBalanceSideFromValue — negative is credit, everything else debit', () => {
  test('a negative value is credit', () => {
    expect(openingBalanceSideFromValue(-150)).toBe('credit');
  });

  test('a positive value is debit', () => {
    expect(openingBalanceSideFromValue(150)).toBe('debit');
  });

  test('zero, null and undefined are debit', () => {
    expect(openingBalanceSideFromValue(0)).toBe('debit');
    expect(openingBalanceSideFromValue(null)).toBe('debit');
    expect(openingBalanceSideFromValue(undefined)).toBe('debit');
  });
});

describe('openingBalanceMagnitude — absolute value, null passthrough', () => {
  test('a negative value yields its absolute value', () => {
    expect(openingBalanceMagnitude(-150)).toBe(150);
  });

  test('a positive value passes through', () => {
    expect(openingBalanceMagnitude(150)).toBe(150);
  });

  test('zero stays zero', () => {
    expect(openingBalanceMagnitude(0)).toBe(0);
  });

  test('null and undefined pass through as null', () => {
    expect(openingBalanceMagnitude(null)).toBe(null);
    expect(openingBalanceMagnitude(undefined)).toBe(null);
  });
});

describe('applyOpeningBalanceSide — the side decides the sign', () => {
  test('credit makes the value negative', () => {
    expect(applyOpeningBalanceSide(100, 'credit')).toBe(-100);
  });

  test('debit makes the value positive', () => {
    expect(applyOpeningBalanceSide(100, 'debit')).toBe(100);
  });

  test('an already-signed value is normalized before the side is applied', () => {
    expect(applyOpeningBalanceSide(-100, 'credit')).toBe(-100);
    expect(applyOpeningBalanceSide(-100, 'debit')).toBe(100);
  });

  test('zero and nullish values give null for either side', () => {
    expect(applyOpeningBalanceSide(0, 'credit')).toBe(null);
    expect(applyOpeningBalanceSide(0, 'debit')).toBe(null);
    expect(applyOpeningBalanceSide(null, 'credit')).toBe(null);
    expect(applyOpeningBalanceSide(undefined, 'debit')).toBe(null);
  });
});

describe('parseOpeningBalanceInput — typed text plus selected side', () => {
  test('an empty string gives null', () => {
    expect(parseOpeningBalanceInput('', 'debit')).toBe(null);
    expect(parseOpeningBalanceInput('', 'credit')).toBe(null);
  });

  test('non-numeric text gives null', () => {
    expect(parseOpeningBalanceInput('abc', 'debit')).toBe(null);
  });

  test('zero gives null', () => {
    expect(parseOpeningBalanceInput('0', 'debit')).toBe(null);
    expect(parseOpeningBalanceInput('0.00', 'credit')).toBe(null);
  });

  test('a plain amount takes the selected side', () => {
    expect(parseOpeningBalanceInput('100', 'debit')).toBe(100);
    expect(parseOpeningBalanceInput('100', 'credit')).toBe(-100);
  });

  test('a negative amount typed with either side selected is normalized to that side', () => {
    expect(parseOpeningBalanceInput('-100', 'debit')).toBe(100);
    expect(parseOpeningBalanceInput('-100', 'credit')).toBe(-100);
  });

  test('decimals are kept', () => {
    expect(parseOpeningBalanceInput('12.50', 'debit')).toBe(12.5);
  });
});
