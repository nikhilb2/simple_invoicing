import { describe, expect, it } from 'vitest';
import { renderToString } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { lacksInvoiceBankDetails } from './invoiceBankNotice';
import BankDetailsNotice from '../components/BankDetailsNotice';

const acct = (over: Record<string, unknown> = {}) => ({
  account_type: 'bank' as const,
  display_on_invoice: true,
  is_active: true,
  ...over,
});

describe('lacksInvoiceBankDetails', () => {
  it('is true with no accounts', () => {
    expect(lacksInvoiceBankDetails([])).toBe(true);
  });
  it('is true when the bank account is not marked for invoices', () => {
    expect(lacksInvoiceBankDetails([acct({ display_on_invoice: false })])).toBe(true);
  });
  it('is true when the marked account is not a bank account', () => {
    expect(lacksInvoiceBankDetails([acct({ account_type: 'cash' })])).toBe(true);
  });
  it('is true when the marked bank account is inactive', () => {
    expect(lacksInvoiceBankDetails([acct({ is_active: false })])).toBe(true);
  });
  it('is false once an active bank account is marked for invoices', () => {
    expect(lacksInvoiceBankDetails([acct({ display_on_invoice: false }), acct()])).toBe(false);
  });
});

describe('BankDetailsNotice', () => {
  it('links to the bank accounts page', () => {
    const html = renderToString(<MemoryRouter><BankDetailsNotice /></MemoryRouter>);
    expect(html).toContain('Your bank details are not on this invoice');
    expect(html).toContain('href="/cash-bank/accounts"');
    expect(html).toContain('Add a bank account');
  });
});
