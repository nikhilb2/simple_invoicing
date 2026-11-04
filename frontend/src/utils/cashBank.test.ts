import { expect, test } from 'vitest';
import { buildCashBankEditPayload, openingBalanceAt } from './cashBank';

const account = { id: 3, account_type: 'bank' };
const form = { entryType: 'credit' as const, amount: 500, date: '2026-10-29', description: 'Fixed date' };
const periodStart = new Date('2026-04-01T00:00:00').getTime();

test('opening balance carries earlier receipts and payments into the next financial year', () => {
  expect(openingBalanceAt(10000, [
    { voucher_type: 'receipt', amount: 5000, account_id: 3, date: '2025-06-01T12:00:00' },
    { voucher_type: 'payment', amount: 2000, account_id: 3, date: '2026-03-31T23:59:59' },
  ], 3, periodStart)).toBe(13000);
});

test('entries at or after the start remain period movements and are not counted twice', () => {
  const opening = openingBalanceAt(10000, [
    { voucher_type: 'receipt', amount: 5000, account_id: 3, date: '2025-06-01T12:00:00' },
    { voucher_type: 'receipt', amount: 1000, account_id: 3, date: '2026-04-01T00:00:00' },
    { voucher_type: 'payment', amount: 200, account_id: 3, date: '2026-04-15T12:00:00' },
    { voucher_type: 'receipt', amount: 9000, account_id: 3, date: '2027-01-01T00:00:00' },
  ], 3, periodStart);
  expect(opening).toBe(15000);
  expect(opening + 1000 - 200).toBe(15800);
});

test('opening balance ignores other accounts, unassigned entries and other voucher types', () => {
  expect(openingBalanceAt(10000, [
    { voucher_type: 'receipt', amount: 5000, account_id: 4, date: '2025-06-01' },
    { voucher_type: 'receipt', amount: 1000, account_id: null, date: '2025-06-01' },
    { voucher_type: 'opening_balance', amount: 200, account_id: 3, date: '2025-06-01' },
  ], 3, periodStart)).toBe(10000);
});

test('an account without earlier entries keeps its configured opening balance', () => {
  expect(openingBalanceAt(10000, [], 3, periodStart)).toBe(10000);
});

test('the no-account register matches both null and absent account ids', () => {
  expect(openingBalanceAt(0, [
    { voucher_type: 'receipt', amount: 500, account_id: null, date: '2026-03-01' },
    { voucher_type: 'payment', amount: 100, date: '2026-03-02' },
    { voucher_type: 'receipt', amount: 900, account_id: 3, date: '2026-03-01' },
  ], null, periodStart)).toBe(400);
});

test('a mid-year period carries movements from earlier in the same year', () => {
  expect(openingBalanceAt(10000, [
    { voucher_type: 'receipt', amount: 500, account_id: 3, date: '2026-04-01T00:00:00' },
  ], 3, new Date('2026-07-01T00:00:00').getTime())).toBe(10500);
});

test('opening balance sums decimal amounts in paise', () => {
  expect(openingBalanceAt(0.1, [
    { voucher_type: 'receipt', amount: 0.2, account_id: 3, date: '2026-03-01' },
  ], 3, periodStart)).toBe(0.3);
});

test('invalid entry dates and an incomplete period cannot become earlier movements', () => {
  const payments = [{ voucher_type: 'receipt' as const, amount: 500, account_id: 3, date: 'invalid' }];
  expect(openingBalanceAt(10000, payments, 3, periodStart)).toBe(10000);
  expect(openingBalanceAt(10000, [{ ...payments[0], date: '2026-03-01' }], 3, NaN)).toBe(10000);
});

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
