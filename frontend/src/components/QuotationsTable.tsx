import { Link } from 'react-router-dom';
import type { Quotation } from '../types/api';
import formatCurrency, { formatDate } from '../utils/formatting';
import {
  QUOTATION_DOCUMENT_LABELS,
  QUOTATION_STATUS_LABELS,
  allowedQuotationActions,
  quotationStatusBadgeClass,
} from '../utils/quotationStatus';

type QuotationsTableProps = {
  quotations: Quotation[];
  onOpen: (quotation: Quotation) => void;
  onConvert: (quotation: Quotation) => void;
};

export default function QuotationsTable({ quotations, onOpen, onConvert }: QuotationsTableProps) {
  return (
    <div className="invoice-feed-table-wrap">
      <table className="invoice-feed-table" data-testid="quotations-table">
        <thead>
          <tr>
            <th scope="col">Number</th>
            <th scope="col">Type</th>
            <th scope="col">Date</th>
            <th scope="col">Party</th>
            <th scope="col" style={{ textAlign: 'right' }}>Amount</th>
            <th scope="col">Valid until</th>
            <th scope="col">Status</th>
            <th scope="col">Invoice</th>
            <th scope="col" aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {quotations.map((quotation) => {
            const canConvert = allowedQuotationActions(quotation).includes('convert');
            return (
              <tr key={quotation.id} data-testid={`quotation-row-${quotation.id}`}>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <button type="button" className="link-button" onClick={() => onOpen(quotation)}>
                    {quotation.quotation_number}
                  </button>
                </td>
                <td>{QUOTATION_DOCUMENT_LABELS[quotation.document_type]}</td>
                <td style={{ whiteSpace: 'nowrap' }}>{formatDate(quotation.quotation_date)}</td>
                <td>{quotation.ledger_name || '—'}</td>
                <td style={{ textAlign: 'right' }}>
                  {formatCurrency(quotation.total_amount, quotation.company_currency_code || 'INR')}
                </td>
                <td style={{ whiteSpace: 'nowrap' }} className={quotation.is_expired ? 'error-text' : undefined}>
                  {quotation.valid_until ? formatDate(quotation.valid_until) : 'No expiry'}
                </td>
                <td>
                  <span className={quotationStatusBadgeClass(quotation.display_status)}>
                    {QUOTATION_STATUS_LABELS[quotation.display_status]}
                  </span>
                </td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  {quotation.converted_invoice_number ? (
                    <Link to={`/invoices-view?search=${encodeURIComponent(quotation.converted_invoice_number)}`}>
                      {quotation.converted_invoice_number}
                    </Link>
                  ) : '—'}
                </td>
                <td>
                  {canConvert ? (
                    <button
                      type="button"
                      className="button button--ghost button--small"
                      aria-label="Convert to invoice"
                      title="Convert to invoice"
                      onClick={() => onConvert(quotation)}
                    >
                      Convert
                    </button>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
