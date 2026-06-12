import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchCompanyProfile, fetchDueInvoicePage, fetchInvoiceById, fetchLedgers, type DueInvoiceFilters } from '../features/invoices/api';
import type { CompanyProfile, Invoice, Ledger } from '../types/api';
import { sendDueReminders, type DueRemindersResponse } from '../api/emailLogs';
import { getApiErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import InvoicePreview from '../components/InvoicePreview';
import ConfirmDialog from '../components/ConfirmDialog';
import formatCurrency from '../utils/formatting';
import { formatInvoiceDateLabel } from '../utils/invoiceDueDate.ts';
import EmptyState from '../components/EmptyState';

type DueFilterMode = 'all' | 'overdue' | 'next7' | 'next15' | 'custom-days' | 'exact-date';

function addDays(baseDate: Date, days: number) {
  const next = new Date(baseDate);
  next.setDate(next.getDate() + days);
  return next;
}

function toIsoDate(date: Date) {
  return date.toISOString().slice(0, 10);
}

function buildDueWindow(mode: DueFilterMode, customDays: number, exactDate: string) {
  const today = new Date();
  const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());

  switch (mode) {
    case 'overdue':
      return { dueDateTo: toIsoDate(addDays(startOfToday, -1)) };
    case 'next7':
      return { dueDateFrom: toIsoDate(startOfToday), dueDateTo: toIsoDate(addDays(startOfToday, 7)) };
    case 'next15':
      return { dueDateFrom: toIsoDate(startOfToday), dueDateTo: toIsoDate(addDays(startOfToday, 15)) };
    case 'custom-days':
      return { dueDateFrom: toIsoDate(startOfToday), dueDateTo: toIsoDate(addDays(startOfToday, Math.max(customDays, 0))) };
    case 'exact-date':
      return exactDate ? { dueDateFrom: exactDate, dueDateTo: exactDate } : {};
    case 'all':
    default:
      return {};
  }
}

function dueBadgeLabel(dueInDays: number | null) {
  if (dueInDays === null) return 'No due date';
  if (dueInDays < 0) return `${Math.abs(dueInDays)} days overdue`;
  if (dueInDays === 0) return 'Due today';
  return `Due in ${dueInDays} days`;
}

export default function InvoiceDuesPage() {
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [ledgers, setLedgers] = useState<Ledger[]>([]);
  const [items, setItems] = useState<Invoice[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [totalPages, setTotalPages] = useState(1);
  const [search, setSearch] = useState('');
  const [searchDraft, setSearchDraft] = useState('');
  const [ledgerId, setLedgerId] = useState<number | undefined>(undefined);
  const [mode, setMode] = useState<DueFilterMode>('overdue');
  const [customDays, setCustomDays] = useState(30);
  const [exactDate, setExactDate] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [previewInvoice, setPreviewInvoice] = useState<Invoice | null>(null);
  const [sendingReminders, setSendingReminders] = useState(false);
  const [showRemindersConfirm, setShowRemindersConfirm] = useState(false);
  const [remindersResult, setRemindersResult] = useState<string>('');
  const [remindersSuccess, setRemindersSuccess] = useState('');

  const currencyCode = company?.currency_code || 'INR';
  const dueWindow = useMemo(() => buildDueWindow(mode, customDays, exactDate), [mode, customDays, exactDate]);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const [companyProfile, ledgerList] = await Promise.all([fetchCompanyProfile(), fetchLedgers()]);
        if (cancelled) return;
        setCompany(companyProfile);
        setLedgers(ledgerList);
      } catch {
        if (!cancelled) {
          setError('Unable to load dues page filters');
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        setLoading(true);
        setError('');
        const filters: DueInvoiceFilters = {
          page,
          pageSize,
          search,
          ledgerId,
          dueDateFrom: dueWindow.dueDateFrom,
          dueDateTo: dueWindow.dueDateTo,
        };
        const response = await fetchDueInvoicePage(filters);
        if (cancelled) return;
        setItems(response.items);
        setTotal(response.total);
        setTotalPages(response.total_pages);
      } catch {
        if (!cancelled) {
          setItems([]);
          setTotal(0);
          setTotalPages(1);
          setError('Unable to load due invoices');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [dueWindow.dueDateFrom, dueWindow.dueDateTo, ledgerId, page, pageSize, search]);

  async function handlePreviewInvoice(invoiceId: number) {
    try {
      setError('');
      const invoice = await fetchInvoiceById(invoiceId);
      setPreviewInvoice(invoice);
    } catch {
      setError('Unable to load invoice preview');
    }
  }

  const outstandingTotal = items.reduce((sum, invoice) => sum + invoice.outstanding_amount, 0);

  const handleSendReminders = useCallback(async () => {
    setShowRemindersConfirm(false);
    setSendingReminders(true);
    setRemindersResult('');
    setRemindersSuccess('');
    setError('');
    try {
      const result: DueRemindersResponse = await sendDueReminders();
      const parts: string[] = [];
      if (result.sent.length > 0) {
        parts.push(`Sent to ${result.sent.length} ledgers`);
      }
      if (result.skipped.length > 0) {
        const names = result.skipped.map((s) => s.ledger_name).join(', ');
        parts.push(`Skipped ${result.skipped.length} (no email): ${names}`);
      }
      if (result.failed.length > 0) {
        const names = result.failed.map((f) => f.ledger_name).join(', ');
        parts.push(`Failed ${result.failed.length}: ${names}`);
      }
      setRemindersSuccess(parts.join('. ') || 'No reminders needed.');
      setRemindersResult(result.message);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Failed to send reminders'));
    } finally {
      setSendingReminders(false);
    }
  }, []);

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Invoices</p>
          <h1 className="page-title">Dues</h1>
          <p className="section-copy">Track overdue and upcoming invoice dues, narrow by ledger, and preview invoices before following up.</p>
        </div>
        <div className="status-chip">{total} invoices</div>
      </section>

      <StatusToasts error={error} onClearError={() => setError('')} onClearSuccess={() => {}} />

      <section className="content-grid">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Filters</p>
              <h2 className="nav-panel__title">Due window</h2>
            </div>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            {[
              { value: 'overdue', label: 'Overdue' },
              { value: 'next7', label: 'Next 7 days' },
              { value: 'next15', label: 'Next 15 days' },
              { value: 'custom-days', label: 'Custom days' },
              { value: 'exact-date', label: 'Exact date' },
              { value: 'all', label: 'All dues' },
            ].map((option) => (
              <button
                key={option.value}
                type="button"
                className={mode === option.value ? 'button button--primary button--small' : 'button button--ghost button--small'}
                onClick={() => {
                  setMode(option.value as DueFilterMode);
                  setPage(1);
                }}
              >
                {option.label}
              </button>
            ))}
          </div>

          <div className="field-grid">
            <div className="field">
              <label htmlFor="dues-search">Search</label>
              <input
                id="dues-search"
                className="input"
                type="text"
                value={searchDraft}
                placeholder="Invoice number or ledger"
                onChange={(event) => setSearchDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    setSearch(searchDraft.trim());
                    setPage(1);
                  }
                }}
              />
            </div>
            <div className="field">
              <label htmlFor="dues-ledger">Ledger</label>
              <select
                id="dues-ledger"
                className="input"
                value={ledgerId ?? ''}
                onChange={(event) => {
                  setLedgerId(event.target.value ? Number(event.target.value) : undefined);
                  setPage(1);
                }}
              >
                <option value="">All ledgers</option>
                {ledgers.map((ledger) => (
                  <option key={ledger.id} value={ledger.id}>{ledger.name}</option>
                ))}
              </select>
            </div>
          </div>

          {mode === 'custom-days' ? (
            <div className="field">
              <label htmlFor="dues-custom-days">Days ahead</label>
              <input
                id="dues-custom-days"
                className="input"
                type="number"
                min="0"
                step="1"
                value={customDays}
                onChange={(event) => {
                  setCustomDays(parseInt(event.target.value || '0', 10));
                  setPage(1);
                }}
              />
            </div>
          ) : null}

          {mode === 'exact-date' ? (
            <div className="field">
              <label htmlFor="dues-exact-date">Exact due date</label>
              <input
                id="dues-exact-date"
                className="input"
                type="date"
                value={exactDate}
                onChange={(event) => {
                  setExactDate(event.target.value);
                  setPage(1);
                }}
              />
            </div>
          ) : null}

          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              type="button"
              className="button button--secondary"
              onClick={() => {
                setSearch(searchDraft.trim());
                setPage(1);
              }}
            >
              Apply search
            </button>
            <button
              type="button"
              className="button button--ghost"
              onClick={() => {
                setMode('overdue');
                setLedgerId(undefined);
                setSearch('');
                setSearchDraft('');
                setCustomDays(30);
                setExactDate('');
                setPage(1);
              }}
            >
              Reset filters
            </button>
          </div>

          <div style={{ borderTop: '1px solid var(--border-color, #e0e0e0)', paddingTop: '12px', marginTop: '4px' }}>
            <button
              type="button"
              className="button button--primary"
              disabled={sendingReminders}
              onClick={() => setShowRemindersConfirm(true)}
            >
              {sendingReminders ? 'Sending…' : 'Send reminders to all'}
            </button>
          </div>

          {remindersSuccess ? (
            <div className="summary-box" style={{ marginTop: '8px' }}>
              <p className="eyebrow" style={{ color: 'var(--success-color, #155724)' }}>{remindersResult}</p>
              <p className="muted-text">{remindersSuccess}</p>
            </div>
          ) : null}

          <div className="summary-box">
            <p className="eyebrow">Visible outstanding</p>
            <p className="summary-box__value">{formatCurrency(outstandingTotal, currencyCode)}</p>
            <p className="muted-text">Current page total across {items.length} invoices</p>
          </div>
        </article>

        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Invoices</p>
              <h2 className="nav-panel__title">Due list</h2>
            </div>
            <div className="status-chip">Page {page} of {Math.max(totalPages, 1)}</div>
          </div>

          <div className="invoice-list">
            {loading ? (
              <EmptyState message="Loading due invoices..." />
            ) : items.length === 0 ? (
              <EmptyState message="No invoices match your due filters. Try adjusting the due window or search." />
            ) : null}
            {!loading
              ? items.map((invoice) => (
                  <div key={invoice.id} className="invoice-row">
                    <div className="invoice-row__meta">
                      <strong>{invoice.invoice_number || `#${invoice.id}`}</strong>
                      <span className="table-subtext">
                        {invoice.ledger_name || 'Unknown ledger'}
                        {' · '}
                        Invoice {formatInvoiceDateLabel(invoice.invoice_date)}
                        {' · '}
                        Due {formatInvoiceDateLabel(invoice.due_date)}
                      </span>
                      <span className="table-subtext">
                        {dueBadgeLabel(invoice.due_in_days)}
                        {' · '}
                        Status {invoice.payment_status}
                        {' · '}
                        Remaining {formatCurrency(invoice.outstanding_amount, currencyCode)}
                      </span>
                    </div>
                    <span className="invoice-row__price">{formatCurrency(invoice.total_amount, currencyCode)}</span>
                    <div style={{ display: 'flex', gap: '6px' }}>
                      {invoice.ledger_id ? (
                        <Link className="button button--ghost button--small" to={`/ledgers/${invoice.ledger_id}`}>
                          Ledger
                        </Link>
                      ) : null}
                      <button
                        type="button"
                        className="button button--ghost button--small"
                        onClick={() => void handlePreviewInvoice(invoice.id)}
                      >
                        View
                      </button>
                    </div>
                  </div>
                ))
              : null}
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px' }}>
            <button
              type="button"
              className="button button--ghost"
              disabled={page <= 1}
              onClick={() => setPage((current) => Math.max(current - 1, 1))}
            >
              Previous
            </button>
            <button
              type="button"
              className="button button--ghost"
              disabled={page >= totalPages}
              onClick={() => setPage((current) => current + 1)}
            >
              Next
            </button>
          </div>
        </article>
      </section>

      {previewInvoice ? (
        <InvoicePreview
          invoice={previewInvoice}
          onClose={() => setPreviewInvoice(null)}
          onError={(message) => setError(message)}
        />
      ) : null}

      {showRemindersConfirm ? (
        <ConfirmDialog
          title="Send due reminders"
          message="This will email a payment reminder to every ledger with outstanding dues. Are you sure?"
          confirmText="Send to all"
          cancelText="Cancel"
          onConfirm={handleSendReminders}
          onCancel={() => setShowRemindersConfirm(false)}
        />
      ) : null}
    </div>
  );
}
