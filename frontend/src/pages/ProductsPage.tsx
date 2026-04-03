import { useEffect, useState } from 'react';
import api, { getApiErrorMessage } from '../api/client';
import type { CompanyProfile, PaginatedProducts, Product, ProductCreate } from '../types/api';
import StatusToasts from '../components/StatusToasts';
import ConfirmDialog from '../components/ConfirmDialog';

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

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [deletingProductId, setDeletingProductId] = useState<number | null>(null);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [pendingDeleteProductId, setPendingDeleteProductId] = useState<number | null>(null);
  const [editingProductId, setEditingProductId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  const pageSize = 20;
  const [form, setForm] = useState({
    sku: '',
    name: '',
    description: '',
    hsn_sac: '',
    price: '',
    gst_rate: '0',
  });

  const activeCurrencyCode = company?.currency_code || 'USD';

  async function loadProducts() {
    try {
      setLoading(true);
      setError('');
      const [productsRes, companyRes] = await Promise.all([
        api.get<PaginatedProducts>('/products/', {
          params: { page, page_size: pageSize, search },
        }),
        api.get<CompanyProfile>('/company/'),
      ]);
      setProducts(productsRes.data.items);
      setTotal(productsRes.data.total);
      setTotalPages(productsRes.data.total_pages);
      setCompany(companyRes.data);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load products'));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadProducts();
  }, [page, search]);

  function resetForm() {
    setForm({ sku: '', name: '', description: '', hsn_sac: '', price: '', gst_rate: '0' });
    setEditingProductId(null);
  }

  function startEditProduct(product: Product) {
    setError('');
    setSuccess('');
    setEditingProductId(product.id);
    setForm({
      sku: product.sku,
      name: product.name,
      description: product.description ?? '',
      hsn_sac: product.hsn_sac ?? '',
      price: String(product.price),
      gst_rate: String(product.gst_rate),
    });
  }

  async function handleSubmitProduct(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    try {
      setSubmitting(true);
      setError('');
      setSuccess('');

      const payload: ProductCreate = {
        sku: form.sku.trim(),
        name: form.name.trim(),
        description: form.description.trim(),
        hsn_sac: form.hsn_sac.trim(),
        price: Number(form.price),
        gst_rate: Number(form.gst_rate),
      };

      if (editingProductId) {
        await api.put<Product>(`/products/${editingProductId}`, payload);
        setSuccess('Product updated successfully.');
      } else {
        await api.post<Product>('/products/', payload);
        setSuccess('Product created successfully.');
      }

      resetForm();
      await loadProducts();
    } catch (err) {
      setError(getApiErrorMessage(err, editingProductId ? 'Unable to update product' : 'Unable to create product'));
    } finally {
      setSubmitting(false);
    }
  }

  function handleDeleteProduct(productId: number) {
    setPendingDeleteProductId(productId);
    setShowDeleteDialog(true);
  }

  function cancelDeleteProduct() {
    setShowDeleteDialog(false);
    setPendingDeleteProductId(null);
  }

  async function confirmDeleteProduct() {
    if (pendingDeleteProductId === null) return;
    setShowDeleteDialog(false);

    try {
      setDeletingProductId(pendingDeleteProductId);
      setError('');
      setSuccess('');

      await api.delete(`/products/${pendingDeleteProductId}`);
      if (editingProductId === pendingDeleteProductId) {
        resetForm();
      }

      setSuccess('Product deleted successfully.');
      await loadProducts();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to delete product'));
    } finally {
      setDeletingProductId(null);
      setPendingDeleteProductId(null);
    }
  }

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Products</p>
          <h1 className="page-title">Catalog intake</h1>
          <p className="section-copy">Create products, keep pricing current, and review the active SKU list.</p>
        </div>
        <div className="status-chip">{total} loaded</div>
      </section>

      <StatusToasts error={error} success={success} onClearError={() => setError('')} onClearSuccess={() => setSuccess('')} />

      <section className="content-grid">
        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Create product</p>
              <h2 className="nav-panel__title">{editingProductId ? `Editing product #${editingProductId}` : 'New SKU'}</h2>
            </div>
          </div>

          <form className="stack" onSubmit={handleSubmitProduct}>
            <div className="field-grid">
              <div className="field">
                <label htmlFor="sku">SKU</label>
                <input
                  id="sku"
                  className="input"
                  value={form.sku}
                  onChange={(event) => setForm((current) => ({ ...current, sku: event.target.value }))}
                  placeholder="RSP-1001"
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="price">Price</label>
                <input
                  id="price"
                  className="input"
                  type="number"
                  min="0"
                  step="0.01"
                  value={form.price}
                  onChange={(event) => setForm((current) => ({ ...current, price: event.target.value }))}
                  placeholder="99.00"
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="hsn-sac">HSN/SAC</label>
                <input
                  id="hsn-sac"
                  className="input"
                  value={form.hsn_sac}
                  onChange={(event) => setForm((current) => ({ ...current, hsn_sac: event.target.value }))}
                  placeholder="8471 or 9983"
                />
              </div>
              <div className="field">
                <label htmlFor="gst-rate">GST %</label>
                <input
                  id="gst-rate"
                  className="input"
                  type="number"
                  min="0"
                  max="100"
                  step="0.01"
                  value={form.gst_rate}
                  onChange={(event) => setForm((current) => ({ ...current, gst_rate: event.target.value }))}
                  placeholder="18"
                  required
                />
              </div>
              <div className="field field--full">
                <label htmlFor="name">Name</label>
                <input
                  id="name"
                  className="input"
                  value={form.name}
                  onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                  placeholder="Simple Controller"
                  required
                />
              </div>
              <div className="field field--full">
                <label htmlFor="description">Description</label>
                <textarea
                  id="description"
                  className="textarea"
                  value={form.description}
                  onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
                  placeholder="Optional details for operators and quoting."
                />
              </div>
            </div>

            <div className="button-row">
              {editingProductId ? (
                <button type="button" className="button button--secondary" onClick={resetForm} title="Cancel edit" aria-label="Cancel edit">
                  Cancel edit
                </button>
              ) : null}
              <button className="button button--primary" disabled={submitting} title={editingProductId ? "Update product" : "Create product"} aria-label={editingProductId ? "Update product" : "Create product"}>
                {submitting ? (editingProductId ? 'Updating product...' : 'Saving product...') : editingProductId ? 'Update product' : 'Create product'}
              </button>
            </div>
          </form>
        </article>

        <article className="panel stack">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Current catalog</p>
              <h2 className="nav-panel__title">Products list</h2>
            </div>
          </div>

          <div className="field">
            <label htmlFor="product-search">Search by name</label>
            <input
              id="product-search"
              className="input"
              type="search"
              placeholder="Type to search products..."
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
            />
          </div>

          <div className="table-list">
            {loading ? <div className="empty-state">Loading products...</div> : null}
            {!loading && products.length === 0 ? <div className="empty-state">No products have been created yet.</div> : null}
            {!loading
              ? products.map((product) => (
                  <div key={product.id} className="table-row">
                    <div className="table-row__meta">
                      <strong>{product.name}</strong>
                      <span className="table-subtext">
                        {product.sku}
                        {product.hsn_sac ? ` • HSN/SAC ${product.hsn_sac}` : ''}
                        {` • GST ${product.gst_rate}%`}
                        {product.description ? ` • ${product.description}` : ''}
                      </span>
                    </div>
                    <span className="table-row__price">{formatCurrency(product.price, activeCurrencyCode)}</span>
                    <div className="table-row__actions">
                      <button type="button" className="button button--ghost" onClick={() => startEditProduct(product)} disabled={submitting} title={`Edit product ${product.name}`} aria-label={`Edit product ${product.name}`}>
                        Edit
                      </button>
                      <button
                        type="button"
                        className="button button--danger"
                        onClick={() => handleDeleteProduct(product.id)}
                        disabled={deletingProductId === product.id}
                        title={`Delete product ${product.name}`}
                        aria-label={`Delete product ${product.name}`}
                      >
                        {deletingProductId === product.id ? 'Deleting...' : 'Delete'}
                      </button>
                    </div>
                  </div>
                ))
              : null}
          </div>

          {totalPages > 1 ? (
            <div className="button-row" style={{ justifyContent: 'center', paddingTop: '8px' }}>
              <button
                type="button"
                className="button button--ghost"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
                title="Previous page"
                aria-label="Previous page"
              >
                Previous
              </button>
              <span className="muted-text" style={{ alignSelf: 'center' }}>
                Page {page} of {totalPages}
              </span>
              <button
                type="button"
                className="button button--ghost"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
                title="Next page"
                aria-label="Next page"
              >
                Next
              </button>
            </div>
          ) : null}
        </article>
      </section>

      {showDeleteDialog ? (
        <ConfirmDialog
          message={`Are you sure you want to delete product #${pendingDeleteProductId}? This cannot be undone.`}
          title="Delete product"
          confirmText="Delete"
          cancelText="Cancel"
          danger={true}
          onConfirm={() => void confirmDeleteProduct()}
          onCancel={cancelDeleteProduct}
        />
      ) : null}
    </div>
  );
}
