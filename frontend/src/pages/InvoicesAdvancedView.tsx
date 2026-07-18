import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, Download, LayoutGrid, SlidersHorizontal, Table as TableIcon, X } from 'lucide-react';
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
import { exportInvoicesCsv, fetchCompanyProfile, fetchInvoicePage, fetchProducts } from '../features/invoices/api';
import { invoiceQueryKeys } from '../features/invoices/queryKeys';
import EmptyState from '../components/EmptyState';

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

function toISODate(d: Date): string {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

type DatePreset = 'today' | 'this_month' | 'prev_month';

function computePreset(preset: DatePreset): { from: string; to: string } {
  const now = new Date();
  switch (preset) {
    case 'today':
      return { from: toISODate(now), to: toISODate(now) };
    case 'this_month':
      return {
        from: toISODate(new Date(now.getFullYear(), now.getMonth(), 1)),
        to: toISODate(new Date(now.getFullYear(), now.getMonth() + 1, 0)),
      };
    case 'prev_month':
      return {
        from: toISODate(new Date(now.getFullYear(), now.getMonth() - 1, 1)),
        to: toISODate(new Date(now.getFullYear(), now.getMonth(), 0)),
      };
  }
}

export default function InvoicesAdvancedView() {
  const { activeFY, loading: fyLoading } = useFY();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { requestCancel } = useInvoiceCancelStore();
  const [actionError, setActionError] = useState('');
  const [actionSuccess, setActionSuccess] = useState('');
  const [exporting, setExporting] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);

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

  const duplicateMutation = useMutation({
    mutationFn: (invoiceId: number) => api.get<Invoice>(`/invoices/${invoiceId}`),
    onSuccess: (data) => {
      setActionSuccess('Invoice data loaded. Opening create page…');
      setTimeout(() => navigate(`/invoices?duplicate=${data.data.id}`), 400);
    },
    onError: (err) => setActionError(getApiErrorMessage(err, 'Unable to load invoice for duplication')),
  });

  function handleDuplicate(invoice: Invoice) {
    duplicateMutation.mutate(invoice.id);
  }

  function handleCancelRequest(invoice: Invoice) {
    requestCancel(invoice.id, invoice.invoice_number);
  }

  function handleRestore(invoice: Invoice) {
    restoreMutation.mutate(invoice.id);
  }

  async function handleExportCsv() {
    setExporting(true);
    setActionError('');
    try {
      await exportInvoicesCsv({
        search: invoiceSearch,
        showCancelled,
        financialYearId: shouldUseAllFY ? undefined : activeFY?.id,
        productId: productId ?? undefined,
        includeDescription: searchDescription,
        voucherType,
        dateFrom,
        dateTo,
      });
      setActionSuccess('Invoice CSV downloaded.');
    } catch (err) {
      setActionError(getApiErrorMessage(err, 'Unable to export invoices'));
    } finally {
      setExporting(false);
    }
  }

  function handleApplyPreset(preset: 'today' | 'this_month' | 'prev_month' | 'current_fy') {
    if (preset === 'current_fy') {
      if (activeFY) {
        setDateRange(activeFY.start_date.slice(0, 10), activeFY.end_date.slice(0, 10));
      }
      return;
    }
    const { from, to } = computePreset(preset);
    setDateRange(from, to);
  }

  function handleResetFilters() {
    resetFilters();
    setSearchParams({});
  }

  const [searchParams, setSearchParams] = useSearchParams();

  const {
    viewType,
    invoiceSearch,
    searchDescription,
    showCancelled,
    allowAllFY,
    page,
    productId,
    voucherType,
    dateFrom,
    dateTo,
    setViewType,
    setInvoiceSearch,
    setSearchDescription,
    setShowCancelled,
    setAllowAllFY,
    setPage,
    resetPage,
    setProductId,
    setVoucherType,
    setDateFrom,
    setDateTo,
    setDateRange,
    resetFilters,
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
    queryKey: invoiceQueryKeys.list(page, pageSize, invoiceSearch, showCancelled, financialYearId, productId ?? undefined, searchDescription, voucherType, dateFrom, dateTo),
    queryFn: () => fetchInvoicePage({
      page,
      pageSize,
      search: invoiceSearch,
      showCancelled,
      financialYearId,
      productId: productId ?? undefined,
      includeDescription: searchDescription,
      voucherType,
      dateFrom,
      dateTo,
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
  }, [invoiceSearch, searchDescription, showCancelled, allowAllFY, activeFY?.id, productId, voucherType, dateFrom, dateTo]);

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
          <EmptyState 
            message="No active financial year is set for this company." 
            action={
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
            }
          />
        </section>
      </div>
    );
  }

  const activeFilterCount = [
    voucherType !== 'all',
    Boolean(dateFrom),
    Boolean(dateTo),
    allowAllFY,
    searchDescription,
    showCancelled,
  ].filter(Boolean).length;

  return (
    <div className="invoice-feed-view stack">
      <section className="panel invoice-feed-view__header">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Invoices</p>
            <h1 className="page-title" style={{ margin: 0 }}>Invoice Feed</h1>
          </div>

          {/* View switcher — segmented tabs, kept separate from the action buttons */}
          <div className="invoice-feed-view__view-tabs" role="tablist" aria-label="Invoice view">
            <button
              type="button"
              role="tab"
              aria-selected={viewType === 'card'}
              onClick={() => setViewType('card')}
              className={`button button--small ${viewType === 'card' ? 'button--primary' : 'button--ghost'}`}
            >
              <LayoutGrid size={16} />
              Card
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={viewType === 'table'}
              onClick={() => setViewType('table')}
              className={`button button--small ${viewType === 'table' ? 'button--primary' : 'button--ghost'}`}
            >
              <TableIcon size={16} />
              Table
            </button>
          </div>
        </div>

        {/* Toolbar: search + primary actions */}
        <div className="invoice-feed-view__toolbar">
          <input
            type="text"
            placeholder="Search by party or product..."
            value={invoiceSearch}
            onChange={(e) => setInvoiceSearch(e.target.value)}
            className="input invoice-feed-view__search"
          />

          <div className="invoice-feed-view__toolbar-actions">
            <button
              type="button"
              className={`button button--small ${filtersOpen || activeFilterCount > 0 ? 'button--primary' : 'button--ghost'}`}
              onClick={() => setFiltersOpen((open) => !open)}
              aria-expanded={filtersOpen}
            >
              <SlidersHorizontal size={16} />
              Filters
              {activeFilterCount > 0 && (
                <span className="invoice-feed-view__filter-badge">{activeFilterCount}</span>
              )}
              <ChevronDown
                size={16}
                className="invoice-feed-view__chevron"
                style={{ transform: filtersOpen ? 'rotate(180deg)' : 'none' }}
              />
            </button>

            <button
              type="button"
              className="button button--primary button--small"
              onClick={handleExportCsv}
              disabled={exporting}
            >
              <Download size={16} />
              {exporting ? 'Preparing…' : 'Export CSV'}
            </button>
            <button
              type="button"
              className="button button--ghost button--small"
              onClick={handleResetFilters}
            >
              Reset
            </button>
          </div>
        </div>

        {filtersOpen && (
        <div className="invoice-feed-view__advanced">
        {/* Filters: voucher type, date range, presets, toggles */}
        <div className="invoice-feed-view__filters">
          <label className="invoice-feed-view__field">
            <span className="invoice-feed-view__field-label">Voucher type</span>
            <select
              className="input"
              value={voucherType}
              onChange={(e) => setVoucherType(e.target.value as typeof voucherType)}
            >
              <option value="all">All</option>
              <option value="sales">Sales</option>
              <option value="purchase">Purchase</option>
            </select>
          </label>

          <label className="invoice-feed-view__field">
            <span className="invoice-feed-view__field-label">From date</span>
            <input
              type="date"
              className="input"
              value={dateFrom}
              max={dateTo || undefined}
              onChange={(e) => setDateFrom(e.target.value)}
            />
          </label>

          <label className="invoice-feed-view__field">
            <span className="invoice-feed-view__field-label">To date</span>
            <input
              type="date"
              className="input"
              value={dateTo}
              min={dateFrom || undefined}
              onChange={(e) => setDateTo(e.target.value)}
            />
          </label>

          <div className="invoice-feed-view__field">
            <span className="invoice-feed-view__field-label">Quick range</span>
            <div className="button-row">
              <button type="button" className="button button--ghost button--small" onClick={() => handleApplyPreset('today')}>Today</button>
              <button type="button" className="button button--ghost button--small" onClick={() => handleApplyPreset('this_month')}>This month</button>
              <button type="button" className="button button--ghost button--small" onClick={() => handleApplyPreset('prev_month')}>Prev month</button>
              {activeFY && (
                <button type="button" className="button button--ghost button--small" onClick={() => handleApplyPreset('current_fy')}>Current FY</button>
              )}
            </div>
          </div>
        </div>

        {/* Boolean toggles */}
        <div className="invoice-feed-view__toggles">
          <label className="invoice-feed-view__checkbox">
            <input
              type="checkbox"
              checked={allowAllFY}
              onChange={(e) => setAllowAllFY(e.target.checked)}
            />
            <span>Search all FY</span>
          </label>
          <label className="invoice-feed-view__checkbox">
            <input
              type="checkbox"
              checked={searchDescription}
              onChange={(e) => setSearchDescription(e.target.checked)}
            />
            <span>Include item description</span>
          </label>
          <label className="invoice-feed-view__checkbox">
            <input
              type="checkbox"
              checked={showCancelled}
              onChange={(e) => setShowCancelled(e.target.checked)}
            />
            <span>Show cancelled</span>
          </label>
        </div>
        </div>
        )}

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
          <EmptyState message="Loading invoices..." />
        ) : invoices.length === 0 ? (
          <EmptyState 
            message={invoiceSearch ? "No invoices match your search." : "No invoices registered yet. Create your first invoice to get started."} 
            action={!invoiceSearch ? { label: 'Create First Invoice', onClick: () => navigate('/invoices') } : undefined}
          />
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
                  onDuplicate={handleDuplicate}
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
