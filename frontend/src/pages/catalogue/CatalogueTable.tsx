import { useEffect, useRef } from 'react';
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Check,
  Factory,
  Pencil,
  ScanBarcode,
  SlidersHorizontal,
  Trash2,
} from 'lucide-react';
import formatCurrency from '../../utils/formatting';
import { deepLinkClass } from '../../utils/deepLink';
import PublishToMarketplaceButton from '../../components/PublishToMarketplaceButton';
import { formatQuantity, isLowStock } from './types';
import type { CatalogueRow, RowEdit, SortKey, SortOrder } from './types';

/**
 * The catalogue grid.
 *
 * A real <table>, not a div feed: the three pages this replaces rendered rows as
 * flex cards with no header, so no column had a name and nothing lined up. With
 * real headers the header row can also carry the sort controls, instead of the
 * detached "Sort:" button strip the old Inventory page used.
 *
 * Editing is per ROW, not per cell. The old grid saved one cell per request —
 * a full product was ~24 clicks and 24 round trips, and clicking a second cell
 * silently discarded the first one's unsaved text. Here a row opens as a set of
 * fields with one Save.
 */

/** Columns that carry a numeric figure, right-aligned by convention. */
type Column = {
  key: string;
  label: string;
  sort?: SortKey;
  numeric?: boolean;
  /** Hidden below the wide breakpoint to keep the core columns readable. */
  secondary?: boolean;
};

const COLUMNS: Column[] = [
  { key: 'product', label: 'Product', sort: 'name' },
  { key: 'stock', label: 'Stock', sort: 'stock', numeric: true },
  { key: 'selling', label: 'Selling', sort: 'price', numeric: true },
  { key: 'purchase', label: 'Purchase', sort: 'purchase_price', numeric: true, secondary: true },
  { key: 'reorder', label: 'Reorder', sort: 'reorder_level', numeric: true, secondary: true },
  { key: 'gst', label: 'GST', sort: 'gst_rate', numeric: true, secondary: true },
  { key: 'lastSold', label: 'Last sold', sort: 'last_sold', secondary: true },
  { key: 'actions', label: 'Actions' },
];

type CatalogueTableProps = {
  rows: CatalogueRow[];
  loading: boolean;
  currencyCode: string;
  sortBy: SortKey;
  sortOrder: SortOrder;
  onSort: (key: SortKey) => void;
  highlightId: number | null;
  editingId: number | null;
  editValues: RowEdit | null;
  savingId: number | null;
  rowError: string;
  onEditChange: (next: RowEdit) => void;
  onStartEdit: (row: CatalogueRow) => void;
  onCancelEdit: () => void;
  onSaveEdit: () => void;
  onAdjustStock: (row: CatalogueRow) => void;
  onOpenSerials: (row: CatalogueRow) => void;
  onConfigureBom: (row: CatalogueRow) => void;
  onOpenFullEdit: (row: CatalogueRow) => void;
  onDelete: (row: CatalogueRow) => void;
};

function formatDate(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

export default function CatalogueTable({
  rows,
  loading,
  currencyCode,
  sortBy,
  sortOrder,
  onSort,
  highlightId,
  editingId,
  editValues,
  savingId,
  rowError,
  onEditChange,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  onAdjustStock,
  onOpenSerials,
  onConfigureBom,
  onOpenFullEdit,
  onDelete,
}: CatalogueTableProps) {
  const firstEditRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (editingId !== null) firstEditRef.current?.focus();
  }, [editingId]);

  return (
    <div className="catalogue-table-wrap">
      <table className="catalogue-table">
        <thead>
          <tr>
            {COLUMNS.map((column) => {
              const active = column.sort && sortBy === column.sort;
              const className = [
                column.numeric ? 'catalogue-table__num' : '',
                column.secondary ? 'catalogue-table__col--secondary' : '',
              ]
                .filter(Boolean)
                .join(' ');
              return (
                <th
                  key={column.key}
                  className={className || undefined}
                  scope="col"
                  aria-sort={
                    active ? (sortOrder === 'asc' ? 'ascending' : 'descending') : undefined
                  }
                >
                  {column.sort ? (
                    <button
                      type="button"
                      className={`catalogue-sort${active ? ' catalogue-sort--active' : ''}`}
                      onClick={() => onSort(column.sort as SortKey)}
                    >
                      {column.label}
                      {/* The direction has to be visible, not only announced: the
                          old pages showed a bidirectional icon that never changed,
                          so sighted users could not tell asc from desc. */}
                      {active ? (
                        sortOrder === 'asc' ? (
                          <ArrowUp size={13} aria-hidden="true" />
                        ) : (
                          <ArrowDown size={13} aria-hidden="true" />
                        )
                      ) : (
                        <ArrowUpDown size={13} aria-hidden="true" />
                      )}
                    </button>
                  ) : (
                    column.label
                  )}
                </th>
              );
            })}
          </tr>
        </thead>

        <tbody>
          {loading
            ? [0, 1, 2, 3, 4].map((index) => (
                <tr key={`skeleton-${index}`} aria-hidden="true">
                  {COLUMNS.map((column) => (
                    <td
                      key={column.key}
                      className={column.secondary ? 'catalogue-table__col--secondary' : undefined}
                    >
                      <span className="skeleton catalogue-table__skeleton" />
                    </td>
                  ))}
                </tr>
              ))
            : rows.map((row) => {
                const editing = editingId === row.id;
                const saving = savingId === row.id;
                const low = isLowStock(row);

                if (editing && editValues) {
                  return (
                    <tr
                      key={row.id}
                      id={`catalogue-row-${row.id}`}
                      className={deepLinkClass(
                        highlightId === row.id,
                        'catalogue-row catalogue-row--editing',
                      )}
                    >
                      <td>
                        <div className="catalogue-edit-pair">
                          <input
                            ref={firstEditRef}
                            className="input input--grid"
                            value={editValues.name}
                            aria-label="Product name"
                            onChange={(e) => onEditChange({ ...editValues, name: e.target.value })}
                          />
                          <input
                            className="input input--grid catalogue-edit-pair__sku"
                            value={editValues.sku}
                            aria-label="SKU"
                            onChange={(e) => onEditChange({ ...editValues, sku: e.target.value })}
                          />
                        </div>
                      </td>
                      <td className="catalogue-table__num">
                        {/* Stock is never a free-text cell — it moves only through
                            the audited adjustment flow. */}
                        <span className="catalogue-table__locked">
                          {formatQuantity(row.current_stock, row.allow_decimal)}
                        </span>
                      </td>
                      <td className="catalogue-table__num">
                        <input
                          className="input input--grid"
                          type="number"
                          step="0.01"
                          min="0"
                          value={editValues.selling_price}
                          aria-label="Selling price"
                          onChange={(e) =>
                            onEditChange({ ...editValues, selling_price: e.target.value })
                          }
                        />
                      </td>
                      <td className="catalogue-table__num catalogue-table__col--secondary">
                        <input
                          className="input input--grid"
                          type="number"
                          step="0.01"
                          min="0"
                          value={editValues.purchase_price}
                          aria-label="Purchase price"
                          onChange={(e) =>
                            onEditChange({ ...editValues, purchase_price: e.target.value })
                          }
                        />
                      </td>
                      <td className="catalogue-table__num catalogue-table__col--secondary">
                        <input
                          className="input input--grid"
                          type="number"
                          step={row.allow_decimal ? '0.001' : '1'}
                          min="0"
                          value={editValues.reorder_level}
                          aria-label="Reorder level"
                          onChange={(e) =>
                            onEditChange({ ...editValues, reorder_level: e.target.value })
                          }
                        />
                      </td>
                      <td className="catalogue-table__num catalogue-table__col--secondary">
                        <input
                          className="input input--grid"
                          type="number"
                          step="0.01"
                          min="0"
                          max="100"
                          value={editValues.gst_rate}
                          aria-label="GST rate"
                          onChange={(e) =>
                            onEditChange({ ...editValues, gst_rate: e.target.value })
                          }
                        />
                      </td>
                      <td className="catalogue-table__col--secondary">
                        <span className="table-subtext">{formatDate(row.last_sold_at)}</span>
                      </td>
                      <td>
                        <div className="catalogue-row__actions">
                          <button
                            type="button"
                            className={`button button--primary button--small${saving ? ' is-busy' : ''}`}
                            onClick={onSaveEdit}
                            disabled={saving}
                          >
                            <Check size={14} aria-hidden="true" />
                            {saving ? 'Saving…' : 'Save'}
                          </button>
                          <button
                            type="button"
                            className="button button--ghost button--small"
                            onClick={onCancelEdit}
                            disabled={saving}
                          >
                            Cancel
                          </button>
                        </div>
                        {rowError ? (
                          <p className="catalogue-row__error" role="alert">
                            {rowError}
                          </p>
                        ) : null}
                      </td>
                    </tr>
                  );
                }

                return (
                  <tr
                    key={row.id}
                    id={`catalogue-row-${row.id}`}
                    className={deepLinkClass(
                      highlightId === row.id,
                      `catalogue-row${row.status === 'inactive' ? ' catalogue-row--inactive' : ''}`,
                    )}
                  >
                    <td>
                      <div className="catalogue-cell__product">
                        <span className="catalogue-cell__name">{row.name}</span>
                        <span className="catalogue-cell__tags">
                          <span className="catalogue-sku">{row.sku}</span>
                          {/* The API calls this "inactive", but the flag behind
                              it is maintain_inventory — a service is not a
                              disabled product, it is one nobody counts. */}
                          {row.status === 'inactive' ? (
                            <span className="status-chip status-chip--paused">Not stocked</span>
                          ) : null}
                          {row.track_serials ? (
                            <span className="status-chip" title="Stock is tracked per unit">
                              Serialised
                            </span>
                          ) : null}
                          {row.is_producable ? (
                            <span className="status-chip">Made in-house</span>
                          ) : null}
                        </span>
                      </div>
                    </td>

                    <td className="catalogue-table__num">
                      {row.maintain_inventory ? (
                        <button
                          type="button"
                          className={`catalogue-stock${low ? ' catalogue-stock--low' : ''}`}
                          onClick={() => onAdjustStock(row)}
                          title={`Adjust stock for ${row.name}`}
                          /* The button's content is a bare quantity, so without
                             this its accessible name is "25 Pieces" — a number
                             with no verb, and unaddressable by role and name. */
                          aria-label={`Adjust stock for ${row.name}, currently ${formatQuantity(
                            row.current_stock,
                            row.allow_decimal,
                          )} ${row.unit}${low ? ', low' : ''}`}
                        >
                          <span className="catalogue-stock__value">
                            {formatQuantity(row.current_stock, row.allow_decimal)}
                          </span>
                          <span className="catalogue-stock__unit">{row.unit}</span>
                          {low ? <span className="catalogue-stock__flag">Low</span> : null}
                        </button>
                      ) : (
                        <span className="catalogue-table__locked" title="Stock is not maintained">
                          Not tracked
                        </span>
                      )}
                    </td>

                    <td className="catalogue-table__num catalogue-table__figure">
                      {formatCurrency(row.selling_price, currencyCode)}
                    </td>
                    <td className="catalogue-table__num catalogue-table__col--secondary">
                      {formatCurrency(row.purchase_price, currencyCode)}
                    </td>
                    <td className="catalogue-table__num catalogue-table__col--secondary">
                      {row.reorder_level > 0
                        ? formatQuantity(row.reorder_level, row.allow_decimal)
                        : '—'}
                    </td>
                    <td className="catalogue-table__num catalogue-table__col--secondary">
                      {row.gst_rate}%
                    </td>
                    <td className="catalogue-table__col--secondary">
                      <span className="table-subtext">{formatDate(row.last_sold_at)}</span>
                    </td>

                    <td>
                      <div className="catalogue-row__actions">
                        <button
                          type="button"
                          className="button button--ghost button--icon"
                          onClick={() => onStartEdit(row)}
                          title={`Quick edit ${row.name}`}
                          aria-label={`Quick edit ${row.name}`}
                        >
                          <Pencil size={16} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          className="button button--ghost button--icon"
                          onClick={() => onOpenFullEdit(row)}
                          title={`All settings for ${row.name}`}
                          aria-label={`All settings for ${row.name}`}
                        >
                          <SlidersHorizontal size={16} aria-hidden="true" />
                        </button>
                        {row.track_serials ? (
                          <button
                            type="button"
                            className="button button--ghost button--icon"
                            onClick={() => onOpenSerials(row)}
                            title={`Serial numbers for ${row.name}`}
                            aria-label={`Serial numbers for ${row.name}`}
                          >
                            <ScanBarcode size={16} aria-hidden="true" />
                          </button>
                        ) : null}
                        {row.is_producable ? (
                          <button
                            type="button"
                            className="button button--ghost button--icon"
                            onClick={() => onConfigureBom(row)}
                            title={`Bill of materials for ${row.name}`}
                            aria-label={`Bill of materials for ${row.name}`}
                          >
                            <Factory size={16} aria-hidden="true" />
                          </button>
                        ) : null}
                        <PublishToMarketplaceButton
                          productId={row.id}
                          productName={row.name}
                          quantity={row.current_stock}
                          variant="icon"
                        />
                        <button
                          type="button"
                          className="button button--danger button--icon"
                          onClick={() => onDelete(row)}
                          title={`Delete ${row.name}`}
                          aria-label={`Delete ${row.name}`}
                        >
                          <Trash2 size={16} aria-hidden="true" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
        </tbody>
      </table>
    </div>
  );
}
