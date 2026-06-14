import { useEffect, useMemo, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import api, { getApiErrorMessage, getBlobErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import { useFY } from '../context/FYContext';
import type {
  CompanyProfile,
  Gstr1Summary,
  Gstr1ValidationResult,
  TaxLedger,
} from '../types/api';
import formatCurrency from '../utils/formatting';

function defaultDateRange() {
  const today = new Date();
  const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);
  const toIso = (date: Date) => date.toISOString().slice(0, 10);
  return { fromDate: toIso(firstDay), toDate: toIso(today) };
}

type Tab = 'tax-ledger' | 'gstr1';

type Gstr1Step = 'select-period' | 'validate' | 'summary';

export default function TaxLedgerPage() {
  const { activeFY } = useFY();

  // ── Shared state ──
  const [tab, setTab] = useState<Tab>('tax-ledger');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // ── Tax Ledger tab ──
  const [period, setPeriod] = useState(() => ({
    fromDate: activeFY?.start_date ?? defaultDateRange().fromDate,
    toDate: activeFY?.end_date ?? defaultDateRange().toDate,
  }));
  const [voucherType, setVoucherType] = useState<'all' | 'sales' | 'purchase'>('all');
  const [gstRate, setGstRate] = useState('');
  const [taxLedger, setTaxLedger] = useState<TaxLedger | null>(null);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState<'pdf' | 'csv' | null>(null);

  const activeCurrencyCode = company?.currency_code || 'INR';
  const entries = taxLedger?.entries ?? [];
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  const rowVirtualizer = useVirtualizer({
    count: entries.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: () => 44,
    overscan: 12,
  });

  const virtualItems = rowVirtualizer.getVirtualItems();
  const topPadding = virtualItems.length > 0 ? virtualItems[0].start : 0;
  const bottomPadding = virtualItems.length > 0
    ? rowVirtualizer.getTotalSize() - virtualItems[virtualItems.length - 1].end
    : 0;

  const numericGstRate = useMemo(() => {
    if (!gstRate.trim()) return undefined;
    const parsed = Number(gstRate);
    return Number.isFinite(parsed) ? parsed : undefined;
  }, [gstRate]);

  // ── GSTR-1 tab ──
  const [gstr1Period, setGstr1Period] = useState(() => ({
    fromDate: activeFY?.start_date ?? defaultDateRange().fromDate,
    toDate: activeFY?.end_date ?? defaultDateRange().toDate,
  }));
  const [gstr1Step, setGstr1Step] = useState<Gstr1Step>('select-period');
  const [gstr1Validation, setGstr1Validation] = useState<Gstr1ValidationResult | null>(null);
  const [gstr1Summary, setGstr1Summary] = useState<Gstr1Summary | null>(null);
  const [gstr1Loading, setGstr1Loading] = useState(false);
  const [gstr1Downloading, setGstr1Downloading] = useState<'json' | 'csv' | 'pdf' | null>(null);

  // ═══════════════════════════════════════════════════════════════════════
  //  Tax Ledger tab — load & export
  // ═══════════════════════════════════════════════════════════════════════

  async function loadTaxLedger() {
    try {
      setLoading(true);
      setError('');
      const [taxLedgerResponse, companyResponse] = await Promise.all([
        api.get<TaxLedger>('/ledgers/tax-ledger/', {
          params: {
            from_date: period.fromDate,
            to_date: period.toDate,
            voucher_type: voucherType === 'all' ? undefined : voucherType,
            gst_rate: numericGstRate,
          },
        }),
        api.get<CompanyProfile>('/company/'),
      ]);
      setTaxLedger(taxLedgerResponse.data);
      setCompany(companyResponse.data);
    } catch (err) {
      setTaxLedger(null);
      setError(getApiErrorMessage(err, 'Unable to load tax ledger'));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadTaxLedger();
  }, [period.fromDate, period.toDate, voucherType, numericGstRate]);

  useEffect(() => {
    setPeriod({
      fromDate: activeFY?.start_date ?? defaultDateRange().fromDate,
      toDate: activeFY?.end_date ?? defaultDateRange().toDate,
    });
    setGstr1Period({
      fromDate: activeFY?.start_date ?? defaultDateRange().fromDate,
      toDate: activeFY?.end_date ?? defaultDateRange().toDate,
    });
  }, [activeFY]);

  async function handleTaxLedgerDownload(format: 'pdf' | 'csv') {
    try {
      setDownloading(format);
      setError('');
      const response = await api.get(`/ledgers/tax-ledger/${format}`, {
        params: {
          from_date: period.fromDate,
          to_date: period.toDate,
          voucher_type: voucherType === 'all' ? undefined : voucherType,
          gst_rate: numericGstRate,
        },
        responseType: 'blob',
      });
      const url = window.URL.createObjectURL(response.data as Blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `tax_ledger_${period.fromDate}_${period.toDate}.${format}`;
      link.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(await getBlobErrorMessage(err, `Unable to download tax ledger ${format.toUpperCase()}`));
    } finally {
      setDownloading(null);
    }
  }

  // ═══════════════════════════════════════════════════════════════════════
  //  GSTR-1 tab — validate, summary, export
  // ═══════════════════════════════════════════════════════════════════════

  async function handleGstr1Validate() {
    try {
      setGstr1Loading(true);
      setError('');
      setGstr1Validation(null);
      setGstr1Summary(null);

      const response = await api.get<Gstr1ValidationResult>(
        '/ledgers/tax-ledger/gstr1/validate',
        { params: { from_date: gstr1Period.fromDate, to_date: gstr1Period.toDate } },
      );
      setGstr1Validation(response.data);
      // Always move to the results step so validation errors (or the all-clear)
      // are rendered. Previously we only advanced on success, so an invalid
      // result left the user on the period screen with nothing shown.
      setGstr1Step('validate');

      if (response.data.status === 'valid') {
        setSuccess('Validation passed. You can now view the filing summary.');
      } else {
        setError(
          `Validation found ${response.data.invalid_invoices} invoice(s) with errors. ` +
          'Resolve the issues below before generating GSTR-1.',
        );
      }
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to validate GSTR-1 data'));
    } finally {
      setGstr1Loading(false);
    }
  }

  async function handleGstr1SkipValidation() {
    setGstr1Step('summary');
    try {
      setGstr1Loading(true);
      setError('');
      const response = await api.get<Gstr1Summary>(
        '/ledgers/tax-ledger/gstr1/summary',
        { params: { from_date: gstr1Period.fromDate, to_date: gstr1Period.toDate } },
      );
      setGstr1Summary(response.data);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load GSTR-1 summary'));
    } finally {
      setGstr1Loading(false);
    }
  }

  async function handleGstr1Download(format: 'json' | 'csv' | 'pdf') {
    try {
      setGstr1Downloading(format);
      setError('');
      const response = await api.get(`/ledgers/tax-ledger/gstr1/export-${format}`, {
        params: { from_date: gstr1Period.fromDate, to_date: gstr1Period.toDate },
        responseType: 'blob',
      });
      const url = window.URL.createObjectURL(response.data as Blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `gstr1_${gstr1Period.fromDate}_${gstr1Period.toDate}.${format}`;
      link.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(await getBlobErrorMessage(err, `Unable to download GSTR-1 ${format.toUpperCase()}`));
    } finally {
      setGstr1Downloading(null);
    }
  }

  // ═══════════════════════════════════════════════════════════════════════
  //  Render
  // ═══════════════════════════════════════════════════════════════════════

  return (
    <div className="page-grid">
      {/* ── Tab bar ── */}
      <section className="page-hero">
        <div>
          <p className="eyebrow">GST reports</p>
          <h1 className="page-title">Tax ledger</h1>
          <p className="section-copy">
            Track SGST, CGST &amp; IGST debit/credit and file GSTR-1 returns.
          </p>
        </div>
        <div className="status-chip">
          {tab === 'tax-ledger' ? `${entries.length} rows` : 'GSTR-1'}
        </div>
      </section>

      <div className="tab-bar" style={{ display: 'flex', gap: 0, marginBottom: '0.5rem' }}>
        <button
          type="button"
          className={`button ${tab === 'tax-ledger' ? 'button--primary' : 'button--ghost'}`}
          onClick={() => setTab('tax-ledger')}
        >
          Tax Ledger
        </button>
        <button
          type="button"
          className={`button ${tab === 'gstr1' ? 'button--primary' : 'button--ghost'}`}
          onClick={() => setTab('gstr1')}
        >
          GSTR-1 Filing
        </button>
      </div>

      <StatusToasts
        error={error}
        success={success}
        onClearError={() => setError('')}
        onClearSuccess={() => setSuccess('')}
      />

      {tab === 'tax-ledger' ? (
        <>
          <TaxLedgerFilters
            period={period}
            setPeriod={setPeriod}
            voucherType={voucherType}
            setVoucherType={setVoucherType}
            gstRate={gstRate}
            setGstRate={setGstRate}
            downloading={downloading}
            onDownload={(fmt) => { void handleTaxLedgerDownload(fmt); }}
            activeCurrencyCode={activeCurrencyCode}
            taxLedger={taxLedger}
          />

          <section className="panel stack">
            <div className="panel__header">
              <div>
                <p className="eyebrow">Entries</p>
                <h2 className="nav-panel__title">
                  Invoice + GST rate ledger rows
                </h2>
              </div>
            </div>

            {loading ? (
              <div className="empty-state">Loading tax ledger...</div>
            ) : null}
            {!loading && (!taxLedger || taxLedger.entries.length === 0) ? (
              <div className="empty-state">No tax entries found for this filter.</div>
            ) : null}

            {!loading && entries.length > 0 ? (
              <div
                ref={scrollContainerRef}
                className="table-wrap tax-ledger-scroll"
              >
                <table className="invoice-feed-table tax-ledger-table">
                  <thead className="tax-ledger-thead--sticky">
                    <tr>
                      <th>Date</th>
                      <th>Reference</th>
                      <th>Ledger</th>
                      <th>GSTIN</th>
                      <th>Type</th>
                      <th>GST %</th>
                      <th className="text-right">Taxable</th>
                      <th className="text-right">Dr SGST</th>
                      <th className="text-right">Dr CGST</th>
                      <th className="text-right">Dr IGST</th>
                      <th className="text-right">Cr SGST</th>
                      <th className="text-right">Cr CGST</th>
                      <th className="text-right">Cr IGST</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topPadding > 0 && (
                      <tr>
                        <td colSpan={13} style={{ height: `${topPadding}px`, padding: 0 }} />
                      </tr>
                    )}
                    {virtualItems.map((virtualRow) => {
                      const entry = entries[virtualRow.index];
                      const rowClass =
                        entry.source_voucher_type === 'sales'
                          ? 'tax-ledger-row--sales'
                          : 'tax-ledger-row--purchase';
                      const typeBadgeClass =
                        entry.source_voucher_type === 'sales'
                          ? 'invoice-type-badge invoice-type-badge--sales'
                          : 'invoice-type-badge invoice-type-badge--purchase';

                      return (
                        <tr
                          key={`${entry.entry_type}-${entry.entry_id}-${entry.gst_rate}`}
                          className={rowClass}
                          style={{ height: `${virtualRow.size}px` }}
                        >
                          <td>
                            {new Date(entry.date).toLocaleDateString()}
                          </td>
                          <td>
                            <strong className="text-xs">{entry.reference_number}</strong>
                          </td>
                          <td className="text-xs">{entry.ledger_name}</td>
                          <td className="text-xs" style={{ fontFamily: 'monospace' }}>
                            {entry.ledger_gst || '-'}
                          </td>
                          <td>
                            <div className="tax-ledger-type-cell">
                              <span className={typeBadgeClass}>
                                {entry.source_voucher_type}
                              </span>
                              {entry.entry_type === 'credit_note' ? (
                                <span className="tax-ledger-note-tag">Credit Note</span>
                              ) : null}
                            </div>
                          </td>
                          <td>{entry.gst_rate.toFixed(2)}%</td>
                          <td className="text-right">
                            {formatCurrency(entry.taxable_amount, activeCurrencyCode)}
                          </td>
                          <td className="text-right">
                            {entry.debit_sgst > 0
                              ? formatCurrency(entry.debit_sgst, activeCurrencyCode)
                              : '-'}
                          </td>
                          <td className="text-right">
                            {entry.debit_cgst > 0
                              ? formatCurrency(entry.debit_cgst, activeCurrencyCode)
                              : '-'}
                          </td>
                          <td className="text-right">
                            {entry.debit_igst > 0
                              ? formatCurrency(entry.debit_igst, activeCurrencyCode)
                              : '-'}
                          </td>
                          <td className="text-right">
                            {entry.credit_sgst > 0
                              ? formatCurrency(entry.credit_sgst, activeCurrencyCode)
                              : '-'}
                          </td>
                          <td className="text-right">
                            {entry.credit_cgst > 0
                              ? formatCurrency(entry.credit_cgst, activeCurrencyCode)
                              : '-'}
                          </td>
                          <td className="text-right">
                            {entry.credit_igst > 0
                              ? formatCurrency(entry.credit_igst, activeCurrencyCode)
                              : '-'}
                          </td>
                        </tr>
                      );
                    })}
                    {bottomPadding > 0 && (
                      <tr>
                        <td colSpan={13} style={{ height: `${bottomPadding}px`, padding: 0 }} />
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            ) : null}
          </section>
        </>
      ) : (
        /* ── GSTR-1 Filing Tab ── */
        <Gstr1FilingTab
          period={gstr1Period}
          setPeriod={setGstr1Period}
          step={gstr1Step}
          setStep={setGstr1Step}
          validation={gstr1Validation}
          summary={gstr1Summary}
          loading={gstr1Loading}
          downloading={gstr1Downloading}
          onValidate={() => { void handleGstr1Validate(); }}
          onSkipValidation={() => { void handleGstr1SkipValidation(); }}
          onDownload={(fmt) => { void handleGstr1Download(fmt); }}
          onReset={() => {
            setGstr1Step('select-period');
            setGstr1Validation(null);
            setGstr1Summary(null);
          }}
          activeCurrencyCode={activeCurrencyCode}
        />
      )}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────
   Tax Ledger Filters (shared across Tab)
   ──────────────────────────────────────────────────────────────────────── */

function TaxLedgerFilters({
  period,
  setPeriod,
  voucherType,
  setVoucherType,
  gstRate,
  setGstRate,
  downloading,
  onDownload,
  activeCurrencyCode,
  taxLedger,
}: {
  period: { fromDate: string; toDate: string };
  setPeriod: React.Dispatch<React.SetStateAction<{ fromDate: string; toDate: string }>>;
  voucherType: 'all' | 'sales' | 'purchase';
  setVoucherType: (v: 'all' | 'sales' | 'purchase') => void;
  gstRate: string;
  setGstRate: (v: string) => void;
  downloading: 'pdf' | 'csv' | null;
  onDownload: (fmt: 'pdf' | 'csv') => void;
  activeCurrencyCode: string;
  taxLedger: TaxLedger | null;
}) {
  return (
    <section className="content-grid">
      <article className="panel stack">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Filters</p>
            <h2 className="nav-panel__title">Reporting scope</h2>
          </div>
        </div>

        <div className="field-grid">
          <div className="field">
            <label htmlFor="tax-ledger-from">From</label>
            <input
              id="tax-ledger-from"
              className="input"
              type="date"
              value={period.fromDate}
              onChange={(e) =>
                setPeriod((c) => ({ ...c, fromDate: e.target.value }))
              }
            />
          </div>
          <div className="field">
            <label htmlFor="tax-ledger-to">To</label>
            <input
              id="tax-ledger-to"
              className="input"
              type="date"
              value={period.toDate}
              onChange={(e) =>
                setPeriod((c) => ({ ...c, toDate: e.target.value }))
              }
            />
          </div>
          <div className="field">
            <label htmlFor="tax-ledger-voucher-type">Voucher type</label>
            <select
              id="tax-ledger-voucher-type"
              className="input"
              value={voucherType}
              onChange={(e) =>
                setVoucherType(e.target.value as 'all' | 'sales' | 'purchase')
              }
            >
              <option value="all">All</option>
              <option value="sales">Sales</option>
              <option value="purchase">Purchase</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="tax-ledger-gst-rate">GST rate</label>
            <input
              id="tax-ledger-gst-rate"
              className="input"
              type="number"
              min="0"
              step="0.01"
              placeholder="All rates"
              value={gstRate}
              onChange={(e) => setGstRate(e.target.value)}
            />
          </div>
        </div>

        <div className="button-row">
          <button
            type="button"
            className="button button--primary"
            onClick={() => onDownload('pdf')}
            disabled={downloading !== null}
          >
            {downloading === 'pdf' ? 'Downloading PDF...' : 'Export PDF'}
          </button>
          <button
            type="button"
            className="button button--secondary"
            onClick={() => onDownload('csv')}
            disabled={downloading !== null}
          >
            {downloading === 'csv' ? 'Downloading CSV...' : 'Export CSV'}
          </button>
        </div>

        <div className="summary-box">
          <p className="eyebrow">Net tax</p>
          <p className="summary-box__value">
            {formatCurrency(taxLedger?.totals.net_total_tax ?? 0, activeCurrencyCode)}
          </p>
          <p className="muted-text">
            Dr{' '}
            {formatCurrency(taxLedger?.totals.debit_total_tax ?? 0, activeCurrencyCode)}{' '}
            · Cr{' '}
            {formatCurrency(taxLedger?.totals.credit_total_tax ?? 0, activeCurrencyCode)}
          </p>
        </div>
      </article>

      <article className="panel stack">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Summary</p>
            <h2 className="nav-panel__title">GST bucket balances</h2>
          </div>
        </div>

        <div className="field-grid">
          <div className="summary-box">
            <p className="eyebrow">CGST net</p>
            <p className="summary-box__value">
              {formatCurrency(taxLedger?.totals.net_cgst ?? 0, activeCurrencyCode)}
            </p>
            <p className="muted-text">
              Dr{' '}
              {formatCurrency(taxLedger?.totals.debit_cgst ?? 0, activeCurrencyCode)}{' '}
              · Cr{' '}
              {formatCurrency(taxLedger?.totals.credit_cgst ?? 0, activeCurrencyCode)}
            </p>
          </div>
          <div className="summary-box">
            <p className="eyebrow">SGST net</p>
            <p className="summary-box__value">
              {formatCurrency(taxLedger?.totals.net_sgst ?? 0, activeCurrencyCode)}
            </p>
            <p className="muted-text">
              Dr{' '}
              {formatCurrency(taxLedger?.totals.debit_sgst ?? 0, activeCurrencyCode)}{' '}
              · Cr{' '}
              {formatCurrency(taxLedger?.totals.credit_sgst ?? 0, activeCurrencyCode)}
            </p>
          </div>
          <div className="summary-box">
            <p className="eyebrow">IGST net</p>
            <p className="summary-box__value">
              {formatCurrency(taxLedger?.totals.net_igst ?? 0, activeCurrencyCode)}
            </p>
            <p className="muted-text">
              Dr{' '}
              {formatCurrency(taxLedger?.totals.debit_igst ?? 0, activeCurrencyCode)}{' '}
              · Cr{' '}
              {formatCurrency(taxLedger?.totals.credit_igst ?? 0, activeCurrencyCode)}
            </p>
          </div>
        </div>
      </article>
    </section>
  );
}

/* ────────────────────────────────────────────────────────────────────────
   GSTR-1 Filing Tab
   ──────────────────────────────────────────────────────────────────────── */

function Gstr1FilingTab({
  period,
  setPeriod,
  step,
  validation,
  summary,
  loading,
  downloading,
  onValidate,
  onSkipValidation,
  onDownload,
  onReset,
  activeCurrencyCode,
}: {
  period: { fromDate: string; toDate: string };
  setPeriod: React.Dispatch<React.SetStateAction<{ fromDate: string; toDate: string }>>;
  step: string;
  setStep: (s: Gstr1Step) => void;
  validation: Gstr1ValidationResult | null;
  summary: Gstr1Summary | null;
  loading: boolean;
  downloading: 'json' | 'csv' | 'pdf' | null;
  onValidate: () => void;
  onSkipValidation: () => void;
  onDownload: (fmt: 'json' | 'csv' | 'pdf') => void;
  onReset: () => void;
  activeCurrencyCode: string;
}) {
  if (step === 'select-period') {
    return (
      <section className="content-grid">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Step 1</p>
              <h2 className="nav-panel__title">Select filing period</h2>
            </div>
          </div>

          <div className="field-grid">
            <div className="field">
              <label htmlFor="gstr1-from">From</label>
              <input
                id="gstr1-from"
                className="input"
                type="date"
                value={period.fromDate}
                onChange={(e) => setPeriod((c) => ({ ...c, fromDate: e.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="gstr1-to">To</label>
              <input
                id="gstr1-to"
                className="input"
                type="date"
                value={period.toDate}
                onChange={(e) => setPeriod((c) => ({ ...c, toDate: e.target.value }))}
              />
            </div>
          </div>

          <div className="button-row">
            <button
              type="button"
              className="button button--primary"
              onClick={onValidate}
              disabled={loading}
            >
              {loading ? 'Validating...' : 'Validate & Proceed'}
            </button>
            <button
              type="button"
              className="button button--ghost"
              onClick={onSkipValidation}
              disabled={loading}
            >
              Skip validation
            </button>
          </div>
        </article>
      </section>
    );
  }

  if (step === 'validate' && validation) {
    return (
      <section className="content-grid">
        <article className="panel stack" style={{ gridColumn: '1 / -1' }}>
          <div className="panel__header">
            <div>
              <p className="eyebrow">Step 2</p>
              <h2 className="nav-panel__title">Validation Results</h2>
            </div>
            <span
              className={`status-chip ${
                validation.status === 'valid' ? 'status-chip--success' : 'status-chip--error'
              }`}
            >
              {validation.status === 'valid' ? '✓ Valid' : '✕ Invalid'}
            </span>
          </div>

          <p className="muted-text" style={{ marginBottom: '1rem' }}>
            {validation.total_invoices} invoice(s) checked:{' '}
            {validation.valid_invoices} valid, {validation.invalid_invoices} with errors
          </p>

          {validation.errors.length > 0 && (
            <div className="table-wrap" style={{ maxHeight: 360, overflow: 'auto' }}>
              <table className="invoice-feed-table">
                <thead>
                  <tr>
                    <th>Invoice #</th>
                    <th>Field</th>
                    <th>Issue</th>
                    <th>Severity</th>
                  </tr>
                </thead>
                <tbody>
                  {validation.errors.map((err, i) => (
                    <tr key={i}>
                      <td className="text-xs">{err.invoice_number}</td>
                      <td className="text-xs">{err.field}</td>
                      <td className="text-xs">{err.message}</td>
                      <td>
                        <span
                          className={`invoice-type-badge ${
                            err.severity === 'error'
                              ? 'invoice-type-badge--purchase'
                              : 'invoice-type-badge--sales'
                          }`}
                        >
                          {err.severity}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {validation.errors.length === 0 && (
            <p style={{ color: 'var(--success, #22c55e)' }}>
              No issues found! Data is ready for filing.
            </p>
          )}

          <div className="button-row" style={{ marginTop: '1rem' }}>
            <button
              type="button"
              className="button"
              onClick={onReset}
            >
              ← Back
            </button>
            {validation.status === 'valid' && (
              <button
                type="button"
                className="button button--primary"
                onClick={() => {
                  void onSkipValidation();
                }}
              >
                View Summary →
              </button>
            )}
          </div>
        </article>
      </section>
    );
  }

  if (step === 'summary' && summary) {
    return (
      <>
        <Gstr1SummaryView
          summary={summary}
          activeCurrencyCode={activeCurrencyCode}
        />

        {/* Download buttons */}
        <section className="content-grid">
          <article className="panel stack">
            <div className="panel__header">
              <div>
                <p className="eyebrow">Step 3</p>
                <h2 className="nav-panel__title">Download Exports</h2>
              </div>
            </div>

            <div className="button-row">
              <button
                type="button"
                className="button button--primary"
                onClick={() => onDownload('json')}
                disabled={downloading !== null}
              >
                {downloading === 'json' ? 'Downloading...' : 'Download JSON'}
              </button>
              <button
                type="button"
                className="button button--secondary"
                onClick={() => onDownload('csv')}
                disabled={downloading !== null}
              >
                {downloading === 'csv' ? 'Downloading...' : 'Download CSV'}
              </button>
              <button
                type="button"
                className="button button--ghost"
                onClick={() => onDownload('pdf')}
                disabled={downloading !== null}
              >
                {downloading === 'pdf' ? 'Downloading...' : 'Download PDF'}
              </button>
            </div>
          </article>

          <article className="panel stack">
            <div className="panel__header">
              <div>
                <p className="eyebrow">Actions</p>
                <h2 className="nav-panel__title">Navigation</h2>
              </div>
            </div>
            <button
              type="button"
              className="button button--ghost"
              onClick={onReset}
            >
              ← Back to period selection
            </button>
          </article>
        </section>
      </>
    );
  }

  // Loading state for summary fetch
  if (step === 'summary' && !summary) {
    return (
      <section className="content-grid">
        <article className="panel stack">
          <div className="empty-state">Loading GSTR-1 summary...</div>
        </article>
      </section>
    );
  }

  return null;
}

/* ────────────────────────────────────────────────────────────────────────
   GSTR-1 Summary View
   ──────────────────────────────────────────────────────────────────────── */

function Gstr1SummaryView({
  summary,
  activeCurrencyCode,
}: {
  summary: Gstr1Summary;
  activeCurrencyCode: string;
}) {
  return (
    <section className="content-grid">
      {/* B2B / B2CL / B2CS */}
      <article className="panel stack">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Filing summary</p>
            <h2 className="nav-panel__title">Supply categories</h2>
          </div>
        </div>

        <div className="field-grid">
          <CategoryCard label="B2B (with GSTIN)" data={summary.b2b} currency={activeCurrencyCode} />
          <CategoryCard label="B2CL (&gt;2.5L)" data={summary.b2cl} currency={activeCurrencyCode} />
          <CategoryCard label="B2CS (≤2.5L)" data={summary.b2cs} currency={activeCurrencyCode} />
          <CategoryCard label="Nil Rated/Exempt" data={summary.nil_rated} currency={activeCurrencyCode} />
        </div>
      </article>

      {/* Credit / Debit Notes */}
      <article className="panel stack">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Adjustments</p>
            <h2 className="nav-panel__title">Credit &amp; Debit Notes</h2>
          </div>
        </div>

        <div className="field-grid">
          <CategoryCard label="Credit Notes" data={summary.credit_notes} currency={activeCurrencyCode} />
          <CategoryCard label="Debit Notes" data={summary.debit_notes} currency={activeCurrencyCode} />
        </div>
      </article>

      {/* HSN Summary */}
      <article className="panel stack" style={{ gridColumn: '1 / -1' }}>
        <div className="panel__header">
          <div>
            <p className="eyebrow">HSN-wise summary</p>
            <h2 className="nav-panel__title">Commodity breakdown</h2>
          </div>
        </div>

        <div className="table-wrap" style={{ maxHeight: 320, overflow: 'auto' }}>
          <table className="invoice-feed-table">
            <thead>
              <tr>
                <th>HSN/SAC</th>
                <th className="text-right">Qty</th>
                <th className="text-right">Taxable Value</th>
                <th className="text-right">CGST</th>
                <th className="text-right">SGST</th>
                <th className="text-right">IGST</th>
                <th className="text-right">Total Tax</th>
              </tr>
            </thead>
            <tbody>
              {summary.hsn_summary.map((item) => (
                <tr key={item.hsn_code}>
                  <td className="text-xs" style={{ fontFamily: 'monospace' }}>
                    {item.hsn_code}
                  </td>
                  <td className="text-right">{item.quantity}</td>
                  <td className="text-right">
                    {formatCurrency(item.taxable_value, activeCurrencyCode)}
                  </td>
                  <td className="text-right">
                    {formatCurrency(item.cgst, activeCurrencyCode)}
                  </td>
                  <td className="text-right">
                    {formatCurrency(item.sgst, activeCurrencyCode)}
                  </td>
                  <td className="text-right">
                    {formatCurrency(item.igst, activeCurrencyCode)}
                  </td>
                  <td className="text-right">
                    {formatCurrency(item.total_tax, activeCurrencyCode)}
                  </td>
                </tr>
              ))}
              {summary.hsn_summary.length === 0 && (
                <tr>
                  <td colSpan={7} className="text-xs text-center muted-text">
                    No HSN data
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </article>

      {/* Document Summary */}
      <article className="panel stack">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Documents</p>
            <h2 className="nav-panel__title">Document summary</h2>
          </div>
        </div>

        <div className="field-grid">
          <div className="summary-box">
            <p className="eyebrow">Total Invoices</p>
            <p className="summary-box__value">{summary.doc_summary.total_invoices}</p>
          </div>
          <div className="summary-box">
            <p className="eyebrow">Credit Notes</p>
            <p className="summary-box__value">{summary.doc_summary.total_credit_notes}</p>
          </div>
          <div className="summary-box">
            <p className="eyebrow">Debit Notes</p>
            <p className="summary-box__value">{summary.doc_summary.total_debit_notes}</p>
          </div>
        </div>
      </article>
    </section>
  );
}

/* ────────────────────────────────────────────────────────────────────────
   Category Card
   ──────────────────────────────────────────────────────────────────────── */

function CategoryCard({
  label,
  data,
  currency,
}: {
  label: string;
  data: {
    invoice_count: number;
    taxable_value: number;
    cgst: number;
    sgst: number;
    igst: number;
    total_tax: number;
  };
  currency: string;
}) {
  return (
    <div className="summary-box">
      <p className="eyebrow">{label}</p>
      <p className="summary-box__value">
        {data.invoice_count} invoice(s)
      </p>
      <p className="muted-text">
        Taxable: {formatCurrency(data.taxable_value, currency)}
        {data.total_tax > 0
          ? ` · Tax: ${formatCurrency(data.total_tax, currency)}`
          : ''}
      </p>
    </div>
  );
}
