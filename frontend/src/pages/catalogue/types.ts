/**
 * The single row shape behind the Catalogue page.
 *
 * Products, Inventory and Products & Inventory each had their own row type over
 * the same underlying record — `inventory.product_id` is UNIQUE, so stock is a
 * column on a product, not a separate entity. One page, one row type.
 *
 * Fields come from `GET /products/with-inventory`.
 */
export type CatalogueRow = {
  id: number;
  sku: string;
  name: string;
  description: string | null;
  hsn_sac: string | null;
  purchase_price: number;
  selling_price: number;
  current_stock: number;
  reorder_level: number;
  /** 'active' mirrors product.maintain_inventory. */
  status: 'active' | 'inactive';
  unit: string;
  gst_rate: number;
  track_serials: boolean;
  maintain_inventory: boolean;
  allow_decimal: boolean;
  is_producable: boolean;
  production_cost: number | null;
  date_added: string | null;
  last_sold_at: string | null;
};

export type PaginatedCatalogue = {
  items: CatalogueRow[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
};

/** Columns the server can sort on. Every sortable header maps to one of these. */
export type SortKey =
  | 'name'
  | 'sku'
  | 'price'
  | 'purchase_price'
  | 'stock'
  | 'reorder_level'
  | 'gst_rate'
  | 'date_added'
  | 'last_sold';

export type SortOrder = 'asc' | 'desc';

/** The list filters. Mirrored into the URL so a view survives a refresh. */
export type CatalogueFilters = {
  search: string;
  status: '' | 'active' | 'inactive';
  lowStock: boolean;
  sortBy: SortKey;
  sortOrder: SortOrder;
  page: number;
};

/**
 * Stock is below the level at which it should be reordered.
 *
 * A reorder level of 0 means "not tracked for reordering" — without this guard
 * every zero-stock product with no threshold set would flag as low.
 */
export function isLowStock(row: CatalogueRow): boolean {
  return row.reorder_level > 0 && row.current_stock <= row.reorder_level;
}

/** Quantities render as integers unless the product opts into fractions. */
export function formatQuantity(value: number, allowDecimal: boolean): string {
  return allowDecimal ? String(Number(value.toFixed(3))) : String(Math.round(value));
}

/** The subset of a row that quick row-edit exposes as fields. */
export type RowEdit = {
  name: string;
  sku: string;
  selling_price: string;
  purchase_price: string;
  reorder_level: string;
  gst_rate: string;
};

export function rowEditFrom(row: CatalogueRow): RowEdit {
  return {
    name: row.name,
    sku: row.sku,
    selling_price: String(row.selling_price),
    purchase_price: String(row.purchase_price),
    reorder_level: String(row.reorder_level),
    gst_rate: String(row.gst_rate),
  };
}
