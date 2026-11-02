import { describe, expect, test } from 'vitest';
import { GST_STATES, isInterstatePlaceOfSupply, resolvePlaceOfSupply } from './gstStates';

const HOME = '29AAAAA0000A1Z5';
const BUYER = '27AAPFU0939F1ZV';

describe('resolvePlaceOfSupply', () => {
  test('an unregistered buyer defaults to the seller state', () => {
    expect(resolvePlaceOfSupply(null, '1', HOME, null)).toBe('29');
  });

  test('a registered buyer defaults to the state on their GSTIN', () => {
    expect(resolvePlaceOfSupply(null, '1', HOME, BUYER)).toBe('27');
  });

  test('a choice wins for the ledger it was made for', () => {
    expect(resolvePlaceOfSupply({ ledgerId: '1', code: '10' }, '1', HOME, null)).toBe('10');
  });

  test('a choice does not follow the user to another ledger', () => {
    expect(resolvePlaceOfSupply({ ledgerId: '1', code: '10' }, '2', HOME, BUYER)).toBe('27');
  });

  test('a buyer GSTIN starting 99 is not a state, so nothing is assumed', () => {
    expect(resolvePlaceOfSupply(null, '1', HOME, '99AAAAA0000A1Z5')).toBe('');
  });

  test('a seller with no GSTIN has no place of supply', () => {
    expect(resolvePlaceOfSupply({ ledgerId: '1', code: '10' }, '1', null, BUYER)).toBe('');
  });
});

describe('isInterstatePlaceOfSupply', () => {
  test('another state is interstate', () => {
    expect(isInterstatePlaceOfSupply('10', HOME)).toBe(true);
  });

  test('the seller state is not', () => {
    expect(isInterstatePlaceOfSupply('29', HOME)).toBe(false);
  });

  test('nothing to compare is not', () => {
    expect(isInterstatePlaceOfSupply('', HOME)).toBe(false);
    expect(isInterstatePlaceOfSupply('10', null)).toBe(false);
  });
});

test('every state code is listed once', () => {
  const codes = GST_STATES.map((state) => state.code);
  expect(new Set(codes).size).toBe(codes.length);
});
