import { beforeEach, describe, expect, it } from 'vitest';
import { useInvoiceFeedViewStore } from './useInvoiceFeedViewStore';
import { textParam } from '../utils/deepLink';

/**
 * The regression these cover: a user followed InvoicesPageView's "Open invoice"
 * link to /invoices-view?search=INV-2026-27-160 and saw the wrong rows. The
 * param was never read, so the feed kept the filters it happened to be holding
 * — this store is a module singleton, so an in-app navigation carries the
 * previous visit's search straight through.
 */

const initial = useInvoiceFeedViewStore.getState();

/** What InvoicesAdvancedView's mount effect does, minus React. */
function landOn(url: string) {
  const search = textParam(new URLSearchParams(new URL(url, 'https://x').search), 'search');
  if (search !== null) {
    useInvoiceFeedViewStore.getState().applySearchDeepLink(search);
  }
}

beforeEach(() => {
  useInvoiceFeedViewStore.setState(initial, true);
});

describe('?search= deep link', () => {
  it('overrides a stale search left over from the previous visit', () => {
    useInvoiceFeedViewStore.getState().setInvoiceSearch('some other party');
    useInvoiceFeedViewStore.getState().setPage(4);

    landOn('/invoices-view?search=INV-2026-27-160');

    expect(useInvoiceFeedViewStore.getState().invoiceSearch).toBe('INV-2026-27-160');
    // Paging is per result set; keeping page 4 would land the deep link on an
    // empty page of its own results.
    expect(useInvoiceFeedViewStore.getState().page).toBe(1);
  });

  it('widens FY and cancelled so the named document is actually reachable', () => {
    expect(useInvoiceFeedViewStore.getState().allowAllFY).toBe(false);
    expect(useInvoiceFeedViewStore.getState().showCancelled).toBe(false);

    landOn('/invoices-view?search=INV-2026-27-160');

    expect(useInvoiceFeedViewStore.getState().allowAllFY).toBe(true);
    expect(useInvoiceFeedViewStore.getState().showCancelled).toBe(true);
  });

  it('carries an encoded label through unchanged', () => {
    landOn(`/invoices-view?search=${encodeURIComponent('Acme Traders & Co')}`);
    expect(useInvoiceFeedViewStore.getState().invoiceSearch).toBe('Acme Traders & Co');
  });

  it('leaves the feed alone when the param is absent or blank', () => {
    useInvoiceFeedViewStore.getState().setInvoiceSearch('kept');

    landOn('/invoices-view?product_id=7');
    landOn('/invoices-view?search=');
    landOn('/invoices-view?search=%20');

    expect(useInvoiceFeedViewStore.getState().invoiceSearch).toBe('kept');
    // No term, no reason to change the scope of the feed either.
    expect(useInvoiceFeedViewStore.getState().allowAllFY).toBe(false);
    expect(useInvoiceFeedViewStore.getState().showCancelled).toBe(false);
  });

  it('does not stop the user typing over it afterwards', () => {
    landOn('/invoices-view?search=INV-2026-27-160');
    useInvoiceFeedViewStore.getState().setInvoiceSearch('INV-2026-27-161');
    expect(useInvoiceFeedViewStore.getState().invoiceSearch).toBe('INV-2026-27-161');
  });
});

describe('resetFilters', () => {
  it('clears the widening a deep link applied, so the Filters badge tells the truth', () => {
    landOn('/invoices-view?search=INV-2026-27-160');
    useInvoiceFeedViewStore.getState().setVoucherType('sales');
    useInvoiceFeedViewStore.getState().setDateRange('2026-04-01', '2026-06-30');

    useInvoiceFeedViewStore.getState().resetFilters();

    const state = useInvoiceFeedViewStore.getState();
    expect(state.invoiceSearch).toBe('');
    expect(state.allowAllFY).toBe(false);
    expect(state.showCancelled).toBe(false);
    expect(state.searchDescription).toBe(false);
    expect(state.voucherType).toBe('all');
    expect(state.dateFrom).toBe('');
    expect(state.dateTo).toBe('');
    expect(state.productId).toBeNull();
    expect(state.page).toBe(1);
  });

  it('keeps the view type, which is a preference rather than a filter', () => {
    useInvoiceFeedViewStore.getState().setViewType('table');
    useInvoiceFeedViewStore.getState().resetFilters();
    expect(useInvoiceFeedViewStore.getState().viewType).toBe('table');
  });
});
