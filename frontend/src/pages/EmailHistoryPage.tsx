import { useState } from 'react';
import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { getApiErrorMessage } from '../api/client';
import { listEmailLogs } from '../api/emailLogs';
import type { EmailLog } from '../api/emailLogs';
import StatusToasts from '../components/StatusToasts';
import EmptyState from '../components/EmptyState';

const PAGE_SIZE = 20;

const EMAIL_TYPE_LABELS: Record<string, string> = {
  invoice: 'Invoice',
  ledger_statement: 'Ledger Statement',
  payment_reminder: 'Payment Reminder',
  other: 'Other',
};

function today() {
  return new Date().toISOString().slice(0, 10);
}

function monthStart() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`;
}

export default function EmailHistoryPage() {
  const [page, setPage] = useState(1);
  const [fromDate, setFromDate] = useState(monthStart());
  const [toDate, setToDate] = useState(today());
  const [emailType, setEmailType] = useState('');
  const [status, setStatus] = useState('');
  const [expandedError, setExpandedError] = useState<number | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ['email-logs', page, fromDate, toDate, emailType, status],
    queryFn: () =>
      listEmailLogs({
        page,
        page_size: PAGE_SIZE,
        from_date: fromDate || undefined,
        to_date: toDate || undefined,
        email_type: emailType || undefined,
        status: status || undefined,
      }),
    placeholderData: keepPreviousData,
  });

  function handleFilterChange() {
    setPage(1);
  }

  function formatDate(iso: string) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Settings</p>
          <h1 className="page-title">Email history</h1>
          <p className="section-copy">A log of all outbound emails sent from this company.</p>
        </div>
        {data && <div className="status-chip">{data.total} emails</div>}
      </section>

      <StatusToasts error={error ? getApiErrorMessage(error) : ''} onClearError={() => {}} onClearSuccess={() => {}} />

      <section className="content-grid">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Filters</p>
              <h2 className="nav-panel__title">Narrow results</h2>
            </div>
          </div>

          <div className="field-grid">
            <div className="field">
              <label htmlFor="email-log-from">From date</label>
              <input
                id="email-log-from"
                className="input"
                type="date"
                value={fromDate}
                onChange={e => { setFromDate(e.target.value); handleFilterChange(); }}
              />
            </div>
            <div className="field">
              <label htmlFor="email-log-to">To date</label>
              <input
                id="email-log-to"
                className="input"
                type="date"
                value={toDate}
                onChange={e => { setToDate(e.target.value); handleFilterChange(); }}
              />
            </div>
            <div className="field">
              <label htmlFor="email-log-type">Email type</label>
              <select
                id="email-log-type"
                className="input"
                value={emailType}
                onChange={e => { setEmailType(e.target.value); handleFilterChange(); }}
              >
                <option value="">All types</option>
                <option value="invoice">Invoice</option>
                <option value="ledger_statement">Ledger Statement</option>
                <option value="payment_reminder">Payment Reminder</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="email-log-status">Status</label>
              <select
                id="email-log-status"
                className="input"
                value={status}
                onChange={e => { setStatus(e.target.value); handleFilterChange(); }}
              >
                <option value="">All</option>
                <option value="sent">Sent</option>
                <option value="failed">Failed</option>
              </select>
            </div>
          </div>
        </article>

        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Log</p>
              <h2 className="nav-panel__title">Sent emails</h2>
            </div>
          </div>

          <div className="invoice-list">
            {isLoading && <EmptyState message="Loading emails..." />}
            {!isLoading && (!data || data.items.length === 0) && (
              <EmptyState message="No emails found for the selected filters." />
            )}
            {!isLoading && data?.items.map((log: EmailLog) => (
              <div key={log.id}>
                <div
                  className="invoice-row"
                  style={{ cursor: log.error_message ? 'pointer' : 'default' }}
                  onClick={() => log.error_message
                    ? setExpandedError(expandedError === log.id ? null : log.id)
                    : undefined}
                >
                  <div className="invoice-row__meta">
                    <strong>{log.subject}</strong>
                    <span className="table-subtext">
                      To: {log.to_email}
                      {log.cc ? ` · CC: ${log.cc}` : ''}
                    </span>
                    <span className="table-subtext">
                      {formatDate(log.sent_at)} · {EMAIL_TYPE_LABELS[log.email_type] ?? log.email_type}
                    </span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '4px' }}>
                    <span
                      className={`status-chip ${log.status === 'sent' ? 'status-chip--active' : 'status-chip--cancelled'}`}
                    >
                      {log.status === 'sent' ? 'Sent' : 'Failed'}
                    </span>
                    {log.error_message && (
                      <span className="table-subtext">tap to {expandedError === log.id ? 'hide' : 'show'} error</span>
                    )}
                  </div>
                </div>
                {expandedError === log.id && log.error_message && (
                  <div
                    style={{
                      padding: '8px 16px',
                      background: 'var(--color-surface-raised, #fef2f2)',
                      borderLeft: '3px solid var(--color-error, #e53e3e)',
                      fontSize: '0.8rem',
                      fontFamily: 'monospace',
                      color: 'var(--color-error, #c53030)',
                      marginBottom: '2px',
                    }}
                  >
                    {log.error_message}
                  </div>
                )}
              </div>
            ))}
          </div>

          {data && data.total_pages > 1 && (
            <div className="button-row">
              <button
                type="button"
                className="button button--secondary"
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page <= 1}
              >
                Previous
              </button>
              <span className="table-subtext" style={{ alignSelf: 'center' }}>
                Page {data.page} of {data.total_pages}
              </span>
              <button
                type="button"
                className="button button--secondary"
                onClick={() => setPage(p => Math.min(data.total_pages, p + 1))}
                disabled={page >= data.total_pages}
              >
                Next
              </button>
            </div>
          )}
        </article>
      </section>
    </div>
  );
}
