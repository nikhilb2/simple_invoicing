import type { DueDateMode } from './invoiceDueDate.ts';

const STORAGE_KEY = 'invoice_composer_prefs';

/**
 * The composer settings a user tends to pick the same way on every invoice —
 * "I always enter prices inclusive of GST", "I always round off", "my terms are
 * net 30" — so they are not re-selected for each invoice.
 *
 * Deliberately excluded: anything that is a fact about *one* invoice rather
 * than a habit. A discount value, an exact due date, a supplier reference and a
 * shipping address are all per-invoice, and restoring them onto the next
 * invoice would silently change what a customer is billed.
 */
export type InvoiceComposerPrefs = {
  showAdvanced: boolean;
  taxInclusive: boolean;
  applyRoundOff: boolean;
  dueDateMode: DueDateMode;
  dueDateDays: string;
  invoiceDiscountType: 'percentage' | 'net';
};

export const DEFAULT_INVOICE_COMPOSER_PREFS: InvoiceComposerPrefs = {
  showAdvanced: false,
  taxInclusive: false,
  applyRoundOff: false,
  dueDateMode: 'none',
  dueDateDays: '',
  invoiceDiscountType: 'percentage',
};

function isDueDateMode(value: unknown): value is DueDateMode {
  return value === 'none' || value === 'exact' || value === 'days';
}

/**
 * Stored JSON is untrusted — it can be left over from an older shape of this
 * type, or edited by hand — so every field is checked individually and falls
 * back to its default rather than being trusted wholesale.
 */
export function readInvoiceComposerPrefs(): InvoiceComposerPrefs {
  const defaults = DEFAULT_INVOICE_COMPOSER_PREFS;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaults;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return defaults;
    const stored = parsed as Record<string, unknown>;
    return {
      showAdvanced: typeof stored.showAdvanced === 'boolean' ? stored.showAdvanced : defaults.showAdvanced,
      taxInclusive: typeof stored.taxInclusive === 'boolean' ? stored.taxInclusive : defaults.taxInclusive,
      applyRoundOff: typeof stored.applyRoundOff === 'boolean' ? stored.applyRoundOff : defaults.applyRoundOff,
      dueDateMode: isDueDateMode(stored.dueDateMode) ? stored.dueDateMode : defaults.dueDateMode,
      // A term is a small whole number of days; anything else is not a term.
      dueDateDays:
        typeof stored.dueDateDays === 'string' && /^\d{0,4}$/.test(stored.dueDateDays)
          ? stored.dueDateDays
          : defaults.dueDateDays,
      invoiceDiscountType: stored.invoiceDiscountType === 'net' ? 'net' : defaults.invoiceDiscountType,
    };
  } catch {
    // Malformed JSON, or localStorage unavailable in a privacy mode.
    return defaults;
  }
}

/**
 * Called from the change handlers rather than from an effect on the values:
 * loading an invoice for editing — or duplicating one — sets the same state
 * programmatically, and that is the source invoice's setting, not the user's
 * standing preference.
 */
export function updateInvoiceComposerPrefs(patch: Partial<InvoiceComposerPrefs>): void {
  try {
    const next = { ...readInvoiceComposerPrefs(), ...patch };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Storage disabled — the in-memory selection still works for this session.
  }
}
