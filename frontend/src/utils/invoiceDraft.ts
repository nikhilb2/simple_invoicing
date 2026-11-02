/**
 * What the create-invoice modal would throw away if it closed now.
 *
 * The modal compares the form against a snapshot taken once its data has
 * loaded (the first ledger and product are filled in for the user then), so
 * only the user's own edits count. Line ids are left out: adding a line and
 * removing it again leaves nothing to lose.
 */

export type InvoiceDraftItem = {
  id: number;
  productId: string;
  quantity: string;
  unit_price: string;
  description: string;
  discount_type: string;
  discount_value: string;
  serials: string[];
};

export type InvoiceDraft = {
  ledgerId: string;
  voucherType: string;
  taxInclusive: boolean;
  invoiceDate: string;
  dueDateMode: string;
  dueDate: string;
  dueDateDays: string;
  referenceNotes: string;
  items: InvoiceDraftItem[];
};

/** A string that is equal for two drafts exactly when discarding one loses nothing the other has. */
export function invoiceDraftSnapshot(draft: InvoiceDraft): string {
  return JSON.stringify({
    ...draft,
    // JSON.stringify leaves out undefined properties, so this drops the id.
    items: draft.items.map((item) => ({ ...item, id: undefined })),
  });
}
