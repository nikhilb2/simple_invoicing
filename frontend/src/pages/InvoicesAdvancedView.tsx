import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { LayoutGrid, Table as TableIcon, X } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import api, { getApiErrorMessage } from '../api/client';
import type { Invoice } from '../types/api';
import { useFY } from '../context/FYContext';
import InvoicesTable from '../components/InvoicesTable';
import InvoicesCompactCard from '../components/InvoicesCompactCard';
import InvoicesTotalBreakdown from '../components/InvoicesTotalBreakdown';
import InvoicePreview from '../components/InvoicePreview';
import StatusToasts from '../components/StatusToasts';
import type { Product } from '../types/api';
import { useInvoiceFeedViewStore } from '../store/useInvoiceFeedViewStore';
import { useInvoiceModalStore } from '../store/useInvoiceModalStore';
import { useInvoiceCancelStore } from '../store/useInvoiceCancelStore';
import { fetchCompanyProfile, fetchInvoicePage, fetchProducts } from '../features/invoices/api';
import { invoiceQueryKeys } from '../features/invoices/queryKeys';

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
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { requestCancel } = useInvoiceCancelStore();
  const [actionError, setActionError] = useState('');
  const [actionSuccess, setActionSuccess] = useState('');

  const restoreMutation = useMutation({
    mutationFn: (invoiceId: number) => api.post(`/invoices/${invoiceId}/restore`),
    onSuccess: () => {
      setActionSuccess('Invoice restored. Inventory has been re-applied.');
      void queryClient.invalidateQueries({ queryKey: invoiceQueryKeys.all });
    },
    onError: (err) => setActionError(getApiErrorMessage(err, 'Unable to restore invoice')),
  });

  function handleEdit(invoice: Invoice) {
    navigate(`/invoices?edit=${invoice.id}`);
  }

  function handleCreditNote(invoice: Invoice) {
    navigate('/credit-notes', { state: { invoiceId: invoice.id } });
  }

  function handleCancelRequest(invoice: Invoice) {
    requestCancel(invoice.id, invoice.invoice_number);
  }

  function handleRestore(invoice: Invoice) {
    restoreMutation.mutate(invoice.id);
  }

  const [searchParams, setSearchParams] = useSearchParams();

  const {
    viewType,
    invoiceSearch,
    showCancelled,
    allowAllFY,
    page,
    productId,
    setViewType,
    setInvoiceSearch,
    setShowCancelled,
    setAllowAllFY,
    setPage,
    resetPage,
    setProductId,
  } = useInvoiceFeedViewStore();

  // Sync ?product_id from URL into store on mount
  useEffect(() => {
    const urlProductId = searchParams.get('product_id');
    if (urlProductId !== null) {
      const parsed = parseInt(urlProductId, 10);
      if (!isNaN(parsed)) {
        setProductId(parsed);
        setAllowAllFY(true);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const { previewInvoice, openPreview, closePreview } = useInvoiceModalStore();
  const pageSize = 20;
  const shouldUseAllFY = allowAllFY;
  const isFYReady = shouldUseAllFY || Boolean(activeFY);
  const financialYearId = shouldUseAllFY ? undefined : activeFY?.id;

  const invoicesQuery = useQuery({
    queryKey: invoiceQueryKeys.list(page, pageSize, invoiceSearch, showCancelled, financialYearId, productId ?? undefined),
    queryFn: () => fetchInvoicePage({
      page,
      pageSize,
      search: invoiceSearch,
      showCancelled,
      financialYearId,
      productId: productId ?? undefined,
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

  useEffect(() => {
    resetPage();
  }, [invoiceSearch, showCancelled, allowAllFY, activeFY?.id, productId]);

  const invoices = invoicesQuery.data?.items ?? [];
  const totalPages = invoicesQuery.data?.total_pages ?? 1;
  const company = companyQuery.data ?? null;
  const activeCurrencyCode = company?.currency_code || 'INR';
  const products = productsQuery.data ?? [];

  const loading =
    fyLoading ||
    invoicesQuery.isLoading ||
    companyQuery.isLoading ||
    productsQuery.isLoading;

  const error = useMemo(() => {
    if (invoicesQuery.error) return getApiErrorMessage(invoicesQuery.error, 'Unable to load invoices');
    if (companyQuery.error) return getApiErrorMessage(companyQuery.error, 'Unable to load company profile');
    if (productsQuery.error) return getApiErrorMessage(productsQuery.error, 'Unable to load products');
    return '';
  }, [companyQuery.error, invoicesQuery.error, productsQuery.error]);

  const allPagesBreakdown = useMemo(() => {
    const summary = invoicesQuery.data?.summary;
    if (!summary) {
      return calculateBreakdown(invoices);
    }

    return {
      total: summary.total_listed,
      credit: summary.credit_total,
      debit: summary.debit_total,
      cancelled: summary.cancelled_total,
    };
  }, [invoicesQuery.data?.summary, invoices]);
  const currentPageBreakdown = useMemo(() => calculateBreakdown(invoices), [invoices]);

  if (fyLoading || companyQuery.isLoading || productsQuery.isLoading) {
    return <div className="p-8 text-center">Loading...</div>;
  }

  if (!shouldUseAllFY && !activeFY) {
    return (
      <div className="invoice-feed-view stack">
        <section className="panel">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Invoices</p>
              <h1 className="page-title" style={{ margin: 0 }}>Invoice Feed</h1>
            </div>
          </div>
          <div className="empty-state" style={{ gap: 12 }}>
            <p>No active financial year is set for this company.</p>
            <div className="button-row" style={{ justifyContent: 'center' }}>
              <button
                type="button"
                className="button button--primary"
                onClick={() => setAllowAllFY(true)}
              >
                Search all FY
              </button>
              <button
                type="button"
                className="button button--ghost"
                onClick={() => navigate('/company')}
              >
                Open Company Setup
              </button>
            </div>
          </div>
        </section>
      </div>
    );
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

        {/* Product filter badge */}
        {productId !== null && (
          <div className="invoice-feed-view__fy-label" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>
              Filtered by product: <strong>{products.find((p) => p.id === productId)?.name ?? `#${productId}`}</strong>
            </span>
            <button
              type="button"
              className="button button--ghost button--small"
              style={{ padding: '2px 6px', lineHeight: 1 }}
              title="Clear product filter"
              onClick={() => {
                setProductId(null);
                setSearchParams({});
              }}
            >
              <X size={14} />
            </button>
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
        currencyCode={activeCurrencyCode}
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
                  currencyCode={activeCurrencyCode}
                  onPreview={openPreview}
                  onEdit={handleEdit}
                  onCancel={handleCancelRequest}
                  onRestore={handleRestore}
                  onCreditNote={handleCreditNote}
                />
              ))}
          </div>
        ) : (
          <InvoicesTable
            invoices={invoices}
            currencyCode={activeCurrencyCode}
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
        currencyCode={activeCurrencyCode}
        title="Summary of current visible page"
        note="This summary is calculated only from the invoice entries visible on this page."
      />

      {/* Invoice Preview Modal */}
      {previewInvoice && (
        <InvoicePreview
          invoice={previewInvoice}
          onClose={closePreview}
        />
      )}

      <StatusToasts
        success={actionSuccess}
        error={actionError}
        onClearSuccess={() => setActionSuccess('')}
        onClearError={() => setActionError('')}
      />
    </div>
  );
}
