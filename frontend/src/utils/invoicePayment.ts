import type { Invoice } from '../types/api';

/**
 * Whether "Record payment" belongs on an invoice: a live sales invoice that
 * still has money owing. Purchase vouchers are bills we pay, not receipts we
 * take, and a cancelled or fully paid invoice has nothing left to collect.
 */
export function canRecordPayment(invoice: Pick<Invoice, 'voucher_type' | 'status' | 'payment_status' | 'outstanding_amount' | 'ledger_id'>): boolean {
  return (
    invoice.voucher_type === 'sales'
    && invoice.status === 'active'
    && invoice.payment_status !== 'paid'
    && Number(invoice.outstanding_amount) > 0
    && Boolean(invoice.ledger_id)
  );
}
