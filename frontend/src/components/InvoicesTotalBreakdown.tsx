import formatCurrency from '../utils/formatting';

interface Breakdown {
  credit: number;
  debit: number;
  cancelled: number;
  total: number;
}

interface InvoicesTotalBreakdownProps {
  breakdown: Breakdown;
  currencyCode: string;
  title?: string;
  note?: string;
}

export default function InvoicesTotalBreakdown({ breakdown, currencyCode, title, note }: InvoicesTotalBreakdownProps) {
  return (
    <section className="panel invoice-feed-breakdown">
      {(title || note) && (
        <div className="invoice-feed-breakdown__header">
          {title ? <h3 className="invoice-feed-breakdown__title">{title}</h3> : null}
          {note ? <p className="invoice-feed-breakdown__note">{note}</p> : null}
        </div>
      )}
      <div className="invoice-feed-breakdown__grid">
        <div className="invoice-feed-breakdown__cell">
          <div className="invoice-feed-breakdown__label">Total Listed</div>
          <div className="invoice-feed-breakdown__value">{formatCurrency(breakdown.total, currencyCode)}</div>
        </div>
        <div className="invoice-feed-breakdown__cell">
          <div className="invoice-feed-breakdown__label">Credit (Purchase)</div>
          <div className="invoice-feed-breakdown__value invoice-feed-breakdown__value--purchase">{formatCurrency(breakdown.credit, currencyCode)}</div>
        </div>
        <div className="invoice-feed-breakdown__cell">
          <div className="invoice-feed-breakdown__label">Debit (Sales)</div>
          <div className="invoice-feed-breakdown__value invoice-feed-breakdown__value--sales">{formatCurrency(breakdown.debit, currencyCode)}</div>
        </div>
        <div className="invoice-feed-breakdown__cell">
          <div className="invoice-feed-breakdown__label">Cancelled</div>
          <div className="invoice-feed-breakdown__value invoice-feed-breakdown__value--cancelled">{formatCurrency(breakdown.cancelled, currencyCode)}</div>
        </div>
        <div className="invoice-feed-breakdown__cell">
          <div className="invoice-feed-breakdown__label">Active Total</div>
          <div className="invoice-feed-breakdown__value invoice-feed-breakdown__value--active">
            {formatCurrency(breakdown.credit + breakdown.debit, currencyCode)}
          </div>
        </div>
      </div>
    </section>
  );
}
