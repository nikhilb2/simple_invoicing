import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import QuotationsTable from './QuotationsTable';
import type { Quotation } from '../types/api';

function quotation(overrides: Partial<Quotation> = {}): Quotation {
  return {
    id: 1,
    document_type: 'quotation',
    quotation_number: 'QT-2026-001',
    status: 'open',
    is_expired: false,
    display_status: 'open',
    quotation_date: '2026-06-01',
    valid_until: '2026-07-01',
    financial_year_id: null,
    ledger_id: 3,
    ledger_name: 'Acme & Sons',
    ledger_address: null,
    ledger_gst: null,
    ledger_phone: null,
    company_name: 'Mofna Traders',
    company_gst: null,
    company_currency_code: 'INR',
    shipping_address: null,
    shipping_address_label: null,
    shipping_address_id: null,
    reference_notes: null,
    tax_inclusive: false,
    apply_round_off: false,
    round_off_amount: 0,
    discount_type: null,
    discount_value: null,
    taxable_amount: 200,
    total_tax_amount: 36,
    cgst_amount: 18,
    sgst_amount: 18,
    igst_amount: 0,
    total_amount: 236,
    status_note: null,
    accepted_at: null,
    declined_at: null,
    converted_at: null,
    cancelled_at: null,
    created_at: '2026-06-01T00:00:00',
    updated_at: '2026-06-01T00:00:00',
    items: [],
    converted_invoice_id: null,
    converted_invoice_number: null,
    invoices: [],
    ...overrides,
  };
}

function render(quotations: Quotation[]) {
  return renderToStaticMarkup(
    <MemoryRouter>
      <QuotationsTable quotations={quotations} onOpen={() => {}} onConvert={() => {}} />
    </MemoryRouter>,
  );
}

describe('QuotationsTable', () => {
  it('shows the columns a shop works from', () => {
    const html = render([quotation()]);
    expect(html).toContain('QT-2026-001');
    expect(html).toContain('Quotation');
    expect(html).toContain('Acme &amp; Sons');
    expect(html).toContain('236');
    expect(html).toContain('Open');
  });

  it('names a proforma in full', () => {
    const html = render([quotation({ document_type: 'proforma', quotation_number: 'PI-2026-001' })]);
    expect(html).toContain('Proforma invoice');
    expect(html).toContain('PI-2026-001');
  });

  it('offers conversion only while the document can convert', () => {
    expect(render([quotation()])).toContain('Convert to invoice');
    expect(render([quotation({ status: 'accepted', display_status: 'accepted' })])).toContain('Convert to invoice');
    expect(render([quotation({ status: 'declined', display_status: 'declined' })])).not.toContain('Convert to invoice');
    expect(render([quotation({ status: 'cancelled', display_status: 'cancelled' })])).not.toContain('Convert to invoice');
    expect(render([quotation({ status: 'converted', display_status: 'converted' })])).not.toContain('Convert to invoice');
  });

  it('still offers conversion on an expired document, and marks the date', () => {
    const html = render([quotation({ is_expired: true, display_status: 'expired' })]);
    expect(html).toContain('Convert to invoice');
    expect(html).toContain('Expired');
    expect(html).toContain('error-text');
  });

  it('says so when there is no expiry', () => {
    expect(render([quotation({ valid_until: null })])).toContain('No expiry');
  });

  it('links to the live invoice', () => {
    const html = render([quotation({
      status: 'converted',
      display_status: 'converted',
      converted_invoice_id: 9,
      converted_invoice_number: 'INV-2026-009',
    })]);
    expect(html).toContain('INV-2026-009');
    expect(html).toContain('/invoices-view?search=INV-2026-009');
  });

  it('has no payment language anywhere', () => {
    const html = render([quotation()]);
    expect(html).not.toMatch(/Paid|Unpaid|Due|Balance/);
  });
});
