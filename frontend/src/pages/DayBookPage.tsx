import { useEffect, useMemo, useState } from 'react';
import api, { getApiErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import ScopeBar, { Metric } from '../components/ScopeBar';
import DateRangePresets from '../components/DateRangePresets';
import type { CompanyProfile, DayBook, DayBookEntry } from '../types/api';
import formatCurrency from '../utils/formatting';
import { toIsoDate } from '../utils/dateRanges';
import { useFY } from '../context/FYContext';

function defaultDateRange() {
  const today = new Date();
  const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);

  return {
    fromDate: toIsoDate(firstDay),
    toDate: toIsoDate(today),
  };
}

const DAY_HEADING = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  day: 'numeric',
  month: 'short',
  year: 'numeric',
});

/** `sales` → `sales`, `credit note` → `credit-note`; the modifier suffix. */
function tagModifier(voucherType: string) {
  return voucherType.trim().toLowerCase().replace(/[\s_]+/g, '-');
}

/** Vouchers arrive newest-first; a day book is read a day at a time, so the
 *  rows are banded under the date they fell on rather than repeating it. */
function groupByDay(entries: DayBookEntry[]) {
  const days: { date: string; entries: DayBookEntry[] }[] = [];

  for (const entry of entries) {
    const date = entry.date.slice(0, 10);
    const last = days[days.length - 1];
    if (last && last.date === date) last.entries.push(entry);
    else days.push({ date, entries: [entry] });
  }

  return days;
}

export default function DayBookPage() {
  const { activeFY } = useFY();
  const [period, setPeriod] = useState(() => ({
    fromDate: activeFY?.start_date ?? defaultDateRange().fromDate,
    toDate: activeFY?.end_date ?? defaultDateRange().toDate,
  }));
  const [dayBook, setDayBook] = useState<DayBook | null>(null);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [search, setSearch] = useState('');
  const [voucherType, setVoucherType] = useState('all');
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

  // Memoised rather than `dayBook?.entries ?? []`: the bare fallback is a fresh
  // array on every render, which re-ran every derivation below it.
  const allEntries = useMemo(() => dayBook?.entries ?? [], [dayBook]);

  // The voucher kinds actually present, so the filter never offers a choice
  // that empties the register.
  const voucherTypes = useMemo(
    () => [...new Set(allEntries.map((entry) => entry.voucher_type).filter(Boolean))].sort(),
    [allEntries],
  );

  // Narrowing the loaded period is a scan of at most a few thousand rows, and
  // doing it here rather than server-side keeps it instant as you type.
  const entries = useMemo(() => {
    const needle = search.trim().toLowerCase();

    return allEntries.filter((entry) => {
      if (voucherType !== 'all' && entry.voucher_type !== voucherType) return false;
      if (!needle) return true;
      return [entry.reference_number, entry.ledger_name, entry.particulars, entry.voucher_type]
        .some((field) => field?.toLowerCase().includes(needle));
    });
  }, [allEntries, search, voucherType]);

  const filtered = entries.length !== allEntries.length;

  // The footer totals what is on screen; the bar carries the period's own
  // totals, so a filtered view never quietly restates a different number as
  // "the period".
  const visibleTotals = useMemo(
    () => entries.reduce(
      (acc, entry) => ({ debit: acc.debit + entry.debit, credit: acc.credit + entry.credit }),
      { debit: 0, credit: 0 },
    ),
    [entries],
  );

  const days = useMemo(() => groupByDay(entries), [entries]);

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
        <div className="status-chip">
          {filtered ? `${entries.length} of ${allEntries.length} vouchers` : `${allEntries.length} vouchers`}
        </div>
      </section>

      <StatusToasts error={error} onClearError={() => setError('')} onClearSuccess={() => {}} />

      <ScopeBar
        presets={(
          <DateRangePresets
            value={period}
            onChange={setPeriod}
            fy={activeFY}
          />
        )}
        metrics={(
          <>
            <Metric label="Period debit" value={formatCurrency(dayBook?.total_debit ?? 0, activeCurrencyCode)} />
            <Metric label="Period credit" value={formatCurrency(dayBook?.total_credit ?? 0, activeCurrencyCode)} />
          </>
        )}
        actions={(
          <>
            <button
              type="button"
              className="button button--primary button--small"
              onClick={() => { void handleDownload('pdf'); }}
              disabled={downloading !== null}
            >
              {downloading === 'pdf' ? 'Downloading…' : 'Export PDF'}
            </button>
            <button
              type="button"
              className="button button--secondary button--small"
              onClick={() => { void handleDownload('csv'); }}
              disabled={downloading !== null}
            >
              {downloading === 'csv' ? 'Downloading…' : 'Export CSV'}
            </button>
          </>
        )}
      >
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
        <div className="field">
          <label htmlFor="day-book-voucher-type">Voucher type</label>
          <select
            id="day-book-voucher-type"
            className="select"
            value={voucherType}
            onChange={(event) => setVoucherType(event.target.value)}
          >
            <option value="all">All types</option>
            {voucherTypes.map((type) => (
              <option key={type} value={type}>{type}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="day-book-search">Find</label>
          <input
            id="day-book-search"
            className="input"
            type="search"
            placeholder="Reference, ledger or particulars"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
      </ScopeBar>

      <section className="content-grid content-grid--single">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Entries</p>
              <h2 className="nav-panel__title">Voucher register</h2>
            </div>
            {filtered ? (
              <button type="button" className="button button--ghost button--small" onClick={() => { setSearch(''); setVoucherType('all'); }}>
                Clear filters
              </button>
            ) : null}
          </div>

          {loading ? <div className="empty-state">Loading vouchers...</div> : null}

          {!loading && entries.length === 0 ? (
            <div className="empty-state">
              {allEntries.length === 0
                ? 'No vouchers found for this period.'
                : 'No vouchers match these filters.'}
            </div>
          ) : null}

          {!loading && entries.length > 0 ? (
            <div className="register-scroll">
              <div className="register">
                <div className="register__head" role="row">
                  <span className="register__date">Date</span>
                  <span>Voucher</span>
                  <span>Ledger</span>
                  <span>Particulars</span>
                  <span className="register__num">Debit</span>
                  <span className="register__num">Credit</span>
                </div>

                {days.map((day) => (
                  <div key={day.date} className="register__day-group">
                    <div className="register__day">
                      <span>{DAY_HEADING.format(new Date(`${day.date}T00:00:00`))}</span>
                      <span className="register__day-count">
                        {day.entries.length} {day.entries.length === 1 ? 'voucher' : 'vouchers'}
                      </span>
                    </div>

                    {day.entries.map((entry, idx) => (
                      <div key={`${entry.entry_type}-${entry.entry_id}-${idx}`} className="register__row">
                        <span className="register__date">{entry.date.slice(0, 10)}</span>
                        <span className="register__cell register__voucher">
                          <span className={`register__tag register__tag--${tagModifier(entry.voucher_type)}`}>
                            {entry.voucher_type}
                          </span>
                          {entry.reference_number ? (
                            <span className="register__ref">{entry.reference_number}</span>
                          ) : null}
                        </span>
                        <span className="register__cell">{entry.ledger_name}</span>
                        <span className="register__cell table-subtext">{entry.particulars}</span>
                        <span className="register__num register__debit">
                          {entry.debit > 0
                            ? formatCurrency(entry.debit, activeCurrencyCode)
                            : <span className="register__nil">—</span>}
                        </span>
                        <span className="register__num register__credit">
                          {entry.credit > 0
                            ? formatCurrency(entry.credit, activeCurrencyCode)
                            : <span className="register__nil">—</span>}
                        </span>
                      </div>
                    ))}
                  </div>
                ))}

                <div className="register__foot">
                  {/* The date cell drops out of the grid on a narrow page, so
                      the footer's leading spacer has to drop with it. */}
                  <span className="register__date" />
                  <span />
                  <span />
                  <span>{filtered ? 'Filtered total' : 'Period total'}</span>
                  <span className="register__num register__debit">
                    {formatCurrency(visibleTotals.debit, activeCurrencyCode)}
                  </span>
                  <span className="register__num register__credit">
                    {formatCurrency(visibleTotals.credit, activeCurrencyCode)}
                  </span>
                </div>
              </div>
            </div>
          ) : null}
        </article>
      </section>
    </div>
  );
}
