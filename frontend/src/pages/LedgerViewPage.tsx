import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, ChevronDown, FileText, FilePlus, Mail, Pencil, ReceiptText } from 'lucide-react';
import api, { getApiErrorMessage } from '../api/client';
import type { CompanyProfile, Invoice, Ledger, LedgerStatement, PaymentCreate, Product } from '../types/api';
import InvoicePreview from '../components/InvoicePreview';
import StatementPreview from '../components/StatementPreview';
import StatusToasts from '../components/StatusToasts';
import CreateInvoiceModal from '../components/CreateInvoiceModal';
import SendEmailModal from '../components/SendEmailModal';
import formatCurrency from '../utils/formatting';

function defaultDateRange() {
  const today = new Date();
  const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);
  const toIso = (d: Date) => d.toISOString().slice(0, 10);
  return { fromDate: toIso(firstDay), toDate: toIso(today) };
}

export default function LedgerViewPage() {
  const { id } = useParams<{ id: string }>();
  const ledgerId = Number(id);
  const navigate = useNavigate();

  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [statement, setStatement] = useState<LedgerStatement | null>(null);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [previewInvoice, setPreviewInvoice] = useState<Invoice | null>(null);
  const [loadingLedger, setLoadingLedger] = useState(true);
  const [loadingStatement, setLoadingStatement] = useState(false);
  const [error, setError] = useState('');
  const [period, setPeriod] = useState(defaultDateRange);
  const [refreshKey, setRefreshKey] = useState(0);
  const [showPaymentForm, setShowPaymentForm] = useState(false);
  const [paymentForm, setPaymentForm] = useState<PaymentCreate>({
    ledger_id: ledgerId,
    voucher_type: 'receipt',
    amount: 0,
    date: new Date().toISOString().slice(0, 16),
    mode: '',
    reference: '',
    notes: '',
  });
  const [submittingPayment, setSubmittingPayment] = useState(false);
  const [showStatementPreview, setShowStatementPreview] = useState(false);
  const [showInvoiceModal, setShowInvoiceModal] = useState(false);
  const [showEmailModal, setShowEmailModal] = useState(false);
  const [showActionsDropdown, setShowActionsDropdown] = useState(false);
  const actionsDropdownRef = useRef<HTMLDivElement>(null);

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
        const [ledgerRes, companyRes, productsRes] = await Promise.all([
          api.get<Ledger>(`/ledgers/${ledgerId}`),
          api.get<CompanyProfile>('/company/'),
          api.get<{ items: Product[] }>('/products/', { params: { page_size: 500 } }),
        ]);
        if (cancelled) return;
        setLedger(ledgerRes.data);
        setCompany(companyRes.data);
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

  const activeCurrencyCode = company?.currency_code || 'INR';

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
      await api.post('/payments/', paymentForm);
      setShowPaymentForm(false);
      setPaymentForm({
        ledger_id: ledgerId,
        voucher_type: 'receipt',
        amount: 0,
        date: new Date().toISOString().slice(0, 16),
        mode: '',
        reference: '',
        notes: '',
      });
      // Refresh statement
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to record payment'));
    } finally {
      setSubmittingPayment(false);
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
            {ledger.gst} · {ledger.phone_number}
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
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </section>

      <StatusToasts error={error} onClearError={() => setError('')} onClearSuccess={() => {}} />

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
                      <strong>{entry.voucher_type} #{entry.entry_id}</strong>
                      <span className="table-subtext">{new Date(entry.date).toLocaleDateString()} · {entry.particulars}</span>
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
                    ) : null}
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
                  <label htmlFor="pay-date">Date</label>
                  <input
                    id="pay-date"
                    className="input"
                    type="datetime-local"
                    value={paymentForm.date}
                    onChange={(e) => setPaymentForm((f) => ({ ...f, date: e.target.value }))}
                  />
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
          products={products}
          currencyCode={activeCurrencyCode}
          onClose={() => setPreviewInvoice(null)}
          onError={(msg) => setError(msg)}
        />
      ) : null}

      {showInvoiceModal ? (
        <CreateInvoiceModal
          preselectedLedgerId={ledgerId}
          onClose={() => setShowInvoiceModal(false)}
          onCreated={(msg) => {
            setShowInvoiceModal(false);
            setRefreshKey((k) => k + 1);
            setError('');
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
          onSuccess={(message) => {
            setShowEmailModal(false);
            setError('');
            // Could show success message here
          }}
          onError={(message) => setError(message)}
        />
      )}
    </div>
  );
}
