import { describe, expect, it } from 'vitest';
import { buildLedgersCsv, LEDGERS_CSV_HEADERS, ledgerToCsvRow } from './exports';
import type { Ledger } from '../../types/api';

const ledger = (overrides: Partial<Ledger> = {}): Ledger => ({
  id: 1,
  name: 'Acme Traders',
  address: 'Kathmandu',
  gst: '27ABCDE1234F1Z5',
  opening_balance: null,
  balance: 1500,
  phone_number: '9800000001',
  email: 'acme@example.com',
  website: null,
  bank_name: null,
  branch_name: null,
  account_name: null,
  account_number: null,
  ifsc_code: null,
  ...overrides,
});

describe('ledgerToCsvRow', () => {
  it('maps a ledger to the header order', () => {
    expect(ledgerToCsvRow(ledger())).toEqual([
      'Acme Traders',
      '27ABCDE1234F1Z5',
      '9800000001',
      'acme@example.com',
      1500,
    ]);
  });

  it('renders null email and balance as empty cells', () => {
    expect(ledgerToCsvRow(ledger({ email: null, balance: null }))).toEqual([
      'Acme Traders',
      '27ABCDE1234F1Z5',
      '9800000001',
      '',
      '',
    ]);
  });

  it('keeps a negative (credit) balance numeric', () => {
    expect(ledgerToCsvRow(ledger({ balance: -250 }))[4]).toBe(-250);
  });
});

describe('buildLedgersCsv', () => {
  it('renders headers and rows', () => {
    expect(buildLedgersCsv([ledger()])).toBe(
      'Name,GSTIN,Phone,Email,Balance\r\nAcme Traders,27ABCDE1234F1Z5,9800000001,acme@example.com,1500',
    );
  });

  it('renders headers only for an empty list', () => {
    expect(buildLedgersCsv([])).toBe('Name,GSTIN,Phone,Email,Balance');
  });

  it('escapes commas, quotes, and newlines through the shared helper', () => {
    expect(buildLedgersCsv([ledger({ name: 'Acme, Ltd' })])).toContain('"Acme, Ltd"');
    expect(buildLedgersCsv([ledger({ name: 'Say "hi"' })])).toContain('"Say ""hi"""');
    expect(buildLedgersCsv([ledger({ name: 'Line one\nLine two' })])).toContain('"Line one\nLine two"');
  });

  it('exposes the headers the page downloads', () => {
    expect(LEDGERS_CSV_HEADERS).toEqual(['Name', 'GSTIN', 'Phone', 'Email', 'Balance']);
  });
});
