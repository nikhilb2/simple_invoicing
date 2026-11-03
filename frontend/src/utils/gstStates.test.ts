import { describe, expect, test } from 'vitest';
import {
  GST_STATES,
  isInterstatePlaceOfSupply,
  placeOfSupplyOptions,
  resolvePlaceOfSupply,
  stalePlaceOfSupplyWarning,
} from './gstStates';

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

describe('placeOfSupplyOptions', () => {
  const codes = (current: string) => placeOfSupplyOptions(current).map((state) => state.code);

  test('retired codes are not offered', () => {
    expect(codes('37')).toContain('37');
    expect(codes('37')).not.toContain('28');
    expect(codes('37')).not.toContain('25');
    expect(codes('')).not.toContain('28');
  });

  test('an old document keeps showing the retired code it carries', () => {
    expect(codes('28')).toContain('28');
    expect(codes('28')).not.toContain('25');
    expect(codes('25')).toContain('25');
  });

  test('a buyer GSTIN with a retired code still resolves', () => {
    expect(resolvePlaceOfSupply(null, '1', HOME, '28AAAAA0000A1Z5')).toBe('28');
  });
});

describe('stalePlaceOfSupplyWarning', () => {
  test('warns when the saved state is not the one on the buyer\'s GSTIN now', () => {
    const warning = stalePlaceOfSupplyWarning('29', '29', BUYER);
    expect(warning).toContain('29 – Karnataka');
    expect(warning).toContain('27 – Maharashtra');
    expect(warning).toContain("won't change on its own");
  });

  test('quiet when they match, or the buyer still has no GSTIN', () => {
    expect(stalePlaceOfSupplyWarning('27', '27', BUYER)).toBeNull();
    expect(stalePlaceOfSupplyWarning('29', '29', null)).toBeNull();
  });

  test('quiet when nothing was saved, or the user has already picked another state', () => {
    expect(stalePlaceOfSupplyWarning(null, '27', BUYER)).toBeNull();
    expect(stalePlaceOfSupplyWarning('29', '10', BUYER)).toBeNull();
  });

  test('quiet for a buyer GSTIN whose code is not a state', () => {
    expect(stalePlaceOfSupplyWarning('29', '29', '99AAAAA0000A1Z5')).toBeNull();
  });
});

test('every state code is listed once', () => {
  const codes = GST_STATES.map((state) => state.code);
  expect(new Set(codes).size).toBe(codes.length);
});
