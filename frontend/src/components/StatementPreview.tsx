import { useState } from 'react';
import api, { getApiErrorMessage } from '../api/client';
import type { CompanyProfile, Ledger, LedgerStatement } from '../types/api';
import formatCurrency from '../utils/formatting';
import SendEmailModal from './SendEmailModal';

type StatementPreviewProps = {
  ledger: Ledger;
  statement: LedgerStatement;
  company: CompanyProfile | null;
  currencyCode: string;
  onClose: () => void;
  onError?: (message: string) => void;
};

export default function StatementPreview({ ledger, statement, company, currencyCode, onClose, onError }: StatementPreviewProps) {
  const [showEmailModal, setShowEmailModal] = useState(false);
  const companyDetails = [
    company?.gst ? `GST: ${company.gst}` : '',
    company?.phone_number ? `Phone: ${company.phone_number}` : '',
  ].filter(Boolean).join(' · ');

  const companyContact = [
    company?.email ? `Email: ${company.email}` : '',
    company?.website ? `Web: ${company.website}` : '',
  ].filter(Boolean).join(' · ');

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="statement-preview-title">
      <div className="modal-panel modal-panel--invoice-preview">
        <div className="panel__header no-print">
          <div>
            <p className="eyebrow">Statement preview</p>
            <h2 id="statement-preview-title" className="nav-panel__title">
              {ledger.name} — {statement.from_date} to {statement.to_date}
            </h2>
          </div>
          <div className="button-row">
            <button type="button" className="button button--secondary" onClick={() => window.print()} title="Print statement" aria-label="Print statement">
              Print
            </button>
            <button
              type="button"
              className="button button--primary"
              title="Download statement PDF"
              aria-label="Download statement PDF"
              onClick={async () => {
                try {
                  const response = await api.get(`/ledgers/${ledger.id}/statement/pdf`, {
                    params: { from_date: statement.from_date, to_date: statement.to_date },
                    responseType: 'blob',
                  });
                  const url = window.URL.createObjectURL(response.data as Blob);
                  const link = document.createElement('a');
                  link.href = url;
                  link.download = `statement_${ledger.name.replace(/\s+/g, '_').slice(0, 30)}_${statement.from_date}_${statement.to_date}.pdf`;
                  link.click();
                  window.URL.revokeObjectURL(url);
                } catch (err) {
                  onError?.(getApiErrorMessage(err, 'Unable to download PDF'));
                }
              }}
            >
              Download PDF
            </button>
            <button
              type="button"
              className="button button--primary"
              onClick={() => setShowEmailModal(true)}
              title="Email statement"
              aria-label="Email statement"
            >
              Email Statement
            </button>
            <button type="button" className="button button--ghost" onClick={onClose} title="Close statement preview" aria-label="Close statement preview">
              Close
            </button>
          </div>
        </div>

        <article className="invoice-print-root invoice-sheet">
          <header className="invoice-sheet__header">
            <div>
              <p className="eyebrow">Issued by</p>
              <h3>{company?.name || 'Company not set'}</h3>
              <p>{company?.address || 'Address not provided'}</p>
              <p>{companyDetails}</p>
              <p>{companyContact}</p>
            </div>
            <div className="invoice-sheet__meta">
              <span className="invoice-badge">Ledger Statement</span>
              <h2>{ledger.name}</h2>
              <p>{new Date(statement.from_date).toLocaleDateString()} – {new Date(statement.to_date).toLocaleDateString()}</p>
            </div>
          </header>

          <section className="invoice-sheet__billto">
            <p className="eyebrow">Ledger</p>
            <h4>{ledger.name}</h4>
            <p>{ledger.address}</p>
            <p>
              GST: {ledger.gst} · Phone: {ledger.phone_number}
              {ledger.email ? ` · ${ledger.email}` : ''}
            </p>
          </section>

          <section style={{ display: 'flex', gap: '12px', marginBottom: '16px' }}>
            {[
              { label: 'Opening Balance', value: statement.opening_balance },
              { label: 'Period Debit', value: statement.period_debit },
              { label: 'Period Credit', value: statement.period_credit },
              { label: 'Closing Balance', value: statement.closing_balance, highlight: true },
            ].map((item) => (
              <div
                key={item.label}
                style={{
                  flex: 1,
                  background: '#f9fafb',
                  border: '1px solid #e5e7eb',
                  borderRadius: '6px',
                  padding: '10px 12px',
                  textAlign: 'center',
                }}
              >
                <p className="eyebrow">{item.label}</p>
                <p style={{
                  fontSize: item.highlight ? '18px' : '14px',
                  fontWeight: 700,
                  color: item.highlight ? '#1a56db' : '#1f2937',
                }}>
                  {formatCurrency(item.value, currencyCode)}
                </p>
              </div>
            ))}
          </section>

          <section>
            <table className="invoice-sheet__table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Voucher</th>
                  <th>Particulars</th>
                  <th className="right">Debit</th>
                  <th className="right">Credit</th>
                </tr>
              </thead>
              <tbody>
                {statement.entries.length === 0 ? (
                  <tr>
                    <td colSpan={5} style={{ textAlign: 'center', color: '#9ca3af' }}>
                      No entries in this period
                    </td>
                  </tr>
                ) : (
                  statement.entries.map((entry, idx) => (
                    <tr key={`${entry.entry_type}-${entry.entry_id}-${idx}`}>
                      <td>{new Date(entry.date).toLocaleDateString()}</td>
                      <td>{entry.voucher_type} #{entry.entry_id}</td>
                      <td>{entry.particulars}</td>
                      <td className="right">{entry.debit > 0 ? formatCurrency(entry.debit, currencyCode) : ''}</td>
                      <td className="right">{entry.credit > 0 ? formatCurrency(entry.credit, currencyCode) : ''}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </section>

          <section className="invoice-sheet__footer">
            <div />
            <div className="invoice-sheet__totals">
              <p className="eyebrow">Closing Balance</p>
              <p className="invoice-sheet__total-value">
                {formatCurrency(statement.closing_balance, currencyCode)}
              </p>
              <p className="muted-text">Generated on {new Date().toLocaleDateString()}</p>
            </div>
          </section>
        </article>
      </div>

      {showEmailModal && (
        <SendEmailModal
          type="statement"
          entityId={ledger.id}
          defaultTo={ledger.email || ''}
          defaultSubject={`Account Statement from ${company?.name || 'Company'}`}
          fromDate={statement.from_date}
          toDate={statement.to_date}
          onClose={() => setShowEmailModal(false)}
          onSuccess={(message) => {
            setShowEmailModal(false);
            // Could show success toast here if needed
          }}
          onError={(message) => onError?.(message)}
        />
      )}
    </div>
  );
}
