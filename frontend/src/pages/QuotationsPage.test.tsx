import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import QuotationsPage from './QuotationsPage';
import { quotationQueryKeys } from '../features/quotations/queryKeys';
import type { PaginatedQuotations } from '../types/api';

function render(initialEntry = '/quotations', data?: PaginatedQuotations) {
  const client = new QueryClient();
  if (data) {
    const params = new URLSearchParams(initialEntry.split('?')[1] ?? '');
    const status = params.get('status') ?? undefined;
    client.setQueryData(
      quotationQueryKeys.list({
        page: 1,
        pageSize: 20,
        search: '',
        status: status as never,
        documentType: undefined,
      }),
      data,
    );
  }
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <QuotationsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const empty: PaginatedQuotations = {
  items: [],
  total: 0,
  page: 1,
  page_size: 20,
  total_pages: 1,
  status_counts: {},
};

describe('QuotationsPage', () => {
  it('starts both documents from the composer', () => {
    const html = render();
    expect(html).toContain('href="/invoices?new=quotation"');
    expect(html).toContain('href="/invoices?new=proforma"');
  });

  it('says plainly that nothing here touches the books', () => {
    const html = render();
    expect(html).toContain('nothing here affects stock, ledgers, reports or returns');
  });

  it('offers a chip for every status, including the derived one', () => {
    const html = render();
    for (const label of ['All', 'Open', 'Accepted', 'Expired', 'Converted', 'Declined', 'Cancelled']) {
      expect(html).toContain(`>${label}<`);
    }
  });

  it('shows a loading state before the first response', () => {
    expect(render()).toContain('Loading quotations');
  });

  it('explains what a quotation is when there are none', () => {
    const html = render('/quotations', empty);
    expect(html).toContain('No quotations yet');
    expect(html).toContain('moves no stock');
  });

  it('counts on the chips', () => {
    const html = render('/quotations', { ...empty, status_counts: { open: 4, expired: 2 } });
    expect(html).toContain('Open (4)');
    expect(html).toContain('Expired (2)');
  });

  it('has a different message when a filter comes up empty', () => {
    const html = render('/quotations?status=expired', empty);
    expect(html).toContain('Nothing matches these filters');
    expect(html).toContain('aria-pressed="true"');
  });

  it('never offers anything to do with payment', () => {
    expect(render('/quotations', empty)).not.toMatch(/Paid|Unpaid|Record payment|Pay by/);
  });
});
