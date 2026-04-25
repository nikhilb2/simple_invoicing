import { useEffect, useState } from 'react';
import api, { getApiErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import type { CompanyProfile, DayBook } from '../types/api';
import formatCurrency from '../utils/formatting';
import { useFY } from '../context/FYContext';

function defaultDateRange() {
  const today = new Date();
  const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);
  const toIso = (date: Date) => date.toISOString().slice(0, 10);

  return {
    fromDate: toIso(firstDay),
    toDate: toIso(today),
  };
}

export default function DayBookPage() {
  const { activeFY } = useFY();
  const [period, setPeriod] = useState(() => ({
    fromDate: activeFY?.start_date ?? defaultDateRange().fromDate,
    toDate: activeFY?.end_date ?? defaultDateRange().toDate,
  }));
  const [dayBook, setDayBook] = useState<DayBook | null>(null);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState<'pdf' | 'csv' | null>(null);
  const [error, setError] = useState('');

  const activeCurrencyCode = company?.currency_code || 'USD';

  async function loadDayBook() {
    try {
      setLoading(true);
      setError('');

      const [dayBookResponse, companyResponse] = await Promise.all([
        api.get<DayBook>('/ledgers/day-book', {
          params: {
            from_date: period.fromDate,
            to_date: period.toDate,
          },
        }),
        api.get<CompanyProfile>('/company/'),
      ]);

      setDayBook(dayBookResponse.data);
      setCompany(companyResponse.data);
    } catch (err) {
      setDayBook(null);
      setError(getApiErrorMessage(err, 'Unable to load day book'));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadDayBook();
  }, [period.fromDate, period.toDate]);

  // Re-initialise date range when active FY changes
  useEffect(() => {
    setPeriod({
      fromDate: activeFY?.start_date ?? defaultDateRange().fromDate,
      toDate: activeFY?.end_date ?? defaultDateRange().toDate,
    });
  }, [activeFY]);

  async function handleDownload(format: 'pdf' | 'csv') {
    try {
      setDownloading(format);
      setError('');

      const response = await api.get(`/ledgers/day-book/${format}`, {
        params: {
          from_date: period.fromDate,
          to_date: period.toDate,
        },
        responseType: 'blob',
      });

      const url = window.URL.createObjectURL(response.data as Blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `day_book_${period.fromDate}_${period.toDate}.${format}`;
      link.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(getApiErrorMessage(err, `Unable to download day book ${format.toUpperCase()}`));
    } finally {
      setDownloading(null);
    }
  }

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Accounting</p>
          <h1 className="page-title">Day book</h1>
          <p className="section-copy">A minimal Tally-style voucher register for the selected period.</p>
        </div>
        <div className="status-chip">{dayBook?.entries.length ?? 0} vouchers</div>
      </section>

      <StatusToasts error={error} onClearError={() => setError('')} onClearSuccess={() => {}} />

      <section className="content-grid">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Period</p>
              <h2 className="nav-panel__title">Voucher range</h2>
            </div>
          </div>

          <div className="field-grid">
            <div className="field">
              <label htmlFor="day-book-from">From</label>
              <input
                id="day-book-from"
                className="input"
                type="date"
                value={period.fromDate}
                onChange={(event) => setPeriod((current) => ({ ...current, fromDate: event.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="day-book-to">To</label>
              <input
                id="day-book-to"
                className="input"
                type="date"
                value={period.toDate}
                onChange={(event) => setPeriod((current) => ({ ...current, toDate: event.target.value }))}
              />
            </div>
          </div>

          <div className="button-row">
            <button
              type="button"
              className="button button--primary"
              onClick={() => { void handleDownload('pdf'); }}
              disabled={downloading !== null}
            >
              {downloading === 'pdf' ? 'Downloading PDF...' : 'Download PDF'}
            </button>
            <button
              type="button"
              className="button button--secondary"
              onClick={() => { void handleDownload('csv'); }}
              disabled={downloading !== null}
            >
              {downloading === 'csv' ? 'Downloading CSV...' : 'Download CSV'}
            </button>
          </div>

          <div className="summary-box">
            <p className="eyebrow">Totals</p>
            <p className="summary-box__value">Dr {formatCurrency(dayBook?.total_debit ?? 0, activeCurrencyCode)}</p>
            <p className="muted-text">Cr {formatCurrency(dayBook?.total_credit ?? 0, activeCurrencyCode)}</p>
          </div>
        </article>

        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Entries</p>
              <h2 className="nav-panel__title">Voucher register</h2>
            </div>
          </div>

          <div className="invoice-list">
            {loading ? <div className="empty-state">Loading vouchers...</div> : null}
            {!loading && (!dayBook || dayBook.entries.length === 0) ? <div className="empty-state">No vouchers found for this period.</div> : null}
            {!loading && dayBook
              ? dayBook.entries.map((entry, idx) => (
                  <div key={`${entry.entry_type}-${entry.entry_id}-${idx}`} className="invoice-row">
                    <div className="invoice-row__meta">
                      <strong>{entry.reference_number || `${entry.voucher_type} #${entry.entry_id}`}</strong>
                      <span className="table-subtext">{new Date(entry.date).toLocaleDateString()} · {entry.ledger_name}</span>
                      <span className="table-subtext">{entry.particulars}</span>
                    </div>
                    <span className="invoice-row__price">
                      {entry.debit > 0
                        ? `Dr ${formatCurrency(entry.debit, activeCurrencyCode)}`
                        : `Cr ${formatCurrency(entry.credit, activeCurrencyCode)}`}
                    </span>
                  </div>
                ))
              : null}
          </div>
        </article>
      </section>
    </div>
  );
}
