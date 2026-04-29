import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, ChevronDown, FileText, FilePlus, Mail, Pencil, ReceiptText, Trash2 } from 'lucide-react';
import api, { getApiErrorMessage } from '../api/client';
import type { CompanyAccount, CompanyProfile, Invoice, Ledger, LedgerStatement, OutstandingInvoice, Payment, PaymentCreate, PaymentInvoiceAllocation, PaymentUpdate, Product } from '../types/api';
import InvoicePreview from '../components/InvoicePreview';
import PaymentReceiptPreview from '../components/PaymentReceiptPreview';
import StatementPreview from '../components/StatementPreview';
import StatusToasts from '../components/StatusToasts';
import CreateInvoiceModal from '../components/CreateInvoiceModal';
import SendEmailModal from '../components/SendEmailModal';
import ConfirmDialog from '../components/ConfirmDialog';
import formatCurrency from '../utils/formatting';
import { useFY } from '../context/FYContext';
import { fetchOutstandingInvoices } from '../features/invoices/api';
import { formatInvoiceDateLabel } from '../utils/invoiceDueDate.ts';

function defaultDateRange() {
  const today = new Date();
  const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);
  const toIso = (d: Date) => d.toISOString().slice(0, 10);
  return { fromDate: toIso(firstDay), toDate: toIso(today) };
}

function createDefaultPaymentForm(ledgerId: number): PaymentCreate {
  return {
    ledger_id: ledgerId,
    voucher_type: 'receipt',
    amount: 0,
    account_id: null,
    date: new Date().toISOString().slice(0, 16),
    mode: '',
    reference: '',
    notes: '',
    invoice_allocations: [],
  };
}

function createDefaultEditPaymentForm(): PaymentUpdate {
  return {
    voucher_type: 'receipt',
    amount: 0,
    account_id: null,
    date: new Date().toISOString().slice(0, 16),
    mode: '',
    reference: '',
    notes: '',
    invoice_allocations: [],
  };
}

function sumAllocatedAmount(allocations: PaymentInvoiceAllocation[] | undefined): number {
  return (allocations ?? []).reduce((total, allocation) => total + Number(allocation.allocated_amount || 0), 0);
}

function buildSuggestedAllocations(invoices: OutstandingInvoice[]): PaymentInvoiceAllocation[] {
  return invoices
    .filter((invoice) => (invoice.suggested_allocation_amount || 0) > 0)
    .map((invoice) => ({
      invoice_id: invoice.id,
      invoice_number: invoice.invoice_number,
      invoice_date: invoice.invoice_date,
      due_date: invoice.due_date,
      allocated_amount: invoice.suggested_allocation_amount || 0,
    }));
}

function upsertAllocation(
  allocations: PaymentInvoiceAllocation[] | undefined,
  invoice: OutstandingInvoice,
  allocatedAmount: number,
): PaymentInvoiceAllocation[] {
  const nextAllocations = [...(allocations ?? [])];
  const existingIndex = nextAllocations.findIndex((allocation) => allocation.invoice_id === invoice.id);
  const nextAllocation: PaymentInvoiceAllocation = {
    invoice_id: invoice.id,
    invoice_number: invoice.invoice_number,
    invoice_date: invoice.invoice_date,
    due_date: invoice.due_date,
    allocated_amount: allocatedAmount,
  };

  if (existingIndex >= 0) {
    nextAllocations[existingIndex] = { ...nextAllocations[existingIndex], ...nextAllocation };
    return nextAllocations;
  }

  return [...nextAllocations, nextAllocation];
}

function removeAllocation(allocations: PaymentInvoiceAllocation[] | undefined, invoiceId: number): PaymentInvoiceAllocation[] {
  return (allocations ?? []).filter((allocation) => allocation.invoice_id !== invoiceId);
}

export default function LedgerViewPage() {
  const { id } = useParams<{ id: string }>();
  const ledgerId = Number(id);
  const navigate = useNavigate();
  const { activeFY } = useFY();

  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [statement, setStatement] = useState<LedgerStatement | null>(null);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [companyAccounts, setCompanyAccounts] = useState<CompanyAccount[]>([]);
    // Products are loaded with ledger data for future allocation/product flows.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [products, setProducts] = useState<Product[]>([]);
  const [previewInvoice, setPreviewInvoice] = useState<Invoice | null>(null);
  const [previewReceiptId, setPreviewReceiptId] = useState<number | null>(null);
  const [previewReceiptNumber, setPreviewReceiptNumber] = useState<string | null>(null);
  const [loadingLedger, setLoadingLedger] = useState(true);
  const [loadingStatement, setLoadingStatement] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [period, setPeriod] = useState(() => ({
    fromDate: activeFY?.start_date ?? defaultDateRange().fromDate,
    toDate: activeFY?.end_date ?? defaultDateRange().toDate,
  }));
  const [refreshKey, setRefreshKey] = useState(0);
  const [showPaymentForm, setShowPaymentForm] = useState(false);
  const [paymentForm, setPaymentForm] = useState<PaymentCreate>(() => createDefaultPaymentForm(ledgerId));
  const [outstandingInvoices, setOutstandingInvoices] = useState<OutstandingInvoice[]>([]);
  const [loadingOutstandingInvoices, setLoadingOutstandingInvoices] = useState(false);
  const [submittingPayment, setSubmittingPayment] = useState(false);
  const [showStatementPreview, setShowStatementPreview] = useState(false);
  const [showInvoiceModal, setShowInvoiceModal] = useState(false);
  const [showEmailModal, setShowEmailModal] = useState(false);
  const [showActionsDropdown, setShowActionsDropdown] = useState(false);
  const actionsDropdownRef = useRef<HTMLDivElement>(null);
  const [editingPayment, setEditingPayment] = useState<Payment | null>(null);
  const [editPaymentForm, setEditPaymentForm] = useState<PaymentUpdate>(() => createDefaultEditPaymentForm());
  const [editOutstandingInvoices, setEditOutstandingInvoices] = useState<OutstandingInvoice[]>([]);
  const [loadingEditOutstandingInvoices, setLoadingEditOutstandingInvoices] = useState(false);
  const [submittingEditPayment, setSubmittingEditPayment] = useState(false);
  const [confirmDeletePaymentId, setConfirmDeletePaymentId] = useState<number | null>(null);
  const [deletingPayment, setDeletingPayment] = useState(false);
  const [allocationCreateSearch, setAllocationCreateSearch] = useState('');
  const [allocationEditSearch, setAllocationEditSearch] = useState('');

  useEffect(() => {
    if (!showPaymentForm) setAllocationCreateSearch('');
  }, [showPaymentForm]);

  useEffect(() => {
    if (!editingPayment) setAllocationEditSearch('');
  }, [editingPayment]);

  useEffect(() => {
    if (!showActionsDropdown) return;
    function handleClickOutside(e: MouseEvent) {
      if (actionsDropdownRef.current && !actionsDropdownRef.current.contains(e.target as Node)) {
        setShowActionsDropdown(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showActionsDropdown]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoadingLedger(true);
        const [ledgerRes, companyRes, accountsRes, productsRes] = await Promise.all([
          api.get<Ledger>(`/ledgers/${ledgerId}`),
          api.get<CompanyProfile>('/company/'),
          api.get<CompanyAccount[]>('/company-accounts/'),
          api.get<{ items: Product[] }>('/products/', { params: { page_size: 500 } }),
        ]);
        if (cancelled) return;
        setLedger(ledgerRes.data);
        setCompany(companyRes.data);
        setCompanyAccounts(accountsRes.data);
        setProducts(productsRes.data.items);
      } catch (err) {
        if (!cancelled) setError(getApiErrorMessage(err, 'Unable to load ledger'));
      } finally {
        if (!cancelled) setLoadingLedger(false);
      }
    })();
    return () => { cancelled = true; };
  }, [ledgerId]);

  useEffect(() => {
    if (!ledgerId || !period.fromDate || !period.toDate) return;
    let cancelled = false;
    (async () => {
      try {
        setLoadingStatement(true);
        setError('');
        const res = await api.get<LedgerStatement>(`/ledgers/${ledgerId}/statement`, {
          params: { from_date: period.fromDate, to_date: period.toDate },
        });
        if (!cancelled) setStatement(res.data);
      } catch (err) {
        if (!cancelled) {
          setStatement(null);
          setError(getApiErrorMessage(err, 'Unable to load ledger statement'));
        }
      } finally {
        if (!cancelled) setLoadingStatement(false);
      }
    })();
    return () => { cancelled = true; };
  }, [ledgerId, period.fromDate, period.toDate, refreshKey]);

  // Re-initialise date range when active FY changes
  useEffect(() => {
    setPeriod({
      fromDate: activeFY?.start_date ?? defaultDateRange().fromDate,
      toDate: activeFY?.end_date ?? defaultDateRange().toDate,
    });
  }, [activeFY]);

  useEffect(() => {
    if (!showPaymentForm) return;

    let cancelled = false;
    (async () => {
      try {
        setLoadingOutstandingInvoices(true);
        const invoices = await fetchOutstandingInvoices({
          ledgerId,
          voucherType: paymentForm.voucher_type as 'receipt' | 'payment',
          amount: paymentForm.amount > 0 ? paymentForm.amount : undefined,
        });
        if (!cancelled) {
          setOutstandingInvoices(invoices);
        }
      } catch (err) {
        if (!cancelled) {
          setError(getApiErrorMessage(err, 'Unable to load outstanding invoices'));
        }
      } finally {
        if (!cancelled) {
          setLoadingOutstandingInvoices(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [ledgerId, paymentForm.amount, paymentForm.voucher_type, showPaymentForm]);

  useEffect(() => {
    if (!editingPayment) return;

    let cancelled = false;
    (async () => {
      try {
        setLoadingEditOutstandingInvoices(true);
        const invoices = await fetchOutstandingInvoices({
          ledgerId,
          voucherType: editPaymentForm.voucher_type as 'receipt' | 'payment',
          amount: editPaymentForm.amount > 0 ? editPaymentForm.amount : undefined,
          paymentId: editingPayment.id,
        });
        if (!cancelled) {
          setEditOutstandingInvoices(invoices);
        }
      } catch (err) {
        if (!cancelled) {
          setError(getApiErrorMessage(err, 'Unable to load invoice allocations'));
        }
      } finally {
        if (!cancelled) {
          setLoadingEditOutstandingInvoices(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [editPaymentForm.amount, editPaymentForm.voucher_type, editingPayment, ledgerId]);

  const activeCurrencyCode = company?.currency_code || 'INR';

  function renderAllocationSection(input: {
    allocations: PaymentInvoiceAllocation[] | undefined;
    amount: number;
    outstanding: OutstandingInvoice[];
    loading: boolean;
    voucherType: PaymentCreate['voucher_type'] | PaymentUpdate['voucher_type'];
    onChange: (allocations: PaymentInvoiceAllocation[]) => void;
    title: string;
    searchQuery: string;
    onSearchChange: (q: string) => void;
  }) {
    if (input.voucherType !== 'receipt' && input.voucherType !== 'payment') {
      return null;
    }

    const allocatedTotal = sumAllocatedAmount(input.allocations);
    const remainingUnallocated = input.amount - allocatedTotal;
    const filteredInvoices = input.searchQuery.trim()
      ? input.outstanding.filter((inv) =>
          (inv.invoice_number ?? '').toLowerCase().includes(input.searchQuery.trim().toLowerCase())
        )
      : input.outstanding;

    return (
      <div className="summary-box stack" style={{ gap: '12px' }}>
        <div className="panel__header" style={{ marginBottom: 0 }}>
          <div>
            <p className="eyebrow">Invoice Allocation</p>
            <h3 className="nav-panel__title" style={{ margin: 0 }}>{input.title}</h3>
          </div>
          <button
            type="button"
            className="button button--secondary button--small"
            onClick={() => input.onChange(buildSuggestedAllocations(input.outstanding))}
            disabled={input.loading || input.outstanding.length === 0 || input.amount <= 0}
          >
            Auto Select Oldest
          </button>
        </div>

        <p className="muted-text" style={{ margin: 0 }}>
          Allocated {formatCurrency(allocatedTotal, activeCurrencyCode)}
          {' · '}
          {remainingUnallocated >= 0
            ? `Unallocated ${formatCurrency(remainingUnallocated, activeCurrencyCode)}`
            : `Over-allocated by ${formatCurrency(Math.abs(remainingUnallocated), activeCurrencyCode)}`}
        </p>

        {!input.loading && input.outstanding.length > 0 ? (
          <input
            type="search"
            className="input"
            placeholder="Search by invoice number…"
            value={input.searchQuery}
            onChange={(e) => input.onSearchChange(e.target.value)}
            aria-label="Search invoices by number"
          />
        ) : null}

        {input.loading ? <p className="muted-text" style={{ margin: 0 }}>Loading invoice options...</p> : null}
        {!input.loading && input.outstanding.length === 0 ? (
          <p className="muted-text" style={{ margin: 0 }}>No outstanding invoices are available for this ledger.</p>
        ) : null}
        {!input.loading && input.outstanding.length > 0 && filteredInvoices.length === 0 ? (
          <p className="muted-text" style={{ margin: 0 }}>No invoices match your search.</p>
        ) : null}

        {!input.loading && filteredInvoices.length > 0 ? (
          <div className="stack" style={{ gap: '10px', maxHeight: '320px', overflowY: 'auto', paddingRight: '4px' }}>
            {filteredInvoices.map((invoice) => {
              const existingAllocation = (input.allocations ?? []).find((allocation) => allocation.invoice_id === invoice.id);
              const isSelected = Boolean(existingAllocation);

              return (
                <div key={invoice.id} className="summary-box" style={{ padding: '14px' }}>
                  <div style={{ display: 'grid', gap: '10px' }}>
                    <label style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', cursor: 'pointer' }}>
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={(event) => {
                          if (!event.target.checked) {
                            input.onChange(removeAllocation(input.allocations, invoice.id));
                            return;
                          }

                          const defaultAmount = invoice.suggested_allocation_amount || invoice.remaining_amount;
                          input.onChange(upsertAllocation(input.allocations, invoice, defaultAmount));
                        }}
                      />
                      <div style={{ display: 'grid', gap: '4px', flex: 1 }}>
                        <strong>{invoice.invoice_number || `#${invoice.id}`}</strong>
                        <span className="table-subtext">
                          Invoice {formatInvoiceDateLabel(invoice.invoice_date)}
                          {' · '}
                          Due {formatInvoiceDateLabel(invoice.due_date)}
                          {' · '}
                          Remaining {formatCurrency(invoice.remaining_amount, activeCurrencyCode)}
                        </span>
                        <span className="table-subtext">
                          Status {invoice.payment_status}
                          {typeof invoice.due_in_days === 'number' ? ` · ${invoice.due_in_days} days` : ''}
                        </span>
                      </div>
                    </label>

                    {isSelected ? (
                      <div className="field" style={{ marginLeft: '28px' }}>
                        <label htmlFor={`allocation-${input.title}-${invoice.id}`}>Allocated amount</label>
                        <input
                          id={`allocation-${input.title}-${invoice.id}`}
                          className="input"
                          type="number"
                          min="0.01"
                          step="0.01"
                          value={existingAllocation?.allocated_amount || ''}
                          onChange={(event) => {
                            const nextAmount = parseFloat(event.target.value) || 0;
                            input.onChange(upsertAllocation(input.allocations, invoice, nextAmount));
                          }}
                        />
                      </div>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}
      </div>
    );
  }

  async function handleViewInvoice(invoiceId: number) {
    try {
      setError('');
      const res = await api.get<Invoice>(`/invoices/${invoiceId}`);
      setPreviewInvoice(res.data);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load invoice'));
    }
  }

  async function handleSubmitPayment(e: React.FormEvent) {
    e.preventDefault();
    if (paymentForm.amount <= 0) {
      setError('Amount must be greater than 0');
      return;
    }
    try {
      setSubmittingPayment(true);
      setError('');
      const res = await api.post<Payment>('/payments/', paymentForm);
      setShowPaymentForm(false);
      setPaymentForm(createDefaultPaymentForm(ledgerId));
      setOutstandingInvoices([]);
      // Refresh statement
      setRefreshKey((k) => k + 1);
      if (res.data.warnings?.includes('invoice_date_outside_fy') && activeFY) {
        setSuccess(
          `⚠️ This date is outside the active financial year (${activeFY.label}). The payment was still recorded.`,
        );
      }
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to record payment'));
    } finally {
      setSubmittingPayment(false);
    }
  }

  async function handleLoadEditPayment(paymentId: number) {
    try {
      setError('');
      const res = await api.get<Payment>(`/payments/${paymentId}`);
      setEditingPayment(res.data);
      setEditPaymentForm({
        voucher_type: res.data.voucher_type,
        amount: res.data.amount,
        account_id: res.data.account_id ?? null,
        date: res.data.date.slice(0, 16),
        mode: res.data.mode || '',
        reference: res.data.reference || '',
        notes: res.data.notes || '',
        invoice_allocations: (res.data.invoice_allocations ?? []).map((allocation) => ({
          id: allocation.id,
          invoice_id: allocation.invoice_id,
          invoice_number: allocation.invoice_number,
          invoice_date: allocation.invoice_date,
          due_date: allocation.due_date,
          allocated_amount: allocation.allocated_amount,
        })),
      });
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load payment'));
    }
  }

  async function handleUpdatePayment(e: React.FormEvent) {
    e.preventDefault();
    if (!editingPayment) return;
    if ((editPaymentForm.amount ?? 0) <= 0) {
      setError('Amount must be greater than 0');
      return;
    }
    try {
      setSubmittingEditPayment(true);
      setError('');
      await api.put<Payment>(`/payments/${editingPayment.id}`, editPaymentForm);
      setEditingPayment(null);
      setEditOutstandingInvoices([]);
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to update payment'));
    } finally {
      setSubmittingEditPayment(false);
    }
  }

  async function handleConfirmDeletePayment() {
    if (confirmDeletePaymentId === null) return;
    try {
      setDeletingPayment(true);
      setError('');
      await api.delete(`/payments/${confirmDeletePaymentId}`);
      setConfirmDeletePaymentId(null);
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to cancel payment'));
    } finally {
      setDeletingPayment(false);
    }
  }

  if (loadingLedger) {
    return (
      <div className="page-grid">
        <section className="page-hero">
          <div>
            <p className="eyebrow">Ledgers</p>
            <h1 className="page-title">Loading ledger...</h1>
          </div>
        </section>
      </div>
    );
  }

  if (!ledger) {
    return (
      <div className="page-grid">
        <section className="page-hero">
          <div>
            <p className="eyebrow">Ledgers</p>
            <h1 className="page-title">Ledger not found</h1>
          </div>
        </section>
        <StatusToasts error={error} onClearError={() => setError('')} onClearSuccess={() => {}} />
      </div>
    );
  }

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Ledger statement</p>
          <h1 className="page-title">{ledger.name}</h1>
          <p className="section-copy">
            {[ledger.gst ? `GST: ${ledger.gst}` : '', ledger.phone_number].filter(Boolean).join(' · ')}
            {ledger.email ? ` · ${ledger.email}` : ''}
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <button
            type="button"
            className="button button--ghost"
            onClick={() => navigate('/ledgers')}
            title="Back to ledgers"
            aria-label="Back to ledgers"
            style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
          >
            <ArrowLeft size={16} />
            Back
          </button>

          <div className="split-button">
            <button
              type="button"
              className="button button--primary split-button__main"
              onClick={() => setShowPaymentForm(true)}
              title="Record receipt or payment"
              aria-label="Record Receipt / Payment"
            >
              <ReceiptText size={16} />
              Record Receipt / Payment
            </button>
            <div className="action-dropdown" ref={actionsDropdownRef}>
              <button
                type="button"
                className="button button--primary split-button__caret"
                onClick={() => setShowActionsDropdown((v) => !v)}
                aria-label="More ledger actions"
                aria-haspopup="true"
                aria-expanded={showActionsDropdown}
                title="More actions"
              >
                <ChevronDown size={14} />
              </button>
              {showActionsDropdown ? (
                <div className="action-dropdown__menu" role="menu">
                  <button
                    type="button"
                    className="action-dropdown__item"
                    role="menuitem"
                    aria-label="Send Reminder"
                    onClick={() => { setShowActionsDropdown(false); setShowEmailModal(true); }}
                  >
                    <Mail size={16} />
                    Send Reminder
                  </button>
                  <button
                    type="button"
                    className="action-dropdown__item"
                    role="menuitem"
                    aria-label="Create Invoice"
                    onClick={() => { setShowActionsDropdown(false); setShowInvoiceModal(true); }}
                  >
                    <FilePlus size={16} />
                    Create Invoice
                  </button>
                  <button
                    type="button"
                    className="action-dropdown__item"
                    role="menuitem"
                    aria-label="Create Credit Note"
                    onClick={() => { setShowActionsDropdown(false); navigate(`/credit-notes?ledger=${ledgerId}`); }}
                  >
                    <FileText size={16} />
                    Create Credit Note
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </section>

      <StatusToasts
        error={error}
        success={success}
        onClearError={() => setError('')}
        onClearSuccess={() => setSuccess('')}
      />

      <section className="content-grid">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Ledger details</p>
              <h2 className="nav-panel__title">Account info</h2>
            </div>
            <button
              type="button"
              className="button button--ghost button--icon"
              onClick={() => navigate(`/ledgers/${ledgerId}/edit`)}
              title="Edit ledger"
              aria-label="Edit ledger"
            >
              <Pencil size={16} />
            </button>
          </div>

          <div className="summary-box">
            <p><strong>Address:</strong> {ledger.address}</p>
            {ledger.website ? <p><strong>Website:</strong> {ledger.website}</p> : null}
            {(ledger.bank_name || ledger.account_number) ? (
              <p>
                <strong>Bank:</strong> {ledger.bank_name || 'N/A'}
                {ledger.branch_name ? ` (${ledger.branch_name})` : ''} · A/C: {ledger.account_number || 'N/A'}
                {ledger.ifsc_code ? ` · IFSC: ${ledger.ifsc_code}` : ''}
              </p>
            ) : null}
          </div>
        </article>

        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Period statement</p>
              <h2 className="nav-panel__title">Period view</h2>
            </div>
            {statement && statement.entries.length > 0 ? (
              <button
                type="button"
                className="button button--secondary"
                onClick={() => setShowStatementPreview(true)}
                title="Preview statement PDF"
                aria-label="Preview statement PDF"
                style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
              >
                <FileText size={15} />
                Preview / PDF
              </button>
            ) : null}
          </div>

          <div className="field-grid">
            <div className="field">
              <label htmlFor="statement-from">From</label>
              <input
                id="statement-from"
                className="input"
                type="date"
                value={period.fromDate}
                onChange={(e) => setPeriod((c) => ({ ...c, fromDate: e.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="statement-to">To</label>
              <input
                id="statement-to"
                className="input"
                type="date"
                value={period.toDate}
                onChange={(e) => setPeriod((c) => ({ ...c, toDate: e.target.value }))}
              />
            </div>
          </div>

          <div className="summary-box">
            <p className="eyebrow">Tally-style summary</p>
            <p className="summary-box__value">{statement ? formatCurrency(statement.closing_balance, activeCurrencyCode) : formatCurrency(0, activeCurrencyCode)}</p>
            <p className="muted-text">
              Opening {statement ? formatCurrency(statement.opening_balance, activeCurrencyCode) : formatCurrency(0, activeCurrencyCode)} · Debit{' '}
              {statement ? formatCurrency(statement.period_debit, activeCurrencyCode) : formatCurrency(0, activeCurrencyCode)} · Credit{' '}
              {statement ? formatCurrency(statement.period_credit, activeCurrencyCode) : formatCurrency(0, activeCurrencyCode)}
            </p>
          </div>

          <div className="invoice-list">
            {loadingStatement ? <div className="empty-state">Loading statement...</div> : null}
            {!loadingStatement && statement && statement.entries.length === 0 ? (
              <div className="empty-state">No voucher entries in selected period.</div>
            ) : null}
            {!loadingStatement && statement
              ? statement.entries.map((entry, idx) => (
                  <div key={`${entry.entry_type}-${entry.entry_id}-${idx}`} className="invoice-row">
                    <div className="invoice-row__meta">
                      <strong>{entry.reference_number || `${entry.voucher_type} #${entry.entry_id}`}</strong>
                      <span className="table-subtext">{new Date(entry.date).toLocaleDateString()} · {entry.particulars}</span>
                      {entry.entry_type === 'payment' ? (
                        <>
                          <span className="table-subtext">
                            Account: {entry.account_display_name || 'Unallocated'}
                            {entry.account_type ? ` (${entry.account_type})` : ''}
                          </span>
                          {entry.invoice_allocations && entry.invoice_allocations.length > 0 ? (
                            <div className="receipt-allocation-strip">
                              <div className="receipt-allocation-strip__header">
                                <span className="receipt-allocation-strip__title">
                                  Allocated invoices ({entry.invoice_allocations.length})
                                </span>
                                <span className="receipt-allocation-strip__total">
                                  {formatCurrency(sumAllocatedAmount(entry.invoice_allocations as PaymentInvoiceAllocation[]), activeCurrencyCode)}
                                </span>
                              </div>
                              <div className="receipt-allocation-strip__chips">
                                {entry.invoice_allocations.map((allocation) => (
                                  <span
                                    key={`${entry.entry_id}-${allocation.invoice_id}`}
                                    className="receipt-allocation-chip"
                                  >
                                    <span className="receipt-allocation-chip__invoice">
                                      {allocation.invoice_number || `#${allocation.invoice_id}`}
                                    </span>
                                    <span
                                      className={`receipt-allocation-chip__status receipt-allocation-chip__status--${
                                        allocation.payment_status === 'paid'
                                          ? 'full'
                                          : allocation.payment_status === 'partial'
                                            ? 'partial'
                                            : 'unpaid'
                                      }`}
                                    >
                                      {allocation.payment_status === 'paid'
                                        ? 'Full'
                                        : allocation.payment_status === 'partial'
                                          ? 'Partial'
                                          : 'Unpaid'}
                                    </span>
                                    <span className="receipt-allocation-chip__amount">
                                      {formatCurrency(allocation.allocated_amount || 0, activeCurrencyCode)}
                                    </span>
                                  </span>
                                ))}
                              </div>
                            </div>
                          ) : null}
                        </>
                      ) : null}
                    </div>
                    <span className="invoice-row__price">
                      {entry.debit > 0 ? `Dr ${formatCurrency(entry.debit, activeCurrencyCode)}` : `Cr ${formatCurrency(entry.credit, activeCurrencyCode)}`}
                    </span>
                    {entry.entry_type === 'invoice' ? (
                      <button
                        type="button"
                        className="button button--ghost button--small"
                        onClick={() => void handleViewInvoice(entry.entry_id)}
                        title="View invoice"
                        aria-label="View invoice"
                      >
                        View
                      </button>
                    ) : entry.voucher_type === 'Opening Balance' ? (
                      <button
                        type="button"
                        className="button button--ghost button--small"
                        onClick={() => navigate(`/ledgers/${ledgerId}/edit`)}
                        title="Edit ledger opening balance"
                        aria-label="Edit ledger opening balance"
                      >
                        Edit Ledger
                      </button>
                    ) : (
                      <div style={{ display: 'flex', gap: '4px' }}>
                        <button
                          type="button"
                          className="button button--ghost button--small"
                          onClick={() => { setPreviewReceiptId(entry.entry_id); setPreviewReceiptNumber(null); }}
                          title="View receipt PDF"
                          aria-label="View receipt PDF"
                        >
                          Receipt
                        </button>
                        <button
                          type="button"
                          className="button button--ghost button--small"
                          onClick={() => void handleLoadEditPayment(entry.entry_id)}
                          title="Edit payment"
                          aria-label="Edit payment"
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          type="button"
                          className="button button--ghost button--small"
                          onClick={() => setConfirmDeletePaymentId(entry.entry_id)}
                          title="Cancel payment"
                          aria-label="Cancel payment"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    )}
                  </div>
                ))
              : null}
          </div>
        </article>
      </section>

      {showStatementPreview && statement ? (
        <StatementPreview
          ledger={ledger}
          statement={statement}
          company={company}
          currencyCode={activeCurrencyCode}
          onClose={() => setShowStatementPreview(false)}
          onError={(msg) => setError(msg)}
        />
      ) : null}

      {showPaymentForm ? (
        <div className="modal-overlay" role="dialog" aria-modal="true" onClick={() => setShowPaymentForm(false)}>
          <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
            <div className="panel stack">
              <div className="panel__header">
                <h2 className="nav-panel__title">Record Receipt / Payment</h2>
                <button type="button" className="button button--ghost" onClick={() => setShowPaymentForm(false)} title="Close payment dialog" aria-label="Close payment dialog">✕</button>
              </div>
              <form onSubmit={(e) => void handleSubmitPayment(e)} className="stack">
                <div className="field">
                  <label htmlFor="pay-type">Type</label>
                  <select
                    id="pay-type"
                    className="input"
                    value={paymentForm.voucher_type}
                    onChange={(e) => setPaymentForm((f) => ({ ...f, voucher_type: e.target.value as 'receipt' | 'payment' }))}
                  >
                    <option value="receipt">Receipt (money received)</option>
                    <option value="payment">Payment (money paid)</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="pay-amount">Amount</label>
                  <input
                    id="pay-amount"
                    className="input"
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={paymentForm.amount || ''}
                    onChange={(e) => setPaymentForm((f) => ({ ...f, amount: parseFloat(e.target.value) || 0 }))}
                    required
                  />
                </div>
                <div className="field">
                  <label htmlFor="pay-account">Account</label>
                  <select
                    id="pay-account"
                    className="input"
                    value={paymentForm.account_id ?? ''}
                    onChange={(e) => setPaymentForm((f) => ({ ...f, account_id: e.target.value ? Number(e.target.value) : null }))}
                  >
                    <option value="">Unallocated</option>
                    {companyAccounts.map((account) => (
                      <option key={account.id} value={account.id}>
                        {account.display_name} ({account.account_type})
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="pay-date">Date</label>
                  <input
                    id="pay-date"
                    className="input"
                    type="datetime-local"
                    value={paymentForm.date}
                    onChange={(e) => setPaymentForm((f) => ({ ...f, date: e.target.value }))}
                  />
                  {activeFY !== null && paymentForm.date && (
                    paymentForm.date.slice(0, 10) < activeFY.start_date ||
                    paymentForm.date.slice(0, 10) > activeFY.end_date
                  ) ? (
                    <p className="field-warning">
                      ⚠️ This date is outside the active financial year ({activeFY.label}). The payment will still be recorded.
                    </p>
                  ) : null}
                </div>
                <div className="field">
                  <label htmlFor="pay-mode">Mode</label>
                  <select
                    id="pay-mode"
                    className="input"
                    value={paymentForm.mode}
                    onChange={(e) => setPaymentForm((f) => ({ ...f, mode: e.target.value }))}
                  >
                    <option value="">Select mode</option>
                    <option value="cash">Cash</option>
                    <option value="bank">Bank Transfer</option>
                    <option value="upi">UPI</option>
                    <option value="cheque">Cheque</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="pay-ref">Reference (optional)</label>
                  <input
                    id="pay-ref"
                    className="input"
                    type="text"
                    placeholder="Cheque no, txn ID..."
                    value={paymentForm.reference}
                    onChange={(e) => setPaymentForm((f) => ({ ...f, reference: e.target.value }))}
                  />
                </div>
                <div className="field">
                  <label htmlFor="pay-notes">Notes (optional)</label>
                  <input
                    id="pay-notes"
                    className="input"
                    type="text"
                    value={paymentForm.notes}
                    onChange={(e) => setPaymentForm((f) => ({ ...f, notes: e.target.value }))}
                  />
                </div>
                {renderAllocationSection({
                  allocations: paymentForm.invoice_allocations,
                  amount: paymentForm.amount,
                  outstanding: outstandingInvoices,
                  loading: loadingOutstandingInvoices,
                  voucherType: paymentForm.voucher_type,
                  onChange: (invoice_allocations) => setPaymentForm((current) => ({ ...current, invoice_allocations })),
                  title: 'Allocate against invoices',
                  searchQuery: allocationCreateSearch,
                  onSearchChange: setAllocationCreateSearch,
                })}
                <button type="submit" className="button button--primary" disabled={submittingPayment} title="Save payment" aria-label="Save payment">
                  {submittingPayment ? 'Saving...' : 'Save'}
                </button>
              </form>
            </div>
          </div>
        </div>
      ) : null}

      {previewInvoice ? (
        <InvoicePreview
          invoice={previewInvoice}
          onClose={() => setPreviewInvoice(null)}
          onError={(msg) => setError(msg)}
        />
      ) : null}

      {previewReceiptId !== null ? (
        <PaymentReceiptPreview
          paymentId={previewReceiptId}
          paymentNumber={previewReceiptNumber}
          onClose={() => { setPreviewReceiptId(null); setPreviewReceiptNumber(null); }}
          onError={(msg) => setError(msg)}
        />
      ) : null}

      {showInvoiceModal ? (
        <CreateInvoiceModal
          preselectedLedgerId={ledgerId}
          onClose={() => setShowInvoiceModal(false)}
          onCreated={(msg, warningMsg, createdInvoice) => {
            setShowInvoiceModal(false);
            setPreviewInvoice(createdInvoice);
            setRefreshKey((k) => k + 1);
            setError('');
            setSuccess(warningMsg ?? msg);
          }}
          onError={(msg) => setError(msg)}
        />
      ) : null}

      {showEmailModal && (
        <SendEmailModal
          type="reminder"
          entityId={ledgerId}
          defaultTo={ledger?.email || ''}
          defaultSubject={`Payment Reminder from ${company?.name || 'Company'}`}
          onClose={() => setShowEmailModal(false)}
          onSuccess={() => {
            setShowEmailModal(false);
            setError('');
            // Could show success message here
          }}
          onError={(message) => setError(message)}
        />
      )}

      {editingPayment ? (
        <div className="modal-overlay" role="dialog" aria-modal="true" onClick={() => setEditingPayment(null)}>
          <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
            <div className="panel stack">
              <div className="panel__header">
                <h2 className="nav-panel__title">Edit Payment #{editingPayment.id}</h2>
                <button type="button" className="button button--ghost" onClick={() => setEditingPayment(null)} title="Close" aria-label="Close">✕</button>
              </div>
              <form onSubmit={(e) => void handleUpdatePayment(e)} className="stack">
                <div className="field">
                  <label htmlFor="edit-pay-type">Type</label>
                  <select
                    id="edit-pay-type"
                    className="input"
                    value={editPaymentForm.voucher_type}
                    onChange={(e) => setEditPaymentForm((f) => ({ ...f, voucher_type: e.target.value as 'receipt' | 'payment' }))}
                  >
                    <option value="receipt">Receipt (money received)</option>
                    <option value="payment">Payment (money paid)</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="edit-pay-amount">Amount</label>
                  <input
                    id="edit-pay-amount"
                    className="input"
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={editPaymentForm.amount || ''}
                    onChange={(e) => setEditPaymentForm((f) => ({ ...f, amount: parseFloat(e.target.value) || 0 }))}
                    required
                  />
                </div>
                <div className="field">
                  <label htmlFor="edit-pay-account">Account</label>
                  <select
                    id="edit-pay-account"
                    className="input"
                    value={editPaymentForm.account_id ?? ''}
                    onChange={(e) => setEditPaymentForm((f) => ({ ...f, account_id: e.target.value ? Number(e.target.value) : null }))}
                  >
                    <option value="">Unallocated</option>
                    {companyAccounts.map((account) => (
                      <option key={account.id} value={account.id}>
                        {account.display_name} ({account.account_type})
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="edit-pay-date">Date</label>
                  <input
                    id="edit-pay-date"
                    className="input"
                    type="datetime-local"
                    value={editPaymentForm.date}
                    onChange={(e) => setEditPaymentForm((f) => ({ ...f, date: e.target.value }))}
                  />
                  {activeFY !== null && editPaymentForm.date && (
                    editPaymentForm.date.slice(0, 10) < activeFY.start_date ||
                    editPaymentForm.date.slice(0, 10) > activeFY.end_date
                  ) ? (
                    <p className="field-warning">
                      ⚠️ This date is outside the active financial year ({activeFY.label}). The payment will still be saved.
                    </p>
                  ) : null}
                </div>
                <div className="field">
                  <label htmlFor="edit-pay-mode">Mode</label>
                  <select
                    id="edit-pay-mode"
                    className="input"
                    value={editPaymentForm.mode}
                    onChange={(e) => setEditPaymentForm((f) => ({ ...f, mode: e.target.value }))}
                  >
                    <option value="">Select mode</option>
                    <option value="cash">Cash</option>
                    <option value="bank">Bank Transfer</option>
                    <option value="upi">UPI</option>
                    <option value="cheque">Cheque</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="edit-pay-ref">Reference (optional)</label>
                  <input
                    id="edit-pay-ref"
                    className="input"
                    type="text"
                    placeholder="Cheque no, txn ID..."
                    value={editPaymentForm.reference}
                    onChange={(e) => setEditPaymentForm((f) => ({ ...f, reference: e.target.value }))}
                  />
                </div>
                <div className="field">
                  <label htmlFor="edit-pay-notes">Notes (optional)</label>
                  <input
                    id="edit-pay-notes"
                    className="input"
                    type="text"
                    value={editPaymentForm.notes}
                    onChange={(e) => setEditPaymentForm((f) => ({ ...f, notes: e.target.value }))}
                  />
                </div>
                {renderAllocationSection({
                  allocations: editPaymentForm.invoice_allocations,
                  amount: editPaymentForm.amount ?? 0,
                  outstanding: editOutstandingInvoices,
                  loading: loadingEditOutstandingInvoices,
                  voucherType: editPaymentForm.voucher_type,
                  onChange: (invoice_allocations) => setEditPaymentForm((current) => ({ ...current, invoice_allocations })),
                  title: 'Edit invoice allocations',
                  searchQuery: allocationEditSearch,
                  onSearchChange: setAllocationEditSearch,
                })}
                <button type="submit" className="button button--primary" disabled={submittingEditPayment} title="Update payment" aria-label="Update payment">
                  {submittingEditPayment ? 'Saving...' : 'Update'}
                </button>
              </form>
            </div>
          </div>
        </div>
      ) : null}

      {confirmDeletePaymentId !== null ? (
        <ConfirmDialog
          title="Cancel payment?"
          message="This will mark the payment as cancelled and remove it from the ledger balance. This cannot be undone."
          confirmText={deletingPayment ? 'Cancelling...' : 'Cancel Payment'}
          cancelText="Keep"
          danger
          onConfirm={() => void handleConfirmDeletePayment()}
          onCancel={() => setConfirmDeletePaymentId(null)}
        />
      ) : null}
    </div>
  );
}
