/**
 * Taking the catalogue off the screen: a CSV download and a print-ready report.
 *
 * Both are pure functions over the *current view*. They deliberately own no
 * page state — an export must never blank the list it was launched from, so
 * the caller keeps its own busy flag and these throw a user-facing message on
 * failure for the caller to toast.
 */
import api, { cleanParams, getBlobErrorMessage } from '../../api/client';
import formatCurrency from '../../utils/formatting';
import { formatQuantity, isLowStock } from './types';
import type { CatalogueFilters, CatalogueRow, PaginatedCatalogue, SortKey } from './types';

export type ExportFilters = Pick<
  CatalogueFilters,
  'search' | 'status' | 'lowStock' | 'serials' | 'sortBy' | 'sortOrder'
>;

/** The list endpoint's maximum `page_size`; the report pages at it. */
const PAGE_SIZE = 500;

/**
 * Ceiling on a single printed report.
 *
 * A print window holding tens of thousands of rows locks the browser up, so
 * there has to be a limit — but a limit the user is not told about produces a
 * report that quietly disagrees with the catalogue. When this bites, the cap is
 * printed at the top of the document *and* reported back to the caller.
 */
const MAX_REPORT_ROWS = 5000;

const SORT_LABELS: Record<SortKey, string> = {
  name: 'item name',
  sku: 'item code',
  price: 'selling price',
  purchase_price: 'purchase price',
  stock: 'stock',
  reorder_level: 'reorder level',
  gst_rate: 'GST rate',
  date_added: 'date added',
  last_sold: 'last sold',
};

/** Escapes text destined for the generated report's HTML. */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * The filters as the API names them.
 *
 * `sort_by`/`sort_order` are accepted by the list endpoint only — the CSV
 * endpoint always sorts by name — so callers pass `withSort` accordingly.
 *
 * Exported so a test can assert every filter reaches the wire: a filter the
 * grid applies and this omits produces an export that silently disagrees with
 * the screen it was launched from.
 */
export function toQueryParams(filters: ExportFilters, withSort: boolean): Record<string, unknown> {
  return cleanParams({
    search: filters.search.trim(),
    status: filters.status,
    // Only sent when on: `low_stock=false` is the server default anyway, and
    // omitting it keeps the request URL readable in the network log.
    low_stock: filters.lowStock ? true : undefined,
    serials: filters.serials,
    sort_by: withSort ? filters.sortBy : undefined,
    sort_order: withSort ? filters.sortOrder : undefined,
  });
}

/** One line describing the view, so a printed sheet explains itself. */
function describeFilters(filters: ExportFilters): string {
  const parts: string[] = [];
  const search = filters.search.trim();
  if (search) parts.push(`matching "${search}"`);
  if (filters.status === 'active') parts.push('active items only');
  if (filters.status === 'inactive') parts.push('inactive items only');
  if (filters.lowStock) parts.push('low stock only');
  if (filters.serials === 'tracked') parts.push('serial-tracked items only');
  if (filters.serials === 'untracked') parts.push('items without serial tracking');
  if (parts.length === 0) parts.push('all items, no filters applied');
  parts.push(`sorted by ${SORT_LABELS[filters.sortBy]} (${filters.sortOrder === 'asc' ? 'ascending' : 'descending'})`);
  return parts.join(' · ');
}

/** Downloads the filtered catalogue as CSV via GET /products/export-csv. */
export async function exportCatalogueCsv(filters: ExportFilters): Promise<void> {
  let blob: Blob;
  try {
    const res = await api.get<Blob>('/products/export-csv', {
      params: toQueryParams(filters, false),
      responseType: 'blob',
    });
    blob = new Blob([res.data], { type: 'text/csv;charset=utf-8' });
  } catch (err) {
    // A failed blob request carries its JSON detail inside the Blob body.
    throw new Error(await getBlobErrorMessage(err, 'Unable to export the catalogue as CSV.'));
  }

  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement('a');
    link.href = url;
    link.download = `catalogue_${new Date().toISOString().slice(0, 10)}.csv`;
    // Firefox ignores a click on an anchor that is not in the document.
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

/**
 * Every row the current filters select, paged at the API maximum.
 *
 * Returns the total the server reported alongside the rows so the caller can
 * tell a complete report from a capped one.
 */
async function fetchAllRows(filters: ExportFilters): Promise<{ rows: CatalogueRow[]; total: number }> {
  const params = toQueryParams(filters, true);
  const rows: CatalogueRow[] = [];
  let page = 1;
  let total = 0;
  let totalPages = 1;

  while (page <= totalPages && rows.length < MAX_REPORT_ROWS) {
    const res = await api.get<PaginatedCatalogue>('/products/with-inventory', {
      params: { ...params, page, page_size: PAGE_SIZE },
    });
    total = res.data.total;
    totalPages = Math.max(1, res.data.total_pages);
    // A page that comes back empty while the server still claims more pages
    // would otherwise spin this loop forever.
    if (res.data.items.length === 0) break;
    rows.push(...res.data.items);
    page += 1;
  }

  return { rows: rows.slice(0, MAX_REPORT_ROWS), total };
}

/**
 * The printable document.
 *
 * Hard-coded light colours are correct here and nowhere else in this app: this
 * markup represents a sheet of paper, not an app surface, and it is rendered in
 * a bare browser window that never sees the app's theme tokens.
 */
function buildReportHtml(
  rows: CatalogueRow[],
  total: number,
  filters: ExportFilters,
  currencyCode: string
): string {
  const generatedAt = new Date().toLocaleString();
  const capped = total > rows.length;
  const countLine = capped
    ? `Showing ${rows.length} of ${total} items — this report is capped at ${MAX_REPORT_ROWS} rows`
    : `${rows.length} item${rows.length === 1 ? '' : 's'}`;

  const body = rows
    .map((row) => {
      const low = isLowStock(row);
      const classes = [row.status === 'inactive' ? 'is-inactive' : '', low ? 'is-low' : '']
        .filter(Boolean)
        .join(' ');
      // One cell per header, in header order. The old report skipped
      // reorder_level and every later column printed under the wrong heading.
      return `
        <tr class="${classes}">
          <td>${escapeHtml(row.name)}${row.status === 'inactive' ? ' <span class="tag">Inactive</span>' : ''}</td>
          <td>${escapeHtml(row.sku)}</td>
          <td class="num">${escapeHtml(formatCurrency(row.selling_price, currencyCode))}</td>
          <td class="num">${escapeHtml(formatCurrency(row.purchase_price, currencyCode))}</td>
          <td class="num">${escapeHtml(formatQuantity(row.current_stock, row.allow_decimal))}${low ? ' <span class="tag tag--low">Low</span>' : ''}</td>
          <td class="num">${escapeHtml(formatQuantity(row.reorder_level, row.allow_decimal))}</td>
          <td>${escapeHtml(row.description ?? '')}</td>
          <td>${escapeHtml(row.hsn_sac ?? '')}</td>
          <td>${escapeHtml(row.unit)}</td>
          <td class="num">${escapeHtml(String(row.gst_rate))}%</td>
        </tr>`;
    })
    .join('');

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Product Catalogue Report</title>
  <style>
    body { font-family: -apple-system, "Segoe UI", sans-serif; padding: 24px; color: #1a1a1a; background: #ffffff; }
    h1 { font-size: 18px; margin: 0 0 6px; }
    .meta { font-size: 11px; color: #555; margin: 0 0 3px; }
    .meta strong { color: #1a1a1a; }
    .notice { font-size: 11px; color: #8a5a00; background: #fdf3d8; border: 1px solid #e8cf92; border-radius: 4px; padding: 6px 8px; margin: 10px 0 0; }
    table { width: 100%; border-collapse: collapse; font-size: 11px; margin-top: 14px; }
    th { background: #f4f4f4; text-align: left; padding: 6px 8px; border-bottom: 2px solid #ccc; }
    th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; }
    td { padding: 5px 8px; border-bottom: 1px solid #eee; vertical-align: top; }
    tr.is-inactive td { color: #999; }
    tr.is-low td { background: #fff6f6; }
    .tag { font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.4px; border: 1px solid #bbb; border-radius: 3px; padding: 0 3px; color: #666; }
    .tag--low { border-color: #d08b8b; color: #a33; }
    .empty { margin-top: 24px; font-size: 12px; color: #666; }
    thead { display: table-header-group; }
    tr { break-inside: avoid; }
    @media print { body { padding: 0; } .notice { border-color: #999; } }
  </style>
</head>
<body>
  <h1>Product Catalogue Report</h1>
  <p class="meta">Generated <strong>${escapeHtml(generatedAt)}</strong></p>
  <p class="meta">${escapeHtml(countLine)}</p>
  <p class="meta">Filters: ${escapeHtml(describeFilters(filters))}</p>
  ${capped ? `<p class="notice">This report was capped at ${MAX_REPORT_ROWS} rows. Narrow the filters to print the remaining ${total - rows.length} item(s).</p>` : ''}
  ${rows.length === 0
    ? '<p class="empty">No items match the current filters.</p>'
    : `<table>
    <thead>
      <tr>
        <th>Item Name</th>
        <th>Item Code</th>
        <th class="num">Selling Price</th>
        <th class="num">Purchase Price</th>
        <th class="num">Stock</th>
        <th class="num">Reorder</th>
        <th>Description</th>
        <th>HSN Code</th>
        <th>Unit</th>
        <th class="num">GST %</th>
      </tr>
    </thead>
    <tbody>${body}
    </tbody>
  </table>`}
  <script>window.onload = function () { window.print(); };<\/script>
</body>
</html>`;
}

/** Opens a print-ready report of the filtered catalogue in a new window. */
export async function exportCataloguePdf(filters: ExportFilters, currencyCode: string): Promise<void> {
  const { rows, total } = await fetchAllRows(filters);
  const html = buildReportHtml(rows, total, filters, currencyCode);

  const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
  const printWindow = window.open(url, '_blank');
  if (!printWindow) {
    URL.revokeObjectURL(url);
    // The old code checked this and then declared success anyway, so a blocked
    // pop-up looked like a working export that produced nothing.
    throw new Error('The report window was blocked. Allow pop-ups for this site, then try again.');
  }

  const revoke = () => URL.revokeObjectURL(url);
  printWindow.addEventListener('load', revoke, { once: true });
  // Some browsers never fire `load` on a document opened from a blob URL, and
  // an un-revoked object URL is held for the lifetime of the tab.
  window.setTimeout(revoke, 60_000);

  if (total > rows.length) {
    // The document says so too, but the user launched this from the catalogue
    // and may never scroll the print preview to the notice.
    throw new Error(
      `The report shows the first ${rows.length} of ${total} items — printing is capped at ${MAX_REPORT_ROWS} rows. Narrow the filters to include the rest.`
    );
  }
}
