import type { PaymentUpdate } from '../types/api';

export type CashBankEditingEntry = {
  id: number;
  voucher_type: 'receipt' | 'payment';
  amount: number;
  date: string;
  notes: string;
  ledger_id: number | null;
  reference: string | null;
  mode: string | null;
};

export type CashBankEntryForm = {
  entryType: 'debit' | 'credit';
  amount: number;
  date: string;
  description: string;
};

/**
 * Payload for saving an edit from the Cash & Bank register. It deliberately
 * never carries invoice_allocations: omitting that field tells the backend
 * to leave the payment's existing allocations alone, while sending an empty
 * list would delete them. The original reference is sent back so an edit
 * does not clear it, and a ledger linked payment keeps its original mode;
 * only an account only entry (ledger_id == null) takes the account type as
 * its mode, as before.
 */
export function buildCashBankEditPayload(
  editingEntry: CashBankEditingEntry,
  selectedAccount: { id: number; account_type: string },
  entryForm: CashBankEntryForm,
): PaymentUpdate {
  const voucherType = entryForm.entryType === 'debit' ? 'payment' : 'receipt';
  return {
    voucher_type: voucherType,
    amount: entryForm.amount,
    account_id: selectedAccount.id,
    date: `${entryForm.date}T00:00:00`,
    mode:
      editingEntry.ledger_id != null
        ? (editingEntry.mode ?? undefined)
        : selectedAccount.account_type,
    reference: editingEntry.reference ?? undefined,
    notes: entryForm.description.trim() || undefined,
  };
}
