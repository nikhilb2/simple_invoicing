import type { Gstr3bWarningDocument } from './types';

/** Where a warning sends you to fix the document it names. */
export function documentLink(document: Gstr3bWarningDocument): string {
  return document.kind === 'credit_note'
    ? `/credit-notes?cn_id=${document.id}`
    : `/invoices-view?invoice_id=${document.id}`;
}
