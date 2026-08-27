import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Download, FileText, Plus, Search, Upload, X } from 'lucide-react';
import api, { getApiErrorMessage } from '../api/client';
import StatusToasts from '../components/StatusToasts';
import ConfirmDialog from '../components/ConfirmDialog';
import EmptyState from '../components/EmptyState';
import Pagination from '../components/Pagination';
import Tabs from '../components/Tabs';
import BOMConfigModal from '../components/BOMConfigModal';
import SerialBackfillModal from '../components/SerialBackfillModal';
import useDebouncedValue from '../hooks/useDebouncedValue';
import { numericParam, useDeepLinkScroll } from '../utils/deepLink';
import { scanCode } from '../features/serials/api';
import type { CompanyProfile, Product, ProductCreate } from '../types/api';
import CatalogueTable from './catalogue/CatalogueTable';
import ProductFormModal from './catalogue/ProductFormModal';
import type { BackfillTarget } from './catalogue/ProductFormModal';
import StockAdjustModal from './catalogue/StockAdjustModal';
import SerialHistoryDrawer from './catalogue/SerialHistoryDrawer';
import ImportModal from './catalogue/ImportModal';
import { exportCatalogueCsv, exportCataloguePdf } from './catalogue/exports';
import { isLowStock, isSerialFilter, rowEditFrom } from './catalogue/types';
import type {
  CatalogueRow,
  PaginatedCatalogue,
  RowEdit,
  SerialFilter,
  SortKey,
  SortOrder,
} from './catalogue/types';

/**
 * The catalogue.
 *
 * This replaces /products, /inventory and /products-inventory, which were three
 * views of one record — `inventory.product_id` is UNIQUE, so stock is a column
 * on a product, not a separate entity. Three sidebar entries for one thing meant
 * the answer to "where do I change a price?" was "it depends", and the third
 * page was a superset of neither of the other two.
 *
 * The views below are filters over one list, not separate pages, so a product
 * and its stock are never more than a tab apart.
 */

const PAGE_SIZE = 25;

const VIEWS = [
  { id: 'all', label: 'All items' },
  { id: 'low', label: 'Low stock' },
  { id: 'inactive', label: 'Not stocked' },
] as const;

type ViewId = (typeof VIEWS)[number]['id'];

function isViewId(value: string | null): value is ViewId {
  return value === 'all' || value === 'low' || value === 'inactive';
}

export default function CataloguePage() {
  const [searchParams, setSearchParams] = useSearchParams();

  // Filters live in the URL. The old grid held them in component state, so a
  // refresh or a browser Back silently reset the view you had built.
  const view: ViewId = isViewId(searchParams.get('view')) ? (searchParams.get('view') as ViewId) : 'all';
  const search = searchParams.get('q') ?? '';
  // Serial tracking is orthogonal to the views above — "low stock" and
  // "serial-tracked" is a question worth asking — so it is its own param
  // rather than a fourth tab.
  const serials: SerialFilter = isSerialFilter(searchParams.get('serials'))
    ? (searchParams.get('serials') as SerialFilter)
    : '';
  const sortBy = (searchParams.get('sort') as SortKey) || 'name';
  const sortOrder: SortOrder = searchParams.get('dir') === 'desc' ? 'desc' : 'asc';
  const page = Math.max(1, Number(searchParams.get('page') ?? '1') || 1);

  const debouncedSearch = useDebouncedValue(search, 300);

  const [rows, setRows] = useState<CatalogueRow[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loadFailed, setLoadFailed] = useState(false);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editValues, setEditValues] = useState<RowEdit | null>(null);
  const [savingId, setSavingId] = useState<number | null>(null);
  const [rowError, setRowError] = useState('');

  const [formRow, setFormRow] = useState<CatalogueRow | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [adjustRow, setAdjustRow] = useState<CatalogueRow | null>(null);
  const [serialsRow, setSerialsRow] = useState<CatalogueRow | null>(null);
  const [bomTarget, setBomTarget] = useState<{ id: number; name: string } | null>(null);
  const [backfill, setBackfill] = useState<{ product: BackfillTarget; payload: ProductCreate } | null>(
    null,
  );
  const [importOpen, setImportOpen] = useState(false);
  const [deleteRow, setDeleteRow] = useState<CatalogueRow | null>(null);
  const [exporting, setExporting] = useState<'csv' | 'pdf' | null>(null);

  const [highlightId, setHighlightId] = useState<number | null>(null);
  /* A scanned-code link names one unit, so its drawer opens pre-filtered to it. */
  const [deepLinkSerials, setDeepLinkSerials] = useState<{ productId: number; serial: string } | null>(
    null,
  );
  const deepLinkHandled = useRef(false);

  /* A stale response must never overwrite a fresher one: without this guard,
     typing fast lets an early request land last and repopulate the list with
     results for a search the user has already moved past. */
  const latestRequest = useRef(0);

  const statusFilter = view === 'inactive' ? 'inactive' : '';
  const lowStock = view === 'low';

  const loadData = useCallback(async () => {
    const requestId = latestRequest.current + 1;
    latestRequest.current = requestId;
    setLoading(true);

    try {
      const response = await api.get<PaginatedCatalogue>('/products/with-inventory', {
        params: {
          page,
          page_size: PAGE_SIZE,
          search: debouncedSearch,
          status: statusFilter,
          low_stock: lowStock,
          serials,
          sort_by: sortBy,
          sort_order: sortOrder,
        },
      });
      if (latestRequest.current !== requestId) return;

      setRows(response.data.items);
      setTotal(response.data.total);
      setTotalPages(response.data.total_pages);
      setLoadFailed(false);
    } catch (err) {
      if (latestRequest.current !== requestId) return;
      setRows([]);
      setTotal(0);
      // Distinguished from an empty catalogue: the old pages showed the
      // "add your first product" onboarding CTA to users whose fetch had failed.
      setLoadFailed(true);
      setError(getApiErrorMessage(err, 'Unable to load the catalogue'));
    } finally {
      if (latestRequest.current === requestId) setLoading(false);
    }
  }, [page, debouncedSearch, statusFilter, lowStock, serials, sortBy, sortOrder]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // The company profile only supplies the currency symbol and never changes
  // between pages, so it is fetched once rather than on every keystroke.
  useEffect(() => {
    api
      .get<CompanyProfile>('/company/')
      .then((response) => setCompany(response.data))
      .catch(() => setCompany(null));
  }, []);

  const currencyCode = company?.currency_code || 'USD';

  function setParams(next: Record<string, string | null>) {
    const params = new URLSearchParams(searchParams);
    Object.entries(next).forEach(([key, value]) => {
      if (value === null || value === '') params.delete(key);
      else params.set(key, value);
    });
    setSearchParams(params, { replace: true });
  }

  function changeView(nextView: ViewId) {
    setParams({ view: nextView === 'all' ? null : nextView, page: null });
  }

  function changeSearch(value: string) {
    setParams({ q: value || null, page: null });
  }

  function changeSerials(value: SerialFilter) {
    setParams({ serials: value || null, page: null });
  }

  function handleSort(key: SortKey) {
    if (sortBy === key) {
      setParams({ dir: sortOrder === 'asc' ? 'desc' : 'asc' });
    } else {
      setParams({ sort: key, dir: 'asc', page: null });
    }
  }

  /* A deep link from an MCP citation names one product, so the list has to move
     onto it: the filters are cleared and the row is flagged. Runs once — after
     that the user owns the view. */
  const deepLinkProductId = numericParam(searchParams, 'product_id');
  const deepLinkSerial = searchParams.get('serial');

  useEffect(() => {
    if (deepLinkHandled.current) return;
    if (deepLinkProductId === null && !deepLinkSerial) return;
    deepLinkHandled.current = true;

    async function resolveDeepLink() {
      try {
        if (deepLinkSerial) {
          const lookup = await scanCode(deepLinkSerial);
          if (!lookup.found) {
            setError(lookup.detail);
            return;
          }
          const product =
            lookup.result.kind === 'serial' ? lookup.result.serial.product : lookup.result.product;
          // Searching the SKU leaves the linked row as the only result, so the
          // citation lands on the record rather than somewhere on page 7.
          setHighlightId(product.id);
          setDeepLinkSerials({ productId: product.id, serial: deepLinkSerial });
          // `serials` clears too: a link that names one unit must not land on
          // a list still filtered to the other kind of product.
          setParams({ q: product.sku, view: null, serials: null, page: null, serial: null });
          return;
        }

        if (deepLinkProductId !== null) {
          const response = await api.get<Product>(`/products/${deepLinkProductId}`);
          setHighlightId(response.data.id);
          setParams({ q: response.data.sku, view: null, serials: null, page: null, product_id: null });
        }
      } catch (err) {
        setError(
          getApiErrorMessage(err, 'That link points to a record we could not find in this company'),
        );
      }
    }

    void resolveDeepLink();
    // Intentionally runs on mount only; the ref makes re-entry a no-op.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useDeepLinkScroll(highlightId !== null ? `catalogue-row-${highlightId}` : null, !loading);

  /* The scanned unit's row only exists after the SKU search lands, so the drawer
     waits for it rather than opening on an id it cannot render. */
  useEffect(() => {
    if (!deepLinkSerials) return;
    const match = rows.find((row) => row.id === deepLinkSerials.productId);
    if (match) setSerialsRow(match);
  }, [deepLinkSerials, rows]);

  const lowStockCount = useMemo(() => rows.filter(isLowStock).length, [rows]);

  function startEdit(row: CatalogueRow) {
    setRowError('');
    setEditingId(row.id);
    setEditValues(rowEditFrom(row));
  }

  function cancelEdit() {
    setEditingId(null);
    setEditValues(null);
    setRowError('');
  }

  async function saveEdit() {
    if (editingId === null || !editValues) return;

    // Said inline, beside the row, rather than as a toast that appears far from
    // the field that caused it.
    if (!editValues.name.trim()) {
      setRowError('Product name cannot be empty.');
      return;
    }
    if (!editValues.sku.trim()) {
      setRowError('SKU cannot be empty.');
      return;
    }
    const selling = Number(editValues.selling_price);
    const purchase = Number(editValues.purchase_price);
    const reorder = Number(editValues.reorder_level);
    const gst = Number(editValues.gst_rate);
    if (Number.isNaN(selling) || selling < 0) {
      setRowError('Selling price must be a number of 0 or more.');
      return;
    }
    if (Number.isNaN(purchase) || purchase < 0) {
      setRowError('Purchase price must be a number of 0 or more.');
      return;
    }
    if (Number.isNaN(reorder) || reorder < 0) {
      setRowError('Reorder level must be a number of 0 or more.');
      return;
    }
    if (Number.isNaN(gst) || gst < 0 || gst > 100) {
      setRowError('GST rate must be between 0 and 100.');
      return;
    }

    try {
      setSavingId(editingId);
      setRowError('');
      // current_stock is deliberately absent: stock moves only through the
      // audited adjustment flow, so a row edit can never overwrite it.
      await api.put(`/products/${editingId}/with-inventory`, {
        name: editValues.name.trim(),
        sku: editValues.sku.trim(),
        selling_price: selling,
        purchase_price: purchase,
        reorder_level: reorder,
        gst_rate: gst,
      });
      setSuccess(`${editValues.name.trim()} saved.`);
      cancelEdit();
      await loadData();
    } catch (err) {
      setRowError(getApiErrorMessage(err, 'Unable to save this row'));
    } finally {
      setSavingId(null);
    }
  }

  async function confirmDelete() {
    if (!deleteRow) return;
    const target = deleteRow;
    setDeleteRow(null);
    try {
      await api.delete(`/products/${target.id}`);
      setSuccess(`${target.name} deleted.`);
      await loadData();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Unable to delete this product'));
    }
  }

  async function runExport(kind: 'csv' | 'pdf') {
    const filters = {
      search,
      status: statusFilter as '' | 'active' | 'inactive',
      lowStock,
      serials,
      sortBy,
      sortOrder,
    };
    try {
      setExporting(kind);
      if (kind === 'csv') {
        await exportCatalogueCsv(filters);
        setSuccess('CSV exported for the current view.');
      } else {
        await exportCataloguePdf(filters, currencyCode);
        setSuccess('Report opened for printing.');
      }
    } catch (err) {
      setError(getApiErrorMessage(err, `Unable to export the ${kind.toUpperCase()}`));
    } finally {
      setExporting(null);
    }
  }

  const rangeStart = (page - 1) * PAGE_SIZE + 1;
  const rangeEnd = Math.min(page * PAGE_SIZE, total);
  const filtersActive = Boolean(search) || view !== 'all' || serials !== '';

  /* A filtered-to-nothing list has to name the filter that emptied it —
     "No products match this view" reads as an empty catalogue. */
  const emptyMessage =
    serials === 'tracked'
      ? 'No serial-tracked products match this view.'
      : serials === 'untracked'
        ? 'No products without serial tracking match this view.'
        : 'No products match this view.';

  return (
    <div className="page-grid">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Catalogue</p>
          <h1 className="page-title">Products &amp; stock</h1>
          <p className="section-copy">
            Every product you sell, with what is on the shelf. Prices edit in the row; stock moves
            through an audited adjustment.
          </p>
        </div>
        <div className="page-hero__actions">
          {!loading && total > 0 ? (
            <span className="status-chip">
              {total} {total === 1 ? 'product' : 'products'}
            </span>
          ) : null}
          {!loading && lowStockCount > 0 && view !== 'low' ? (
            <button
              type="button"
              className="status-chip status-chip--warning catalogue-low-chip"
              onClick={() => changeView('low')}
              title="Show only low-stock items"
            >
              {lowStockCount} low on this page
            </button>
          ) : null}
          <button
            type="button"
            className="button button--primary"
            onClick={() => {
              setFormRow(null);
              setFormOpen(true);
            }}
          >
            <Plus size={16} aria-hidden="true" />
            New product
          </button>
        </div>
      </section>

      <StatusToasts
        error={error}
        success={success}
        onClearError={() => setError('')}
        onClearSuccess={() => setSuccess('')}
      />

      <section className="content-grid content-grid--single">
        <article className="panel stack catalogue-panel">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Registry</p>
              <h2 className="nav-panel__title">Catalogue</h2>
            </div>
            <div className="button-row">
              <button
                type="button"
                className={`button button--ghost button--small${exporting === 'csv' ? ' is-busy' : ''}`}
                onClick={() => void runExport('csv')}
                disabled={exporting !== null}
              >
                <Download size={15} aria-hidden="true" />
                CSV
              </button>
              <button
                type="button"
                className={`button button--ghost button--small${exporting === 'pdf' ? ' is-busy' : ''}`}
                onClick={() => void runExport('pdf')}
                disabled={exporting !== null}
              >
                <FileText size={15} aria-hidden="true" />
                Report
              </button>
              <button
                type="button"
                className="button button--ghost button--small"
                onClick={() => setImportOpen(true)}
              >
                <Upload size={15} aria-hidden="true" />
                Import
              </button>
            </div>
          </div>

          <Tabs tabs={VIEWS.map((v) => ({ id: v.id, label: v.label }))} value={view} onChange={changeView} label="Catalogue views" />

          <div className="catalogue-toolbar">
            <div className="catalogue-search">
              <Search size={16} className="catalogue-search__icon" aria-hidden="true" />
              <label className="sr-only" htmlFor="catalogue-search">
                Search the catalogue
              </label>
              <input
                id="catalogue-search"
                className="input catalogue-search__input"
                type="search"
                placeholder="Search by name, SKU or serial..."
                value={search}
                onChange={(e) => changeSearch(e.target.value)}
              />
              {search ? (
                <button
                  type="button"
                  className="catalogue-search__clear"
                  onClick={() => changeSearch('')}
                  title="Clear search"
                  aria-label="Clear search"
                >
                  <X size={14} aria-hidden="true" />
                </button>
              ) : null}
            </div>
            <label className="catalogue-filter">
              <span className="catalogue-filter__label">Serials</span>
              {/* A select, not a second tab bar: three more segmented buttons
                  beside the view tabs would read as three more views, and a
                  native select carries its own keyboard behaviour and label. */}
              <select
                className={`select catalogue-filter__select${serials ? ' catalogue-filter__select--on' : ''}`}
                value={serials}
                onChange={(e) => changeSerials(e.target.value as SerialFilter)}
              >
                <option value="">All products</option>
                <option value="tracked">Serial-tracked</option>
                <option value="untracked">Not serial-tracked</option>
              </select>
            </label>
            {!loading && total > 0 ? (
              <p className="catalogue-toolbar__count">
                Showing{' '}
                <strong>
                  {rangeStart}–{rangeEnd}
                </strong>{' '}
                of {total}
              </p>
            ) : null}
          </div>

          {loading ? (
            <p className="sr-only" role="status">
              Loading the catalogue...
            </p>
          ) : null}

          {!loading && loadFailed ? (
            <EmptyState
              message="The catalogue could not be loaded."
              action={{ label: 'Try again', onClick: () => void loadData() }}
            />
          ) : null}

          {!loading && !loadFailed && rows.length === 0 && filtersActive ? (
            <EmptyState
              message={emptyMessage}
              action={{
                label: 'Clear filters',
                onClick: () => setParams({ q: null, view: null, serials: null, page: null }),
              }}
            />
          ) : null}

          {!loading && !loadFailed && rows.length === 0 && !filtersActive ? (
            <EmptyState
              message="No products yet. Add your first one to start invoicing and tracking stock."
              action={{
                label: 'Add first product',
                onClick: () => {
                  setFormRow(null);
                  setFormOpen(true);
                },
              }}
            />
          ) : null}

          {loading || rows.length > 0 ? (
            <CatalogueTable
              rows={rows}
              loading={loading}
              currencyCode={currencyCode}
              sortBy={sortBy}
              sortOrder={sortOrder}
              onSort={handleSort}
              highlightId={highlightId}
              editingId={editingId}
              editValues={editValues}
              savingId={savingId}
              rowError={rowError}
              onEditChange={setEditValues}
              onStartEdit={startEdit}
              onCancelEdit={cancelEdit}
              onSaveEdit={() => void saveEdit()}
              onAdjustStock={setAdjustRow}
              onOpenSerials={setSerialsRow}
              onConfigureBom={(row) => setBomTarget({ id: row.id, name: row.name })}
              onOpenFullEdit={(row) => {
                setFormRow(row);
                setFormOpen(true);
              }}
              onDelete={setDeleteRow}
            />
          ) : null}

          {!loading && !loadFailed ? (
            <Pagination
              page={page}
              totalPages={totalPages}
              total={total}
              pageSize={PAGE_SIZE}
              itemLabel="products"
              onPageChange={(next) => setParams({ page: next === 1 ? null : String(next) })}
            />
          ) : null}
        </article>
      </section>

      {formOpen ? (
        <ProductFormModal
          row={formRow}
          onCancel={() => setFormOpen(false)}
          onSaved={(message) => {
            setFormOpen(false);
            setSuccess(message);
            void loadData();
          }}
          onNeedsSerialBackfill={(product, payload) => {
            setFormOpen(false);
            setBackfill({ product, payload });
          }}
          onConfigureBom={(id, name) => {
            setFormOpen(false);
            setBomTarget({ id, name });
          }}
        />
      ) : null}

      {adjustRow ? (
        <StockAdjustModal
          row={adjustRow}
          onCancel={() => setAdjustRow(null)}
          onAdjusted={(message) => {
            setAdjustRow(null);
            setSuccess(message);
            void loadData();
          }}
        />
      ) : null}

      {serialsRow ? (
        <SerialHistoryDrawer
          row={serialsRow}
          initialSearch={
            deepLinkSerials?.productId === serialsRow.id ? deepLinkSerials.serial : undefined
          }
          onClose={() => {
            setSerialsRow(null);
            setDeepLinkSerials(null);
          }}
        />
      ) : null}

      {bomTarget ? (
        <BOMConfigModal
          productId={bomTarget.id}
          productName={bomTarget.name}
          onClose={() => setBomTarget(null)}
        />
      ) : null}

      {backfill ? (
        <SerialBackfillModal
          productId={backfill.product.id}
          productName={backfill.product.name}
          productSku={backfill.product.sku}
          payload={backfill.payload}
          onSaved={() => {
            setBackfill(null);
            setSuccess('Serial tracking enabled.');
            void loadData();
          }}
          onCancel={() => setBackfill(null)}
        />
      ) : null}

      {importOpen ? (
        <ImportModal
          onClose={() => setImportOpen(false)}
          onImported={() => {
            setSuccess('Catalogue imported.');
            void loadData();
          }}
        />
      ) : null}

      {deleteRow ? (
        <ConfirmDialog
          title="Delete product"
          message={`Delete ${deleteRow.name} (${deleteRow.sku})? This cannot be undone.`}
          confirmText="Delete"
          danger
          onConfirm={() => void confirmDelete()}
          onCancel={() => setDeleteRow(null)}
        />
      ) : null}
    </div>
  );
}
