import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Gstr3bWorksheetPage, { Gstr3bWorksheetView } from './Gstr3bWorksheetPage';
import { documentLink } from '../features/gstr3b/links';
import type { Gstr3bRow, Gstr3bWorksheet } from '../features/gstr3b/types';

function notTracked(key: string, table: string, label: string): Gstr3bRow {
  return {
    key,
    table,
    label,
    source: 'not_tracked',
    note: null,
    taxable_value: null,
    igst: null,
    cgst: null,
    sgst: null,
    components: [],
  };
}

const worksheet: Gstr3bWorksheet = {
  title: 'GSTR-3B worksheet',
  headline: 'Worksheet, not a return',
  disclaimer: 'An estimate.',
  from_date: '2026-06-01',
  to_date: '2026-06-30',
  period_type: 'month',
  period_label: 'June 2026',
  warnings: [
    {
      code: 'unregistered_buyer',
      severity: 'warning',
      title: 'Sales to unregistered buyers who may be inter-state',
      message: 'Place of supply is not recorded.',
      documents: [{ kind: 'invoice', id: 7, number: 'INV/26 #7', detail: null }],
    },
    {
      code: 'note_exceeds_source',
      severity: 'warning',
      title: 'Credit notes larger than the invoice line they reverse',
      message: 'Check these notes.',
      documents: [{ kind: 'credit_note', id: 12, number: 'CN-12', detail: 'Over by a bit' }],
    },
    {
      code: 'company_gstin',
      severity: 'warning',
      title: 'Your company GSTIN needs attention',
      message: 'Fix it in company settings.',
      documents: [],
    },
  ],
  known_limits: ['Every purchase counts as eligible input credit.'],
  sections: [
    {
      key: '3.1',
      title: '3.1 Outward supplies',
      note: null,
      rows: [
        {
          key: '3.1a',
          table: '3.1(a)',
          label: 'Outward taxable supplies',
          source: 'from_books',
          note: 'Sales lines above 0%.',
          taxable_value: 1000,
          igst: 0,
          cgst: 90,
          sgst: 90,
          components: [
            { label: 'Sales invoices', taxable_value: 1100, igst: 0, cgst: 99, sgst: 99 },
            { label: 'Less: credit notes issued', taxable_value: 100, igst: 0, cgst: 9, sgst: 9 },
          ],
        },
        notTracked('3.1b', '3.1(b)', 'Outward taxable supplies (zero rated)'),
      ],
    },
    { key: '3.2', title: '3.2 Inter-state supplies', note: 'Stays empty until place of supply is recorded.', rows: [notTracked('3.2-uin', '3.2', 'UIN holders')] },
    {
      key: '4',
      title: '4 Eligible input tax credit',
      note: null,
      rows: [
        {
          key: '4a5',
          table: '4(A)(5)',
          label: 'All other ITC',
          source: 'from_books',
          note: null,
          taxable_value: null,
          igst: 45,
          cgst: 0,
          sgst: 0,
          components: [],
        },
      ],
    },
    { key: '5', title: '5 Exempt inward supplies', note: 'Table 5.1 comes from the GST portal.', rows: [notTracked('5-nongst', '5', 'Non-GST supplies')] },
  ],
  setoff: {
    source: 'from_books',
    note: 'Estimated from the rows above.',
    lines: [
      { head: 'igst', output_tax: 0, input_credit: 45, credit_used: 0, payable: 0, credit_carried_forward: 0 },
      { head: 'cgst', output_tax: 90, input_credit: 0, credit_used: 45, payable: 45, credit_carried_forward: 0 },
      { head: 'sgst', output_tax: 90, input_credit: 0, credit_used: 0, payable: 90, credit_carried_forward: 0 },
    ],
    total_payable: 135,
    total_credit_carried_forward: 0,
    rows: [notTracked('6.1-rcm', '6.1', 'Tax on reverse charge')],
  },
  table_5_1_note: 'Table 5.1 comes from the GST portal.',
};

function renderView(sheet: Gstr3bWorksheet = worksheet) {
  return renderToStaticMarkup(
    <MemoryRouter>
      <Gstr3bWorksheetView worksheet={sheet} />
    </MemoryRouter>,
  );
}

function renderPage() {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Gstr3bWorksheetPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Gstr3bWorksheetPage', () => {
  it('says what it is before any figures have loaded', () => {
    const html = renderPage();
    expect(html).toContain('Worksheet, not a return.');
    expect(html).toContain('estimate from your own books');
    expect(html).toContain('cross-checking');
    expect(html).toContain('not a filing');
    expect(html).toContain('auto-populated on the GST portal take precedence');
  });

  it('offers CSV and PDF and no JSON export', () => {
    const html = renderPage();
    expect(html).toContain('Export CSV');
    expect(html).toContain('Export PDF');
    expect(html).not.toContain('JSON');
  });

  it('holds the exports back until there is a worksheet to export', () => {
    expect(renderPage()).toMatch(/<button[^>]*disabled[^>]*>Export CSV/);
  });
});

describe('Gstr3bWorksheetView', () => {
  it('lays the tables out in the order of the return, with warnings first', () => {
    const html = renderView();
    const order = ['Why this may not match the portal', 'data-section="3.1"', 'data-section="3.2"', 'data-section="4"', 'data-section="5"', 'data-section="6.1"'];
    const positions = order.map((marker) => html.indexOf(marker));
    expect(positions.every((position) => position >= 0)).toBe(true);
    expect([...positions].sort((a, b) => a - b)).toEqual(positions);
  });

  it('shows a source on every row', () => {
    const html = renderView();
    expect(html).toContain('worksheet-source--from_books');
    expect(html).toContain('worksheet-source--not_tracked');
    expect(html).toContain('From books');
    expect(html).toContain('Not tracked');
  });

  it('shows figures for a tracked row and none for an untracked one', () => {
    const html = renderView();
    const tracked = html.slice(html.indexOf('data-row="3.1a"'), html.indexOf('Sales invoices'));
    expect(tracked).toContain('1,000.00');
    const untracked = html.slice(html.indexOf('data-row="3.1b"'), html.indexOf('data-section="3.2"'));
    expect(untracked).toContain('Not tracked');
    expect(untracked).not.toContain('0.00');
  });

  it('shows what a net figure is the net of', () => {
    const html = renderView();
    expect(html).toContain('Sales invoices');
    expect(html).toContain('Less: credit notes issued');
  });

  it('links a warning to its invoice the way GSTR-1 does', () => {
    expect(renderView()).toContain('href="/invoices-view?invoice_id=7"');
  });

  it('links a warning about a credit note to that note', () => {
    expect(renderView()).toContain('href="/credit-notes?cn_id=12"');
  });

  it('shows a warning that names no document without a document list', () => {
    const html = renderView();
    const start = html.indexOf('Your company GSTIN needs attention');
    expect(start).toBeGreaterThan(-1);
    expect(html.slice(start, html.indexOf('Known limits'))).not.toContain('<details');
  });

  it('states the known limits even when no document raised a warning', () => {
    const html = renderView({ ...worksheet, warnings: [] });
    expect(html).toContain('Nothing in this period');
    expect(html).toContain('Every purchase counts as eligible input credit.');
  });

  it('caps a very long document list and says where the rest are', () => {
    const documents = Array.from({ length: 60 }, (_, index) => ({
      kind: 'invoice' as const,
      id: index,
      number: `INV-${index}`,
      detail: null,
    }));
    const html = renderView({
      ...worksheet,
      warnings: [{ code: 'unregistered_buyer', severity: 'warning', title: 'Many', message: 'Many.', documents }],
    });
    expect(html).toContain('INV-49');
    expect(html).not.toContain('INV-50<');
    expect(html).toContain('And 10 more. The CSV export lists every one.');
  });

  it('keeps table 5.1 as a note about the portal', () => {
    expect(renderView()).toContain('Table 5.1 comes from the GST portal.');
  });

  it('explains why table 3.2 is empty', () => {
    expect(renderView()).toContain('Stays empty until place of supply is recorded.');
  });

  it('shows the estimated cash payable from the set-off', () => {
    const html = renderView();
    const start = html.indexOf('data-section="6.1"');
    expect(html.slice(start)).toContain('135.00');
    expect(html.slice(start)).toContain('Payable in cash');
  });
});

describe('documentLink', () => {
  it('opens an invoice by id, which the invoices page fetches even if cancelled or in another year', () => {
    expect(documentLink({ kind: 'invoice', id: 1, number: 'A&B', detail: null })).toBe('/invoices-view?invoice_id=1');
  });
});
