import { useEffect, useState } from 'react';
import { useEscapeClose } from '../hooks/useEscapeClose';
import api, { getApiErrorMessage } from '../api/client';
import type { InvoiceCreate, Invoice, Ledger, Product } from '../types/api';
import { useFY } from '../context/FYContext';
import formatCurrency from '../utils/formatting';
import { formatInvoiceDateLabel, resolveDueDate, type DueDateMode } from '../utils/invoiceDueDate.ts';
import { formatInvoiceTaxBreakdown, isInterstateSupply } from '../utils/invoiceTax';
import ProductCombobox from './ProductCombobox';
import LedgerCombobox from './LedgerCombobox';

type InvoiceFormItem = {
  id: number;
  productId: string;
  quantity: string;
  unit_price: string;
  description: string;
};

function createItem(id: number, productId = '', unitPrice = ''): InvoiceFormItem {
  return { id, productId, quantity: '1', unit_price: unitPrice, description: '' };
}

type CreateInvoiceModalProps = {
  /** Pre-selected ledger ID (used when opened from ledger view) */
  preselectedLedgerId?: number;
  /** Pre-selected voucher type */
  preselectedVoucherType?: 'sales' | 'purchase';
  onClose: () => void;
  /** Called after a successful invoice creation with message, optional FY warning, and created invoice */
  onCreated: (message: string, warningMessage: string | undefined, invoice: Invoice) => void;
  onError: (message: string) => void;
};

export default function CreateInvoiceModal({
  preselectedLedgerId,
  preselectedVoucherType,
  onClose,
  onCreated,
  onError,
}: CreateInvoiceModalProps) {
  const { activeFY } = useFY();
  const [products, setProducts] = useState<Product[]>([]);
  const [ledgers, setLedgers] = useState<Ledger[]>([]);
  const [selectedLedgerId, setSelectedLedgerId] = useState(preselectedLedgerId ? String(preselectedLedgerId) : '');
  const [voucherType, setVoucherType] = useState<'sales' | 'purchase'>(preselectedVoucherType || 'sales');
  const [taxInclusive, setTaxInclusive] = useState(false);
  const [invoiceDate, setInvoiceDate] = useState(new Date().toISOString().slice(0, 10));
  const [dueDateMode, setDueDateMode] = useState<DueDateMode>('none');
  const [dueDate, setDueDate] = useState('');
  const [dueDateDays, setDueDateDays] = useState('');
  const [referenceNotes, setReferenceNotes] = useState('');
  const [items, setItems] = useState<InvoiceFormItem[]>([createItem(1)]);
  const [nextItemId, setNextItemId] = useState(2);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [currencyCode, setCurrencyCode] = useState('INR');
  const [companyGst, setCompanyGst] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const [productsRes, ledgersRes, companyRes] = await Promise.all([
          api.get<{ items: Product[] }>('/products/', { params: { page_size: 500 } }),
          api.get<{ items: Ledger[] }>('/ledgers/', { params: { page_size: 500 } }),
          api.get<{ currency_code: string | null; gst: string | null }>('/company/'),
        ]);
        if (cancelled) return;
        setProducts(productsRes.data.items);
        setLedgers(ledgersRes.data.items);
        setCurrencyCode(companyRes.data.currency_code || 'INR');
        setCompanyGst(companyRes.data.gst || null);

        if (!preselectedLedgerId && ledgersRes.data.items.length > 0) {
          setSelectedLedgerId(String(ledgersRes.data.items[0].id));
        }

        const defaultProduct = productsRes.data.items[0];
        if (defaultProduct) {
          setItems([createItem(1, String(defaultProduct.id), String(defaultProduct.price))]);
        }
      } catch (err) {
        onError(getApiErrorMessage(err, 'Unable to load form data'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const totalAmount = items.reduce((sum, item) => {
    const product = products.find((p) => p.id === Number(item.productId));
    const quantity = Number(item.quantity);
    const unitPrice = item.unit_price ? Number(item.unit_price) : (product?.price || 0);
    const gstRate = product?.gst_rate || 0;
    if (!product || Number.isNaN(quantity)) return sum;

    if (taxInclusive) {
      return sum + unitPrice * quantity;
    }

    const taxableAmount = unitPrice * quantity;
    return sum + taxableAmount + taxableAmount * gstRate / 100;
  }, 0);

  function addItem() {
    const defaultProduct = products[0];
    setItems((c) => [...c, createItem(nextItemId, String(defaultProduct?.id ?? ''), String(defaultProduct?.price ?? ''))]);
    setNextItemId((c) => c + 1);
  }

  function removeItem(id: number) {
    setItems((c) => (c.length === 1 ? c : c.filter((i) => i.id !== id)));
  }

  function updateItem(id: number, key: 'productId' | 'quantity' | 'unit_price' | 'description', value: string) {
    setItems((c) => c.map((i) => (i.id === id ? { ...i, [key]: value } : i)));
  }

  const isDateOutsideFY =
    activeFY !== null &&
    invoiceDate !== '' &&
    (invoiceDate < activeFY.start_date || invoiceDate > activeFY.end_date);
  const selectedLedger = ledgers.find((ledger) => ledger.id === Number(selectedLedgerId));
  const composerInterstateSupply = isInterstateSupply(companyGst, selectedLedger?.gst);
  const resolvedDueDate = resolveDueDate({
    mode: dueDateMode,
    invoiceDate,
    exactDate: dueDate,
    daysFromInvoice: dueDateDays,
  });

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      setSubmitting(true);
      const payload: InvoiceCreate = {
        ledger_id: Number(selectedLedgerId),
        voucher_type: voucherType,
        invoice_date: invoiceDate,
        due_date: resolvedDueDate ?? invoiceDate,
        reference_notes: voucherType === 'sales' ? (referenceNotes.trim() || null) : null,
        tax_inclusive: taxInclusive,
        items: items.map((item) => ({
          product_id: Number(item.productId),
          quantity: Number(item.quantity),
          unit_price: item.unit_price ? Number(item.unit_price) : undefined,
          description: item.description || undefined,
        })),
      };
      const res = await api.post<Invoice>('/invoices/', payload);
      const msg = voucherType === 'sales'
        ? 'Sales invoice created. Inventory has been reduced.'
        : 'Purchase invoice created. Inventory has been increased.';
      const warningMsg =
        res.data.warnings?.includes('invoice_date_outside_fy') && activeFY
          ? `⚠️ This date is outside the active financial year (${activeFY.label}). The invoice was still created.`
          : undefined;
      onCreated(msg, warningMsg, res.data);
    } catch (err) {
      onError(getApiErrorMessage(err, 'Unable to create invoice'));
    } finally {
      setSubmitting(false);
    }
  }

  useEscapeClose(onClose);

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="create-invoice-modal-title" onClick={onClose}>
      <div className="modal-panel modal-panel--invoice-preview" onClick={(e) => e.stopPropagation()}>
        <div className="panel__header">
          <div>
            <p className="eyebrow">Quick create</p>
            <h2 id="create-invoice-modal-title" className="nav-panel__title">Create invoice</h2>
          </div>
          <div className="button-row">
            <div className="status-chip">Total {formatCurrency(totalAmount, currencyCode)}</div>
            <button type="button" className="button button--ghost" onClick={onClose} title="Close invoice dialog" aria-label="Close invoice dialog">✕</button>
          </div>
        </div>

        {loading ? (
          <div className="empty-state">Loading form data...</div>
        ) : (
          <form className="stack" onSubmit={(e) => void handleSubmit(e)}>
            <div className="field-grid">
              <div className="field">
                <label htmlFor="modal-inv-voucher-type">Voucher type</label>
                <select
                  id="modal-inv-voucher-type"
                  className="select"
                  value={voucherType}
                  onChange={(e) => setVoucherType(e.target.value as 'sales' | 'purchase')}
                >
                  <option value="sales">Sales</option>
                  <option value="purchase">Purchase</option>
                </select>
              </div>

              <div className="field">
                <label htmlFor="modal-inv-ledger">Ledger</label>
                <LedgerCombobox
                  id="modal-inv-ledger"
                  ledgers={ledgers}
                  value={selectedLedgerId}
                  onChange={setSelectedLedgerId}
                  required
                  disabled={!!preselectedLedgerId}
                />
              </div>

              <div className="field">
                <label htmlFor="modal-inv-date">Invoice date</label>
                <input
                  id="modal-inv-date"
                  className="input"
                  type="date"
                  value={invoiceDate}
                  onChange={(e) => setInvoiceDate(e.target.value)}
                  required
                />
                {isDateOutsideFY && activeFY ? (
                  <p className="field-warning">
                    ⚠️ This date is outside the active financial year ({activeFY.label}). The invoice will still be created.
                  </p>
                ) : null}
              </div>

              <div className="field">
                <label htmlFor="modal-inv-due-mode">Due date</label>
                <select
                  id="modal-inv-due-mode"
                  className="select"
                  value={dueDateMode}
                  onChange={(e) => setDueDateMode(e.target.value as DueDateMode)}
                >
                  <option value="none">No due date</option>
                  <option value="exact">Choose exact date</option>
                  <option value="days">Set days from invoice date</option>
                </select>
              </div>

              {dueDateMode === 'exact' ? (
                <div className="field">
                  <label htmlFor="modal-inv-due-date">Exact due date</label>
                  <input
                    id="modal-inv-due-date"
                    className="input"
                    type="date"
                    value={dueDate}
                    min={invoiceDate || undefined}
                    onChange={(e) => setDueDate(e.target.value)}
                  />
                </div>
              ) : null}

              {dueDateMode === 'days' ? (
                <div className="field">
                  <label htmlFor="modal-inv-due-days">Days from invoice date</label>
                  <input
                    id="modal-inv-due-days"
                    className="input"
                    type="number"
                    min="0"
                    step="1"
                    value={dueDateDays}
                    onChange={(e) => setDueDateDays(e.target.value)}
                    placeholder="0"
                  />
                </div>
              ) : null}

              {voucherType === 'sales' ? (
                <div className="field" style={{ gridColumn: '1 / -1' }}>
                  <label htmlFor="modal-inv-reference-notes">Reference Notes</label>
                  <input
                    id="modal-inv-reference-notes"
                    className="input"
                    type="text"
                    value={referenceNotes}
                    onChange={(e) => setReferenceNotes(e.target.value)}
                    placeholder="PO number or customer reference"
                  />
                </div>
              ) : null}
            </div>

            {dueDateMode !== 'none' ? (
              <p className="muted-text" style={{ margin: 0 }}>
                {resolvedDueDate
                  ? `Resolved due date: ${formatInvoiceDateLabel(resolvedDueDate)}`
                  : 'Select a valid due date or enter the number of days from the invoice date.'}
              </p>
            ) : null}

            <div className="field" style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: 0 }}>
              <input
                id="modal-inv-tax-inclusive"
                type="checkbox"
                checked={taxInclusive}
                onChange={(e) => setTaxInclusive(e.target.checked)}
              />
              <label htmlFor="modal-inv-tax-inclusive" style={{ marginBottom: 0, cursor: 'pointer' }}>
                Prices include GST
              </label>
            </div>

            <div className="stack">
              {items.map((item, index) => {
                const selectedProduct = products.find((p) => p.id === Number(item.productId));
                const selectedUnit = selectedProduct?.unit || 'Pieces';
                const allowDecimalQuantity = Boolean(selectedProduct?.allow_decimal);
                const unitPrice = item.unit_price ? Number(item.unit_price) : (selectedProduct?.price || 0);
                const gstRate = selectedProduct?.gst_rate || 0;
                let lineTotal: number;
                let taxAmount: number;
                if (taxInclusive) {
                  lineTotal = unitPrice * Number(item.quantity || 0);
                  taxAmount = lineTotal - lineTotal / (1 + gstRate / 100);
                } else {
                  const taxableAmount = unitPrice * Number(item.quantity || 0);
                  taxAmount = taxableAmount * gstRate / 100;
                  lineTotal = taxableAmount + taxAmount;
                }

                return (
                  <div key={item.id} className="line-item">
                    <div className="field">
                      <label htmlFor={`modal-inv-product-${item.id}`}>Line {index + 1}</label>
                      <ProductCombobox
                        id={`modal-inv-product-${item.id}`}
                        products={products}
                        value={item.productId}
                        onChange={(productId, newProduct) => {
                          updateItem(item.id, 'productId', productId);
                          updateItem(item.id, 'unit_price', String(newProduct.price));
                        }}
                        required
                      />
                    </div>

                    <div className="field">
                      <label htmlFor={`modal-inv-qty-${item.id}`}>Qty ({selectedUnit})</label>
                      <input
                        id={`modal-inv-qty-${item.id}`}
                        className="input"
                        type="number"
                        min={allowDecimalQuantity ? '0.001' : '1'}
                        step={allowDecimalQuantity ? '0.001' : '1'}
                        value={item.quantity}
                        onChange={(e) => updateItem(item.id, 'quantity', e.target.value)}
                        required
                      />
                    </div>

                    <div className="field">
                      <label htmlFor={`modal-inv-price-${item.id}`}>{taxInclusive ? 'Amount (incl. GST)' : 'Price'}</label>
                      <input
                        id={`modal-inv-price-${item.id}`}
                        className="input"
                        type="number"
                        step="0.01"
                        min="0"
                        value={item.unit_price}
                        onChange={(e) => updateItem(item.id, 'unit_price', e.target.value)}
                        placeholder={selectedProduct ? String(selectedProduct.price) : '0.00'}
                      />
                    </div>

                    <div className="line-item__price">
                      {formatCurrency(lineTotal, currencyCode)}
                      <div className="table-subtext">
                        {formatInvoiceTaxBreakdown({
                          gstRate,
                          taxAmount,
                          currencyCode,
                          interstateSupply: composerInterstateSupply,
                        })}
                      </div>
                    </div>
                    <button type="button" className="button button--danger" onClick={() => removeItem(item.id)} title={`Remove line item ${index + 1}`} aria-label={`Remove line item ${index + 1}`}>Remove</button>
                      <div className="field" style={{ gridColumn: '1 / -1' }}>
                        <label htmlFor={`modal-inv-description-${item.id}`}>Description (optional)</label>
                        <textarea
                          id={`modal-inv-description-${item.id}`}
                          className="input"
                          rows={2}
                          value={item.description}
                          onChange={(e) => updateItem(item.id, 'description', e.target.value)}
                          placeholder="Serial number, batch code, or item notes"
                        />
                      </div>
                  </div>
                );
              })}
            </div>

            <div className="button-row">
              <button type="button" className="button button--ghost" onClick={addItem} disabled={products.length === 0} title="Add line item" aria-label="Add line item">
                Add line item
              </button>
              <button type="button" className="button button--secondary" onClick={onClose} title="Cancel invoice creation" aria-label="Cancel invoice creation">Cancel</button>
              <button className="button button--primary" disabled={submitting || products.length === 0 || !selectedLedgerId} title="Create invoice" aria-label="Create invoice">
                {submitting ? 'Creating invoice...' : 'Create invoice'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
