import { useEffect, useState } from 'react';
import { Pencil, Trash2, Settings2 } from 'lucide-react';
import api, { getApiErrorMessage } from '../api/client';
import type { CompanyProfile, PaginatedProducts, Product, ProductCreate } from '../types/api';
import StatusToasts from '../components/StatusToasts';
import ConfirmDialog from '../components/ConfirmDialog';
import BOMConfigModal from '../components/BOMConfigModal';
import formatCurrency from '../utils/formatting';
import EmptyState from '../components/EmptyState';

const UNIT_OPTIONS = ['Pieces', 'Kg', 'g', 'm', 'l', 'Ounce'];
const CUSTOM_UNIT_VALUE = '__custom__';

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
    unit: 'Pieces',
    allow_decimal: false,
    maintain_inventory: true,
    initial_quantity: '0',
    is_producable: false,
    production_cost: '',
  });
  const [bomModalProductId, setBomModalProductId] = useState<number | null>(null);
  const [bomModalProductName, setBomModalProductName] = useState('');

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
    setForm({ sku: '', name: '', description: '', hsn_sac: '', price: '', gst_rate: '0', unit: 'Pieces', allow_decimal: false, maintain_inventory: true, initial_quantity: '0', is_producable: false, production_cost: '' });
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
      unit: product.unit || 'Pieces',
      allow_decimal: product.allow_decimal,
      maintain_inventory: product.maintain_inventory,
      initial_quantity: '0',
      is_producable: product.is_producable,
      production_cost: product.production_cost != null ? String(product.production_cost) : '',
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
        unit: form.unit.trim() || 'Pieces',
        allow_decimal: form.allow_decimal,
        maintain_inventory: form.maintain_inventory,
        is_producable: form.is_producable,
        production_cost: form.production_cost !== '' ? Number(form.production_cost) : null,
        ...(editingProductId ? {} : { initial_quantity: Number(form.initial_quantity) }),
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
              <div className="field">
                <label htmlFor="unit">Unit</label>
                <select
                  id="unit"
                  className="input"
                  value={UNIT_OPTIONS.includes(form.unit) ? form.unit : CUSTOM_UNIT_VALUE}
                  onChange={(event) => {
                    const value = event.target.value;
                    setForm((current) => ({
                      ...current,
                      unit: value === CUSTOM_UNIT_VALUE ? '' : value,
                    }));
                  }}
                >
                  {UNIT_OPTIONS.map((unitOption) => (
                    <option key={unitOption} value={unitOption}>{unitOption}</option>
                  ))}
                  <option value={CUSTOM_UNIT_VALUE}>Other (custom)</option>
                </select>
              </div>
              {UNIT_OPTIONS.includes(form.unit) ? null : (
                <div className="field">
                  <label htmlFor="custom-unit">Custom unit</label>
                  <input
                    id="custom-unit"
                    className="input"
                    value={form.unit}
                    onChange={(event) => setForm((current) => ({ ...current, unit: event.target.value }))}
                    placeholder="e.g. cm, ml, pack"
                    required
                  />
                </div>
              )}
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
              <div className="field field--full" style={{ marginBottom: 0 }}>
                <label htmlFor="maintain-inventory" style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: 0 }}>
                  <input
                    id="maintain-inventory"
                    type="checkbox"
                    checked={form.maintain_inventory}
                    onChange={(event) => setForm((current) => ({ ...current, maintain_inventory: event.target.checked }))}
                  />
                  Maintain inventory for this product
                </label>
                <span className="field-hint">
                  Turn this off for service-style items such as service charges.
                </span>
              </div>
              <div className="field field--full" style={{ marginBottom: 0 }}>
                <label htmlFor="allow-decimal" style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: 0 }}>
                  <input
                    id="allow-decimal"
                    type="checkbox"
                    checked={form.allow_decimal}
                    onChange={(event) => setForm((current) => ({ ...current, allow_decimal: event.target.checked }))}
                  />
                  Allow decimal quantity
                </label>
                <span className="field-hint">
                  Turn this on for units like Kg, l, m and other fractional stock.
                </span>
              </div>
              <div className="field field--full" style={{ marginBottom: 0 }}>
                <label htmlFor="is-producable" style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: 0 }}>
                  <input
                    id="is-producable"
                    type="checkbox"
                    checked={form.is_producable}
                    onChange={(event) => setForm((current) => ({ ...current, is_producable: event.target.checked }))}
                  />
                  Producable item (assembled from components)
                </label>
                <span className="field-hint">
                  Enable to configure a Bill of Materials and allow production from raw components.
                </span>
              </div>
              {form.is_producable ? (
                <div className="field">
                  <label htmlFor="production-cost">Additional production cost (optional)</label>
                  <input
                    id="production-cost"
                    className="input"
                    type="number"
                    min="0"
                    step="0.01"
                    value={form.production_cost}
                    onChange={(event) => setForm((current) => ({ ...current, production_cost: event.target.value }))}
                    placeholder="e.g. 5.00 for labour/overhead"
                  />
                  <span className="field-hint">Added on top of component material cost.</span>
                </div>
              ) : null}
              {!editingProductId && form.maintain_inventory ? (
                <div className="field">
                  <label htmlFor="initial-quantity">Initial stock quantity</label>
                  <input
                    id="initial-quantity"
                    className="input"
                    type="number"
                    min="0"
                    step={form.allow_decimal ? '0.001' : '1'}
                    value={form.initial_quantity}
                    onChange={(event) => setForm((current) => ({ ...current, initial_quantity: event.target.value }))}
                    placeholder="0"
                  />
                  <span className="field-hint">Starting inventory count for this product.</span>
                </div>
              ) : null}
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
            {loading ? <EmptyState message="Loading products..." /> : null}
            {!loading && products.length === 0 && !search ? (
              <EmptyState
                message="No products registered yet. Add your first product to start building your catalog."
                action={{ label: 'Add First Product', onClick: () => document.getElementById('sku')?.focus() }}
              />
            ) : null}
            {!loading && products.length === 0 && search ? (
              <EmptyState message="No products match your search." />
            ) : null}
            {!loading
              ? products.map((product) => (
                  <div key={product.id} className="table-row">
                    <div className="table-row__meta">
                      <strong>{product.name}</strong>
                      <span className="table-subtext">
                        {product.sku}
                        {product.maintain_inventory ? ' • Tracked' : ' • Untracked'}
                        {` • Unit ${product.unit}`}
                        {product.allow_decimal ? ' • Decimal qty' : ' • Whole qty'}
                        {product.hsn_sac ? ` • HSN/SAC ${product.hsn_sac}` : ''}
                        {` • GST ${product.gst_rate}%`}
                        {product.description ? ` • ${product.description}` : ''}
                      </span>
                    </div>
                    <span className="table-row__price">{formatCurrency(product.price, activeCurrencyCode)}</span>
                    <div className="table-row__actions">
                      {product.is_producable ? (
                        <button
                          type="button"
                          className="button button--ghost button--icon"
                          onClick={() => { setBomModalProductId(product.id); setBomModalProductName(product.name); }}
                          disabled={submitting}
                          title={`Configure BOM for ${product.name}`}
                          aria-label={`Configure BOM for ${product.name}`}
                        >
                          <Settings2 size={16} />
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="button button--ghost button--icon"
                        onClick={() => startEditProduct(product)}
                        disabled={submitting}
                        title={`Edit product ${product.name}`}
                        aria-label={`Edit product ${product.name}`}
                      >
                        <Pencil size={16} />
                      </button>
                      <button
                        type="button"
                        className="button button--danger button--icon"
                        onClick={() => handleDeleteProduct(product.id)}
                        disabled={deletingProductId === product.id}
                        title={`Delete product ${product.name}`}
                        aria-label={`Delete product ${product.name}`}
                      >
                        <Trash2 size={16} />
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
      {bomModalProductId !== null ? (
        <BOMConfigModal
          productId={bomModalProductId}
          productName={bomModalProductName}
          onClose={() => { setBomModalProductId(null); setBomModalProductName(''); }}
        />
      ) : null}
    </div>
  );
}
