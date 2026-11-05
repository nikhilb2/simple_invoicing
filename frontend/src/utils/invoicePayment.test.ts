import { describe, expect, test } from 'vitest';
import { canRecordPayment } from './invoicePayment';

const base = {
  voucher_type: 'sales' as const,
  status: 'active' as const,
  payment_status: 'unpaid' as const,
  outstanding_amount: 500,
  ledger_id: 7,
};

describe('canRecordPayment', () => {
  test('offered on unpaid and partly paid sales invoices', () => {
    expect(canRecordPayment(base)).toBe(true);
    expect(canRecordPayment({ ...base, payment_status: 'partial', outstanding_amount: 120 })).toBe(true);
  });

  test('hidden when fully paid or nothing is owed', () => {
    expect(canRecordPayment({ ...base, payment_status: 'paid', outstanding_amount: 0 })).toBe(false);
    expect(canRecordPayment({ ...base, outstanding_amount: 0 })).toBe(false);
  });

  test('hidden for cancelled invoices and purchase vouchers', () => {
    expect(canRecordPayment({ ...base, status: 'cancelled' })).toBe(false);
    expect(canRecordPayment({ ...base, voucher_type: 'purchase' })).toBe(false);
  });
});
