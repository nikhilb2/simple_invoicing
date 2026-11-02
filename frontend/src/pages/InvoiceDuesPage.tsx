import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { MessageCircle } from 'lucide-react';
import { fetchCompanyProfile, fetchDueInvoicePage, fetchInvoiceById, fetchLedgers, type DueInvoiceFilters } from '../features/invoices/api';
import type { CompanyProfile, Invoice, Ledger } from '../types/api';
import { sendDueReminders, type DueRemindersResponse } from '../api/emailLogs';
import { getApiErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import ScopeBar, { Metric } from '../components/ScopeBar';
import InvoicePreview from '../components/InvoicePreview';
import ConfirmDialog from '../components/ConfirmDialog';
import formatCurrency from '../utils/formatting';
import { buildWhatsAppUrl, toWhatsAppNumber } from '../utils/phone';
import { buildWhatsAppReminderMessage } from '../utils/whatsappReminder';
import { downloadCsv } from '../utils/csv';
import {
  buildDueWindow,
  formatInvoiceDateLabel,
  isOverdueInvoice,
  overdueLabel,
  type DueFilterMode,
} from '../utils/invoiceDueDate.ts';
import { toIsoDate } from '../utils/dateRanges';
import OverdueBadge from '../components/OverdueBadge';
import DuesAgeingStrip from '../components/DuesAgeingStrip';
import EmptyState from '../components/EmptyState';
import LoadingState from '../components/LoadingState';
import {
  parseInvoiceDueSort,
  sortDueInvoices,
  type InvoiceDueSort,
} from '../utils/invoiceDuesSorting';

const DUE_WINDOW_OPTIONS: { value: DueFilterMode; label: string }[] = [
  { value: 'overdue', label: 'Overdue' },
  { value: 'next7', label: 'Next 7 days' },
  { value: 'next15', label: 'Next 15 days' },
  { value: 'custom-days', label: 'Custom days' },
  { value: 'exact-date', label: 'Exact date' },
  { value: 'all', label: 'All dues' },
];

function dueBadgeLabel(dueInDays: number | null) {
  if (dueInDays === null) return 'No due date';
  const overdue = overdueLabel(dueInDays);
  if (overdue !== null) return overdue;
  if (dueInDays === 0) return 'Due today';
  return `Due in ${dueInDays} days`;
}

export default function InvoiceDuesPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  const sortOrder: InvoiceDueSort = parseInvoiceDueSort(
    searchParams.get('sort'),
  );

  function handleSortChange(value: InvoiceDueSort) {
    const nextParams = new URLSearchParams(searchParams);

    if (value === 'default') {
      nextParams.delete('sort');
    } else {
      nextParams.set('sort', value);
    }

    setSearchParams(nextParams, { replace: true });
  }
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
  const sortedItems = useMemo(
    () => sortDueInvoices(items, sortOrder),
    [items, sortOrder],
  );
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

  function handleExportCsv() {
    downloadCsv(
      `invoice_dues_${toIsoDate(new Date())}.csv`,
      ['Customer', 'Invoice number', 'Invoice date', 'Due date', 'Total', 'Amount due'],
      sortedItems.map((invoice) => [
        invoice.ledger_name ?? '',
        invoice.invoice_number ?? `#${invoice.id}`,
        invoice.invoice_date,
        invoice.due_date ?? '',
        invoice.total_amount,
        invoice.outstanding_amount,
      ]),
    );
  }

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
      const noEmail = result.skipped.filter((s) => s.reason_code !== 'net_payable_offset');
      if (noEmail.length > 0) {
        const names = noEmail.map((s) => s.ledger_name).join(', ');
        parts.push(`Skipped ${noEmail.length} (no email): ${names}`);
      }
      const offset = result.skipped.filter((s) => s.reason_code === 'net_payable_offset');
      if (offset.length > 0) {
        const names = offset.map((s) => s.ledger_name).join(', ');
        parts.push(`Skipped ${offset.length} (you owe them as much as they owe you): ${names}`);
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

      <ScopeBar
        presets={(
          <div className="scope-presets" role="group" aria-label="Due window">
            {DUE_WINDOW_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={`scope-preset${mode === option.value ? ' scope-preset--on' : ''}`}
                aria-pressed={mode === option.value}
                onClick={() => {
                  setMode(option.value);
                  setPage(1);
                }}
              >
                {option.label}
              </button>
            ))}
          </div>
        )}
        metrics={(
          <>
            <Metric label="Visible outstanding" value={formatCurrency(outstandingTotal, currencyCode)} />
            <Metric label="Invoices on page" value={items.length} />
          </>
        )}
        actions={(
          <>
            <button
              type="button"
              className="button button--secondary button--small"
              onClick={() => {
                setSearch(searchDraft.trim());
                setPage(1);
              }}
            >
              Apply search
            </button>
            <button
              type="button"
              className="button button--ghost button--small"
              onClick={() => {
                setMode('overdue');
                setLedgerId(undefined);
                setSearch('');
                setSearchDraft('');
                setCustomDays(30);
                setExactDate('');
                setPage(1);
                handleSortChange('default');
              }}
            >
              Reset filters
            </button>
          </>
        )}
      >
        <div className="field">
          <label htmlFor="dues-sort">Sort this page</label>
          <select
            id="dues-sort"
            className="input"
            value={sortOrder}
            onChange={(event) =>
              handleSortChange(event.target.value as InvoiceDueSort)
            }
          >
            <option value="default">Default order</option>
            <option value="amount-desc">Amount due: high to low</option>
            <option value="due-date-asc">Oldest due date first</option>
            <option value="customer-asc">Customer name: A–Z</option>
          </select>
        </div>
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

        {/* Only meaningful under their own window, and the fields grid is
            auto-fit, so they slot in beside the others without a gap when the
            window is one of the four that needs no extra input. */}
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
      </ScopeBar>

      <DuesAgeingStrip
        search={search}
        ledgerId={ledgerId}
        dueDateFrom={dueWindow.dueDateFrom}
        dueDateTo={dueWindow.dueDateTo}
        currencyCode={currencyCode}
      />

      <section className="content-grid content-grid--single">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Invoices</p>
              <h2 className="nav-panel__title">Due list</h2>
            </div>
            <div className="button-row">
              <div className="status-chip">Page {page} of {Math.max(totalPages, 1)}</div>
              <button
                type="button"
                className="button button--secondary button--small"
                disabled={loading || items.length === 0}
                onClick={handleExportCsv}
              >
                Export CSV
              </button>
              <button
                type="button"
                className="button button--primary button--small"
                disabled={sendingReminders}
                onClick={() => setShowRemindersConfirm(true)}
              >
                {sendingReminders ? 'Sending…' : 'Send reminders to all'}
              </button>
            </div>
          </div>

          {remindersSuccess ? (
            <div className="summary-box">
              <p className="eyebrow" style={{ color: 'var(--success-color)' }}>{remindersResult}</p>
              <p className="muted-text">{remindersSuccess}</p>
            </div>
          ) : null}

          <div className="invoice-list">
            {loading ? (
              <LoadingState message="Loading due invoices..." />
            ) : items.length === 0 ? (
              <EmptyState message="No invoices match your due filters. Try adjusting the due window or search." />
            ) : null}
            {!loading
              ? sortedItems.map((invoice) => {
                  const whatsappNumber = toWhatsAppNumber(invoice.ledger_phone);
                  const whatsappUrl = whatsappNumber
                    ? buildWhatsAppUrl(
                        whatsappNumber,
                        buildWhatsAppReminderMessage({
                          customerName: invoice.ledger_name,
                          invoiceNumber: invoice.invoice_number || `#${invoice.id}`,
                          outstandingAmount: invoice.outstanding_amount,
                          currencyCode,
                          dueDate: invoice.due_date,
                          overdue: isOverdueInvoice(invoice),
                        }),
                      )
                    : null;
                  return (
                  <div key={invoice.id} className="invoice-row">
                    <div className="invoice-row__meta">
                      <strong>{invoice.invoice_number || `#${invoice.id}`}</strong>
                      <span className="table-subtext">
                        {invoice.ledger_name || 'Unknown ledger'}
                        {' · '}
                        Invoice {formatInvoiceDateLabel(invoice.invoice_date)}
                        {' · '}
                        Due {formatInvoiceDateLabel(invoice.due_date)}
                        {' '}
                        <OverdueBadge invoice={invoice} />
                      </span>
                      <span className="table-subtext">
                        {isOverdueInvoice(invoice) ? null : (
                          <>
                            {dueBadgeLabel(invoice.due_in_days)}
                            {' · '}
                          </>
                        )}
                        Status {invoice.payment_status}
                        {' · '}
                        Remaining {formatCurrency(invoice.outstanding_amount, currencyCode)}
                      </span>
                      {(invoice.ledger_payable_amount ?? 0) > 0 ? (
                        <span className="table-subtext">
                          You also owe this party {formatCurrency(invoice.ledger_payable_amount ?? 0, currencyCode)} (net{' '}
                          {formatCurrency(Math.abs(invoice.ledger_net_receivable ?? 0), currencyCode)}{' '}
                          {(invoice.ledger_net_receivable ?? 0) > 0 ? 'receivable' : 'payable'})
                        </span>
                      ) : null}
                    </div>
                    <span className="invoice-row__price">{formatCurrency(invoice.total_amount, currencyCode)}</span>
                    <div className="invoice-row__actions">
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
                      {whatsappUrl ? (
                        <a
                          className="button button--ghost button--small"
                          href={whatsappUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          title={`WhatsApp reminder to ${invoice.ledger_name || 'customer'}`}
                          aria-label={`WhatsApp reminder to ${invoice.ledger_name || 'customer'}`}
                        >
                          <MessageCircle size={16} aria-hidden="true" />
                        </a>
                      ) : null}
                    </div>
                  </div>
                  );
                })
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
