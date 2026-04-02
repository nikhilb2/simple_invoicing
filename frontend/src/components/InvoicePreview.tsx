import { useEscapeClose } from '../hooks/useEscapeClose';
import api, { getApiErrorMessage } from '../api/client';
import type { Invoice, Product } from '../types/api';

function formatCurrency(value: number, currencyCode = 'USD') {
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: currencyCode,
    }).format(value);
  } catch {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(value);
  }
}

function getPreviewLineItems(invoice: Invoice, products: Product[]) {
  return (invoice.items || []).map((item) => {
    const matchedProduct = products.find((product) => product.id === item.product_id);
    const gstRate = item.gst_rate ?? matchedProduct?.gst_rate ?? 0;
    const taxableAmount = item.taxable_amount ?? item.unit_price * item.quantity;
    const taxAmount = item.tax_amount ?? taxableAmount * gstRate / 100;
    return {
      ...item,
      productName: matchedProduct?.name || `Product #${item.product_id}`,
      sku: matchedProduct?.sku || 'N/A',
      hsnSac: item.hsn_sac || matchedProduct?.hsn_sac || 'N/A',
      gstRate,
      taxableAmount,
      taxAmount,
    };
  });
}

type InvoicePreviewProps = {
  invoice: Invoice;
  products: Product[];
  currencyCode: string;
  onClose: () => void;
  onError?: (message: string) => void;
};

export default function InvoicePreview({ invoice, products, currencyCode, onClose, onError }: InvoicePreviewProps) {
  const previewCurrencyCode = invoice.company_currency_code || currencyCode;

  useEscapeClose(onClose);

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="invoice-preview-title">
      <div className="modal-panel modal-panel--invoice-preview">
        <div className="panel__header no-print">
          <div>
            <p className="eyebrow">Invoice preview</p>
            <h2 id="invoice-preview-title" className="nav-panel__title">Printable invoice {invoice.invoice_number || `#${invoice.id}`}</h2>
          </div>
          <div className="button-row">
            <button type="button" className="button button--secondary" onClick={() => window.print()} title="Print invoice" aria-label="Print invoice">
              Print
            </button>
            <button
              type="button"
              className="button button--primary"
              title="Download invoice PDF"
              aria-label="Download invoice PDF"
              onClick={async () => {
                try {
                  const response = await api.get(`/invoices/${invoice.id}/pdf`, {
                    responseType: 'blob',
                  });
                  const url = window.URL.createObjectURL(response.data as Blob);
                  const link = document.createElement('a');
                  link.href = url;
                  link.download = `invoice_${invoice.invoice_number || invoice.id}.pdf`;
                  link.click();
                  window.URL.revokeObjectURL(url);
                } catch (err) {
                  onError?.(getApiErrorMessage(err, 'Unable to download PDF'));
                }
              }}
            >
              Download PDF
            </button>
            <button type="button" className="button button--ghost" onClick={onClose} title="Close invoice preview" aria-label="Close invoice preview">
              Close
            </button>
          </div>
        </div>

        <article className="invoice-print-root invoice-sheet">
          <header className="invoice-sheet__header">
            <div>
              <p className="eyebrow">Billed by</p>
              <h3>{invoice.company_name || 'Company not set'}</h3>
              <p>{invoice.company_address || 'Address not provided'}</p>
              <p>
                {invoice.company_gst ? `GST: ${invoice.company_gst}` : ''}
                {invoice.company_phone ? ` · Phone: ${invoice.company_phone}` : ''}
              </p>
              <p>
                {invoice.company_email ? `Email: ${invoice.company_email}` : ''}
                {invoice.company_email && invoice.company_website ? ' · ' : ''}
                {invoice.company_website ? `Web: ${invoice.company_website}` : ''}
              </p>
            </div>
            <div className="invoice-sheet__meta">
              <span className="invoice-badge">{invoice.voucher_type === 'sales' ? 'Sales' : 'Purchase'}</span>
              <h2>Invoice {invoice.invoice_number || `#${invoice.id}`}</h2>
              <p>Date: {new Date(invoice.invoice_date).toLocaleDateString()}</p>
              <p>Currency: {previewCurrencyCode}</p>
            </div>
          </header>

          <section className="invoice-sheet__billto">
            <p className="eyebrow">Bill to</p>
            <h4>{invoice.ledger?.name || invoice.ledger_name || 'Unknown ledger'}</h4>
            <p>{invoice.ledger?.address || invoice.ledger_address || 'Address not provided'}</p>
            <p>
              {(invoice.ledger?.gst || invoice.ledger_gst) ? `GST: ${invoice.ledger?.gst || invoice.ledger_gst}` : ''}
              {(invoice.ledger?.phone_number || invoice.ledger_phone) ? ` · Phone: ${invoice.ledger?.phone_number || invoice.ledger_phone}` : ''}
            </p>
          </section>

          <section className="invoice-sheet__table-wrap">
            <table className="invoice-sheet__table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Item</th>
                  <th>SKU</th>
                  <th>HSN/SAC</th>
                  <th className="right">Qty</th>
                  <th className="right">Unit Price</th>
                  <th className="right">GST %</th>
                  <th className="right">Tax</th>
                  <th className="right">Amount</th>
                </tr>
              </thead>
              <tbody>
                {getPreviewLineItems(invoice, products).map((item, index) => (
                  <tr key={item.id}>
                    <td>{index + 1}</td>
                    <td>{item.productName}</td>
                    <td>{item.sku}</td>
                    <td>{item.hsnSac}</td>
                    <td className="right">{item.quantity}</td>
                    <td className="right">{formatCurrency(item.unit_price, previewCurrencyCode)}</td>
                    <td className="right">{item.gstRate.toFixed(2)}%</td>
                    <td className="right">{formatCurrency(item.taxAmount, previewCurrencyCode)}</td>
                    <td className="right">{formatCurrency(item.line_total, previewCurrencyCode)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="invoice-sheet__footer">
            <div className="invoice-sheet__bank">
              <p className="eyebrow">Payment details</p>
              <p>Bank: {invoice.company_bank_name || 'N/A'}</p>
              <p>Branch: {invoice.company_branch_name || 'N/A'}</p>
              <p>Account: {invoice.company_account_name || 'N/A'}</p>
              <p>A/C No: {invoice.company_account_number || 'N/A'}</p>
              <p>IFSC: {invoice.company_ifsc_code || 'N/A'}</p>
            </div>
            <div className="invoice-sheet__totals">
              <p className="eyebrow">Tax breakup</p>
              <p>Taxable: {formatCurrency(invoice.taxable_amount || 0, previewCurrencyCode)}</p>
              <p>CGST: {formatCurrency(invoice.cgst_amount || 0, previewCurrencyCode)}</p>
              <p>SGST: {formatCurrency(invoice.sgst_amount || 0, previewCurrencyCode)}</p>
              <p>IGST: {formatCurrency(invoice.igst_amount || 0, previewCurrencyCode)}</p>
              <p>Total tax: {formatCurrency(invoice.total_tax_amount || 0, previewCurrencyCode)}</p>
              <p className="eyebrow" style={{ marginTop: '12px' }}>Total due</p>
              <p className="invoice-sheet__total-value">
                {formatCurrency(invoice.total_amount, previewCurrencyCode)}
              </p>
              <p className="muted-text">Authorized by {invoice.company_name || 'Billing company'}</p>
            </div>
          </section>
        </article>
      </div>
    </div>
  );
}
