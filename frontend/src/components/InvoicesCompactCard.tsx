import { Eye, Pencil, RotateCcw, Trash2, FileText } from 'lucide-react';
import type { Invoice } from '../types/api';
import formatCurrency from '../utils/formatting';

interface InvoicesCompactCardProps {
  invoice: Invoice;
  currencyCode: string;
  onPreview: (invoice: Invoice) => void;
  onEdit?: (invoice: Invoice) => void;
  onCancel?: (invoice: Invoice) => void;
  onRestore?: (invoice: Invoice) => void;
  onCreditNote?: (invoice: Invoice) => void;
}

  export default function InvoicesCompactCard({ invoice, currencyCode, onPreview, onEdit, onCancel, onRestore, onCreditNote }: InvoicesCompactCardProps) {
  const isCredit = invoice.voucher_type === 'purchase';
  const isCancelled = invoice.status === 'cancelled';

  return (
      <article className={`invoice-compact-card invoice-compact-card--${invoice.voucher_type} ${isCancelled ? 'invoice-compact-card--cancelled' : ''}`}>
        <div className="invoice-compact-card__grid">
        {/* Main Info */}
          <div className="invoice-compact-card__main">
            <div className="invoice-compact-card__head">
            <div>
                <h3 className="invoice-compact-card__ledger">
                {invoice.ledger?.name || 'Unknown Ledger'}
              </h3>
                <p className="invoice-compact-card__meta">
                Invoice #{invoice.invoice_number}
              </p>
              {invoice.supplier_invoice_number && (
                  <p className="invoice-compact-card__meta">
                  Ref: {invoice.supplier_invoice_number}
                </p>
              )}
            </div>
              <div className="invoice-compact-card__badges">
              {isCancelled && (
                  <span className="invoice-compact-card__cancelled-badge">
                  Cancelled
                </span>
              )}
                <span className={`invoice-type-badge invoice-type-badge--${invoice.voucher_type}`}>
                {isCredit ? 'Purchase' : 'Sales'}
              </span>
            </div>
          </div>

          {/* Address and Date */}
            <div className="invoice-compact-card__details">
            {invoice.ledger?.address && (
                <p className="invoice-compact-card__address">{invoice.ledger.address}</p>
            )}
            {invoice.ledger?.phone_number && (
                <p className="invoice-compact-card__meta">{invoice.ledger.phone_number}</p>
            )}
              <p className="invoice-compact-card__meta">
              {new Date(invoice.invoice_date).toLocaleDateString()}
            </p>
          </div>
        </div>

        {/* Items Summary */}
          <div className="invoice-compact-card__items">
            <div>
              <div className="invoice-compact-card__items-count">{invoice.items.length} items</div>
              <div className="invoice-compact-card__items-list">
              {invoice.items.map((item, idx) => (
                  <div key={idx} className="invoice-compact-card__item">
                  Product #{item.product_id} x{item.quantity}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Amount and Actions */}
          <div className="invoice-compact-card__side">
            <div>
              <div className="invoice-compact-card__meta">
              {isCredit ? 'Credit' : 'Debit'}
            </div>
              <div className={`invoice-compact-card__amount invoice-compact-card__amount--${invoice.voucher_type}`}>
              {formatCurrency(invoice.total_amount, invoice.company_currency_code || currencyCode)}
            </div>
            {invoice.total_tax_amount > 0 && (
                <div className="invoice-compact-card__meta">
                Tax: {formatCurrency(invoice.total_tax_amount, invoice.company_currency_code || currencyCode)}
              </div>
            )}
          </div>

          {/* Action Buttons */}
            <div className="invoice-compact-card__actions">
            <button
                type="button"
              onClick={() => onPreview(invoice)}
                className="button button--ghost button--icon"
              title="Preview"
            >
              <Eye size={16} />
            </button>
            {!isCancelled && (
              <>
                <button
                    type="button"
                    className="button button--ghost button--icon"
                  title="Create credit note"
                  onClick={() => onCreditNote?.(invoice)}
                >
                  <FileText size={16} />
                </button>
                <button
                    type="button"
                    className="button button--ghost button--icon"
                  title="Edit"
                  onClick={() => onEdit?.(invoice)}
                >
                  <Pencil size={16} />
                </button>
              </>
            )}
            {isCancelled && (
              <button
                  type="button"
                  className="button button--ghost button--icon"
                title="Restore"
                onClick={() => onRestore?.(invoice)}
              >
                <RotateCcw size={16} />
              </button>
            )}
            {!isCancelled && (
              <button
                  type="button"
                  className="button button--ghost button--icon"
                title="Cancel"
                onClick={() => onCancel?.(invoice)}
              >
                <Trash2 size={16} />
              </button>
            )}
          </div>
        </div>
      </div>
      </article>
  );
}
