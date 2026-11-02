import { beforeEach, describe, expect, it } from 'vitest';
import {
  DEFAULT_INVOICE_COMPOSER_PREFS,
  readInvoiceComposerPrefs,
  updateInvoiceComposerPrefs,
} from './invoiceComposerPrefs.ts';

const KEY = 'invoice_composer_prefs';

/* These tests run in vitest's default node environment — the project installs
   no DOM implementation — so storage is stubbed in memory. Only the four
   members this module touches are implemented. */
function installMemoryStorage() {
  let store: Record<string, string> = {};
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => (key in store ? store[key] : null),
      setItem: (key: string, value: string) => { store[key] = String(value); },
      removeItem: (key: string) => { delete store[key]; },
      clear: () => { store = {}; },
    },
  });
}

installMemoryStorage();

describe('invoice composer preferences', () => {
  beforeEach(() => localStorage.clear());

  it('falls back to defaults when nothing is stored', () => {
    expect(readInvoiceComposerPrefs()).toEqual(DEFAULT_INVOICE_COMPOSER_PREFS);
  });

  it('round-trips a selection', () => {
    updateInvoiceComposerPrefs({ taxInclusive: true, dueDateMode: 'days', dueDateDays: '30' });
    const prefs = readInvoiceComposerPrefs();
    expect(prefs.taxInclusive).toBe(true);
    expect(prefs.dueDateMode).toBe('days');
    expect(prefs.dueDateDays).toBe('30');
  });

  it('merges a patch instead of replacing the whole record', () => {
    updateInvoiceComposerPrefs({ taxInclusive: true });
    updateInvoiceComposerPrefs({ applyRoundOff: true });
    const prefs = readInvoiceComposerPrefs();
    expect(prefs.taxInclusive).toBe(true);
    expect(prefs.applyRoundOff).toBe(true);
  });

  it('ignores malformed JSON', () => {
    localStorage.setItem(KEY, '{not json');
    expect(readInvoiceComposerPrefs()).toEqual(DEFAULT_INVOICE_COMPOSER_PREFS);
  });

  it('ignores a stored value that is not an object', () => {
    localStorage.setItem(KEY, '"just a string"');
    expect(readInvoiceComposerPrefs()).toEqual(DEFAULT_INVOICE_COMPOSER_PREFS);
    localStorage.setItem(KEY, 'null');
    expect(readInvoiceComposerPrefs()).toEqual(DEFAULT_INVOICE_COMPOSER_PREFS);
  });

  it('rejects field values of the wrong type or an unknown due-date mode', () => {
    localStorage.setItem(
      KEY,
      JSON.stringify({
        showAdvanced: 'yes',
        taxInclusive: 1,
        applyRoundOff: null,
        dueDateMode: 'whenever',
        dueDateDays: 'thirty',
        invoiceDiscountType: 'barter',
      }),
    );
    expect(readInvoiceComposerPrefs()).toEqual(DEFAULT_INVOICE_COMPOSER_PREFS);
  });

  it('keeps the good fields of a partially bad record', () => {
    localStorage.setItem(KEY, JSON.stringify({ taxInclusive: true, dueDateMode: 'whenever' }));
    const prefs = readInvoiceComposerPrefs();
    expect(prefs.taxInclusive).toBe(true);
    expect(prefs.dueDateMode).toBe('none');
  });

  it('never carries a per-invoice discount value across', () => {
    updateInvoiceComposerPrefs({ invoiceDiscountType: 'net' });
    const raw = localStorage.getItem(KEY) ?? '';
    expect(raw).not.toContain('invoiceDiscountValue');
    expect(Object.keys(readInvoiceComposerPrefs())).not.toContain('invoiceDiscountValue');
  });
});
