import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test, vi } from 'vitest';
import InvoicesCompactCard from './InvoicesCompactCard';
import type { Invoice } from '../types/api';

function invoice(overrides: Partial<Invoice>): Invoice {
  return {
    id: 1,
    invoice_number: 'INV-1',
    voucher_type: 'sales',
    status: 'active',
    payment_status: 'unpaid',
    outstanding_amount: 500,
    total_amount: 500,
    total_tax_amount: 0,
    invoice_date: '2026-11-01',
    due_date: '2026-11-01',
    ledger_id: 7,
    ledger: null,
    items: [],
    ...overrides,
  } as Invoice;
}

function render(inv: Invoice, withHandler = true) {
  return renderToStaticMarkup(
    <InvoicesCompactCard
      invoice={inv}
      currencyCode="INR"
      onPreview={vi.fn()}
      onRecordPayment={withHandler ? vi.fn() : undefined}
    />,
  );
}

describe('InvoicesCompactCard record payment', () => {
  test('shows a labelled Record payment button on unpaid and partly paid sales invoices', () => {
    expect(render(invoice({}))).toContain('Record payment');
    expect(render(invoice({ payment_status: 'partial', outstanding_amount: 100 }))).toContain('Record payment');
  });

  test('names the button after its invoice so a screen reader can tell them apart', () => {
    expect(render(invoice({ invoice_number: 'INV-2026-001' }))).toContain('aria-label="Record payment for invoice INV-2026-001"');
    expect(render(invoice({ id: 9, invoice_number: '' }))).toContain('aria-label="Record payment for invoice #9"');
  });

  test('hides it for paid, cancelled and purchase invoices', () => {
    expect(render(invoice({ payment_status: 'paid', outstanding_amount: 0 }))).not.toContain('Record payment');
    expect(render(invoice({ status: 'cancelled' }))).not.toContain('Record payment');
    expect(render(invoice({ voucher_type: 'purchase' }))).not.toContain('Record payment');
  });

  test('hides it when the page gives no handler', () => {
    expect(render(invoice({}), false)).not.toContain('Record payment');
  });
});
