import { useState, useEffect } from 'react';
import { LayoutGrid, Table as TableIcon } from 'lucide-react';
import api, { getApiErrorMessage } from '../api/client';
import type { Invoice, PaginatedInvoices, CompanyProfile } from '../types/api';
import { useFY } from '../context/FYContext';
import InvoicesTable from '../components/InvoicesTable';
import InvoicesCompactCard from '../components/InvoicesCompactCard';
import InvoicesTotalBreakdown from '../components/InvoicesTotalBreakdown';
import InvoicePreview from '../components/InvoicePreview';
import type { Product } from '../types/api';

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
  const { activeFY } = useFY();
  const [viewType, setViewType] = useState<ViewType>('card');
  const [invoices, setInvoices] = useState<Invoice[]>([]);
    const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [invoiceSearch, setInvoiceSearch] = useState('');
  const [showCancelled, setShowCancelled] = useState(false);
  const [allowAllFY, setAllowAllFY] = useState(false);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [previewInvoice, setPreviewInvoice] = useState<Invoice | null>(null);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [allPagesBreakdown, setAllPagesBreakdown] = useState<Breakdown>({ credit: 0, debit: 0, cancelled: 0, total: 0 });
  const pageSize = 20;

  // Build query params based on FY filter
  const getFYParams = () => {
    if (allowAllFY || !activeFY) {
      return {};
    }
    return { financial_year_id: activeFY.id };
  };

  async function loadData() {
    try {
      setLoading(true);
      setError('');
      const [invoicesRes, companyRes, productsRes] = await Promise.all([
        api.get<PaginatedInvoices>('/invoices/', {
          params: { 
            page, 
            page_size: pageSize, 
            search: invoiceSearch, 
            show_cancelled: showCancelled,
            ...getFYParams(),
          },
        }),
        api.get<CompanyProfile>('/company/'),
        api.get<{ items: Product[] }>('/products/', { params: { page_size: 500 } }),
      ]);

      setInvoices(invoicesRes.data.items);
      setTotal(invoicesRes.data.total);
      setTotalPages(invoicesRes.data.total_pages);
      setCompany(companyRes.data);
      setProducts(productsRes.data.items);

      // Build summary for all pages (same filters, all matching entries)
      const summaryRows: Invoice[] = [...invoicesRes.data.items];
      for (let nextPage = 2; nextPage <= invoicesRes.data.total_pages; nextPage += 1) {
        const nextRes = await api.get<PaginatedInvoices>('/invoices/', {
          params: {
            page: nextPage,
            page_size: pageSize,
            search: invoiceSearch,
            show_cancelled: showCancelled,
            ...getFYParams(),
          },
        });
        summaryRows.push(...nextRes.data.items);
      }
      setAllPagesBreakdown(calculateBreakdown(summaryRows));
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load invoices'));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setPage(1); // Reset to first page when search, filters change
  }, [invoiceSearch, showCancelled, allowAllFY]);

  useEffect(() => {
    void loadData();
  }, [page, invoiceSearch, showCancelled, allowAllFY]);

  const currentPageBreakdown = calculateBreakdown(invoices);

  if (!company) {
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
                  onPreview={setPreviewInvoice}
                />
              ))}
          </div>
        ) : (
          <InvoicesTable
            invoices={invoices}
            onRowClick={setPreviewInvoice}
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
          onClose={() => setPreviewInvoice(null)}
        />
      )}
    </div>
  );
}
