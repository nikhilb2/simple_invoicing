import { useEffect, useRef, useState } from 'react';
import { ArrowUpDown, Download, Upload, FileDown, Eye, EyeOff, Check, X } from 'lucide-react';
import api, { getApiErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import formatCurrency from '../utils/formatting';

type ProductInvRow = {
  id: number;
  sku: string;
  name: string;
  description: string | null;
  hsn_sac: string | null;
  purchase_price: number;
  selling_price: number;
  current_stock: number;
  reorder_level: number;
  status: string;
  unit: string;
  gst_rate: number;
};

type PaginatedProductsInv = {
  items: ProductInvRow[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
};

type ImportResult = {
  created: number;
  updated: number;
  errors: Array<{ row: number; message: string }>;
};

export default function ProductsInventoryPage() {
  const [rows, setRows] = useState<ProductInvRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [sortBy, setSortBy] = useState('name');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [currencyCode, setCurrencyCode] = useState('USD');
  const pageSize = 50;

  // Inline editing state
  const [editingCell, setEditingCell] = useState<{ id: number; field: string } | null>(null);
  const [editValue, setEditValue] = useState('');
  const [savingCell, setSavingCell] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Import modal
  const [showImportModal, setShowImportModal] = useState(false);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [importing, setImporting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function loadData() {
    try {
      setLoading(true);
      setError('');
      const params: Record<string, unknown> = {
        page,
        page_size: pageSize,
        search,
        sort_by: sortBy,
        sort_order: sortOrder,
      };
      if (statusFilter) {
        params.status = statusFilter;
      }
      const [productsRes, companyRes] = await Promise.all([
        api.get<PaginatedProductsInv>('/products/with-inventory', { params }),
        api.get('/company').catch(() => null),
      ]);
      setRows(productsRes.data.items);
      setTotal(productsRes.data.total);
      setTotalPages(productsRes.data.total_pages);
      if (companyRes?.data?.currency_code) {
        setCurrencyCode(companyRes.data.currency_code);
      }
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to load products and inventory'));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, [search, statusFilter, sortBy, sortOrder, page]);

  // Focus input on edit
  useEffect(() => {
    if (editingCell && inputRef.current) {
      inputRef.current.focus();
    }
  }, [editingCell]);

  function toggleSort(col: string) {
    if (sortBy === col) {
      setSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortBy(col);
      setSortOrder('asc');
    }
    setPage(1);
  }

  function startEdit(row: ProductInvRow, field: string) {
    let value = '';
    switch (field) {
      case 'name':
        value = row.name;
        break;
      case 'sku':
        value = row.sku;
        break;
      case 'selling_price':
        value = String(row.selling_price);
        break;
      case 'purchase_price':
        value = String(row.purchase_price);
        break;
      case 'current_stock':
        value = String(row.current_stock);
        break;
      case 'reorder_level':
        value = String(row.reorder_level);
        break;
      case 'gst_rate':
        value = String(row.gst_rate);
        break;
      case 'description':
        value = row.description || '';
        break;
      case 'hsn_sac':
        value = row.hsn_sac || '';
        break;
      case 'unit':
        value = row.unit || '';
        break;
    }
    setEditingCell({ id: row.id, field });
    setEditValue(value);
  }

  function cancelEdit() {
    setEditingCell(null);
    setEditValue('');
  }

  async function saveEdit() {
    if (!editingCell) return;

    const cellKey = `${editingCell.id}-${editingCell.field}`;
    setSavingCell(cellKey);
    setError('');
    setSuccess('');

    try {
      const payload: Record<string, unknown> = {};
      switch (editingCell.field) {
        case 'name':
          payload.name = editValue;
          break;
        case 'sku':
          payload.sku = editValue;
          break;
        case 'selling_price':
          payload.selling_price = Number(editValue);
          break;
        case 'purchase_price':
          payload.purchase_price = Number(editValue);
          break;
        case 'current_stock':
          payload.current_stock = Number(editValue);
          break;
        case 'reorder_level':
          payload.reorder_level = Number(editValue);
          break;
        case 'gst_rate':
          payload.gst_rate = Number(editValue);
          break;
        case 'description':
          payload.description = editValue;
          break;
        case 'hsn_sac':
          payload.hsn_sac = editValue;
          break;
        case 'unit':
          payload.unit = editValue;
          break;
        case 'status':
          payload.status = editValue;
          break;
      }

      await api.put(`/products/${editingCell.id}/with-inventory`, payload);
      setEditingCell(null);
      setEditValue('');
      setSuccess('Item updated.');
      await loadData();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to update item'));
    } finally {
      setSavingCell(null);
    }
  }

  function handleCellKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      void saveEdit();
    } else if (e.key === 'Escape') {
      cancelEdit();
    }
  }

  async function toggleStatus(row: ProductInvRow) {
    try {
      setError('');
      setSuccess('');
      const newStatus = row.status === 'active' ? 'inactive' : 'active';
      await api.put(`/products/${row.id}/with-inventory`, { status: newStatus });
      setSuccess(`Item marked as ${newStatus}.`);
      await loadData();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to toggle status'));
    }
  }

  // CSV Export
  async function handleExportCSV() {
    try {
      setError('');
      const res = await api.get('/products/export-csv', { responseType: 'blob' });
      const url = URL.createObjectURL(new Blob([res.data], { type: 'text/csv' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `products_inventory_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      setSuccess('CSV exported.');
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to export CSV'));
    }
  }

  // PDF Export — generate simple HTML and print
  async function handleExportPDF() {
    try {
      setError('');
      setLoading(true);
      const res = await api.get<PaginatedProductsInv>('/products/with-inventory', {
        params: { page: 1, page_size: 500, search },
      });
      const allRows = res.data.items;

      const html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Product Inventory Report</title>
  <style>
    body { font-family: sans-serif; padding: 20px; color: #1a1a1a; }
    h1 { font-size: 18px; margin-bottom: 4px; }
    .date { font-size: 12px; color: #666; margin-bottom: 16px; }
    table { width: 100%; border-collapse: collapse; font-size: 11px; }
    th { background: #f5f5f5; text-align: left; padding: 6px 8px; border-bottom: 2px solid #ccc; }
    td { padding: 5px 8px; border-bottom: 1px solid #eee; }
    .num { text-align: right; }
    .inactive { color: #999; }
    @media print {
      body { padding: 0; }
    }
  </style>
</head>
<body>
  <h1>Product Inventory Report</h1>
  <p class="date">Generated on ${new Date().toLocaleDateString()} — ${allRows.length} items</p>
  <table>
    <thead>
      <tr>
        <th>Item Name</th>
        <th>SKU</th>
        <th>Category</th>
        <th>Selling Price</th>
        <th>Purchase Price</th>
        <th>Stock</th>
        <th>Reorder</th>
        <th>Description</th>
        <th>HSN Code</th>
        <th>Unit</th>
        <th>GST %</th>
      </tr>
    </thead>
    <tbody>
      ${allRows.map((r) => `
        <tr class="${r.status === 'inactive' ? 'inactive' : ''}">
          <td>${escapeHtml(r.name)}</td>
          <td>${escapeHtml(r.sku)}</td>
          <td></td>
          <td class="num">${formatCurrency(r.selling_price, currencyCode)}</td>
          <td class="num">${formatCurrency(r.purchase_price, currencyCode)}</td>
          <td class="num">${r.current_stock}</td>
          <td>${escapeHtml(r.description || '')}</td>
          <td>${escapeHtml(r.hsn_sac || '')}</td>
          <td>${escapeHtml(r.unit)}</td>
          <td class="num">${r.gst_rate}%</td>
        </tr>
      `).join('')}
    </tbody>
  </table>
  <script>window.print();</script>
</body>
</html>`;

      const blob = new Blob([html], { type: 'text/html' });
      const url = URL.createObjectURL(blob);
      const w = window.open(url, '_blank');
      if (w) {
        w.onload = () => { URL.revokeObjectURL(url); };
      }
      setSuccess('PDF report opened for printing.');
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to generate PDF'));
    } finally {
      setLoading(false);
    }
  }

  // CSV Import
  function handleImportClick() {
    setShowImportModal(true);
    setImportResult(null);
  }

  async function handleFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      setImporting(true);
      setError('');
      setImportResult(null);

      const formData = new FormData();
      formData.append('file', file);

      const res = await api.post<ImportResult>('/products/import-csv', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setImportResult(res.data);
      if (res.data.errors.length === 0) {
        setSuccess('CSV imported successfully!');
      }
      await loadData();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to import CSV'));
    } finally {
      setImporting(false);
    }
  }

  function SortHeader({ col, label }: { col: string; label: string }) {
    const active = sortBy === col;
    return (
      <button
        type="button"
        className={`button button--ghost inventory-sort-btn${active ? ' inventory-sort-btn--active' : ''}`}
        onClick={() => toggleSort(col)}
        title={`Sort by ${label}`}
        aria-label={`Sort by ${label}`}
      >
        {label}
        <ArrowUpDown size={12} style={{ marginLeft: 4, opacity: active ? 1 : 0.4 }} />
        {active ? <span className="sr-only">({sortOrder})</span> : null}
      </button>
    );
  }

  function EditableCell({
    row,
    field,
    label,
    isNumeric,
    isStatus,
  }: {
    row: ProductInvRow;
    field: string;
    label: string;
    isNumeric?: boolean;
    isStatus?: boolean;
  }) {
    const isEditing = editingCell?.id === row.id && editingCell?.field === field;
    const cellKey = `${row.id}-${field}`;

    if (isEditing) {
      return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <input
            ref={inputRef}
            type={isNumeric ? 'number' : 'text'}
            step={isNumeric ? '0.01' : undefined}
            className="input"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onKeyDown={handleCellKeyDown}
            style={{ width: '100%', padding: '2px 6px', fontSize: '13px' }}
            disabled={savingCell === cellKey}
          />
          <button
            type="button"
            className="button button--ghost button--icon"
            onClick={() => void saveEdit()}
            disabled={savingCell === cellKey}
            title="Save"
            aria-label="Save"
          >
            {savingCell === cellKey ? '…' : <Check size={14} />}
          </button>
          <button
            type="button"
            className="button button--ghost button--icon"
            onClick={cancelEdit}
            disabled={savingCell === cellKey}
            title="Cancel"
            aria-label="Cancel"
          >
            <X size={14} />
          </button>
        </div>
      );
    }

    let display: string;
    if (isStatus) {
      display = row.status;
    } else if (field === 'selling_price') {
      display = formatCurrency(row.selling_price, currencyCode);
    } else if (field === 'purchase_price') {
      display = formatCurrency(row.purchase_price, currencyCode);
    } else if (field === 'gst_rate') {
      display = `${row.gst_rate}%`;
    } else {
      display = String((row as unknown as Record<string, unknown>)[field] ?? '');
    }

    return (
      <span
        className="editable-cell"
        onClick={() => startEdit(row, field)}
        title={`Click to edit ${label}`}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter') startEdit(row, field); }}
        style={{ cursor: 'pointer', display: 'block', minHeight: 24 }}
      >
        {display || <span style={{ opacity: 0.3 }}>—</span>}
      </span>
    );
  }

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Inventory</p>
          <h1 className="page-title">Products &amp; Stock</h1>
          <p className="section-copy">
            Manage products and inventory in one place. Click any cell to edit inline.
            Use the toolbar to export or import via CSV.
          </p>
        </div>
        <div className="status-chip">{total} items</div>
      </section>

      <StatusToasts
        error={error}
        success={success}
        onClearError={() => setError('')}
        onClearSuccess={() => setSuccess('')}
      />

      <section className="content-grid content-grid--single">
        <article className="panel stack">
          {/* Toolbar */}
          <div className="panel__header" style={{ flexWrap: 'wrap', gap: 12 }}>
            <div className="field" style={{ flex: '1 1 220px', margin: 0 }}>
              <input
                className="input"
                type="search"
                placeholder="Search by name or SKU…"
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                aria-label="Search products"
              />
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <select
                className="select"
                value={statusFilter}
                onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
                style={{ minWidth: 120 }}
                aria-label="Filter by status"
              >
                <option value="">All status</option>
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </select>
              <button
                type="button"
                className="button button--secondary"
                onClick={handleExportCSV}
                title="Export CSV"
                aria-label="Export CSV"
              >
                <Download size={15} style={{ marginRight: 4 }} />
                CSV
              </button>
              <button
                type="button"
                className="button button--secondary"
                onClick={handleExportPDF}
                title="Export PDF"
                aria-label="Export PDF"
              >
                <FileDown size={15} style={{ marginRight: 4 }} />
                PDF
              </button>
              <button
                type="button"
                className="button button--secondary"
                onClick={handleImportClick}
                title="Import CSV"
                aria-label="Import CSV"
              >
                <Upload size={15} style={{ marginRight: 4 }} />
                Import
              </button>
            </div>
          </div>

          {/* Table */}
          <div style={{ overflowX: 'auto' }}>
            <table className="products-inv-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--line-strong, #ddd)' }}>
                  <th style={{ padding: '8px 10px', textAlign: 'left' }}>
                    <SortHeader col="name" label="Item Name" />
                  </th>
                  <th style={{ padding: '8px 10px', textAlign: 'left' }}>
                    <SortHeader col="sku" label="SKU" />
                  </th>
                  <th style={{ padding: '8px 10px', textAlign: 'left' }}>Category</th>
                  <th style={{ padding: '8px 10px', textAlign: 'right' }}>
                    <SortHeader col="price" label="Selling Price" />
                  </th>
                  <th style={{ padding: '8px 10px', textAlign: 'right' }}>Purchase Price</th>
                  <th style={{ padding: '8px 10px', textAlign: 'right' }}>
                    <SortHeader col="stock" label="Stock" />
                  </th>
                  <th style={{ padding: '8px 10px', textAlign: 'right' }}>Reorder</th>
                  <th style={{ padding: '8px 10px', textAlign: 'center' }}>Status</th>
                  <th style={{ padding: '8px 10px', textAlign: 'left' }}>GST</th>
                  <th style={{ padding: '8px 10px', textAlign: 'left' }}>HSN</th>
                  <th style={{ padding: '8px 10px', textAlign: 'left' }}>Unit</th>
                  <th style={{ padding: '8px 10px', textAlign: 'left' }}>Description</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={12} style={{ padding: 24, textAlign: 'center' }}>
                      Loading products…
                    </td>
                  </tr>
                ) : rows.length === 0 ? (
                  <tr>
                    <td colSpan={12} style={{ padding: 24, textAlign: 'center' }}>
                      No products match your search.
                    </td>
                  </tr>
                ) : (
                  rows.map((row) => (
                    <tr key={row.id} className={`inv-row ${row.status === 'inactive' ? 'inv-row--inactive' : ''}`}>
                      <td style={{ padding: '6px 10px' }}>
                        <EditableCell row={row} field="name" label="Name" />
                      </td>
                      <td style={{ padding: '6px 10px', fontFamily: 'monospace', fontSize: '12px' }}>
                        <EditableCell row={row} field="sku" label="SKU" />
                      </td>
                      <td style={{ padding: '6px 10px', color: 'var(--text-muted, #999)' }}>
                        —
                      </td>
                      <td style={{ padding: '6px 10px', textAlign: 'right' }}>
                        <EditableCell row={row} field="selling_price" label="Price" isNumeric />
                      </td>
                      <td style={{ padding: '6px 10px', textAlign: 'right' }}>
                        <EditableCell row={row} field="purchase_price" label="Purchase Price" isNumeric />
                      </td>
                      <td style={{ padding: '6px 10px', textAlign: 'right' }}>
                        <EditableCell row={row} field="current_stock" label="Stock" isNumeric />
                      </td>
                      <td style={{ padding: '6px 10px', textAlign: 'right' }}>
                        <EditableCell row={row} field="reorder_level" label="Reorder" isNumeric />
                      </td>
                      <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                        <button
                          type="button"
                          className={`button button--ghost button--icon`}
                          onClick={() => toggleStatus(row)}
                          title={`Toggle status (currently ${row.status})`}
                          aria-label={`Toggle status for ${row.name}`}
                        >
                          {row.status === 'active' ? (
                            <Eye size={15} style={{ color: 'var(--success, green)' }} />
                          ) : (
                            <EyeOff size={15} style={{ color: 'var(--muted, #999)' }} />
                          )}
                        </button>
                      </td>
                      <td style={{ padding: '6px 10px' }}>
                        <EditableCell row={row} field="gst_rate" label="GST" isNumeric />
                      </td>
                      <td style={{ padding: '6px 10px' }}>
                        <EditableCell row={row} field="hsn_sac" label="HSN" />
                      </td>
                      <td style={{ padding: '6px 10px' }}>
                        <EditableCell row={row} field="unit" label="Unit" />
                      </td>
                      <td style={{ padding: '6px 10px', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        <EditableCell row={row} field="description" label="Description" />
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 ? (
            <div className="button-row" style={{ justifyContent: 'center', paddingTop: 12 }}>
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

      {/* Hidden file input for CSV import */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".csv"
        style={{ display: 'none' }}
        onChange={handleFileSelected}
      />

      {/* Import Modal */}
      {showImportModal ? (
        <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) setShowImportModal(false); }}>
          <div className="modal-panel" style={{ maxWidth: 480 }}>
            <h2 style={{ marginBottom: 16 }}>Import Products from CSV</h2>
            <p className="muted-text" style={{ marginBottom: 16 }}>
              Upload a CSV file with headers like <code>Item Code</code>,{' '}
              <code>Item Name</code>, <code>Selling Price</code>, <code>Current Stock</code>, etc.
              Existing items will be updated by Item Code (SKU).
            </p>
            {importResult ? (
              <div className="import-results">
                <p>
                  <strong>Created:</strong> {importResult.created}{' | '}
                  <strong>Updated:</strong> {importResult.updated}{' | '}
                  <strong>Errors:</strong> {importResult.errors.length}
                </p>
                {importResult.errors.length > 0 && (
                  <ul style={{ maxHeight: 200, overflow: 'auto', marginTop: 8, fontSize: '12px' }}>
                    {importResult.errors.map((err, i) => (
                      <li key={i}>Row {err.row}: {err.message}</li>
                    ))}
                  </ul>
                )}
              </div>
            ) : null}
            <div style={{ marginTop: 16, display: 'flex', gap: 12 }}>
              {!importResult ? (
                <button
                  type="button"
                  className="button button--primary"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={importing}
                >
                  {importing ? 'Importing…' : 'Select CSV file'}
                </button>
              ) : null}
              <button
                type="button"
                className="button button--secondary"
                onClick={() => { setShowImportModal(false); setImportResult(null); }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
