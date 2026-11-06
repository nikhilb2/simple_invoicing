import { describe, expect, test } from 'vitest';
import { backdatedNoteWarning, creditNoteDateChoice, shownCreditNoteDate } from './creditNoteDate';

describe('creditNoteDateChoice', () => {
  test('a date the user left alone or picked back to today is no choice, so none is sent', () => {
    expect(creditNoteDateChoice('2026-11-03', '2026-11-03')).toBeNull();
  });

  test('any other date is kept', () => {
    expect(creditNoteDateChoice('2026-10-15', '2026-11-03')).toBe('2026-10-15');
  });

});

describe('shownCreditNoteDate', () => {
  test('a date left alone follows the clock when the tab regains focus', () => {
    const choice = creditNoteDateChoice('2026-11-03', '2026-11-03');
    expect(shownCreditNoteDate(choice, '2026-11-03')).toBe('2026-11-03');
    expect(shownCreditNoteDate(choice, '2026-11-04')).toBe('2026-11-04');
  });

  test('a date the user picked stays put', () => {
    expect(shownCreditNoteDate('2026-10-15', '2026-11-04')).toBe('2026-10-15');
  });
});

describe('backdatedNoteWarning', () => {
  test('a date in this month has no warning', () => {
    expect(backdatedNoteWarning('2026-11-01', '2026-11-03')).toBeNull();
    expect(backdatedNoteWarning('2026-11-03', '2026-11-03')).toBeNull();
  });

  test('a date in an earlier month names the return it changes', () => {
    const warning = backdatedNoteWarning('2026-10-31', '2026-11-03');
    expect(warning).toContain('October 2026');
    expect(warning).toContain('no later return will carry it');
  });

  test('an earlier year counts, and an empty date has nothing to warn about', () => {
    expect(backdatedNoteWarning('2025-12-31', '2026-01-01')).toContain('December 2025');
    expect(backdatedNoteWarning('', '2026-11-03')).toBeNull();
  });
});
