import type { Product } from '../../types/api';

export type SerialStatus = 'in_stock' | 'sold';

/** The invoice a serial arrived on, or went out on. */
export type SerialInvoiceRef = {
  id: number;
  invoice_number: string | null;
  invoice_date: string;
};

export type Serial = {
  id: number;
  serial_number: string;
  status: SerialStatus;
  product_id: number;
  product: Product;
  purchase_invoice: SerialInvoiceRef | null;
  sales_invoice: SerialInvoiceRef | null;
  created_at: string;
};

/**
 * `GET /serials/scan` resolves a scanned code as a serial first and a product
 * SKU second, so one uninterrupted scanning rhythm covers both handsets and
 * accessories. Neither matching is a 404, not a third variant of this union.
 */
export type ScanResult =
  | { kind: 'serial'; serial: Serial; product: null }
  | { kind: 'product'; serial: null; product: Product };

export type PaginatedSerials = {
  items: Serial[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
};
