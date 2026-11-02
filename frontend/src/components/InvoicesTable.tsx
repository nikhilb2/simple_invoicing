import type { Invoice } from '../types/api';
import formatCurrency from '../utils/formatting';
import { formatInvoiceDateLabel } from '../utils/invoiceDueDate.ts';
import OverdueBadge from './OverdueBadge';

interface InvoicesTableProps {
  invoices: Invoice[];
  currencyCode: string;
  onRowClick: (invoice: Invoice) => void;
}

export default function InvoicesTable({ invoices, currencyCode, onRowClick }: InvoicesTableProps) {
  return (
    <div className="invoice-feed-table-wrap">
      <table className="invoice-feed-table">
        <caption className="sr-only">Invoices</caption>
        <thead>
          <tr>
            <th scope="col">Invoice #</th>
            <th scope="col">Date</th>
            <th scope="col">Due</th>
            <th scope="col">Buyer / Supplier</th>
            <th scope="col">Amount</th>
            <th scope="col">Type</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {invoices.map((invoice) => {
            const isCredit = invoice.voucher_type === 'purchase';
            const isCancelled = invoice.status === 'cancelled';
            const typeLabel = isCredit ? 'Purchase' : 'Sales';

            return (
              <tr
                key={invoice.id}
                onClick={() => onRowClick(invoice)}
                className={isCancelled ? 'is-cancelled' : ''}
              >
                <td className="invoice-feed-table__invoice-number">
                  {invoice.invoice_number}
                </td>
                <td>
                  {formatInvoiceDateLabel(invoice.invoice_date)}
                </td>
                <td className="invoice-feed-table__due">
                  <div>{formatInvoiceDateLabel(invoice.due_date)}</div>
                  <OverdueBadge invoice={invoice} />
                </td>
                <td>
                  <div className="invoice-feed-table__ledger">{invoice.ledger?.name || 'Unknown'}</div>
                  {invoice.supplier_invoice_number && (
                    <div className="invoice-feed-table__meta">Ref: {invoice.supplier_invoice_number}</div>
                  )}
                </td>
                <td className="invoice-feed-table__amount">
                  {formatCurrency(invoice.total_amount, invoice.company_currency_code || currencyCode)}
                </td>
                <td>
                  <span className={`invoice-type-badge invoice-type-badge--${invoice.voucher_type}`}>
                    {typeLabel}
                  </span>
                </td>
                <td>
                  <span className={`invoice-feed-table__status ${isCancelled ? 'invoice-feed-table__status--cancelled' : 'invoice-feed-table__status--active'}`}>
                    {isCancelled ? 'Cancelled' : 'Active'}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
