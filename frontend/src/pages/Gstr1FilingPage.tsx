import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api, { getApiErrorMessage, getBlobErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import ScopeBar, { Metric } from '../components/ScopeBar';
import DateRangePresets from '../components/DateRangePresets';
import { useFY } from '../context/FYContext';
import type { CompanyProfile, Gstr1Summary, Gstr1ValidationResult } from '../types/api';
import formatCurrency from '../utils/formatting';
import { toIsoDate } from '../utils/dateRanges';

type Gstr1Step = 'select-period' | 'validate' | 'summary';

const STEPS: { key: Gstr1Step; label: string }[] = [
  { key: 'select-period', label: 'Period' },
  { key: 'validate', label: 'Validate' },
  { key: 'summary', label: 'Summary' },
];

function defaultDateRange() {
  const today = new Date();
  const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);
  return { fromDate: toIsoDate(firstDay), toDate: toIsoDate(today) };
}

export default function Gstr1FilingPage() {
  const { activeFY } = useFY();

  const [period, setPeriod] = useState(() => ({
    fromDate: activeFY?.start_date ?? defaultDateRange().fromDate,
    toDate: activeFY?.end_date ?? defaultDateRange().toDate,
  }));
  const [step, setStep] = useState<Gstr1Step>('select-period');
  const [validation, setValidation] = useState<Gstr1ValidationResult | null>(null);
  const [summary, setSummary] = useState<Gstr1Summary | null>(null);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState<'json' | 'csv' | 'pdf' | null>(null);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const activeCurrencyCode = company?.currency_code || 'USD';

  useEffect(() => {
    api.get<CompanyProfile>('/company/')
      .then((response) => setCompany(response.data))
      .catch(() => setCompany(null));
  }, []);

  useEffect(() => {
    setPeriod({
      fromDate: activeFY?.start_date ?? defaultDateRange().fromDate,
      toDate: activeFY?.end_date ?? defaultDateRange().toDate,
    });
  }, [activeFY]);

  function reset() {
    setStep('select-period');
    setValidation(null);
    setSummary(null);
  }

  // A return is a statement about one period, so a validation pass or a summary
  // belongs to the period it was run for. Moving the dates has to discard both
  // rather than leave last period's figures on screen under this period's
  // heading.
  function changePeriod(next: { fromDate: string; toDate: string }) {
    setPeriod(next);
    reset();
  }

  async function handleValidate() {
    try {
      setLoading(true);
      setError('');
      setValidation(null);
      setSummary(null);

      const response = await api.get<Gstr1ValidationResult>(
        '/ledgers/tax-ledger/gstr1/validate',
        { params: { from_date: period.fromDate, to_date: period.toDate } },
      );
      setValidation(response.data);
      // Always move to the results step so validation errors (or the all-clear)
      // are rendered. Previously we only advanced on success, so an invalid
      // result left the user on the period screen with nothing shown.
      setStep('validate');

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
      setLoading(false);
    }
  }

  async function handleSummary() {
    setStep('summary');
    try {
      setLoading(true);
      setError('');
      const response = await api.get<Gstr1Summary>(
        '/ledgers/tax-ledger/gstr1/summary',
        { params: { from_date: period.fromDate, to_date: period.toDate } },
      );
      setSummary(response.data);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load GSTR-1 summary'));
    } finally {
      setLoading(false);
    }
  }

  async function handleDownload(format: 'json' | 'csv' | 'pdf') {
    try {
      setDownloading(format);
      setError('');
      const response = await api.get(`/ledgers/tax-ledger/gstr1/export-${format}`, {
        params: { from_date: period.fromDate, to_date: period.toDate },
        responseType: 'blob',
      });
      const url = window.URL.createObjectURL(response.data as Blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `gstr1_${period.fromDate}_${period.toDate}.${format}`;
      link.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(await getBlobErrorMessage(err, `Unable to download GSTR-1 ${format.toUpperCase()}`));
    } finally {
      setDownloading(null);
    }
  }

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">GST reports</p>
          <h1 className="page-title">GSTR-1 filing</h1>
          <p className="section-copy">
            Validate a period&apos;s invoices, review the return category by category, and export it for filing.
          </p>
        </div>
        <Link className="button button--ghost button--small" to="/tax-ledger">
          Tax ledger
        </Link>
      </section>

      <StepRail step={step} />

      <StatusToasts
        error={error}
        success={success}
        onClearError={() => setError('')}
        onClearSuccess={() => setSuccess('')}
      />

      {/* One bar for the whole return: the period it covers, how it validated,
          and whatever the current step lets you do with it. The wizard used to
          restate the period as a panel of its own on step 1 and then hide it
          entirely on steps 2 and 3, so the figures on screen stopped saying
          which months they were for. */}
      <ScopeBar
        presets={<DateRangePresets value={period} onChange={changePeriod} fy={activeFY} label="Filing period" />}
        metrics={validation ? (
          <>
            <Metric label="Invoices checked" value={validation.total_invoices} />
            <Metric label="Valid" value={validation.valid_invoices} tone="accent" />
            <Metric
              label="With errors"
              value={validation.invalid_invoices}
              tone={validation.invalid_invoices > 0 ? 'danger' : undefined}
            />
          </>
        ) : undefined}
        actions={(
          <>
            {step === 'select-period' ? (
              <>
                <button
                  type="button"
                  className="button button--primary button--small"
                  onClick={() => { void handleValidate(); }}
                  disabled={loading}
                >
                  {loading ? 'Validating…' : 'Validate & proceed'}
                </button>
                <button
                  type="button"
                  className="button button--ghost button--small"
                  onClick={() => { void handleSummary(); }}
                  disabled={loading}
                >
                  Skip validation
                </button>
              </>
            ) : null}

            {step === 'validate' ? (
              <>
                <button type="button" className="button button--ghost button--small" onClick={reset}>
                  Back
                </button>
                {validation?.status === 'valid' ? (
                  <button
                    type="button"
                    className="button button--primary button--small"
                    onClick={() => { void handleSummary(); }}
                  >
                    View summary
                  </button>
                ) : (
                  <button
                    type="button"
                    className="button button--secondary button--small"
                    onClick={() => { void handleValidate(); }}
                    disabled={loading}
                  >
                    {loading ? 'Re-checking…' : 'Re-run validation'}
                  </button>
                )}
              </>
            ) : null}

            {step === 'summary' ? (
              <>
                <button type="button" className="button button--ghost button--small" onClick={reset}>
                  Back
                </button>
                {(['json', 'csv', 'pdf'] as const).map((format) => (
                  <button
                    key={format}
                    type="button"
                    className={`button button--small ${format === 'json' ? 'button--primary' : 'button--secondary'}`}
                    onClick={() => { void handleDownload(format); }}
                    disabled={downloading !== null || !summary}
                  >
                    {downloading === format ? 'Downloading…' : `Export ${format.toUpperCase()}`}
                  </button>
                ))}
              </>
            ) : null}
          </>
        )}
      >
        <div className="field">
          <label htmlFor="gstr1-from">From</label>
          <input
            id="gstr1-from"
            className="input"
            type="date"
            value={period.fromDate}
            onChange={(e) => changePeriod({ ...period, fromDate: e.target.value })}
          />
        </div>
        <div className="field">
          <label htmlFor="gstr1-to">To</label>
          <input
            id="gstr1-to"
            className="input"
            type="date"
            value={period.toDate}
            onChange={(e) => changePeriod({ ...period, toDate: e.target.value })}
          />
        </div>
      </ScopeBar>

      {step === 'select-period' ? (
        <section className="content-grid content-grid--single">
          <article className="panel stack">
            <div className="panel__header">
              <div>
                <p className="eyebrow">Step 1</p>
                <h2 className="nav-panel__title">Choose the filing period</h2>
              </div>
            </div>
            <p className="section-copy">
              Set the period in the bar above, then validate. Validation checks every sales invoice
              and note in the period for the fields GSTR-1 requires — a missing or malformed GSTIN,
              a place of supply that does not match the tax charged, an HSN code that is absent.
              Skipping it goes straight to the summary, which is fine for a dry run but will carry
              any of those problems into the export.
            </p>
          </article>
        </section>
      ) : null}

      {step === 'validate' && validation ? (
        <section className="content-grid content-grid--single">
          <article className="panel stack">
            <div className="panel__header">
              <div>
                <p className="eyebrow">Step 2</p>
                <h2 className="nav-panel__title">Validation results</h2>
              </div>
              <span
                className={`status-chip ${
                  validation.status === 'valid' ? 'status-chip--success' : 'status-chip--error'
                }`}
              >
                {validation.status === 'valid' ? '✓ Valid' : '✕ Invalid'}
              </span>
            </div>

            {validation.errors.length > 0 ? (
              <div className="table-wrap" style={{ maxHeight: 480, overflow: 'auto' }}>
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
            ) : (
              <div className="empty-state">No issues found — this period is ready for filing.</div>
            )}
          </article>
        </section>
      ) : null}

      {step === 'summary' ? (
        summary ? (
          <Gstr1SummaryView summary={summary} activeCurrencyCode={activeCurrencyCode} />
        ) : (
          <section className="content-grid content-grid--single">
            <article className="panel stack">
              <div className="empty-state">Loading GSTR-1 summary...</div>
            </article>
          </section>
        )
      ) : null}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────
   Step rail
   ──────────────────────────────────────────────────────────────────────── */

/** Where you are in a three-step return, and how much of it is behind you. As a
 *  tab inside the tax ledger the wizard had no such marker: each step replaced
 *  the last with no sense of how many were left. */
function StepRail({ step }: { step: Gstr1Step }) {
  const current = STEPS.findIndex((s) => s.key === step);

  return (
    <ol className="step-rail">
      {STEPS.map((entry, index) => (
        <li
          key={entry.key}
          className={`step-rail__item${
            index < current ? ' step-rail__item--done' : index === current ? ' step-rail__item--current' : ''
          }`}
          aria-current={index === current ? 'step' : undefined}
        >
          <span className="step-rail__index">{index < current ? '✓' : index + 1}</span>
          {entry.label}
        </li>
      ))}
    </ol>
  );
}

/* ────────────────────────────────────────────────────────────────────────
   GSTR-1 Summary View
   ──────────────────────────────────────────────────────────────────────── */

/* The six supply categories, in the order the return puts them. Splitting them
   across a "categories" panel and an "adjustments" panel made two columns of
   unequal height where the reader wants one comparable set — and the narrow
   one wrapped "0 invoice(s)" onto two lines at .summary-box's 2rem. */
const CATEGORIES: { key: keyof Pick<Gstr1Summary, 'b2b' | 'b2cl' | 'b2cs' | 'nil_rated' | 'credit_notes' | 'debit_notes'>; label: string }[] = [
  { key: 'b2b', label: 'B2B (with GSTIN)' },
  { key: 'b2cl', label: 'B2CL (>2.5L)' },
  { key: 'b2cs', label: 'B2CS (≤2.5L)' },
  { key: 'nil_rated', label: 'Nil rated / exempt' },
  { key: 'credit_notes', label: 'Credit notes' },
  { key: 'debit_notes', label: 'Debit notes' },
];

function Gstr1SummaryView({
  summary,
  activeCurrencyCode,
}: {
  summary: Gstr1Summary;
  activeCurrencyCode: string;
}) {
  const docs = summary.doc_summary;

  return (
    <>
      <section className="content-grid content-grid--single">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Filing summary</p>
              <h2 className="nav-panel__title">Return categories</h2>
            </div>
            <div className="metric-strip">
              <Metric label="Invoices" value={docs.total_invoices} />
              <Metric label="Credit notes" value={docs.total_credit_notes} />
              <Metric label="Debit notes" value={docs.total_debit_notes} />
            </div>
          </div>

          <div className="gstr1-categories">
            {CATEGORIES.map((category) => (
              <CategoryCard
                key={category.key}
                label={category.label}
                data={summary[category.key]}
                currency={activeCurrencyCode}
              />
            ))}
          </div>
        </article>
      </section>

      <section className="content-grid content-grid--single">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">HSN-wise summary</p>
              <h2 className="nav-panel__title">Commodity breakdown</h2>
            </div>
            <div className="status-chip">{summary.hsn_summary.length} codes</div>
          </div>

          <div className="table-wrap" style={{ maxHeight: 420, overflow: 'auto' }}>
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
      </section>
    </>
  );
}

/* ────────────────────────────────────────────────────────────────────────
   Category Card
   ──────────────────────────────────────────────────────────────────────── */

/* Taxable value leads. A return is filed on values, not on how many documents
   carried them — the count is the qualifier, which is the opposite of the way
   this card used to read. */
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
    <div className={`gstr1-category${data.invoice_count === 0 ? ' gstr1-category--empty' : ''}`}>
      <p className="eyebrow">{label}</p>
      <p className="gstr1-category__value">{formatCurrency(data.taxable_value, currency)}</p>
      <p className="gstr1-category__meta">
        <span>{data.invoice_count} {data.invoice_count === 1 ? 'document' : 'documents'}</span>
        <span>Tax {formatCurrency(data.total_tax, currency)}</span>
      </p>
    </div>
  );
}
