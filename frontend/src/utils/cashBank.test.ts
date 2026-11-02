import { expect, test } from 'vitest';
import { buildCashBankEditPayload } from './cashBank';

const account = { id: 3, account_type: 'bank' };
const form = { entryType: 'credit' as const, amount: 500, date: '2026-10-29', description: 'Fixed date' };

test('ledger linked edit keeps the original mode and reference and omits invoice allocations', () => {
  const payload = buildCashBankEditPayload(
    {
      id: 12,
      voucher_type: 'receipt',
      amount: 500,
      date: '2026-10-28',
      notes: '',
      ledger_id: 7,
      reference: 'REF-42',
      mode: 'upi',
    },
    account,
    form,
  );

  expect(payload.mode).toBe('upi');
  expect(payload.reference).toBe('REF-42');
  expect(payload).not.toHaveProperty('invoice_allocations');
});

test('account only edit keeps the account type as its mode', () => {
  const payload = buildCashBankEditPayload(
    {
      id: 13,
      voucher_type: 'receipt',
      amount: 500,
      date: '2026-10-28',
      notes: '',
      ledger_id: null,
      reference: null,
      mode: null,
    },
    account,
    form,
  );

  expect(payload.mode).toBe('bank');
  expect(payload.reference).toBeUndefined();
  expect(payload).not.toHaveProperty('invoice_allocations');
});
