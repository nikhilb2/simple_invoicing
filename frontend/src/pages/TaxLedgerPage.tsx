import { useEffect, useMemo, useState } from 'react';
import api, { getApiErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import { useFY } from '../context/FYContext';
import type { CompanyProfile, TaxLedger } from '../types/api';
import formatCurrency from '../utils/formatting';

function defaultDateRange() {
  const today = new Date();
  const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);
  const toIso = (date: Date) => date.toISOString().slice(0, 10);

  return {
    fromDate: toIso(firstDay),
    toDate: toIso(today),
  };
}

export default function TaxLedgerPage() {
  const { activeFY } = useFY();
  const [period, setPeriod] = useState(() => ({
    fromDate: activeFY?.start_date ?? defaultDateRange().fromDate,
    toDate: activeFY?.end_date ?? defaultDateRange().toDate,
  }));
  const [voucherType, setVoucherType] = useState<'all' | 'sales' | 'purchase'>('all');
  const [gstRate, setGstRate] = useState('');
  const [taxLedger, setTaxLedger] = useState<TaxLedger | null>(null);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const activeCurrencyCode = company?.currency_code || 'INR';
  const numericGstRate = useMemo(() => {
    if (!gstRate.trim()) return undefined;
    const parsed = Number(gstRate);
    return Number.isFinite(parsed) ? parsed : undefined;
  }, [gstRate]);

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

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">GST reports</p>
          <h1 className="page-title">Tax ledger</h1>
          <p className="section-copy">Track SGST, CGST and IGST debit/credit to monitor net tax due.</p>
        </div>
        <div className="status-chip">{taxLedger?.entries.length ?? 0} rows</div>
      </section>

      <StatusToasts error={error} onClearError={() => setError('')} onClearSuccess={() => {}} />

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
                onChange={(event) => setPeriod((current) => ({ ...current, fromDate: event.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="tax-ledger-to">To</label>
              <input
                id="tax-ledger-to"
                className="input"
                type="date"
                value={period.toDate}
                onChange={(event) => setPeriod((current) => ({ ...current, toDate: event.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="tax-ledger-voucher-type">Voucher type</label>
              <select
                id="tax-ledger-voucher-type"
                className="input"
                value={voucherType}
                onChange={(event) => setVoucherType(event.target.value as 'all' | 'sales' | 'purchase')}
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
                onChange={(event) => setGstRate(event.target.value)}
              />
            </div>
          </div>

          <div className="summary-box">
            <p className="eyebrow">Net tax</p>
            <p className="summary-box__value">
              {formatCurrency(taxLedger?.totals.net_total_tax ?? 0, activeCurrencyCode)}
            </p>
            <p className="muted-text">
              Dr {formatCurrency(taxLedger?.totals.debit_total_tax ?? 0, activeCurrencyCode)} · Cr {formatCurrency(taxLedger?.totals.credit_total_tax ?? 0, activeCurrencyCode)}
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
              <p className="summary-box__value">{formatCurrency(taxLedger?.totals.net_cgst ?? 0, activeCurrencyCode)}</p>
              <p className="muted-text">Dr {formatCurrency(taxLedger?.totals.debit_cgst ?? 0, activeCurrencyCode)} · Cr {formatCurrency(taxLedger?.totals.credit_cgst ?? 0, activeCurrencyCode)}</p>
            </div>
            <div className="summary-box">
              <p className="eyebrow">SGST net</p>
              <p className="summary-box__value">{formatCurrency(taxLedger?.totals.net_sgst ?? 0, activeCurrencyCode)}</p>
              <p className="muted-text">Dr {formatCurrency(taxLedger?.totals.debit_sgst ?? 0, activeCurrencyCode)} · Cr {formatCurrency(taxLedger?.totals.credit_sgst ?? 0, activeCurrencyCode)}</p>
            </div>
            <div className="summary-box">
              <p className="eyebrow">IGST net</p>
              <p className="summary-box__value">{formatCurrency(taxLedger?.totals.net_igst ?? 0, activeCurrencyCode)}</p>
              <p className="muted-text">Dr {formatCurrency(taxLedger?.totals.debit_igst ?? 0, activeCurrencyCode)} · Cr {formatCurrency(taxLedger?.totals.credit_igst ?? 0, activeCurrencyCode)}</p>
            </div>
          </div>
        </article>
      </section>

      <section className="panel stack">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Entries</p>
            <h2 className="nav-panel__title">Invoice + GST rate ledger rows</h2>
          </div>
        </div>

        {loading ? <div className="empty-state">Loading tax ledger...</div> : null}
        {!loading && (!taxLedger || taxLedger.entries.length === 0) ? <div className="empty-state">No tax entries found for this filter.</div> : null}

        {!loading && taxLedger && taxLedger.entries.length > 0 ? (
          <div className="table-wrap">
            <table className="invoice-feed-table tax-ledger-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Reference</th>
                  <th>Ledger</th>
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
                {taxLedger.entries.map((entry) => {
                  const rowClass = entry.source_voucher_type === 'sales' ? 'tax-ledger-row--sales' : 'tax-ledger-row--purchase';
                  const typeBadgeClass = entry.source_voucher_type === 'sales' ? 'invoice-type-badge invoice-type-badge--sales' : 'invoice-type-badge invoice-type-badge--purchase';

                  return (
                    <tr key={`${entry.entry_type}-${entry.entry_id}-${entry.gst_rate}`} className={rowClass}>
                      <td>{new Date(entry.date).toLocaleDateString()}</td>
                      <td>
                        <strong>{entry.reference_number}</strong>
                        <div className="table-subtext">{entry.particulars}</div>
                      </td>
                      <td>{entry.ledger_name}</td>
                      <td>
                        <div className="tax-ledger-type-cell">
                          <span className={typeBadgeClass}>{entry.source_voucher_type}</span>
                          {entry.entry_type === 'credit_note' ? <span className="tax-ledger-note-tag">Credit Note</span> : null}
                        </div>
                      </td>
                      <td>{entry.gst_rate.toFixed(2)}%</td>
                      <td className="text-right">{formatCurrency(entry.taxable_amount, activeCurrencyCode)}</td>
                      <td className="text-right">{entry.debit_sgst > 0 ? formatCurrency(entry.debit_sgst, activeCurrencyCode) : '-'}</td>
                      <td className="text-right">{entry.debit_cgst > 0 ? formatCurrency(entry.debit_cgst, activeCurrencyCode) : '-'}</td>
                      <td className="text-right">{entry.debit_igst > 0 ? formatCurrency(entry.debit_igst, activeCurrencyCode) : '-'}</td>
                      <td className="text-right">{entry.credit_sgst > 0 ? formatCurrency(entry.credit_sgst, activeCurrencyCode) : '-'}</td>
                      <td className="text-right">{entry.credit_cgst > 0 ? formatCurrency(entry.credit_cgst, activeCurrencyCode) : '-'}</td>
                      <td className="text-right">{entry.credit_igst > 0 ? formatCurrency(entry.credit_igst, activeCurrencyCode) : '-'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}
