import { useEffect, useState } from 'react';
import api, { getApiErrorMessage } from '../api/client';
import type { CompanyProfile, Invoice, InvoiceCreate, Ledger, LedgerCreate, PaginatedInvoices, Product } from '../types/api';
import InvoicePreview from '../components/InvoicePreview';
import ConfirmDialog from '../components/ConfirmDialog';

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

export default function InvoicesPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [ledgers, setLedgers] = useState<Ledger[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [selectedLedgerId, setSelectedLedgerId] = useState('');
  const [voucherType, setVoucherType] = useState<'sales' | 'purchase'>('sales');
  const [invoiceDate, setInvoiceDate] = useState(new Date().toISOString().slice(0, 10));
  const [showLedgerModal, setShowLedgerModal] = useState(false);
  const [showProductModal, setShowProductModal] = useState(false);
  const [showStockModal, setShowStockModal] = useState(false);
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
          params: { page: invoicePage, page_size: invoicePageSize, search: invoiceSearch },
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

  useEffect(() => {
    void loadInvoicePageData();
  }, [invoicePage, invoiceSearch]);

  const totalAmount = items.reduce((sum, item) => {
    const product = products.find((entry) => entry.id === Number(item.productId));
    const quantity = Number(item.quantity);
    const unitPrice = item.unit_price ? Number(item.unit_price) : (product?.price || 0);
    const gstRate = product?.gst_rate || 0;

    if (!product || Number.isNaN(quantity)) {
      return sum;
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

    try {
      setSubmitting(true);
      setError('');
      setSuccess('');

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
        adjustment: Number(stockForm.adjustment),
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

      {error ? <div className="status-banner status-banner--error">{error}</div> : null}
      {success ? <div className="status-banner status-banner--success">{success}</div> : null}

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
                  onChange={(event) => setVoucherType(event.target.value as 'sales' | 'purchase')}
                >
                  <option value="sales">Sales</option>
                  <option value="purchase">Purchase</option>
                </select>
              </div>

              <div className="field">
                <label htmlFor="invoice-ledger">Ledger</label>
                <select
                  id="invoice-ledger"
                  className="select"
                  value={selectedLedgerId}
                  onChange={(event) => setSelectedLedgerId(event.target.value)}
                  required
                >
                  {ledgers.length === 0 ? <option value="">No ledgers available</option> : null}
                  {ledgers.map((ledger) => (
                    <option key={ledger.id} value={ledger.id}>
                      {ledger.name} ({ledger.gst})
                    </option>
                  ))}
                </select>
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

              <div className="button-row">
                <button type="button" className="button button--secondary" onClick={() => setShowLedgerModal(true)}>
                  Add ledger
                </button>
                <button type="button" className="button button--secondary" onClick={() => setShowProductModal(true)}>
                  Add product
                </button>
                <button type="button" className="button button--secondary" onClick={() => setShowStockModal(true)}>
                  Update stock
                </button>
              </div>
            </div>

            <div className="stack">
              {items.map((item, index) => {
                const selectedProduct = products.find((product) => product.id === Number(item.productId));
                const unitPrice = item.unit_price ? Number(item.unit_price) : (selectedProduct?.price || 0);
                const gstRate = selectedProduct?.gst_rate || 0;
                const taxableAmount = unitPrice * Number(item.quantity || 0);
                const taxAmount = taxableAmount * gstRate / 100;
                const lineTotal = taxableAmount + taxAmount;

                return (
                  <div key={item.id} className="line-item">
                    <div className="field">
                      <label htmlFor={`invoice-product-${item.id}`}>Line {index + 1}</label>
                      <select
                        id={`invoice-product-${item.id}`}
                        className="select"
                        value={item.productId}
                        onChange={(event) => {
                          updateItem(item.id, 'productId', event.target.value);
                          const newProduct = products.find((p) => p.id === Number(event.target.value));
                          if (newProduct) {
                            updateItem(item.id, 'unit_price', String(newProduct.price));
                          }
                        }}
                        required
                      >
                        {products.length === 0 ? <option value="">No products available</option> : null}
                        {products.map((product) => (
                          <option key={product.id} value={product.id}>
                            {product.name} ({product.sku})
                          </option>
                        ))}
                      </select>
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
                      <label htmlFor={`invoice-price-${item.id}`}>Price</label>
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
                    <button type="button" className="button button--danger" onClick={() => removeItem(item.id)}>
                      Remove
                    </button>
                  </div>
                );
              })}
            </div>

            <div className="button-row">
              <button type="button" className="button button--ghost" onClick={addItem} disabled={products.length === 0}>
                Add line item
              </button>
              {editingInvoiceId ? (
                <button type="button" className="button button--secondary" onClick={resetInvoiceForm}>
                  Cancel edit
                </button>
              ) : null}
              <button className="button button--primary" disabled={submitting || products.length === 0 || !selectedLedgerId}>
                {submitting ? (editingInvoiceId ? 'Updating invoice...' : 'Creating invoice...') : editingInvoiceId ? 'Update invoice' : 'Create invoice'}
              </button>
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

          <div className="invoice-list">
            {loading ? (
              <div className="empty-state">
                <p style={{ fontSize: '0.95rem' }}>Loading invoices...</p>
              </div>
            ) : null}
            {!loading && invoices.length === 0 ? (
              <div className="empty-state">
                <p style={{ fontSize: '0.95rem' }}>No invoices created yet. Start by creating your first invoice above.</p>
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
                        </div>
                        <span className={`invoice-type-badge invoice-type-badge--${invoice.voucher_type}`}>
                          {invoice.voucher_type === 'sales' ? 'Sales' : 'Purchase'}
                        </span>
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
                        <button type="button" className="button button--ghost button--small" onClick={() => setPreviewInvoice(invoice)} title="Preview invoice">
                          Preview
                        </button>
                        <button type="button" className="button button--ghost button--small" onClick={() => startEditingInvoice(invoice)} disabled={submitting} title="Edit invoice">
                          Edit
                        </button>
                        <button
                          type="button"
                          className="button button--danger button--small"
                          onClick={() => void handleDeleteInvoice(invoice.id)}
                          disabled={deletingInvoiceId === invoice.id}
                          title="Delete invoice"
                        >
                          {deletingInvoiceId === invoice.id ? 'Deleting...' : 'Delete'}
                        </button>
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
              >
                Next
              </button>
            </div>
          ) : null}
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
                <button type="button" className="button button--ghost" onClick={() => setShowLedgerModal(false)}>
                  Cancel
                </button>
                <button className="button button--primary" disabled={ledgerSubmitting}>
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
                <button type="button" className="button button--ghost" onClick={() => setShowProductModal(false)}>
                  Cancel
                </button>
                <button className="button button--primary" disabled={productSubmitting}>
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
                <select
                  id="modal-stock-product"
                  className="select"
                  value={stockForm.productId}
                  onChange={(event) => setStockForm((current) => ({ ...current, productId: event.target.value }))}
                  required
                >
                  <option value="">Select a product</option>
                  {products.map((product) => (
                    <option key={product.id} value={product.id}>
                      {product.name} ({product.sku})
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="modal-stock-adjustment">Quantity adjustment</label>
                <input
                  id="modal-stock-adjustment"
                  className="input"
                  type="number"
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
                <button type="button" className="button button--ghost" onClick={() => setShowStockModal(false)}>
                  Cancel
                </button>
                <button className="button button--primary" disabled={stockSubmitting}>
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
    </div>
  );
}
