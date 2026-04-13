import { useEffect, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { LayoutGrid, Table as TableIcon } from 'lucide-react';
import { getApiErrorMessage } from '../api/client';
import type { Invoice } from '../types/api';
import { useFY } from '../context/FYContext';
import InvoicesTable from '../components/InvoicesTable';
import InvoicesCompactCard from '../components/InvoicesCompactCard';
import InvoicesTotalBreakdown from '../components/InvoicesTotalBreakdown';
import InvoicePreview from '../components/InvoicePreview';
import type { Product } from '../types/api';
import { useInvoiceFeedViewStore } from '../store/useInvoiceFeedViewStore';
import { useInvoiceModalStore } from '../store/useInvoiceModalStore';
import { fetchCompanyProfile, fetchInvoicePage, fetchInvoiceSummaryPages, fetchProducts } from '../features/invoices/api';
import { invoiceQueryKeys } from '../features/invoices/queryKeys';

type ViewType = 'card' | 'table';

type Breakdown = {
  credit: number;
  debit: number;
  cancelled: number;
  total: number;
};

function calculateBreakdown(rows: Invoice[]): Breakdown {
  return {
    credit: rows
      .filter((inv) => inv.voucher_type === 'purchase' && inv.status === 'active' && inv.ledger)
      .reduce((sum, inv) => sum + inv.total_amount, 0),
    debit: rows
      .filter((inv) => inv.voucher_type === 'sales' && inv.status === 'active' && inv.ledger)
      .reduce((sum, inv) => sum + inv.total_amount, 0),
    cancelled: rows
      .filter((inv) => inv.status === 'cancelled' && inv.ledger)
      .reduce((sum, inv) => sum + inv.total_amount, 0),
    total: rows
      .filter((inv) => inv.status === 'active' || inv.status === 'cancelled')
      .reduce((sum, inv) => sum + inv.total_amount, 0),
  };
}

export default function InvoicesAdvancedView() {
  const { activeFY, loading: fyLoading } = useFY();
  const {
    viewType,
    invoiceSearch,
    showCancelled,
    allowAllFY,
    page,
    setViewType,
    setInvoiceSearch,
    setShowCancelled,
    setAllowAllFY,
    setPage,
    resetPage,
  } = useInvoiceFeedViewStore();
  const { previewInvoice, openPreview, closePreview } = useInvoiceModalStore();
  const pageSize = 20;
  const shouldUseAllFY = allowAllFY;
  const isFYReady = shouldUseAllFY || Boolean(activeFY);
  const financialYearId = shouldUseAllFY ? undefined : activeFY?.id;

  const invoicesQuery = useQuery({
    queryKey: invoiceQueryKeys.list(page, pageSize, invoiceSearch, showCancelled, financialYearId),
    queryFn: () => fetchInvoicePage({
      page,
      pageSize,
      search: invoiceSearch,
      showCancelled,
      financialYearId,
    }),
    enabled: isFYReady && !fyLoading,
  });

  const companyQuery = useQuery({
    queryKey: invoiceQueryKeys.company,
    queryFn: fetchCompanyProfile,
  });

  const productsQuery = useQuery<Product[]>({
    queryKey: invoiceQueryKeys.products,
    queryFn: fetchProducts,
  });

  const summaryRowsQuery = useQuery({
    queryKey: invoiceQueryKeys.summary(
      page,
      pageSize,
      invoiceSearch,
      showCancelled,
      financialYearId,
      invoicesQuery.data?.total_pages,
    ),
    queryFn: async () => {
      const pageData = invoicesQuery.data;
      if (!pageData) {
        return [] as Invoice[];
      }

      return fetchInvoiceSummaryPages(
        {
          pageSize,
          search: invoiceSearch,
          showCancelled,
          financialYearId,
        },
        pageData.total_pages,
        page,
        pageData.items,
      );
    },
    enabled: isFYReady && !fyLoading && Boolean(invoicesQuery.data),
  });

  useEffect(() => {
    resetPage();
  }, [invoiceSearch, showCancelled, allowAllFY, activeFY?.id]);

  const invoices = invoicesQuery.data?.items ?? [];
  const totalPages = invoicesQuery.data?.total_pages ?? 1;
  const company = companyQuery.data ?? null;
  const products = productsQuery.data ?? [];

  const loading =
    fyLoading ||
    invoicesQuery.isLoading ||
    companyQuery.isLoading ||
    productsQuery.isLoading ||
    summaryRowsQuery.isLoading;

  const error = useMemo(() => {
    if (invoicesQuery.error) return getApiErrorMessage(invoicesQuery.error, 'Unable to load invoices');
    if (companyQuery.error) return getApiErrorMessage(companyQuery.error, 'Unable to load company profile');
    if (productsQuery.error) return getApiErrorMessage(productsQuery.error, 'Unable to load products');
    if (summaryRowsQuery.error) return getApiErrorMessage(summaryRowsQuery.error, 'Unable to load invoice summary');
    return '';
  }, [companyQuery.error, invoicesQuery.error, productsQuery.error, summaryRowsQuery.error]);

  const allPagesBreakdown = useMemo(
    () => calculateBreakdown(summaryRowsQuery.data ?? invoices),
    [summaryRowsQuery.data, invoices],
  );
  const currentPageBreakdown = useMemo(() => calculateBreakdown(invoices), [invoices]);

  if (fyLoading || (!shouldUseAllFY && !activeFY) || !company) {
    return <div className="p-8 text-center">Loading...</div>;
  }

  return (
    <div className="invoice-feed-view stack">
      <section className="panel invoice-feed-view__header">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Invoices</p>
            <h1 className="page-title" style={{ margin: 0 }}>Invoice Feed</h1>
          </div>
        </div>

        <div className="invoice-feed-view__controls">
          {/* View Toggle */}
          <div className="button-row">
            <button
              type="button"
              onClick={() => setViewType('card')}
              className={`button button--small ${
                viewType === 'card'
                  ? 'button--primary'
                  : 'button--ghost'
              }`}
            >
              <LayoutGrid size={18} />
              Card
            </button>
            <button
              type="button"
              onClick={() => setViewType('table')}
              className={`button button--small ${
                viewType === 'table'
                  ? 'button--primary'
                  : 'button--ghost'
              }`}
            >
              <TableIcon size={18} />
              Table
            </button>
          </div>

          {/* FY Filter Toggle */}
          <label className="invoice-feed-view__checkbox">
            <input
              type="checkbox"
              checked={allowAllFY}
              onChange={(e) => setAllowAllFY(e.target.checked)}
            />
            <span>Search all FY</span>
          </label>

          {/* Search */}
          <input
            type="text"
            placeholder="Search invoices..."
            value={invoiceSearch}
            onChange={(e) => setInvoiceSearch(e.target.value)}
            className="input invoice-feed-view__search"
          />

          {/* Cancelled toggle */}
          <label className="invoice-feed-view__checkbox">
            <input
              type="checkbox"
              checked={showCancelled}
              onChange={(e) => setShowCancelled(e.target.checked)}
            />
            <span>Show cancelled</span>
          </label>
        </div>

        {/* Current FY Info */}
        {!allowAllFY && (
          <div className="invoice-feed-view__fy-label">
            Showing invoices from: <strong>{activeFY?.label}</strong>
          </div>
        )}
      </section>

      {/* Error Message */}
      {error && (
        <div className="invoice-feed-view__error">
          {error}
        </div>
      )}

      <InvoicesTotalBreakdown
        breakdown={allPagesBreakdown}
        title="Summary of all pages"
        note="This summary includes all invoice entries matching your current filters across every page."
      />

      {/* Content Area */}
      <section className="panel invoice-feed-view__content">
        {loading ? (
          <div className="empty-state">Loading invoices...</div>
        ) : invoices.length === 0 ? (
          <div className="empty-state">No invoices found</div>
        ) : viewType === 'card' ? (
          <div className="invoice-feed-view__card-list">
              {invoices.map((invoice) => (
                <InvoicesCompactCard
                  key={invoice.id}
                  invoice={invoice}
                  onPreview={openPreview}
                />
              ))}
          </div>
        ) : (
          <InvoicesTable
            invoices={invoices}
            onRowClick={openPreview}
          />
        )}
      </section>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="invoice-feed-view__pagination button-row">
          <button
            type="button"
            onClick={() => setPage(Math.max(1, page - 1))}
            disabled={page === 1}
            className="button button--ghost button--small"
          >
            Previous
          </button>
          <span className="invoice-feed-view__page-label">
            Page {page} of {totalPages}
          </span>
          <button
            type="button"
            onClick={() => setPage(Math.min(totalPages, page + 1))}
            disabled={page === totalPages}
            className="button button--ghost button--small"
          >
            Next
          </button>
        </div>
      )}

      <InvoicesTotalBreakdown
        breakdown={currentPageBreakdown}
        title="Summary of current visible page"
        note="This summary is calculated only from the invoice entries visible on this page."
      />

      {/* Invoice Preview Modal */}
      {previewInvoice && (
        <InvoicePreview
          invoice={previewInvoice}
           products={products}
           currencyCode={company?.currency_code ?? ''}
          onClose={closePreview}
        />
      )}
    </div>
  );
}
