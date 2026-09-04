import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useVirtualizer } from '@tanstack/react-virtual';
import api, { getApiErrorMessage, getBlobErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import ScopeBar from '../components/ScopeBar';
import DateRangePresets from '../components/DateRangePresets';
import { useFY } from '../context/FYContext';
import type {
  CompanyProfile,
  TaxLedger,
  TaxLiability,
  TaxLiabilityBucket,
} from '../types/api';
import formatCurrency from '../utils/formatting';

function defaultDateRange() {
  const today = new Date();
  const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);
  const toIso = (date: Date) => date.toISOString().slice(0, 10);
  return { fromDate: toIso(firstDay), toDate: toIso(today) };
}

export default function TaxLedgerPage() {
  const { activeFY } = useFY();

  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

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

  // ═══════════════════════════════════════════════════════════════════════
  //  Load & export
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
  //  Render
  // ═══════════════════════════════════════════════════════════════════════

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">GST reports</p>
          <h1 className="page-title">Tax ledger</h1>
          <p className="section-copy">
            Track SGST, CGST &amp; IGST debit and credit across every voucher in the period.
          </p>
        </div>
        <div className="page-hero__aside">
          <div className="status-chip">{entries.length} rows</div>
          {/* Filing used to be the second half of this page. It has its own
              route now, so the ledger keeps the link that the tab bar was. */}
          <Link className="button button--ghost button--small" to="/gstr1">
            GSTR-1 filing
          </Link>
        </div>
      </section>

      <StatusToasts
        error={error}
        success={success}
        onClearError={() => setError('')}
        onClearSuccess={() => setSuccess('')}
      />

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
        activeFY={activeFY}
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
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────
   Tax Ledger scope + period totals
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
  activeFY,
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
  activeFY: { start_date: string; end_date: string } | null;
}) {
  const totals = taxLedger?.totals;

  return (
    <>
      {/* The exports carry the same scope as the filters, so they ride in the
          bar rather than in a button row that would read as an action on the
          entries table below. */}
      <ScopeBar
        presets={<DateRangePresets value={period} onChange={setPeriod} fy={activeFY} />}
        actions={(
          <>
            <button
              type="button"
              className="button button--primary button--small"
              onClick={() => onDownload('pdf')}
              disabled={downloading !== null}
            >
              {downloading === 'pdf' ? 'Downloading…' : 'Export PDF'}
            </button>
            <button
              type="button"
              className="button button--secondary button--small"
              onClick={() => onDownload('csv')}
              disabled={downloading !== null}
            >
              {downloading === 'csv' ? 'Downloading…' : 'Export CSV'}
            </button>
          </>
        )}
      >
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
      </ScopeBar>

      <article className="panel stack">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Summary</p>
            <h2 className="nav-panel__title">Period totals</h2>
          </div>
          <span className="status-chip">
            {voucherType === 'all' ? 'Sales \u0026 purchase' : voucherType === 'sales' ? 'Sales only' : 'Purchase only'}
          </span>
        </div>

        {/* Taxable value + GST = gross value. Laying the three out as the
            equation they are saves the reader adding two cards together to
            find the figure that has to tie back to the books. */}
        <div className="tax-total-flow">
          <TaxTotalTile
            label="Taxable value"
            value={totals?.net_taxable ?? 0}
            debit={totals?.debit_taxable ?? 0}
            credit={totals?.credit_taxable ?? 0}
            currency={activeCurrencyCode}
          />
          <span className="tax-total-flow__op" aria-hidden="true">+</span>
          <TaxTotalTile
            label="GST"
            value={totals?.net_total_tax ?? 0}
            debit={totals?.debit_total_tax ?? 0}
            credit={totals?.credit_total_tax ?? 0}
            currency={activeCurrencyCode}
          />
          <span className="tax-total-flow__op" aria-hidden="true">=</span>
          <TaxTotalTile
            label="Gross value"
            hint="Taxable + GST"
            value={totals?.net_gross ?? 0}
            debit={totals?.debit_gross ?? 0}
            credit={totals?.credit_gross ?? 0}
            currency={activeCurrencyCode}
            headline
          />
        </div>

        <div className="tax-bucket-group">
          <p className="eyebrow">GST bucket balances</p>
          <div className="tax-bucket-grid">
            <TaxTotalTile
              label="CGST"
              value={totals?.net_cgst ?? 0}
              debit={totals?.debit_cgst ?? 0}
              credit={totals?.credit_cgst ?? 0}
              currency={activeCurrencyCode}
              compact
            />
            <TaxTotalTile
              label="SGST"
              value={totals?.net_sgst ?? 0}
              debit={totals?.debit_sgst ?? 0}
              credit={totals?.credit_sgst ?? 0}
              currency={activeCurrencyCode}
              compact
            />
            <TaxTotalTile
              label="IGST"
              value={totals?.net_igst ?? 0}
              debit={totals?.debit_igst ?? 0}
              credit={totals?.credit_igst ?? 0}
              currency={activeCurrencyCode}
              compact
            />
          </div>
        </div>
      </article>

      <TaxLiabilityPanel
        liability={taxLedger?.liability ?? null}
        voucherType={voucherType}
        gstRate={gstRate}
        currency={activeCurrencyCode}
      />
    </>
  );
}

/* What has to be paid, which is not the same question as what was billed.

   The set-off is done on the server (s.49A/49B, r.88A) because it cannot be
   read off the bucket balances above: CGST credit is useless against an SGST
   liability, so heads that net to zero between them can still leave cash due. */
function TaxLiabilityPanel({
  liability,
  voucherType,
  gstRate,
  currency,
}: {
  liability: TaxLiability | null;
  voucherType: 'all' | 'sales' | 'purchase';
  gstRate: string;
  currency: string;
}) {
  const rows: Array<{ head: string; bucket: TaxLiabilityBucket }> = [
    { head: 'CGST', bucket: liability?.cgst ?? EMPTY_BUCKET },
    { head: 'SGST', bucket: liability?.sgst ?? EMPTY_BUCKET },
    { head: 'IGST', bucket: liability?.igst ?? EMPTY_BUCKET },
  ];

  // A narrowed ledger is a partial return. Sales-only hides the input credit
  // that would reduce this figure, so the number stops being the liability and
  // starts being an upper bound — worth saying outright rather than letting the
  // scope chip carry it.
  const narrowed = voucherType !== 'all' || gstRate.trim() !== '';

  return (
    <article className="panel stack">
      <div className="panel__header">
        <div>
          <p className="eyebrow">Liability</p>
          <h2 className="nav-panel__title">GST payable</h2>
        </div>
      </div>

      {narrowed ? (
        <p className="field-warning">
          {voucherType === 'sales'
            ? 'Filtered to sales, so no input credit is set off — this is output tax, not what you owe.'
            : voucherType === 'purchase'
              ? 'Filtered to purchases, so there is no output tax to set credit against.'
              : `Filtered to ${gstRate}% GST, so this covers one rate rather than the whole return.`}
        </p>
      ) : null}

      <div className="tax-payable-grid">
        <TaxTotalTile
          label="Payable in cash"
          hint="After credit set-off"
          value={liability?.payable ?? 0}
          debit={liability?.output_tax ?? 0}
          credit={liability?.input_credit ?? 0}
          debitLabel="Output tax"
          creditLabel="Input credit"
          currency={currency}
          headline
        />
        <div className="tax-setoff">
          <table className="tax-setoff__table">
            <thead>
              <tr>
                <th>Head</th>
                <th className="text-right">Output tax</th>
                <th className="text-right">Input credit</th>
                <th className="text-right">Set off</th>
                <th className="text-right">Payable</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ head, bucket }) => (
                <tr key={head}>
                  <th scope="row">{head}</th>
                  <td className="text-right">{formatCurrency(bucket.output_tax, currency)}</td>
                  <td className="text-right">{formatCurrency(bucket.input_credit, currency)}</td>
                  <td className="text-right">{formatCurrency(bucket.credit_used, currency)}</td>
                  <td className="text-right tax-setoff__payable">
                    {formatCurrency(bucket.payable, currency)}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row">Total</th>
                <td className="text-right">{formatCurrency(liability?.output_tax ?? 0, currency)}</td>
                <td className="text-right">{formatCurrency(liability?.input_credit ?? 0, currency)}</td>
                <td className="text-right">{formatCurrency(liability?.credit_used ?? 0, currency)}</td>
                <td className="text-right tax-setoff__payable">
                  {formatCurrency(liability?.payable ?? 0, currency)}
                </td>
              </tr>
            </tfoot>
          </table>

          <p className="field-hint tax-setoff__note">
            {(liability?.credit_carried_forward ?? 0) > 0 ? (
              <>
                <strong>{formatCurrency(liability?.credit_carried_forward ?? 0, currency)}</strong>
                {' '}of credit is left over and carries forward.{' '}
              </>
            ) : null}
            Computed from vouchers in this period alone — it does not include credit
            carried in from earlier periods, reverse charge, or your cash ledger balance.
          </p>
        </div>
      </div>
    </article>
  );
}

const EMPTY_BUCKET: TaxLiabilityBucket = {
  output_tax: 0,
  input_credit: 0,
  credit_used: 0,
  payable: 0,
  credit_carried_forward: 0,
};

/* One period total: the net figure, with the debit and credit sides it came
   from underneath. Sales sit on the debit side and purchases on the credit
   side, matching the Dr/Cr columns of the entries table. */
function TaxTotalTile({
  label,
  hint,
  value,
  debit,
  credit,
  debitLabel = 'Dr',
  creditLabel = 'Cr',
  currency,
  headline = false,
  compact = false,
}: {
  label: string;
  hint?: string;
  value: number;
  debit: number;
  credit: number;
  debitLabel?: string;
  creditLabel?: string;
  currency: string;
  headline?: boolean;
  compact?: boolean;
}) {
  const className = [
    'tax-total',
    headline ? 'tax-total--headline' : '',
    compact ? 'tax-total--compact' : '',
    value < 0 ? 'tax-total--negative' : '',
  ].filter(Boolean).join(' ');

  return (
    <div className={className}>
      <p className="eyebrow tax-total__label">
        {label}
        {hint ? <span className="tax-total__hint">{hint}</span> : null}
      </p>
      <p className="tax-total__value">{formatCurrency(value, currency)}</p>
      <p className="tax-total__split">
        <span>{debitLabel} <b>{formatCurrency(debit, currency)}</b></span>
        <span>{creditLabel} <b>{formatCurrency(credit, currency)}</b></span>
      </p>
    </div>
  );
}
