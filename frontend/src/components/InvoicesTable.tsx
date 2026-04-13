import type { Invoice } from '../types/api';
import formatCurrency from '../utils/formatting';

interface InvoicesTableProps {
  invoices: Invoice[];
  onRowClick: (invoice: Invoice) => void;
}

export default function InvoicesTable({ invoices, onRowClick }: InvoicesTableProps) {
  return (
    <div className="invoice-feed-table-wrap">
      <table className="invoice-feed-table">
        <thead>
          <tr>
            <th>Invoice #</th>
            <th>Date</th>
            <th>Buyer / Supplier</th>
            <th>Amount</th>
            <th>Type</th>
            <th>Status</th>
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
                  {new Date(invoice.invoice_date).toLocaleDateString()}
                </td>
                <td>
                  <div className="invoice-feed-table__ledger">{invoice.ledger?.name || 'Unknown'}</div>
                  {invoice.supplier_invoice_number && (
                    <div className="invoice-feed-table__meta">Ref: {invoice.supplier_invoice_number}</div>
                  )}
                </td>
                <td className="invoice-feed-table__amount">
                  {formatCurrency(invoice.total_amount)}
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
