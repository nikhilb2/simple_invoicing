import { useEffect, useState } from 'react';
import { Eye, Pencil, Trash2, RotateCcw } from 'lucide-react';
import api, { getApiErrorMessage } from '../api/client';
import type { CompanyProfile, Invoice, InvoiceCreate, Ledger, LedgerCreate, PaginatedInvoices, Payment, PaymentCreate, Product } from '../types/api';
import InvoicePreview from '../components/InvoicePreview';
import ConfirmDialog from '../components/ConfirmDialog';
import StatusToasts from '../components/StatusToasts';
import ProductCombobox from '../components/ProductCombobox';
import LedgerCombobox from '../components/LedgerCombobox';
import { useEscapeClose } from '../hooks/useEscapeClose';
import formatCurrency from '../utils/formatting';

type InvoiceFormItem = {
  id: number;
  productId: string;
  quantity: string;
  unit_price: string;
};

function createItem(id: number, productId = '', unitPrice = ''): InvoiceFormItem {
  return {
    id,
    productId,
    quantity: '1',
    unit_price: unitPrice,
  };
}

export default function InvoicesPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [ledgers, setLedgers] = useState<Ledger[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [selectedLedgerId, setSelectedLedgerId] = useState('');
  const [voucherType, setVoucherType] = useState<'sales' | 'purchase' | 'payment'>('sales');
  const [taxInclusive, setTaxInclusive] = useState(false);
  const [supplierInvoiceNumber, setSupplierInvoiceNumber] = useState('');
  const [paymentMode, setPaymentMode] = useState('cash');
  const [paymentReference, setPaymentReference] = useState('');
  const [paymentAmount, setPaymentAmount] = useState('');
  const [payments, setPayments] = useState<Payment[]>([]);
  const [listTab, setListTab] = useState<'invoices' | 'payments'>('invoices');
  const [loadingPayments, setLoadingPayments] = useState(false);
  const [invoiceDate, setInvoiceDate] = useState(new Date().toISOString().slice(0, 10));
  const [showLedgerModal, setShowLedgerModal] = useState(false);
  const [showProductModal, setShowProductModal] = useState(false);
  const [showStockModal, setShowStockModal] = useState(false);

  useEscapeClose(() => {
    if (showStockModal) setShowStockModal(false);
    else if (showProductModal) setShowProductModal(false);
    else if (showLedgerModal) setShowLedgerModal(false);
  });

  const [ledgerForm, setLedgerForm] = useState<LedgerCreate>({
    name: '',
    address: '',
    gst: '',
    phone_number: '',
    email: '',
    website: '',
    bank_name: '',
    branch_name: '',
    account_name: '',
    account_number: '',
    ifsc_code: '',
  });
  const [productForm, setProductForm] = useState({ name: '', sku: '', hsn_sac: '', price: '', gst_rate: '0' });
  const [stockForm, setStockForm] = useState({ productId: '', adjustment: '' });
  const [ledgerSubmitting, setLedgerSubmitting] = useState(false);
  const [productSubmitting, setProductSubmitting] = useState(false);
  const [stockSubmitting, setStockSubmitting] = useState(false);
  const [items, setItems] = useState<InvoiceFormItem[]>([createItem(1)]);
  const [nextItemId, setNextItemId] = useState(2);
  const [editingInvoiceId, setEditingInvoiceId] = useState<number | null>(null);
  const [deletingInvoiceId, setDeletingInvoiceId] = useState<number | null>(null);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [pendingDeleteInvoiceId, setPendingDeleteInvoiceId] = useState<number | null>(null);
  const [cancellingInvoiceId, setCancellingInvoiceId] = useState<number | null>(null);
  const [restoringInvoiceId, setRestoringInvoiceId] = useState<number | null>(null);
  const [showCancelDialog, setShowCancelDialog] = useState(false);
  const [pendingCancelInvoiceId, setPendingCancelInvoiceId] = useState<number | null>(null);
  const [showCancelled, setShowCancelled] = useState(false);
  const [previewInvoice, setPreviewInvoice] = useState<Invoice | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [invoicePage, setInvoicePage] = useState(1);
  const [invoiceTotalPages, setInvoiceTotalPages] = useState(1);
  const [invoiceTotal, setInvoiceTotal] = useState(0);
  const [invoiceSearch, setInvoiceSearch] = useState('');
  const invoicePageSize = 20;

  async function loadInvoicePageData() {
    try {
      setLoading(true);
      setError('');
      const [productsRes, ledgersRes, invoicesRes, companyRes] = await Promise.all([
        api.get<{ items: Product[] }>('/products/', { params: { page_size: 500 } }),
        api.get<{ items: Ledger[] }>('/ledgers/', { params: { page_size: 500 } }),
        api.get<PaginatedInvoices>('/invoices/', {
          params: { page: invoicePage, page_size: invoicePageSize, search: invoiceSearch, show_cancelled: showCancelled },
        }),
        api.get<CompanyProfile>('/company/'),
      ]);

      setProducts(productsRes.data.items);
      setLedgers(ledgersRes.data.items);
      setInvoices(invoicesRes.data.items);
      setInvoiceTotal(invoicesRes.data.total);
      setInvoiceTotalPages(invoicesRes.data.total_pages);
      setCompany(companyRes.data);
      setSelectedLedgerId((current) => current || String(ledgersRes.data.items[0]?.id ?? ''));
      setItems((current) =>
        current.map((item, index) => {
          const defaultProduct = productsRes.data.items[index] ?? productsRes.data.items[0];
          return {
            ...item,
            productId: item.productId || String(defaultProduct?.id ?? ''),
            unit_price: item.unit_price || String(defaultProduct?.price ?? ''),
          };
        })
      );
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load invoice data'));
    } finally {
      setLoading(false);
    }
  }

  async function loadPayments() {
    try {
      setLoadingPayments(true);
      const res = await api.get<Payment[]>('/payments/');
      setPayments(res.data);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load payment vouchers'));
    } finally {
      setLoadingPayments(false);
    }
  }

  useEffect(() => {
    void loadInvoicePageData();
  }, [invoicePage, invoiceSearch, showCancelled]);

  const totalAmount = items.reduce((sum, item) => {
    const product = products.find((entry) => entry.id === Number(item.productId));
    const quantity = Number(item.quantity);
    const unitPrice = item.unit_price ? Number(item.unit_price) : (product?.price || 0);
    const gstRate = product?.gst_rate || 0;

    if (!product || Number.isNaN(quantity)) {
      return sum;
    }

    if (taxInclusive) {
      return sum + unitPrice * quantity;
    }
    const taxableAmount = unitPrice * quantity;
    const taxAmount = taxableAmount * gstRate / 100;
    return sum + taxableAmount + taxAmount;
  }, 0);

  const activeCurrencyCode = company?.currency_code || 'USD';

  function addItem() {
    const defaultProduct = products[0];
    setItems((current) => [...current, createItem(nextItemId, String(defaultProduct?.id ?? ''), String(defaultProduct?.price ?? ''))]);
    setNextItemId((current) => current + 1);
  }

  function removeItem(id: number) {
    setItems((current) => (current.length === 1 ? current : current.filter((item) => item.id !== id)));
  }

  function updateItem(id: number, key: 'productId' | 'quantity' | 'unit_price', value: string) {
    setItems((current) => current.map((item) => (item.id === id ? { ...item, [key]: value } : item)));
  }

  function resetInvoiceForm() {
    setEditingInvoiceId(null);
    setSupplierInvoiceNumber('');
    setTaxInclusive(false);
    setPaymentMode('cash');
    setPaymentReference('');
    setPaymentAmount('');
    const defaultProduct = products[0];
    setItems([createItem(1, String(defaultProduct?.id ?? ''), String(defaultProduct?.price ?? ''))]);
    setNextItemId(2);
    setInvoiceDate(new Date().toISOString().slice(0, 10));
  }

  function startEditingInvoice(invoice: Invoice) {
    if (!invoice.ledger_id) {
      setError('This invoice is missing its ledger and cannot be edited.');
      return;
    }

    if (!invoice.items || invoice.items.length === 0) {
      setError('This invoice has no line items and cannot be edited.');
      return;
    }

    setError('');
    setSuccess('');
    setEditingInvoiceId(invoice.id);
    setVoucherType(invoice.voucher_type);
    setSupplierInvoiceNumber(invoice.supplier_invoice_number ?? '');
    setTaxInclusive(invoice.tax_inclusive ?? false);
    setSelectedLedgerId(String(invoice.ledger_id));
    setInvoiceDate(invoice.invoice_date ? invoice.invoice_date.slice(0, 10) : new Date().toISOString().slice(0, 10));

    const nextItems = invoice.items.map((line, index) => ({
      id: index + 1,
      productId: String(line.product_id),
      quantity: String(line.quantity),
      unit_price: String(line.unit_price),
    }));

    setItems(nextItems);
    setNextItemId(nextItems.length + 1);
  }

  async function handleSubmitInvoice(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (voucherType === 'payment') {
      try {
        setSubmitting(true);
        setError('');
        setSuccess('');

        const payload: PaymentCreate = {
          ledger_id: Number(selectedLedgerId),
          voucher_type: 'payment',
          amount: Number(paymentAmount),
          date: invoiceDate ? new Date(invoiceDate).toISOString() : undefined,
          mode: paymentMode || undefined,
          reference: paymentReference.trim() || undefined,
        };

        await api.post<Payment>('/payments/', payload);
        setSuccess('Payment voucher created successfully.');
        resetInvoiceForm();
        if (listTab === 'payments') {
          await loadPayments();
        }
      } catch (err) {
        setError(getApiErrorMessage(err, 'Unable to create payment voucher'));
      } finally {
        setSubmitting(false);
      }
      return;
    }

    try {
      setSubmitting(true);
      setError('');
      setSuccess('');

      const payload: InvoiceCreate = {
        ledger_id: Number(selectedLedgerId),
        voucher_type: voucherType,
        invoice_date: invoiceDate,
        supplier_invoice_number: voucherType === 'purchase' ? (supplierInvoiceNumber.trim() || null) : null,
        tax_inclusive: taxInclusive,
        items: items.map((item) => ({
          product_id: Number(item.productId),
          quantity: Number(item.quantity),
          unit_price: item.unit_price ? Number(item.unit_price) : undefined,
        })),
      };

      if (editingInvoiceId) {
        await api.put<Invoice>(`/invoices/${editingInvoiceId}`, payload);
        setSuccess('Invoice updated successfully. Inventory has been recalculated.');
      } else {
        await api.post<Invoice>('/invoices/', payload);
        setSuccess(
          voucherType === 'sales'
            ? 'Sales invoice created. Inventory has been reduced.'
            : 'Purchase invoice created. Inventory has been increased.'
        );
      }

      resetInvoiceForm();
      await loadInvoicePageData();
    } catch (err) {
      setError(getApiErrorMessage(err, editingInvoiceId ? 'Unable to update invoice' : 'Unable to create invoice'));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDeleteInvoice(invoiceId: number) {
    setPendingDeleteInvoiceId(invoiceId);
    setShowDeleteDialog(true);
  }

  function cancelDeleteInvoice() {
    setShowDeleteDialog(false);
    setPendingDeleteInvoiceId(null);
  }

  async function confirmDeleteInvoice() {
    if (pendingDeleteInvoiceId === null) return;
    setShowDeleteDialog(false);

    try {
      setDeletingInvoiceId(pendingDeleteInvoiceId);
      setError('');
      setSuccess('');
      await api.delete(`/invoices/${pendingDeleteInvoiceId}`);

      if (editingInvoiceId === pendingDeleteInvoiceId) {
        resetInvoiceForm();
      }

      setSuccess('Invoice deleted successfully. Inventory has been rolled back.');
      await loadInvoicePageData();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to delete invoice'));
    } finally {
      setDeletingInvoiceId(null);
      setPendingDeleteInvoiceId(null);
    }
  }

  async function handleCancelInvoice(invoiceId: number) {
    setPendingCancelInvoiceId(invoiceId);
    setShowCancelDialog(true);
  }

  function dismissCancelDialog() {
    setShowCancelDialog(false);
    setPendingCancelInvoiceId(null);
  }

  async function confirmCancelInvoice() {
    if (pendingCancelInvoiceId === null) return;
    setShowCancelDialog(false);

    try {
      setCancellingInvoiceId(pendingCancelInvoiceId);
      setError('');
      setSuccess('');
      await api.delete(`/invoices/${pendingCancelInvoiceId}`);

      if (editingInvoiceId === pendingCancelInvoiceId) {
        resetInvoiceForm();
      }

      setSuccess('Invoice cancelled. Inventory has been reversed.');
      await loadInvoicePageData();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to cancel invoice'));
    } finally {
      setCancellingInvoiceId(null);
      setPendingCancelInvoiceId(null);
    }
  }

  async function handleRestoreInvoice(invoiceId: number) {
    try {
      setRestoringInvoiceId(invoiceId);
      setError('');
      setSuccess('');
      await api.post(`/invoices/${invoiceId}/restore`);
      setSuccess('Invoice restored. Inventory has been re-applied.');
      await loadInvoicePageData();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to restore invoice'));
    } finally {
      setRestoringInvoiceId(null);
    }
  }

  async function handleCreateLedger(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    try {
      setLedgerSubmitting(true);
      setError('');

      const payload: LedgerCreate = {
        name: ledgerForm.name.trim(),
        address: ledgerForm.address.trim(),
        gst: ledgerForm.gst.trim().toUpperCase(),
        phone_number: ledgerForm.phone_number.trim(),
        email: ledgerForm.email.trim(),
        website: ledgerForm.website.trim(),
        bank_name: ledgerForm.bank_name.trim(),
        branch_name: ledgerForm.branch_name.trim(),
        account_name: ledgerForm.account_name.trim(),
        account_number: ledgerForm.account_number.trim(),
        ifsc_code: ledgerForm.ifsc_code.trim().toUpperCase(),
      };

      const response = await api.post<Ledger>('/ledgers/', payload);
      setLedgers((current) => [...current, response.data].sort((a, b) => a.name.localeCompare(b.name)));
      setSelectedLedgerId(String(response.data.id));
      setLedgerForm({
        name: '',
        address: '',
        gst: '',
        phone_number: '',
        email: '',
        website: '',
        bank_name: '',
        branch_name: '',
        account_name: '',
        account_number: '',
        ifsc_code: '',
      });
      setShowLedgerModal(false);
      setSuccess('Ledger added and selected for this invoice.');
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to create ledger'));
    } finally {
      setLedgerSubmitting(false);
    }
  }

  async function handleCreateProduct(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    try {
      setProductSubmitting(true);
      setError('');

      const payload = {
        name: productForm.name.trim(),
        sku: productForm.sku.trim().toUpperCase(),
        hsn_sac: productForm.hsn_sac.trim(),
        price: Number(productForm.price),
        gst_rate: Number(productForm.gst_rate),
      };

      const response = await api.post<Product>('/products/', payload);
      setProducts((current) => [...current, response.data].sort((a, b) => a.name.localeCompare(b.name)));
      setProductForm({ name: '', sku: '', hsn_sac: '', price: '', gst_rate: '0' });
      setShowProductModal(false);
      setSuccess('Product created successfully.');
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to create product'));
    } finally {
      setProductSubmitting(false);
    }
  }

  async function handleUpdateStock(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    try {
      setStockSubmitting(true);
      setError('');

      const payload = {
        product_id: Number(stockForm.productId),
        quantity: Number(stockForm.adjustment),
      };

      await api.post('/inventory/adjust', payload);
      setStockForm({ productId: '', adjustment: '' });
      setShowStockModal(false);
      await loadInvoicePageData();
      setSuccess('Stock updated successfully.');
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to update stock'));
    } finally {
      setStockSubmitting(false);
    }
  }

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Invoices</p>
          <h1 className="page-title">Invoice composer</h1>
          <p className="section-copy">Build multi-line invoices against live product pricing and submit directly to the API.</p>
        </div>
        <div className="status-chip">{invoiceTotal} invoices listed</div>
      </section>

      <StatusToasts error={error} success={success} onClearError={() => setError('')} onClearSuccess={() => setSuccess('')} />

      <section className="content-grid">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Create invoice</p>
              <h2 className="nav-panel__title">{editingInvoiceId ? `Editing invoice #${editingInvoiceId}` : 'Order entry'}</h2>
            </div>
            <div className="status-chip">Projected total {formatCurrency(totalAmount, activeCurrencyCode)}</div>
          </div>

          <div className="summary-box">
            <p className="eyebrow">Billing company</p>
            <p className="summary-box__value" style={{ fontSize: '1.25rem' }}>
              {company?.name?.trim() ? company.name : 'Company not configured'}
            </p>
            <p className="muted-text">
              {company?.gst ? `GST: ${company.gst} · ` : ''}
              {company?.phone_number ? `Phone: ${company.phone_number}` : 'Set details in Company page'}
            </p>
            <p className="muted-text">Currency: {activeCurrencyCode}</p>
            {(company?.email || company?.website) ? (
              <p className="muted-text">
                {company?.email ? `Email: ${company.email}` : ''}
                {company?.email && company?.website ? ' · ' : ''}
                {company?.website ? `Web: ${company.website}` : ''}
              </p>
            ) : null}
            <p className="muted-text">{company?.address || ''}</p>
            {company?.bank_name || company?.account_number ? (
              <p className="muted-text">
                Bank: {company?.bank_name || 'N/A'}
                {company?.branch_name ? ` (${company.branch_name})` : ''} · A/C: {company?.account_number || 'N/A'}
                {company?.ifsc_code ? ` · IFSC: ${company.ifsc_code}` : ''}
              </p>
            ) : null}
          </div>

          <form className="stack" onSubmit={handleSubmitInvoice}>
            <div className="field-grid">
              <div className="field">
                <label htmlFor="invoice-voucher-type">Voucher type</label>
                <select
                  id="invoice-voucher-type"
                  className="select"
                  value={voucherType}
                  onChange={(event) => setVoucherType(event.target.value as 'sales' | 'purchase' | 'payment')}
                >
                  <option value="sales">Sales</option>
                  <option value="purchase">Purchase</option>
                  <option value="payment">Payment</option>
                </select>
              </div>

              <div className="field">
                <label htmlFor="invoice-ledger">Ledger</label>
                <LedgerCombobox
                  id="invoice-ledger"
                  ledgers={ledgers}
                  value={selectedLedgerId}
                  onChange={setSelectedLedgerId}
                  required
                />
              </div>

              <div className="field">
                <label htmlFor="invoice-date">Invoice date</label>
                <input
                  id="invoice-date"
                  className="input"
                  type="date"
                  value={invoiceDate}
                  onChange={(event) => setInvoiceDate(event.target.value)}
                  required
                />
              </div>

              {voucherType === 'purchase' ? (
                <div className="field">
                  <label htmlFor="invoice-supplier-ref">Supplier Invoice #</label>
                  <input
                    id="invoice-supplier-ref"
                    className="input"
                    type="text"
                    value={supplierInvoiceNumber}
                    onChange={(event) => setSupplierInvoiceNumber(event.target.value)}
                    placeholder="Supplier's invoice number"
                  />
                </div>
              ) : null}

              <div className="button-row">
                <button type="button" className="button button--secondary" onClick={() => setShowLedgerModal(true)} title="Add ledger" aria-label="Add ledger">
                  Add ledger
                </button>
                {voucherType !== 'payment' ? (
                  <button type="button" className="button button--secondary" onClick={() => setShowProductModal(true)} title="Add product" aria-label="Add product">
                    Add product
                  </button>
                ) : null}
                {voucherType !== 'payment' ? (
                  <button type="button" className="button button--secondary" onClick={() => setShowStockModal(true)} title="Update stock" aria-label="Update stock">
                    Update stock
                  </button>
                ) : null}
              </div>
            </div>

            {voucherType !== 'payment' ? (
              <div className="field" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input
                  id="invoice-tax-inclusive"
                  type="checkbox"
                  checked={taxInclusive}
                  onChange={(event) => setTaxInclusive(event.target.checked)}
                />
                <label htmlFor="invoice-tax-inclusive" style={{ marginBottom: 0, cursor: 'pointer' }}>Prices include GST</label>
              </div>
            ) : null}

            {voucherType === 'payment' ? (
              <div className="field-grid">
                <div className="field">
                  <label htmlFor="payment-mode">Payment mode</label>
                  <select
                    id="payment-mode"
                    className="select"
                    value={paymentMode}
                    onChange={(event) => setPaymentMode(event.target.value)}
                  >
                    <option value="cash">Cash</option>
                    <option value="cheque">Cheque</option>
                    <option value="upi">UPI</option>
                    <option value="other">Other</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="payment-reference">Reference #</label>
                  <input
                    id="payment-reference"
                    className="input"
                    type="text"
                    value={paymentReference}
                    onChange={(event) => setPaymentReference(event.target.value)}
                    placeholder="Cheque no. or UPI transaction ID"
                  />
                </div>
                <div className="field">
                  <label htmlFor="payment-amount">Amount</label>
                  <input
                    id="payment-amount"
                    className="input"
                    type="number"
                    step="0.01"
                    min="0.01"
                    value={paymentAmount}
                    onChange={(event) => setPaymentAmount(event.target.value)}
                    placeholder="0.00"
                    required
                  />
                </div>
              </div>
            ) : null}

            {voucherType !== 'payment' ? (
              <div className="stack">
                {items.map((item, index) => {
                  const selectedProduct = products.find((product) => product.id === Number(item.productId));
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
                        <label htmlFor={`invoice-product-${item.id}`}>Line {index + 1}</label>
                        <ProductCombobox
                          id={`invoice-product-${item.id}`}
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
                        <label htmlFor={`invoice-quantity-${item.id}`}>Qty</label>
                        <input
                          id={`invoice-quantity-${item.id}`}
                          className="input"
                          type="number"
                          min="1"
                          step="1"
                          value={item.quantity}
                          onChange={(event) => updateItem(item.id, 'quantity', event.target.value)}
                          required
                        />
                      </div>

                      <div className="field">
                        <label htmlFor={`invoice-price-${item.id}`}>{taxInclusive ? 'Amount (incl. GST)' : 'Price'}</label>
                        <input
                          id={`invoice-price-${item.id}`}
                          className="input"
                          type="number"
                          step="0.01"
                          min="0"
                          value={item.unit_price}
                          onChange={(event) => updateItem(item.id, 'unit_price', event.target.value)}
                          placeholder={selectedProduct ? String(selectedProduct.price) : '0.00'}
                        />
                      </div>

                      <div className="line-item__price">
                        {formatCurrency(lineTotal, activeCurrencyCode)}
                        <div className="table-subtext">Incl GST {gstRate}% ({formatCurrency(taxAmount, activeCurrencyCode)})</div>
                      </div>
                      <button type="button" className="button button--danger" onClick={() => removeItem(item.id)} title={`Remove line item ${index + 1}`} aria-label={`Remove line item ${index + 1}`}>
                        Remove
                      </button>
                    </div>
                  );
                })}
              </div>
            ) : null}

            <div className="button-row">
              {voucherType !== 'payment' ? (
                <button type="button" className="button button--ghost" onClick={addItem} disabled={products.length === 0} title="Add line item" aria-label="Add line item">
                  Add line item
                </button>
              ) : null}
              {editingInvoiceId ? (
                <button type="button" className="button button--secondary" onClick={resetInvoiceForm} title="Cancel invoice edit" aria-label="Cancel invoice edit">
                  Cancel edit
                </button>
              ) : null}
              {voucherType === 'payment' ? (
                <button className="button button--primary" disabled={submitting || !selectedLedgerId || !paymentAmount} title="Create payment voucher" aria-label="Create payment voucher">
                  {submitting ? 'Creating payment...' : 'Create payment voucher'}
                </button>
              ) : (
                <button className="button button--primary" disabled={submitting || products.length === 0 || !selectedLedgerId} title={editingInvoiceId ? 'Update invoice' : 'Create invoice'} aria-label={editingInvoiceId ? 'Update invoice' : 'Create invoice'}>
                  {submitting ? (editingInvoiceId ? 'Updating invoice...' : 'Creating invoice...') : editingInvoiceId ? 'Update invoice' : 'Create invoice'}
                </button>
              )}
            </div>
          </form>
        </article>

        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Invoice feed</p>
              <h2 className="nav-panel__title">Recent invoices</h2>
            </div>
          </div>

          <div className="button-row">
            <button
              type="button"
              id="tab-invoices"
              className={`button ${listTab === 'invoices' ? 'button--primary' : 'button--secondary'}`}
              onClick={() => setListTab('invoices')}
              aria-pressed={listTab === 'invoices'}
            >
              Invoices
            </button>
            <button
              type="button"
              id="tab-payments"
              className={`button ${listTab === 'payments' ? 'button--primary' : 'button--secondary'}`}
              onClick={() => { setListTab('payments'); void loadPayments(); }}
              aria-pressed={listTab === 'payments'}
            >
              Payment Vouchers
            </button>
          </div>

          {listTab === 'invoices' ? (
            <>
              <div className="summary-box">
                <p className="eyebrow">Total listed value</p>
                <p className="summary-box__value">
                  {formatCurrency(invoices.reduce((sum, invoice) => sum + invoice.total_amount, 0), activeCurrencyCode)}
                </p>
              </div>

              <div className="field">
                <label htmlFor="invoice-search">Search by ledger name</label>
                <input
                  id="invoice-search"
                  className="input"
              type="search"
              placeholder="Type to search invoices..."
              value={invoiceSearch}
              onChange={(e) => {
                setInvoiceSearch(e.target.value);
                setInvoicePage(1);
              }}
            />
          </div>

          <div className="button-row">
            <button
              type="button"
              id="toggle-show-cancelled"
              className={`button ${showCancelled ? 'button--primary' : 'button--secondary'}`}
              onClick={() => { setShowCancelled((v) => !v); setInvoicePage(1); }}
              aria-pressed={showCancelled}
            >
              {showCancelled ? 'Hide Cancelled' : 'Show Cancelled'}
            </button>
          </div>

          <div className="invoice-list">
            {loading ? (
              <div className="empty-state">
                <p style={{ fontSize: '0.95rem' }}>Loading invoices...</p>
              </div>
            ) : null}
            {!loading && invoices.length === 0 && !invoiceSearch ? (
              <div className="empty-state">
                <p style={{ fontWeight: 600, marginBottom: '8px' }}>No invoices yet</p>
                <p style={{ marginBottom: '16px' }}>Create your first invoice to get started.</p>
                <button
                  type="button"
                  className="button button--primary"
                  onClick={() => document.getElementById('invoice-voucher-type')?.focus()}
                >
                  Create your first invoice
                </button>
              </div>
            ) : null}
            {!loading && invoices.length === 0 && invoiceSearch ? (
              <div className="empty-state">
                <p style={{ fontSize: '0.95rem' }}>No invoices match your search.</p>
              </div>
            ) : null}
            {!loading
              ? invoices.map((invoice) => (
                  <div key={invoice.id} className={`invoice-row invoice-row--${invoice.voucher_type}`}>
                    <div className="invoice-row__main">
                      <div className="invoice-row__header">
                        <div className="invoice-row__identity">
                          <strong className="invoice-row__ledger-name">{invoice.ledger?.name || invoice.ledger_name || 'Unknown ledger'}</strong>
                          <span className="invoice-row__invoice-id">Invoice {invoice.invoice_number || `#${invoice.id}`}</span>
                          {invoice.voucher_type === 'purchase' && invoice.supplier_invoice_number ? (
                            <span className="invoice-row__invoice-id">Supplier Ref: {invoice.supplier_invoice_number}</span>
                          ) : null}
                        </div>
                        {invoice.status === 'cancelled' ? (
                          <span className="invoice-type-badge" style={{ background: '#fee2e2', color: '#b91c1c' }}>Cancelled</span>
                        ) : (
                          <span className={`invoice-type-badge invoice-type-badge--${invoice.voucher_type}`}>
                            {invoice.voucher_type === 'sales' ? 'Sales' : 'Purchase'}
                          </span>
                        )}
                      </div>

                      <div className="invoice-row__chips">
                        <span className="invoice-meta-chip">Date {new Date(invoice.invoice_date).toLocaleDateString()}</span>
                        <span className="invoice-meta-chip">GST {invoice.ledger?.gst || invoice.ledger_gst || 'N/A'}</span>
                        <span className="invoice-meta-chip">Phone {invoice.ledger?.phone_number || invoice.ledger_phone || 'N/A'}</span>
                      </div>

                      <p className="invoice-row__items">
                        {(invoice.items?.length ?? 0)} line items
                        {(invoice.items || []).length > 0
                          ? ` • ${(invoice.items || [])
                              .slice(0, 2)
                              .map((item) => {
                                const matchedProduct = products.find((product) => product.id === item.product_id);
                                const productLabel = matchedProduct?.name || `Product #${item.product_id}`;
                                return `${productLabel} x${item.quantity}`;
                              })
                              .join(', ')}${(invoice.items?.length ?? 0) > 2 ? ' +' : ''}`
                          : ''}
                      </p>

                      <p className="invoice-row__address">{invoice.ledger?.address || invoice.ledger_address || 'Address not provided'}</p>

                      <div className="invoice-row__tax-grid">
                        <span>Taxable: {formatCurrency(invoice.taxable_amount || 0, invoice.company_currency_code || activeCurrencyCode)}</span>
                        <span>Total tax: {formatCurrency(invoice.total_tax_amount || 0, invoice.company_currency_code || activeCurrencyCode)}</span>
                        <span>CGST: {formatCurrency(invoice.cgst_amount || 0, invoice.company_currency_code || activeCurrencyCode)}</span>
                        <span>SGST: {formatCurrency(invoice.sgst_amount || 0, invoice.company_currency_code || activeCurrencyCode)}</span>
                        <span>IGST: {formatCurrency(invoice.igst_amount || 0, invoice.company_currency_code || activeCurrencyCode)}</span>
                        <span>Billed by: {invoice.company_name || 'Company not set'}</span>
                      </div>
                    </div>

                    <div className="invoice-row__aside">
                      <div className="invoice-row__totals">
                        <span className={`invoice-row__amount invoice-row__amount--${invoice.voucher_type}`}>
                          {invoice.voucher_type === 'sales' ? 'Debit' : 'Credit'}
                        </span>
                        <span className="invoice-row__price">
                          {formatCurrency(invoice.total_amount, invoice.company_currency_code || activeCurrencyCode)}
                        </span>
                      </div>

                      <div className="invoice-row__actions">
                        <button
                          type="button"
                          className="button button--ghost button--icon"
                          onClick={() => setPreviewInvoice(invoice)}
                          title="Preview invoice"
                          aria-label={`Preview invoice ${invoice.invoice_number || invoice.id}`}
                        >
                          <Eye size={16} />
                        </button>
                        {invoice.status !== 'cancelled' ? (
                          <button
                            type="button"
                            className="button button--ghost button--icon"
                            onClick={() => startEditingInvoice(invoice)}
                            disabled={submitting}
                            title="Edit invoice"
                            aria-label={`Edit invoice ${invoice.invoice_number || invoice.id}`}
                          >
                            <Pencil size={16} />
                          </button>
                        ) : null}
                        {invoice.status === 'cancelled' ? (
                          <button
                            type="button"
                            className="button button--ghost button--icon"
                            onClick={() => void handleRestoreInvoice(invoice.id)}
                            disabled={restoringInvoiceId === invoice.id}
                            title="Restore invoice"
                            aria-label={`Restore invoice ${invoice.invoice_number || invoice.id}`}
                          >
                            <RotateCcw size={16} />
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="button button--danger button--icon"
                            onClick={() => void handleCancelInvoice(invoice.id)}
                            disabled={cancellingInvoiceId === invoice.id}
                            title="Cancel invoice"
                            aria-label={`Cancel invoice ${invoice.invoice_number || invoice.id}`}
                          >
                            <Trash2 size={16} />
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                ))
              : null}
          </div>

          {invoiceTotalPages > 1 ? (
            <div className="button-row" style={{ justifyContent: 'center', paddingTop: '8px' }}>
              <button
                type="button"
                className="button button--ghost"
                disabled={invoicePage <= 1}
                onClick={() => setInvoicePage((p) => p - 1)}
                title="Previous page"
                aria-label="Previous page"
              >
                Previous
              </button>
              <span className="muted-text" style={{ alignSelf: 'center' }}>
                Page {invoicePage} of {invoiceTotalPages}
              </span>
              <button
                type="button"
                className="button button--ghost"
                disabled={invoicePage >= invoiceTotalPages}
                onClick={() => setInvoicePage((p) => p + 1)}
                title="Next page"
                aria-label="Next page"
              >
                Next
              </button>
            </div>
          ) : null}
            </>
          ) : (
            <>
              {loadingPayments ? (
                <div className="empty-state">
                  <p style={{ fontSize: '0.95rem' }}>Loading payment vouchers...</p>
                </div>
              ) : null}
              {!loadingPayments && payments.length === 0 ? (
                <div className="empty-state">
                  <p style={{ fontWeight: 600, marginBottom: '8px' }}>No payment vouchers yet</p>
                  <p>Select &ldquo;Payment&rdquo; in the voucher type and create one above.</p>
                </div>
              ) : null}
              <div className="invoice-list">
                {payments.map((payment) => {
                  const payee = ledgers.find((l) => l.id === payment.ledger_id);
                  return (
                    <div key={payment.id} className="invoice-row invoice-row--payment">
                      <div className="invoice-row__main">
                        <div className="invoice-row__header">
                          <div className="invoice-row__identity">
                            <strong className="invoice-row__ledger-name">{payee?.name ?? `Ledger #${payment.ledger_id}`}</strong>
                            <span className="invoice-row__invoice-id">{payment.payment_number ?? `PAY-#${payment.id}`}</span>
                          </div>
                          <span className="invoice-type-badge">Payment</span>
                        </div>
                        <div className="invoice-row__chips">
                          <span className="invoice-meta-chip">Date {new Date(payment.date).toLocaleDateString()}</span>
                          {payment.mode ? <span className="invoice-meta-chip">Mode: {payment.mode}</span> : null}
                          {payment.reference ? <span className="invoice-meta-chip">Ref: {payment.reference}</span> : null}
                        </div>
                      </div>
                      <div className="invoice-row__aside">
                        <div className="invoice-row__totals">
                          <span className="invoice-row__amount">Debit</span>
                          <span className="invoice-row__price">{formatCurrency(payment.amount, activeCurrencyCode)}</span>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </article>
      </section>

      {showLedgerModal ? (
        <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="ledger-modal-title">
          <div className="modal-panel">
            <div className="panel__header">
              <div>
                <p className="eyebrow">Quick add</p>
                <h2 id="ledger-modal-title" className="nav-panel__title">Create ledger</h2>
              </div>
            </div>

            <form className="stack" onSubmit={handleCreateLedger}>
              <div className="field">
                <label htmlFor="modal-ledger-name">Name</label>
                <input
                  id="modal-ledger-name"
                  className="input"
                  value={ledgerForm.name}
                  onChange={(event) => setLedgerForm((current) => ({ ...current, name: event.target.value }))}
                  placeholder="Acme Studio"
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="modal-ledger-gst">GST</label>
                <input
                  id="modal-ledger-gst"
                  className="input"
                  value={ledgerForm.gst}
                  onChange={(event) => setLedgerForm((current) => ({ ...current, gst: event.target.value }))}
                  placeholder="27ABCDE1234F1Z5"
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="modal-ledger-phone">Phone number</label>
                <input
                  id="modal-ledger-phone"
                  className="input"
                  value={ledgerForm.phone_number}
                  onChange={(event) => setLedgerForm((current) => ({ ...current, phone_number: event.target.value }))}
                  placeholder="+91 9876543210"
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="modal-ledger-email">Email</label>
                <input
                  id="modal-ledger-email"
                  className="input"
                  value={ledgerForm.email}
                  onChange={(event) => setLedgerForm((current) => ({ ...current, email: event.target.value }))}
                  placeholder="accounts@acme.com"
                />
              </div>
              <div className="field">
                <label htmlFor="modal-ledger-website">Website</label>
                <input
                  id="modal-ledger-website"
                  className="input"
                  value={ledgerForm.website}
                  onChange={(event) => setLedgerForm((current) => ({ ...current, website: event.target.value }))}
                  placeholder="https://acme.com"
                />
              </div>
              <div className="field">
                <label htmlFor="modal-ledger-address">Address</label>
                <textarea
                  id="modal-ledger-address"
                  className="textarea"
                  value={ledgerForm.address}
                  onChange={(event) => setLedgerForm((current) => ({ ...current, address: event.target.value }))}
                  placeholder="221B Baker Street, London"
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="modal-ledger-bank-name">Bank name</label>
                <input
                  id="modal-ledger-bank-name"
                  className="input"
                  value={ledgerForm.bank_name}
                  onChange={(event) => setLedgerForm((current) => ({ ...current, bank_name: event.target.value }))}
                  placeholder="HDFC Bank"
                />
              </div>
              <div className="field">
                <label htmlFor="modal-ledger-branch-name">Branch</label>
                <input
                  id="modal-ledger-branch-name"
                  className="input"
                  value={ledgerForm.branch_name}
                  onChange={(event) => setLedgerForm((current) => ({ ...current, branch_name: event.target.value }))}
                  placeholder="Bandra West"
                />
              </div>
              <div className="field">
                <label htmlFor="modal-ledger-account-name">Account holder</label>
                <input
                  id="modal-ledger-account-name"
                  className="input"
                  value={ledgerForm.account_name}
                  onChange={(event) => setLedgerForm((current) => ({ ...current, account_name: event.target.value }))}
                  placeholder="Acme Traders"
                />
              </div>
              <div className="field">
                <label htmlFor="modal-ledger-account-number">Account number</label>
                <input
                  id="modal-ledger-account-number"
                  className="input"
                  value={ledgerForm.account_number}
                  onChange={(event) => setLedgerForm((current) => ({ ...current, account_number: event.target.value }))}
                  placeholder="123456789012"
                />
              </div>
              <div className="field">
                <label htmlFor="modal-ledger-ifsc">IFSC</label>
                <input
                  id="modal-ledger-ifsc"
                  className="input"
                  value={ledgerForm.ifsc_code}
                  onChange={(event) => setLedgerForm((current) => ({ ...current, ifsc_code: event.target.value }))}
                  placeholder="HDFC0001234"
                />
              </div>

              <div className="button-row">
                <button type="button" className="button button--ghost" onClick={() => setShowLedgerModal(false)} title="Cancel ledger creation" aria-label="Cancel ledger creation">
                  Cancel
                </button>
                <button className="button button--primary" disabled={ledgerSubmitting} title="Save ledger" aria-label="Save ledger">
                  {ledgerSubmitting ? 'Saving ledger...' : 'Save ledger'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {previewInvoice ? (
        <InvoicePreview
          invoice={previewInvoice}
          products={products}
          currencyCode={activeCurrencyCode}
          onClose={() => setPreviewInvoice(null)}
          onError={(msg) => setError(msg)}
        />
      ) : null}

      {showProductModal ? (
        <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="product-modal-title">
          <div className="modal-panel">
            <div className="panel__header">
              <div>
                <p className="eyebrow">Quick add</p>
                <h2 id="product-modal-title" className="nav-panel__title">Create product</h2>
              </div>
            </div>

            <form className="stack" onSubmit={handleCreateProduct}>
              <div className="field">
                <label htmlFor="modal-product-name">Product name</label>
                <input
                  id="modal-product-name"
                  className="input"
                  value={productForm.name}
                  onChange={(event) => setProductForm((current) => ({ ...current, name: event.target.value }))}
                  placeholder="e.g., Widget Pro"
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="modal-product-sku">SKU</label>
                <input
                  id="modal-product-sku"
                  className="input"
                  value={productForm.sku}
                  onChange={(event) => setProductForm((current) => ({ ...current, sku: event.target.value }))}
                  placeholder="e.g., WP-001"
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="modal-product-hsn-sac">HSN/SAC</label>
                <input
                  id="modal-product-hsn-sac"
                  className="input"
                  value={productForm.hsn_sac}
                  onChange={(event) => setProductForm((current) => ({ ...current, hsn_sac: event.target.value }))}
                  placeholder="8471 or 9983"
                />
              </div>
              <div className="field">
                <label htmlFor="modal-product-price">Unit price</label>
                <input
                  id="modal-product-price"
                  className="input"
                  type="number"
                  step="0.01"
                  min="0"
                  value={productForm.price}
                  onChange={(event) => setProductForm((current) => ({ ...current, price: event.target.value }))}
                  placeholder="0.00"
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="modal-product-gst-rate">GST %</label>
                <input
                  id="modal-product-gst-rate"
                  className="input"
                  type="number"
                  min="0"
                  max="100"
                  step="0.01"
                  value={productForm.gst_rate}
                  onChange={(event) => setProductForm((current) => ({ ...current, gst_rate: event.target.value }))}
                  placeholder="18"
                  required
                />
              </div>

              <div className="button-row">
                <button type="button" className="button button--ghost" onClick={() => setShowProductModal(false)} title="Cancel product creation" aria-label="Cancel product creation">
                  Cancel
                </button>
                <button className="button button--primary" disabled={productSubmitting} title="Save product" aria-label="Save product">
                  {productSubmitting ? 'Saving product...' : 'Save product'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {showStockModal ? (
        <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="stock-modal-title">
          <div className="modal-panel">
            <div className="panel__header">
              <div>
                <p className="eyebrow">Inventory</p>
                <h2 id="stock-modal-title" className="nav-panel__title">Update stock</h2>
              </div>
            </div>

            <form className="stack" onSubmit={handleUpdateStock}>
              <div className="field">
                <label htmlFor="modal-stock-product">Product</label>
                <ProductCombobox
                  id="modal-stock-product"
                  products={products}
                  value={stockForm.productId}
                  onChange={(productId) => setStockForm((current) => ({ ...current, productId }))}
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="modal-stock-adjustment">Quantity adjustment</label>
                <input
                  id="modal-stock-adjustment"
                  className="input"
                  type="number"
                  step="1"
                  value={stockForm.adjustment}
                  onChange={(event) => setStockForm((current) => ({ ...current, adjustment: event.target.value }))}
                  placeholder="e.g., +10 to add, -5 to remove"
                  required
                />
              </div>
              <div className="field-hint">
                Use positive numbers to increase stock, negative numbers (like -5) to decrease stock.
              </div>

              <div className="button-row">
                <button type="button" className="button button--ghost" onClick={() => setShowStockModal(false)} title="Cancel stock update" aria-label="Cancel stock update">
                  Cancel
                </button>
                <button className="button button--primary" disabled={stockSubmitting} title="Update stock" aria-label="Update stock">
                  {stockSubmitting ? 'Updating stock...' : 'Update stock'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {showDeleteDialog ? (
        <ConfirmDialog
          message={`Are you sure you want to delete invoice #${pendingDeleteInvoiceId}? Inventory will be rolled back.`}
          title="Delete invoice"
          confirmText="Delete"
          cancelText="Cancel"
          danger={true}
          onConfirm={() => void confirmDeleteInvoice()}
          onCancel={cancelDeleteInvoice}
        />
      ) : null}

      {showCancelDialog ? (
        <ConfirmDialog
          message={`Are you sure you want to cancel invoice #${pendingCancelInvoiceId}? Inventory will be reversed. The invoice will remain visible when showing cancelled invoices.`}
          title="Cancel invoice"
          confirmText="Cancel invoice"
          cancelText="Keep"
          danger={true}
          onConfirm={() => void confirmCancelInvoice()}
          onCancel={dismissCancelDialog}
        />
      ) : null}
    </div>
  );
}
