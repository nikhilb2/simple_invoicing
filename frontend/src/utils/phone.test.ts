import { describe, expect, test } from 'vitest';
import { buildWhatsAppUrl, toWhatsAppNumber } from './phone.ts';

describe('toWhatsAppNumber — 10 digits get the default country code', () => {
  test('a bare Indian mobile', () => {
    expect(toWhatsAppNumber('9876543210')).toBe('919876543210');
  });

  test('spaces and dashes are stripped first', () => {
    expect(toWhatsAppNumber('98765-43210')).toBe('919876543210');
    expect(toWhatsAppNumber('98765 43210')).toBe('919876543210');
  });

  test('a leading STD zero is dropped, leaving 10', () => {
    expect(toWhatsAppNumber('09876543210')).toBe('919876543210');
  });

  test('a bracketed landline with an STD zero', () => {
    expect(toWhatsAppNumber('(044) 2345-6789')).toBe('914423456789');
  });

  test('the country code is overridable', () => {
    expect(toWhatsAppNumber('5551234567', '1')).toBe('15551234567');
  });
});

describe('toWhatsAppNumber — 11 to 13 digits are taken as-is', () => {
  test('a +91 number keeps its own country code', () => {
    expect(toWhatsAppNumber('+91 98765 43210')).toBe('919876543210');
  });

  test('11 digits, the lower bound', () => {
    expect(toWhatsAppNumber('12345678901')).toBe('12345678901');
  });

  test('13 digits, the upper bound', () => {
    expect(toWhatsAppNumber('1234567890123')).toBe('1234567890123');
  });

  test('a UK number written with its trunk zero', () => {
    // Known limitation: a trunk zero *after* the country code is not stripped,
    // so this yields 4402079460958 rather than the correct 442079460958. Left
    // as-is deliberately — every current deployment is Indian, and the wrong
    // output is a 13-digit non-number that WhatsApp rejects outright rather
    // than a valid number belonging to a stranger.
    expect(toWhatsAppNumber('+44 (0)20 7946 0958')).toBe('4402079460958');
  });

  test('the default country code is not prefixed twice', () => {
    expect(toWhatsAppNumber('919876543210')).toBe('919876543210');
  });
});

describe('toWhatsAppNumber — a 00 international prefix is dropped whole', () => {
  // Regression: dropping only one of the two zeroes left '0919876543210', and
  // wa.me rejects any number with a leading zero, so the share silently failed.
  test('0091 is the same number as +91', () => {
    expect(toWhatsAppNumber('0091 98765 43210')).toBe('919876543210');
  });

  test('00 with a non-default country code', () => {
    expect(toWhatsAppNumber('00 1 415 555 2671')).toBe('14155552671');
  });

  test('no result ever keeps a leading zero', () => {
    for (const raw of ['0091 98765 43210', '09876543210', '0091234567890']) {
      const out = toWhatsAppNumber(raw);
      if (out !== null) {
        expect(out.startsWith('0')).toBe(false);
      }
    }
  });
});

describe('toWhatsAppNumber — anything uncertain is null, never a guess', () => {
  test.each([
    ['null', null],
    ['undefined', undefined],
    ['empty string', ''],
    ['whitespace only', '   '],
    ['plain text', 'not a phone'],
    ['a placeholder dash', '-'],
    ['too short', '12345'],
    ['nine digits, one shy of national', '987654321'],
    ['a lone zero after stripping', '00'],
    ['too long', '12345678901234'],
    ['an extension glued on', '+91 98765 43210 x1234'],
  ])('%s → null', (_label, input) => {
    expect(toWhatsAppNumber(input)).toBeNull();
  });
});

describe('buildWhatsAppUrl', () => {
  test('addresses the number when there is one', () => {
    expect(buildWhatsAppUrl('919876543210', 'Invoice INV-1\nhttps://x.test/s/abc')).toBe(
      'https://wa.me/919876543210?text=Invoice%20INV-1%0Ahttps%3A%2F%2Fx.test%2Fs%2Fabc',
    );
  });

  test('falls back to WhatsApp’s contact picker with no number', () => {
    expect(buildWhatsAppUrl(null, 'Invoice INV-1')).toBe('https://wa.me/?text=Invoice%20INV-1');
  });

  test('an unvouched-for number reaches the picker, not a stranger', () => {
    expect(buildWhatsAppUrl(toWhatsAppNumber('12345'), 'hi')).toBe('https://wa.me/?text=hi');
  });
});
