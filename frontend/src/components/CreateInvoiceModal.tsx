import { useEffect, useState } from 'react';
import api, { getApiErrorMessage } from '../api/client';
import type { InvoiceCreate, Ledger, Product } from '../types/api';

type InvoiceFormItem = {
  id: number;
  productId: string;
  quantity: string;
  unit_price: string;
};

function createItem(id: number, productId = '', unitPrice = ''): InvoiceFormItem {
  return { id, productId, quantity: '1', unit_price: unitPrice };
}

function formatCurrency(value: number, currencyCode = 'INR') {
  try {
    return new Intl.NumberFormat('en-IN', { style: 'currency', currency: currencyCode }).format(value);
  } catch {
    return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(value);
  }
}

type CreateInvoiceModalProps = {
  /** Pre-selected ledger ID (used when opened from ledger view) */
  preselectedLedgerId?: number;
  /** Pre-selected voucher type */
  preselectedVoucherType?: 'sales' | 'purchase';
  onClose: () => void;
  /** Called after a successful invoice creation with a success message */
  onCreated: (message: string) => void;
  onError: (message: string) => void;
};

export default function CreateInvoiceModal({
  preselectedLedgerId,
  preselectedVoucherType,
  onClose,
  onCreated,
  onError,
}: CreateInvoiceModalProps) {
  const [products, setProducts] = useState<Product[]>([]);
  const [ledgers, setLedgers] = useState<Ledger[]>([]);
  const [selectedLedgerId, setSelectedLedgerId] = useState(preselectedLedgerId ? String(preselectedLedgerId) : '');
  const [voucherType, setVoucherType] = useState<'sales' | 'purchase'>(preselectedVoucherType || 'sales');
  const [invoiceDate, setInvoiceDate] = useState(new Date().toISOString().slice(0, 10));
  const [items, setItems] = useState<InvoiceFormItem[]>([createItem(1)]);
  const [nextItemId, setNextItemId] = useState(2);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [currencyCode, setCurrencyCode] = useState('INR');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const [productsRes, ledgersRes, companyRes] = await Promise.all([
          api.get<{ items: Product[] }>('/products/', { params: { page_size: 500 } }),
          api.get<{ items: Ledger[] }>('/ledgers/', { params: { page_size: 500 } }),
          api.get<{ currency_code: string | null }>('/company/'),
        ]);
        if (cancelled) return;
        setProducts(productsRes.data.items);
        setLedgers(ledgersRes.data.items);
        setCurrencyCode(companyRes.data.currency_code || 'INR');

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

  function updateItem(id: number, key: 'productId' | 'quantity' | 'unit_price', value: string) {
    setItems((c) => c.map((i) => (i.id === id ? { ...i, [key]: value } : i)));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      setSubmitting(true);
      const payload: InvoiceCreate = {
        ledger_id: Number(selectedLedgerId),
        voucher_type: voucherType,
        invoice_date: invoiceDate,
        items: items.map((item) => ({
          product_id: Number(item.productId),
          quantity: Number(item.quantity),
          unit_price: item.unit_price ? Number(item.unit_price) : undefined,
        })),
      };
      await api.post('/invoices/', payload);
      const msg = voucherType === 'sales'
        ? 'Sales invoice created. Inventory has been reduced.'
        : 'Purchase invoice created. Inventory has been increased.';
      onCreated(msg);
    } catch (err) {
      onError(getApiErrorMessage(err, 'Unable to create invoice'));
    } finally {
      setSubmitting(false);
    }
  }

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
            <button type="button" className="button button--ghost" onClick={onClose}>✕</button>
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
                <select
                  id="modal-inv-ledger"
                  className="select"
                  value={selectedLedgerId}
                  onChange={(e) => setSelectedLedgerId(e.target.value)}
                  required
                  disabled={!!preselectedLedgerId}
                >
                  {ledgers.length === 0 ? <option value="">No ledgers available</option> : null}
                  {ledgers.map((l) => (
                    <option key={l.id} value={l.id}>{l.name} ({l.gst})</option>
                  ))}
                </select>
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
              </div>
            </div>

            <div className="stack">
              {items.map((item, index) => {
                const selectedProduct = products.find((p) => p.id === Number(item.productId));
                const unitPrice = item.unit_price ? Number(item.unit_price) : (selectedProduct?.price || 0);
                const gstRate = selectedProduct?.gst_rate || 0;
                const taxableAmount = unitPrice * Number(item.quantity || 0);
                const taxAmount = taxableAmount * gstRate / 100;
                const lineTotal = taxableAmount + taxAmount;

                return (
                  <div key={item.id} className="line-item">
                    <div className="field">
                      <label htmlFor={`modal-inv-product-${item.id}`}>Line {index + 1}</label>
                      <select
                        id={`modal-inv-product-${item.id}`}
                        className="select"
                        value={item.productId}
                        onChange={(e) => {
                          updateItem(item.id, 'productId', e.target.value);
                          const newProduct = products.find((p) => p.id === Number(e.target.value));
                          if (newProduct) updateItem(item.id, 'unit_price', String(newProduct.price));
                        }}
                        required
                      >
                        {products.length === 0 ? <option value="">No products available</option> : null}
                        {products.map((p) => (
                          <option key={p.id} value={p.id}>{p.name} ({p.sku})</option>
                        ))}
                      </select>
                    </div>

                    <div className="field">
                      <label htmlFor={`modal-inv-qty-${item.id}`}>Qty</label>
                      <input
                        id={`modal-inv-qty-${item.id}`}
                        className="input"
                        type="number"
                        min="1"
                        step="1"
                        value={item.quantity}
                        onChange={(e) => updateItem(item.id, 'quantity', e.target.value)}
                        required
                      />
                    </div>

                    <div className="field">
                      <label htmlFor={`modal-inv-price-${item.id}`}>Price</label>
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
                      <div className="table-subtext">Incl GST {gstRate}% ({formatCurrency(taxAmount, currencyCode)})</div>
                    </div>
                    <button type="button" className="button button--danger" onClick={() => removeItem(item.id)}>Remove</button>
                  </div>
                );
              })}
            </div>

            <div className="button-row">
              <button type="button" className="button button--ghost" onClick={addItem} disabled={products.length === 0}>
                Add line item
              </button>
              <button type="button" className="button button--secondary" onClick={onClose}>Cancel</button>
              <button className="button button--primary" disabled={submitting || products.length === 0 || !selectedLedgerId}>
                {submitting ? 'Creating invoice...' : 'Create invoice'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
