import type { CompanyAccount } from '../types/api';

/**
 * True when no active bank account is marked to print on invoices, so the PDF
 * carries no payment details. Mirrors the backend's invoice_bank_accounts
 * (active, bank, display_on_invoice); the list endpoint already drops inactive
 * accounts, but is_active is checked here too.
 */
export function lacksInvoiceBankDetails(
  accounts: Pick<CompanyAccount, 'account_type' | 'display_on_invoice' | 'is_active'>[],
): boolean {
  return !accounts.some(
    (account) => account.account_type === 'bank' && account.display_on_invoice && account.is_active !== false,
  );
}
